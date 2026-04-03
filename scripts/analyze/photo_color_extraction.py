#!/usr/bin/env python3
"""Extract precise colour data from field photos for every building.

Crops each matched photo to the facade region, extracts dominant colours via
coarse RGB binning, classifies facade / trim / roof colours, and scores
accuracy against current param hex values using CIE76 delta-E.

Usage:
    python scripts/analyze/photo_color_extraction.py
    python scripts/analyze/photo_color_extraction.py \
        --params params/ \
        --photo-dir "PHOTOS KENSINGTON sorted/" \
        --photo-index "PHOTOS KENSINGTON/csv/photo_address_index.csv" \
        --output outputs/photo_colors/
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# ---------------------------------------------------------------------------
# Colour-space helpers
# ---------------------------------------------------------------------------

def _hex_to_rgb(h: str) -> tuple[int, int, int] | None:
    h = (h or "").strip().lstrip("#")
    if len(h) != 6:
        return None
    try:
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    except ValueError:
        return None


def _rgb_to_hex(r: int, g: int, b: int) -> str:
    return f"#{r:02X}{g:02X}{b:02X}"


def _srgb_to_linear(c: float) -> float:
    return ((c + 0.055) / 1.055) ** 2.4 if c > 0.04045 else c / 12.92


def _rgb_to_lab(r: int, g: int, b: int) -> tuple[float, float, float]:
    rl, gl, bl = (_srgb_to_linear(c / 255.0) for c in (r, g, b))
    x = rl * 0.4124564 + gl * 0.3575761 + bl * 0.1804375
    y = rl * 0.2126729 + gl * 0.7151522 + bl * 0.0721750
    z = rl * 0.0193339 + gl * 0.1191920 + bl * 0.9503041
    xn, yn, zn = 0.95047, 1.0, 1.08883

    def f(t: float) -> float:
        return t ** (1.0 / 3.0) if t > 0.008856 else 7.787 * t + 16.0 / 116.0

    fx, fy, fz = f(x / xn), f(y / yn), f(z / zn)
    L = 116.0 * fy - 16.0
    a = 500.0 * (fx - fy)
    b_val = 200.0 * (fy - fz)
    return (L, a, b_val)


def _delta_e(hex1: str, hex2: str) -> float | None:
    rgb1 = _hex_to_rgb(hex1)
    rgb2 = _hex_to_rgb(hex2)
    if rgb1 is None or rgb2 is None:
        return None
    lab1 = _rgb_to_lab(*rgb1)
    lab2 = _rgb_to_lab(*rgb2)
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(lab1, lab2)))


# ---------------------------------------------------------------------------
# Photo index loading
# ---------------------------------------------------------------------------

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


def _normalise_address(addr: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", addr.lower()).strip()


def _find_photo_file(filename: str, photo_dir: Path) -> Path | None:
    """Search for a photo filename anywhere under photo_dir."""
    # Direct path
    direct = photo_dir / filename
    if direct.exists():
        return direct
    # Search subdirectories
    for p in photo_dir.rglob(filename):
        return p
    # Case-insensitive fallback
    fname_lower = filename.lower()
    for p in photo_dir.rglob("*"):
        if p.is_file() and p.name.lower() == fname_lower:
            return p
    return None


# ---------------------------------------------------------------------------
# Image analysis
# ---------------------------------------------------------------------------

def _load_image_array(path: Path) -> np.ndarray | None:
    try:
        from PIL import Image
        img = Image.open(path).convert("RGB")
        return np.asarray(img, dtype=np.uint8)
    except Exception:
        return None


def _crop_facade(arr: np.ndarray) -> np.ndarray:
    """Crop to center 60% width, bottom 80% height (exclude sky)."""
    h, w = arr.shape[:2]
    x_start = int(w * 0.20)
    x_end = int(w * 0.80)
    y_start = int(h * 0.20)  # skip top 20% (sky)
    return arr[y_start:h, x_start:x_end]


def _crop_roof_region(arr: np.ndarray) -> np.ndarray:
    """Top 25% of image, center 60% width."""
    h, w = arr.shape[:2]
    x_start = int(w * 0.20)
    x_end = int(w * 0.80)
    y_end = int(h * 0.25)
    return arr[:y_end, x_start:x_end]


def _crop_trim_region(arr: np.ndarray) -> np.ndarray:
    """Edges of the facade: leftmost/rightmost 15% strips + top/bottom 10% bands."""
    h, w = arr.shape[:2]
    left_strip = arr[int(h * 0.1):int(h * 0.9), :int(w * 0.15)]
    right_strip = arr[int(h * 0.1):int(h * 0.9), int(w * 0.85):]
    top_band = arr[:int(h * 0.10), int(w * 0.15):int(w * 0.85)]
    bottom_band = arr[int(h * 0.90):, int(w * 0.15):int(w * 0.85)]
    parts = [p for p in [left_strip, right_strip, top_band, bottom_band] if p.size > 0]
    if not parts:
        return arr
    return np.concatenate([p.reshape(-1, 3) for p in parts], axis=0).reshape(-1, 1, 3)


def _dominant_colour(arr: np.ndarray, bins: int = 8) -> str:
    """Extract single dominant colour via coarse RGB binning."""
    if arr.size == 0:
        return "#808080"
    flat = arr.reshape(-1, 3)
    quantised = (flat // (256 // bins)).astype(np.int32)
    keys = quantised[:, 0] * bins * bins + quantised[:, 1] * bins + quantised[:, 2]
    counts = np.bincount(keys, minlength=bins ** 3)
    top_bin = int(np.argmax(counts))
    # Recover bin centroid
    step = 256 // bins
    r_bin = (top_bin // (bins * bins)) * step + step // 2
    g_bin = ((top_bin // bins) % bins) * step + step // 2
    b_bin = (top_bin % bins) * step + step // 2
    return _rgb_to_hex(min(r_bin, 255), min(g_bin, 255), min(b_bin, 255))


def _top_colours(arr: np.ndarray, k: int = 5, bins: int = 8) -> list[dict]:
    """Extract top-k colours via coarse binning."""
    if arr.size == 0:
        return []
    flat = arr.reshape(-1, 3)
    quantised = (flat // (256 // bins)).astype(np.int32)
    keys = quantised[:, 0] * bins * bins + quantised[:, 1] * bins + quantised[:, 2]
    counts = np.bincount(keys, minlength=bins ** 3)
    total = max(int(counts.sum()), 1)
    top_indices = np.argsort(counts)[::-1][:k]
    step = 256 // bins
    results = []
    for idx in top_indices:
        idx = int(idx)
        if counts[idx] == 0:
            break
        r_bin = (idx // (bins * bins)) * step + step // 2
        g_bin = ((idx // bins) % bins) * step + step // 2
        b_bin = (idx % bins) * step + step // 2
        results.append({
            "hex": _rgb_to_hex(min(r_bin, 255), min(g_bin, 255), min(b_bin, 255)),
            "pct": round(100.0 * int(counts[idx]) / total, 1),
        })
    return results


def _accuracy_score(de: float | None) -> int:
    """Convert delta-E to 0-100 accuracy score."""
    if de is None:
        return 0
    # delta-E 0 = perfect (100), delta-E >= 50 = terrible (0)
    return max(0, min(100, int(100 - 2 * de)))


# ---------------------------------------------------------------------------
# Main analysis
# ---------------------------------------------------------------------------

def analyse_building(params: dict, photo_path: Path) -> dict | None:
    address = params.get("building_name") or (params.get("_meta") or {}).get("address", "unknown")
    arr = _load_image_array(photo_path)
    if arr is None:
        return None

    facade_crop = _crop_facade(arr)
    roof_crop = _crop_roof_region(arr)
    trim_crop = _crop_trim_region(arr)

    facade_hex = _dominant_colour(facade_crop)
    roof_hex = _dominant_colour(roof_crop)
    trim_hex = _dominant_colour(trim_crop)
    top5 = _top_colours(facade_crop, k=5)

    # Current param colours
    fd = params.get("facade_detail") or {}
    cp = params.get("colour_palette") or {}
    param_facade = fd.get("brick_colour_hex") or cp.get("facade") or ""
    param_trim = fd.get("trim_colour_hex") or cp.get("trim") or ""
    param_roof = cp.get("roof") or ""

    de_facade = _delta_e(facade_hex, param_facade) if param_facade else None
    de_trim = _delta_e(trim_hex, param_trim) if param_trim else None
    de_roof = _delta_e(roof_hex, param_roof) if param_roof else None

    return {
        "address": address,
        "photo": photo_path.name,
        "extracted_colors": {
            "facade_hex": facade_hex,
            "trim_hex": trim_hex,
            "roof_hex": roof_hex,
            "top_5_facade": top5,
        },
        "current_params": {
            "facade_hex": param_facade or None,
            "trim_hex": param_trim or None,
            "roof_hex": param_roof or None,
        },
        "delta_e": {
            "facade": round(de_facade, 1) if de_facade is not None else None,
            "trim": round(de_trim, 1) if de_trim is not None else None,
            "roof": round(de_roof, 1) if de_roof is not None else None,
        },
        "accuracy_score": _accuracy_score(de_facade),
    }


def _address_from_params(params: dict) -> str:
    return (params.get("building_name") or (params.get("_meta") or {}).get("address", "")).strip()


def _find_best_photo(params: dict, photo_index: dict, photo_dir: Path) -> Path | None:
    """Find a matching photo for this building."""
    # Try deep_facade_analysis.source_photo first
    dfa = params.get("deep_facade_analysis") or {}
    src_photo = dfa.get("source_photo")
    if src_photo:
        p = _find_photo_file(src_photo, photo_dir)
        if p:
            return p

    # Try photo_observations.photo
    po = params.get("photo_observations") or {}
    obs_photo = po.get("photo")
    if obs_photo:
        p = _find_photo_file(obs_photo, photo_dir)
        if p:
            return p

    # Fall back to photo index
    addr = _address_from_params(params)
    if not addr:
        return None
    norm = _normalise_address(addr)
    candidates = photo_index.get(norm, [])
    for fname in candidates:
        p = _find_photo_file(fname, photo_dir)
        if p:
            return p
    return None


def run(params_dir: Path, photo_dir: Path, photo_index_path: Path, output_dir: Path) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    photo_index = _load_photo_index(photo_index_path)

    results: list[dict] = []
    street_scores: dict[str, list[int]] = defaultdict(list)
    no_photo_count = 0
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
            no_photo_count += 1
            continue

        result = analyse_building(params, photo_path)
        if result is None:
            continue
        results.append(result)

        # Track per-street
        street = (params.get("site") or {}).get("street") or ""
        if street:
            street_scores[street].append(result["accuracy_score"])

    # Sort by accuracy ascending (worst first)
    results.sort(key=lambda r: r["accuracy_score"])

    per_street = {
        s: {"avg_accuracy": round(sum(sc) / max(len(sc), 1), 1), "count": len(sc)}
        for s, sc in sorted(street_scores.items())
    }

    all_scores = [r["accuracy_score"] for r in results]
    avg_accuracy = round(sum(all_scores) / max(len(all_scores), 1), 1) if all_scores else 0.0

    report = {
        "generated": datetime.now().isoformat(),
        "total_buildings": total,
        "buildings_with_photos": len(results),
        "buildings_without_photos": no_photo_count,
        "average_accuracy": avg_accuracy,
        "per_street_accuracy": per_street,
        "worst_mismatches": results[:20],
        "all_buildings": results,
    }

    out_path = output_dir / "photo_color_report.json"
    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Colour report: {out_path}")
    print(f"  Buildings analysed: {len(results)} / {total}")
    print(f"  Average accuracy:   {avg_accuracy}")
    print(f"  No photo:           {no_photo_count}")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract and compare colours from field photos")
    parser.add_argument("--params", type=Path, default=REPO_ROOT / "params",
                        help="Directory of building param JSON files")
    parser.add_argument("--photo-dir", type=Path,
                        default=REPO_ROOT / "PHOTOS KENSINGTON sorted",
                        help="Root directory of sorted field photos")
    parser.add_argument("--photo-index", type=Path,
                        default=REPO_ROOT / "PHOTOS KENSINGTON" / "csv" / "photo_address_index.csv",
                        help="Photo index CSV")
    parser.add_argument("--output", type=Path, default=REPO_ROOT / "outputs" / "photo_colors",
                        help="Output directory")
    args = parser.parse_args()
    run(args.params, args.photo_dir, args.photo_index, args.output)


if __name__ == "__main__":
    main()
