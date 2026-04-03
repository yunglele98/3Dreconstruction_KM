#!/usr/bin/env python3
"""Ensure every building has its best reference photo linked and rank quality.

Scores each candidate photo for facade visibility (resolution, brightness,
blur, facade coverage, framing) and selects the best per building.  Flags
buildings with no photos as acquisition gaps.

Usage:
    python scripts/analyze/photo_reference_linker.py
    python scripts/analyze/photo_reference_linker.py \
        --params params/ \
        --photo-dir "PHOTOS KENSINGTON sorted/" \
        --photo-index "PHOTOS KENSINGTON/csv/photo_address_index.csv" \
        --output outputs/photo_links/
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
# Photo index loading
# ---------------------------------------------------------------------------

def _normalise_address(addr: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", addr.lower()).strip()


def _load_photo_index(csv_path: Path) -> dict[str, list[str]]:
    """Return {normalised_address: [filename, ...]}."""
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


# ---------------------------------------------------------------------------
# Photo quality scoring
# ---------------------------------------------------------------------------

def _load_image_info(path: Path) -> dict | None:
    """Load image and return basic info dict, or None on failure."""
    try:
        from PIL import Image
        img = Image.open(path)
        w, h = img.size
        gray = np.asarray(img.convert("L"), dtype=np.uint8)
        rgb = np.asarray(img.convert("RGB"), dtype=np.uint8)
        return {"width": w, "height": h, "gray": gray, "rgb": rgb, "path": path}
    except Exception:
        return None


def _score_resolution(w: int, h: int) -> float:
    """Score 0-100 based on image resolution.

    >= 4MP = 100, <= 0.3MP = 0, linear between.
    """
    megapixels = (w * h) / 1_000_000
    if megapixels >= 4.0:
        return 100.0
    if megapixels <= 0.3:
        return 0.0
    return (megapixels - 0.3) / 3.7 * 100.0


def _score_brightness(gray: np.ndarray) -> float:
    """Score 0-100: moderate brightness is best.

    Mean ~100-160 = 100, extremes = 0.
    """
    mean = float(gray.mean())
    if 100 <= mean <= 160:
        return 100.0
    elif mean < 100:
        return max(0.0, mean / 100.0 * 100.0)
    else:
        return max(0.0, (255.0 - mean) / 95.0 * 100.0)


def _score_sharpness(gray: np.ndarray) -> float:
    """Score 0-100 based on Laplacian variance (blur detection).

    Higher variance = sharper.
    """
    # Approximate Laplacian: second derivative via kernel [1, -2, 1]
    # For speed, use simple central differences
    h, w = gray.shape
    if h < 3 or w < 3:
        return 0.0
    g = gray.astype(np.float64)
    lap_y = g[2:, 1:-1] + g[:-2, 1:-1] - 2 * g[1:-1, 1:-1]
    lap_x = g[1:-1, 2:] + g[1:-1, :-2] - 2 * g[1:-1, 1:-1]
    laplacian = lap_y + lap_x
    var = float(laplacian.var())
    # var ~50 = blurry (score 20), ~500+ = sharp (score 100)
    score = max(0.0, min(100.0, var / 5.0))
    return score


def _score_facade_coverage(rgb: np.ndarray) -> float:
    """Estimate facade content ratio (non-sky pixels).

    Sky is approximated as pixels where blue > red and blue > green
    and brightness > 150.
    """
    r = rgb[:, :, 0].astype(np.float64)
    g = rgb[:, :, 1].astype(np.float64)
    b = rgb[:, :, 2].astype(np.float64)
    brightness = (r + g + b) / 3.0
    sky_mask = (b > r) & (b > g) & (brightness > 150)
    sky_ratio = float(sky_mask.sum()) / max(float(sky_mask.size), 1)
    # Less sky = more facade coverage
    coverage = 1.0 - sky_ratio
    return max(0.0, min(100.0, coverage * 100.0))


def _score_framing(gray: np.ndarray) -> float:
    """Score 0-100 based on content being center-framed.

    Facade content should be in the center; empty edges suggest poor framing.
    """
    h, w = gray.shape
    # Compare edge brightness vs center brightness
    center = gray[int(h * 0.25):int(h * 0.75), int(w * 0.25):int(w * 0.75)]
    edge_top = gray[:int(h * 0.1), :]
    edge_bottom = gray[int(h * 0.9):, :]

    center_var = float(center.astype(np.float64).var())
    edge_var = float(edge_top.astype(np.float64).var()) + float(edge_bottom.astype(np.float64).var())

    # Higher center variance relative to edges = center-framed
    if center_var + edge_var < 1.0:
        return 50.0
    ratio = center_var / max(center_var + edge_var / 2, 1.0)
    return max(0.0, min(100.0, ratio * 100.0))


def score_photo(info: dict) -> dict:
    """Score a single photo and return quality metrics."""
    w, h = info["width"], info["height"]
    gray = info["gray"]
    rgb = info["rgb"]

    resolution = _score_resolution(w, h)
    brightness = _score_brightness(gray)
    sharpness = _score_sharpness(gray)
    coverage = _score_facade_coverage(rgb)
    framing = _score_framing(gray)

    overall = (
        resolution * 0.15
        + brightness * 0.15
        + sharpness * 0.25
        + coverage * 0.25
        + framing * 0.20
    )

    return {
        "filename": info["path"].name,
        "resolution": f"{w}x{h}",
        "overall_score": round(overall, 1),
        "components": {
            "resolution": round(resolution, 1),
            "brightness": round(brightness, 1),
            "sharpness": round(sharpness, 1),
            "facade_coverage": round(coverage, 1),
            "framing": round(framing, 1),
        },
    }


# ---------------------------------------------------------------------------
# Main analysis
# ---------------------------------------------------------------------------

def _get_all_candidate_photos(params: dict, photo_index: dict, photo_dir: Path) -> list[Path]:
    """Collect all photo paths that could match this building."""
    paths: list[Path] = []
    seen: set[str] = set()

    def _add(fname: str) -> None:
        if not fname or fname in seen:
            return
        seen.add(fname)
        p = _find_photo_file(fname, photo_dir)
        if p and str(p) not in {str(pp) for pp in paths}:
            paths.append(p)

    # From deep_facade_analysis
    dfa = params.get("deep_facade_analysis") or {}
    _add(dfa.get("source_photo", ""))

    # From photo_observations
    po = params.get("photo_observations") or {}
    _add(po.get("photo", ""))

    # From photo index
    addr = (params.get("building_name") or (params.get("_meta") or {}).get("address", "")).strip()
    if addr:
        norm = _normalise_address(addr)
        for fname in photo_index.get(norm, []):
            _add(fname)

    return paths


def analyse_building(params: dict, photo_index: dict, photo_dir: Path) -> dict:
    address = params.get("building_name") or (params.get("_meta") or {}).get("address", "unknown")
    candidates = _get_all_candidate_photos(params, photo_index, photo_dir)

    if not candidates:
        return {
            "address": address,
            "best_photo": None,
            "best_score": 0,
            "all_photos": [],
            "photo_count": 0,
            "acquisition_gap": True,
        }

    scored: list[dict] = []
    for photo_path in candidates:
        info = _load_image_info(photo_path)
        if info is None:
            continue
        result = score_photo(info)
        scored.append(result)

    if not scored:
        return {
            "address": address,
            "best_photo": None,
            "best_score": 0,
            "all_photos": [p.name for p in candidates],
            "photo_count": len(candidates),
            "acquisition_gap": True,
        }

    scored.sort(key=lambda s: s["overall_score"], reverse=True)
    best = scored[0]

    return {
        "address": address,
        "best_photo": best["filename"],
        "best_score": best["overall_score"],
        "best_detail": best,
        "all_photos": [s["filename"] for s in scored],
        "all_scores": scored,
        "photo_count": len(scored),
        "acquisition_gap": False,
    }


def run(params_dir: Path, photo_dir: Path, photo_index_path: Path, output_dir: Path) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    photo_index = _load_photo_index(photo_index_path)

    results: list[dict] = []
    gaps: list[str] = []
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

        result = analyse_building(params, photo_index, photo_dir)
        results.append(result)
        if result["acquisition_gap"]:
            gaps.append(result["address"])

    # Sort: best-scored first for the links file, gaps at end
    linked = [r for r in results if not r["acquisition_gap"]]
    linked.sort(key=lambda r: r["best_score"], reverse=True)

    # Build compact links mapping
    photo_links = {}
    for r in results:
        entry = {
            "best_photo": r["best_photo"],
            "best_score": r["best_score"],
            "all_photos": r["all_photos"],
            "photo_count": r["photo_count"],
        }
        photo_links[r["address"]] = entry

    all_scores = [r["best_score"] for r in linked]
    avg_score = round(sum(all_scores) / max(len(all_scores), 1), 1) if all_scores else 0.0

    # Score distribution
    excellent = sum(1 for s in all_scores if s >= 80)
    good = sum(1 for s in all_scores if 60 <= s < 80)
    fair = sum(1 for s in all_scores if 40 <= s < 60)
    poor = sum(1 for s in all_scores if s < 40)

    report = {
        "generated": datetime.now().isoformat(),
        "total_buildings": total,
        "buildings_with_photos": len(linked),
        "buildings_without_photos": len(gaps),
        "acquisition_gap_rate_pct": round(100.0 * len(gaps) / max(total, 1), 1),
        "average_best_score": avg_score,
        "quality_distribution": {
            "excellent_80_plus": excellent,
            "good_60_79": good,
            "fair_40_59": fair,
            "poor_below_40": poor,
        },
        "acquisition_gaps": sorted(gaps),
        "photo_links": photo_links,
    }

    # Write links file
    links_path = output_dir / "photo_links.json"
    links_path.write_text(json.dumps(photo_links, indent=2, ensure_ascii=False), encoding="utf-8")

    # Write full report
    report_path = output_dir / "photo_links_report.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Photo links:  {links_path}")
    print(f"Full report:  {report_path}")
    print(f"  Buildings:          {total}")
    print(f"  With photos:        {len(linked)}")
    print(f"  Acquisition gaps:   {len(gaps)} ({report['acquisition_gap_rate_pct']}%)")
    print(f"  Avg best score:     {avg_score}")
    print(f"  Quality: excellent={excellent}, good={good}, fair={fair}, poor={poor}")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Link best reference photo to each building")
    parser.add_argument("--params", type=Path, default=REPO_ROOT / "params",
                        help="Directory of building param JSON files")
    parser.add_argument("--photo-dir", type=Path,
                        default=REPO_ROOT / "PHOTOS KENSINGTON sorted",
                        help="Root directory of sorted field photos")
    parser.add_argument("--photo-index", type=Path,
                        default=REPO_ROOT / "PHOTOS KENSINGTON" / "csv" / "photo_address_index.csv",
                        help="Photo index CSV")
    parser.add_argument("--output", type=Path, default=REPO_ROOT / "outputs" / "photo_links",
                        help="Output directory")
    args = parser.parse_args()
    run(args.params, args.photo_dir, args.photo_index, args.output)


if __name__ == "__main__":
    main()
