#!/usr/bin/env python3
"""Score building condition from field photos using image heuristics.

Analyses colour uniformity, edge regularity, dark patch density, luminance,
and overall texture variance to produce a 0-100 condition score.  Compares
against the ``condition`` field in params and flags disagreements.

Usage:
    python scripts/analyze/photo_condition_scorer.py
    python scripts/analyze/photo_condition_scorer.py \
        --params params/ \
        --photo-dir "PHOTOS KENSINGTON sorted/" \
        --photo-index "PHOTOS KENSINGTON/csv/photo_address_index.csv" \
        --output outputs/photo_condition/
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# ---------------------------------------------------------------------------
# Photo index loading (shared pattern)
# ---------------------------------------------------------------------------

def _normalise_address(addr: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", addr.lower()).strip()


def _load_photo_index(csv_path: Path) -> dict[str, list[str]]:
    index: dict[str, list[str]] = defaultdict(list)
    if not csv_path.exists():
        return index
    with open(csv_path, encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            addr = (row.get("address_or_location") or "").strip()
            fname = (row.get("filename") or "").strip()
            if addr and fname:
                index[_normalise_address(addr)].append(fname)
    return index


def _find_photo_file(filename: str, photo_dir: Path) -> Path | None:
    direct = photo_dir / filename
    if direct.exists():
        return direct
    for p in photo_dir.rglob(filename):
        return p
    fname_lower = filename.lower()
    for p in photo_dir.rglob("*"):
        if p.is_file() and p.name.lower() == fname_lower:
            return p
    return None


def _find_best_photo(params: dict, photo_index: dict, photo_dir: Path) -> Path | None:
    dfa = params.get("deep_facade_analysis") or {}
    src_photo = dfa.get("source_photo")
    if src_photo:
        p = _find_photo_file(src_photo, photo_dir)
        if p:
            return p
    po = params.get("photo_observations") or {}
    obs_photo = po.get("photo")
    if obs_photo:
        p = _find_photo_file(obs_photo, photo_dir)
        if p:
            return p
    addr = (params.get("building_name") or (params.get("_meta") or {}).get("address", "")).strip()
    if not addr:
        return None
    norm = _normalise_address(addr)
    for fname in photo_index.get(norm, []):
        p = _find_photo_file(fname, photo_dir)
        if p:
            return p
    return None


# ---------------------------------------------------------------------------
# Image helpers
# ---------------------------------------------------------------------------

def _load_image_array(path: Path) -> np.ndarray | None:
    try:
        from PIL import Image
        img = Image.open(path).convert("RGB")
        return np.asarray(img, dtype=np.uint8)
    except Exception:
        return None


def _load_grayscale(path: Path) -> np.ndarray | None:
    try:
        from PIL import Image
        img = Image.open(path).convert("L")
        return np.asarray(img, dtype=np.uint8)
    except Exception:
        return None


def _crop_facade(arr: np.ndarray) -> np.ndarray:
    """Center 60% width, bottom 80% height."""
    h, w = arr.shape[:2]
    x_start = int(w * 0.20)
    x_end = int(w * 0.80)
    y_start = int(h * 0.20)
    return arr[y_start:h, x_start:x_end]


# ---------------------------------------------------------------------------
# Condition heuristics
# ---------------------------------------------------------------------------

def _colour_uniformity(rgb: np.ndarray) -> float:
    """Score 0-100: low variance = uniform = well-maintained.

    Returns higher score for more uniform facades.
    """
    flat = rgb.reshape(-1, 3).astype(np.float64)
    # Standard deviation across all pixels per channel
    std_per_ch = flat.std(axis=0)
    avg_std = float(std_per_ch.mean())
    # avg_std ~10 = very uniform (score 100), ~60+ = chaotic (score 0)
    score = max(0.0, min(100.0, 100.0 - (avg_std - 10.0) * 2.0))
    return score


def _edge_regularity(gray: np.ndarray) -> float:
    """Score 0-100: consistent horizontal/vertical edges = good structure.

    Uses Sobel-like gradient approximation.
    """
    # Simple gradient via differences
    gy = np.abs(gray[1:, :].astype(np.float64) - gray[:-1, :].astype(np.float64))
    gx = np.abs(gray[:, 1:].astype(np.float64) - gray[:, :-1].astype(np.float64))

    # Ratio of horizontal + vertical edges to total gradient magnitude
    total_grad = float(gy.sum() + gx.sum())
    if total_grad < 1.0:
        return 50.0  # neutral

    # Strong edges (above threshold) that are mostly h/v aligned
    threshold = 30.0
    strong_h = float((gy > threshold).sum())
    strong_v = float((gx > threshold).sum())
    total_strong = strong_h + strong_v
    total_pixels = float(gy.size + gx.size)

    # Higher density of strong edges = more structured
    density = total_strong / max(total_pixels, 1)
    # density ~0.05 = clean, ~0.20+ = noisy/damaged
    score = max(0.0, min(100.0, 100.0 - (density - 0.03) * 500.0))
    return score


def _dark_patch_ratio(gray: np.ndarray) -> float:
    """Score 0-100: fewer dark patches = better condition.

    Dark patches indicate staining, water damage, or missing elements.
    """
    dark_threshold = 60  # quite dark
    dark_pixels = float((gray < dark_threshold).sum())
    total_pixels = float(gray.size)
    ratio = dark_pixels / max(total_pixels, 1)
    # ratio ~0.05 = clean (score 95), ~0.30+ = heavily stained (score 10)
    score = max(0.0, min(100.0, 100.0 - ratio * 300.0))
    return score


def _luminance_score(gray: np.ndarray) -> float:
    """Score 0-100: moderate brightness = healthy facade.

    Very dark = soiling; very bright may indicate overexposure.
    """
    mean_lum = float(gray.mean())
    # Ideal range: 80-180
    if 80 <= mean_lum <= 180:
        return 100.0
    elif mean_lum < 80:
        return max(0.0, mean_lum / 80.0 * 100.0)
    else:
        return max(0.0, (255.0 - mean_lum) / 75.0 * 100.0)


def _texture_variance(gray: np.ndarray) -> float:
    """Score 0-100 based on local texture variance.

    Very high variance = damaged/deteriorated surface.
    """
    # Compute variance in 16x16 blocks
    h, w = gray.shape
    block = 16
    variances = []
    for y in range(0, h - block, block):
        for x in range(0, w - block, block):
            patch = gray[y:y + block, x:x + block].astype(np.float64)
            variances.append(float(patch.var()))
    if not variances:
        return 50.0
    avg_var = sum(variances) / len(variances)
    # avg_var ~200 = normal brick, ~800+ = damaged
    score = max(0.0, min(100.0, 100.0 - (avg_var - 200.0) * 0.15))
    return score


def _compute_condition_score(rgb: np.ndarray, gray: np.ndarray) -> dict:
    """Combine heuristics into a single condition score."""
    facade_rgb = _crop_facade(rgb)
    facade_gray = _crop_facade(gray)

    uniformity = _colour_uniformity(facade_rgb)
    regularity = _edge_regularity(facade_gray)
    dark_patches = _dark_patch_ratio(facade_gray)
    luminance = _luminance_score(facade_gray)
    texture = _texture_variance(facade_gray)

    # Weighted combination
    overall = (
        uniformity * 0.25
        + regularity * 0.20
        + dark_patches * 0.25
        + luminance * 0.15
        + texture * 0.15
    )

    if overall >= 70:
        label = "good"
    elif overall >= 40:
        label = "fair"
    else:
        label = "poor"

    return {
        "overall_score": round(overall, 1),
        "label": label,
        "components": {
            "colour_uniformity": round(uniformity, 1),
            "edge_regularity": round(regularity, 1),
            "dark_patch_score": round(dark_patches, 1),
            "luminance_score": round(luminance, 1),
            "texture_variance_score": round(texture, 1),
        },
    }


# ---------------------------------------------------------------------------
# Main analysis
# ---------------------------------------------------------------------------

def analyse_building(params: dict, photo_path: Path) -> dict | None:
    address = params.get("building_name") or (params.get("_meta") or {}).get("address", "unknown")
    rgb = _load_image_array(photo_path)
    gray = _load_grayscale(photo_path)
    if rgb is None or gray is None:
        return None

    condition = _compute_condition_score(rgb, gray)

    param_condition = (params.get("condition") or "").lower().strip()
    photo_label = condition["label"]

    agreement = param_condition == photo_label if param_condition else None
    disagreement_flag = False
    if param_condition and not agreement:
        disagreement_flag = True

    return {
        "address": address,
        "photo": photo_path.name,
        "photo_condition": condition,
        "param_condition": param_condition or None,
        "agreement": agreement,
        "disagreement_flag": disagreement_flag,
    }


def run(params_dir: Path, photo_dir: Path, photo_index_path: Path, output_dir: Path) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    photo_index = _load_photo_index(photo_index_path)

    results: list[dict] = []
    agreements = 0
    disagreements = 0
    no_param_condition = 0
    no_photo = 0
    total = 0

    for pf in sorted(params_dir.glob("*.json")):
        if pf.name.startswith("_"):
            continue
        try:
            params = json.loads(pf.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if params.get("skipped"):
            continue
        total += 1

        photo_path = _find_best_photo(params, photo_index, photo_dir)
        if photo_path is None:
            no_photo += 1
            continue

        result = analyse_building(params, photo_path)
        if result is None:
            continue
        results.append(result)
        if result["agreement"] is True:
            agreements += 1
        elif result["agreement"] is False:
            disagreements += 1
        else:
            no_param_condition += 1

    results.sort(key=lambda r: r["photo_condition"]["overall_score"])

    # Score distribution
    score_buckets = {"good": 0, "fair": 0, "poor": 0}
    for r in results:
        score_buckets[r["photo_condition"]["label"]] += 1

    report = {
        "generated": datetime.now().isoformat(),
        "total_buildings": total,
        "buildings_analysed": len(results),
        "buildings_without_photos": no_photo,
        "condition_distribution": score_buckets,
        "param_agreement": agreements,
        "param_disagreement": disagreements,
        "no_param_condition": no_param_condition,
        "agreement_rate_pct": round(100.0 * agreements / max(agreements + disagreements, 1), 1),
        "disagreements": [r for r in results if r.get("disagreement_flag")],
        "worst_condition": results[:20],
        "all_buildings": results,
    }

    out_path = output_dir / "photo_condition_report.json"
    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Condition report: {out_path}")
    print(f"  Buildings analysed:  {len(results)} / {total}")
    print(f"  Distribution:        {score_buckets}")
    print(f"  Agreement rate:      {report['agreement_rate_pct']}%")
    print(f"  Disagreements:       {disagreements}")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Score building condition from field photos")
    parser.add_argument("--params", type=Path, default=REPO_ROOT / "params",
                        help="Directory of building param JSON files")
    parser.add_argument("--photo-dir", type=Path,
                        default=REPO_ROOT / "PHOTOS KENSINGTON sorted",
                        help="Root directory of sorted field photos")
    parser.add_argument("--photo-index", type=Path,
                        default=REPO_ROOT / "PHOTOS KENSINGTON" / "csv" / "photo_address_index.csv",
                        help="Photo index CSV")
    parser.add_argument("--output", type=Path, default=REPO_ROOT / "outputs" / "photo_condition",
                        help="Output directory")
    args = parser.parse_args()
    run(args.params, args.photo_dir, args.photo_index, args.output)


if __name__ == "__main__":
    main()
