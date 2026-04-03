#!/usr/bin/env python3
"""Count windows in field photos via heuristic image analysis.

Uses adaptive thresholding to detect rectangular dark regions (windows),
groups them by vertical position (floor bands), and compares against
windows_per_floor in params.  This is a lightweight validation signal
complementing the ML-based segment_facades.py pipeline.

Usage:
    python scripts/analyze/photo_window_counter.py
    python scripts/analyze/photo_window_counter.py \
        --params params/ \
        --photo-dir "PHOTOS KENSINGTON sorted/" \
        --photo-index "PHOTOS KENSINGTON/csv/photo_address_index.csv" \
        --output outputs/photo_windows/
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

def _load_grayscale(path: Path) -> np.ndarray | None:
    try:
        from PIL import Image
        img = Image.open(path).convert("L")
        return np.asarray(img, dtype=np.uint8)
    except Exception:
        return None


def _adaptive_threshold(gray: np.ndarray, block_size: int = 51, c: int = 15) -> np.ndarray:
    """Simple mean-based adaptive threshold (dark regions become white)."""
    from numpy.lib.stride_tricks import as_strided
    h, w = gray.shape
    pad = block_size // 2
    padded = np.pad(gray.astype(np.float64), pad, mode="edge")
    # Integral image for fast mean
    integral = np.cumsum(np.cumsum(padded, axis=0), axis=1)
    # Mean in block_size x block_size neighbourhood
    y1 = np.arange(h)
    y2 = y1 + block_size
    x1 = np.arange(w)
    x2 = x1 + block_size
    # Using integral image
    s = (integral[np.ix_(y2, x2)]
         - integral[np.ix_(y1, x2)]
         - integral[np.ix_(y2, x1)]
         + integral[np.ix_(y1, x1)])
    mean = s / (block_size * block_size)
    # Pixel is "dark" if below local mean - c
    binary = (gray.astype(np.float64) < (mean - c)).astype(np.uint8) * 255
    return binary


def _find_contour_bboxes(binary: np.ndarray) -> list[tuple[int, int, int, int]]:
    """Find bounding boxes of connected white regions via flood fill.

    Returns list of (x, y, w, h) tuples.
    """
    visited = np.zeros_like(binary, dtype=bool)
    h_img, w_img = binary.shape
    bboxes = []

    for y in range(h_img):
        for x in range(w_img):
            if binary[y, x] > 0 and not visited[y, x]:
                # BFS flood fill
                stack = [(y, x)]
                visited[y, x] = True
                min_y, max_y = y, y
                min_x, max_x = x, x
                pixel_count = 0
                while stack:
                    cy, cx = stack.pop()
                    pixel_count += 1
                    for dy, dx in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                        ny, nx = cy + dy, cx + dx
                        if 0 <= ny < h_img and 0 <= nx < w_img and not visited[ny, nx] and binary[ny, nx] > 0:
                            visited[ny, nx] = True
                            stack.append((ny, nx))
                            min_y = min(min_y, ny)
                            max_y = max(max_y, ny)
                            min_x = min(min_x, nx)
                            max_x = max(max_x, nx)
                bw = max_x - min_x + 1
                bh = max_y - min_y + 1
                if bw > 0 and bh > 0:
                    bboxes.append((min_x, min_y, bw, bh))
    return bboxes


def _detect_windows(gray: np.ndarray) -> list[dict]:
    """Detect window-like rectangles in a grayscale facade image.

    Returns list of {x, y, w, h, cy} dicts for candidate windows.
    """
    h_img, w_img = gray.shape
    min_dim = max(10, min(h_img, w_img) // 40)  # minimum window size ~2.5% of image
    max_dim = min(h_img, w_img) // 3  # maximum window size

    # Downscale large images for performance
    scale = 1.0
    work = gray
    if max(h_img, w_img) > 1200:
        scale = 1200.0 / max(h_img, w_img)
        new_h = int(h_img * scale)
        new_w = int(w_img * scale)
        # Simple downscale via slicing
        step_y = max(1, h_img // new_h)
        step_x = max(1, w_img // new_w)
        work = gray[::step_y, ::step_x]
        min_dim = max(6, int(min_dim * scale))
        max_dim = int(max_dim * scale)

    binary = _adaptive_threshold(work, block_size=max(3, min_dim * 2 | 1), c=12)
    bboxes = _find_contour_bboxes(binary)

    candidates = []
    for x, y, bw, bh in bboxes:
        # Filter by size
        if bw < min_dim or bh < min_dim:
            continue
        if bw > max_dim or bh > max_dim:
            continue
        # Filter by aspect ratio (windows are roughly 0.4 - 2.5 h/w)
        aspect = bh / max(bw, 1)
        if aspect < 0.4 or aspect > 2.5:
            continue
        # Rescale back
        candidates.append({
            "x": int(x / scale),
            "y": int(y / scale),
            "w": int(bw / scale),
            "h": int(bh / scale),
            "cy": int((y + bh / 2) / scale),
        })

    return candidates


def _cluster_by_floor(candidates: list[dict], img_height: int, expected_floors: int = 3) -> list[list[dict]]:
    """Group window candidates into floor bands by y-coordinate clustering.

    Uses simple equal-height band division as a heuristic.
    """
    if not candidates:
        return []

    n_floors = max(expected_floors, 1)
    # Divide image into n_floors horizontal bands
    band_height = img_height / n_floors
    floors: list[list[dict]] = [[] for _ in range(n_floors)]

    for c in candidates:
        band = min(int(c["cy"] / band_height), n_floors - 1)
        # Invert: top band = top floor
        floor_idx = n_floors - 1 - band
        floors[floor_idx].append(c)

    return floors


# ---------------------------------------------------------------------------
# Main analysis
# ---------------------------------------------------------------------------

def analyse_building(params: dict, photo_path: Path) -> dict | None:
    address = params.get("building_name") or (params.get("_meta") or {}).get("address", "unknown")
    gray = _load_grayscale(photo_path)
    if gray is None:
        return None

    # Crop to facade region (center 70%, skip top 10% sky)
    h_img, w_img = gray.shape
    x_start = int(w_img * 0.15)
    x_end = int(w_img * 0.85)
    y_start = int(h_img * 0.10)
    facade = gray[y_start:, x_start:x_end]

    expected_floors = params.get("floors") or 2
    candidates = _detect_windows(facade)
    floor_groups = _cluster_by_floor(candidates, facade.shape[0], expected_floors)

    detected_per_floor = [len(fg) for fg in floor_groups]
    param_wpf = params.get("windows_per_floor")
    if isinstance(param_wpf, list):
        param_list = list(param_wpf)
    elif isinstance(param_wpf, (int, float)):
        param_list = [int(param_wpf)] * expected_floors
    else:
        param_list = []

    # Compute match ratio per floor
    floor_matches = []
    for i in range(max(len(detected_per_floor), len(param_list))):
        det = detected_per_floor[i] if i < len(detected_per_floor) else 0
        exp = param_list[i] if i < len(param_list) else 0
        if exp > 0:
            ratio = min(det, exp) / exp
        elif det == 0:
            ratio = 1.0
        else:
            ratio = 0.0
        floor_matches.append({
            "floor": i + 1,
            "detected": det,
            "expected": exp,
            "match_ratio": round(ratio, 2),
        })

    total_detected = sum(detected_per_floor)
    total_expected = sum(param_list) if param_list else 0
    overall_ratio = (min(total_detected, total_expected) / max(total_expected, 1)) if total_expected > 0 else 0.0

    return {
        "address": address,
        "photo": photo_path.name,
        "param_floors": expected_floors,
        "detected_windows_per_floor": detected_per_floor,
        "param_windows_per_floor": param_list,
        "total_detected": total_detected,
        "total_expected": total_expected,
        "overall_match_ratio": round(overall_ratio, 2),
        "per_floor": floor_matches,
        "candidate_count": len(candidates),
    }


def run(params_dir: Path, photo_dir: Path, photo_index_path: Path, output_dir: Path) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    photo_index = _load_photo_index(photo_index_path)

    results: list[dict] = []
    mismatch_count = 0
    total = 0
    no_photo = 0

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
        if result["overall_match_ratio"] < 0.7:
            mismatch_count += 1

    results.sort(key=lambda r: r["overall_match_ratio"])

    avg_ratio = round(
        sum(r["overall_match_ratio"] for r in results) / max(len(results), 1), 2
    ) if results else 0.0

    report = {
        "generated": datetime.now().isoformat(),
        "total_buildings": total,
        "buildings_analysed": len(results),
        "buildings_without_photos": no_photo,
        "average_match_ratio": avg_ratio,
        "significant_mismatches": mismatch_count,
        "mismatch_rate_pct": round(100.0 * mismatch_count / max(len(results), 1), 1),
        "worst_mismatches": [r for r in results[:20]],
        "all_buildings": results,
    }

    out_path = output_dir / "photo_window_report.json"
    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Window report: {out_path}")
    print(f"  Buildings analysed:      {len(results)} / {total}")
    print(f"  Average match ratio:     {avg_ratio}")
    print(f"  Significant mismatches:  {mismatch_count} ({report['mismatch_rate_pct']}%)")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Count windows in field photos and compare to params")
    parser.add_argument("--params", type=Path, default=REPO_ROOT / "params",
                        help="Directory of building param JSON files")
    parser.add_argument("--photo-dir", type=Path,
                        default=REPO_ROOT / "PHOTOS KENSINGTON sorted",
                        help="Root directory of sorted field photos")
    parser.add_argument("--photo-index", type=Path,
                        default=REPO_ROOT / "PHOTOS KENSINGTON" / "csv" / "photo_address_index.csv",
                        help="Photo index CSV")
    parser.add_argument("--output", type=Path, default=REPO_ROOT / "outputs" / "photo_windows",
                        help="Output directory")
    args = parser.parse_args()
    run(args.params, args.photo_dir, args.photo_index, args.output)


if __name__ == "__main__":
    main()
