#!/usr/bin/env python3
"""Extract reusable architectural elements from iPad LiDAR scans.

Segments scanned meshes into element types (windows, doors, cornices,
brackets) and exports them as individual OBJ files for the asset library.

Usage:
    python scripts/acquire_extract_elements.py --input data/ipad_scans/ --output assets/scanned_elements/
    python scripts/acquire_extract_elements.py --input data/ipad_scans/scan1.ply --output assets/scanned_elements/ --types window,door
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)
REPO_ROOT = Path(__file__).resolve().parent.parent

ELEMENT_TYPES = {
    "window": {"z_range": (1.0, 3.5), "width_range": (0.5, 2.0), "height_range": (0.8, 2.5)},
    "door": {"z_range": (0.0, 2.5), "width_range": (0.6, 1.5), "height_range": (1.8, 3.0)},
    "cornice": {"z_range_pct": (0.85, 1.0), "min_width_pct": 0.6},
    "bracket": {"z_range_pct": (0.8, 0.95), "max_width": 0.5, "max_height": 0.5},
    "column": {"z_range_pct": (0.0, 0.9), "max_width": 0.4},
    "baluster": {"z_range_pct": (0.3, 0.6), "max_width": 0.15},
}


def load_points(path: Path) -> np.ndarray:
    """Load point cloud from PLY."""
    points = []
    in_data = False
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            if line.strip() == "end_header":
                in_data = True
                continue
            if in_data:
                parts = line.strip().split()
                if len(parts) >= 3:
                    try:
                        points.append([float(parts[0]), float(parts[1]), float(parts[2])])
                    except ValueError:
                        pass
    return np.array(points, dtype=np.float32) if points else np.zeros((0, 3))


def extract_elements_from_scan(
    points: np.ndarray,
    element_types: list[str] | None = None,
) -> list[dict]:
    """Extract architectural elements by geometric segmentation.

    Uses height bands and cluster analysis to isolate elements.
    """
    if len(points) < 100:
        return []

    z_min, z_max = points[:, 2].min(), points[:, 2].max()
    total_h = z_max - z_min
    if total_h < 1.0:
        return []

    types_to_check = element_types or list(ELEMENT_TYPES.keys())
    elements = []

    for etype in types_to_check:
        spec = ELEMENT_TYPES.get(etype, {})

        # Determine Z range
        if "z_range" in spec:
            z_lo, z_hi = spec["z_range"]
        elif "z_range_pct" in spec:
            z_lo = z_min + total_h * spec["z_range_pct"][0]
            z_hi = z_min + total_h * spec["z_range_pct"][1]
        else:
            continue

        # Filter points in Z band
        mask = (points[:, 2] >= z_lo) & (points[:, 2] <= z_hi)
        band_pts = points[mask]
        if len(band_pts) < 20:
            continue

        # Simple grid-based clustering for element isolation
        x_min, x_max = band_pts[:, 0].min(), band_pts[:, 0].max()
        y_min, y_max = band_pts[:, 1].min(), band_pts[:, 1].max()
        band_w = x_max - x_min
        band_d = y_max - y_min
        band_h = z_hi - z_lo

        # For cornices: one long element spanning facade
        if etype == "cornice" and band_w > total_h * 0.3:
            elements.append({
                "type": etype,
                "points": len(band_pts),
                "width_m": round(float(band_w), 3),
                "height_m": round(float(band_h), 3),
                "depth_m": round(float(band_d), 3),
                "z_center": round(float((z_lo + z_hi) / 2), 3),
                "bbox": [float(x_min), float(y_min), float(z_lo),
                         float(x_max), float(y_max), float(z_hi)],
            })
            continue

        # For repeating elements: cluster by X position
        if band_w < 0.1:
            continue

        cell_size = 0.3  # 30cm grid
        n_cells = max(1, int(band_w / cell_size))
        cell_counts = np.zeros(n_cells)
        for pt in band_pts:
            idx = min(int((pt[0] - x_min) / cell_size), n_cells - 1)
            cell_counts[idx] += 1

        # Find clusters (consecutive cells with high density)
        threshold = np.mean(cell_counts) + np.std(cell_counts)
        in_cluster = False
        cluster_start = 0
        clusters = []

        for i in range(n_cells):
            if cell_counts[i] > threshold and not in_cluster:
                in_cluster = True
                cluster_start = i
            elif cell_counts[i] <= threshold and in_cluster:
                in_cluster = False
                cw = (i - cluster_start) * cell_size
                # Check size constraints
                width_ok = True
                if "width_range" in spec:
                    width_ok = spec["width_range"][0] <= cw <= spec["width_range"][1]
                elif "max_width" in spec:
                    width_ok = cw <= spec["max_width"]
                if width_ok:
                    clusters.append((cluster_start, i, cw))

        for cs, ce, cw in clusters:
            cx = x_min + (cs + ce) / 2 * cell_size
            elements.append({
                "type": etype,
                "points": int(cell_counts[cs:ce].sum()),
                "width_m": round(cw, 3),
                "height_m": round(float(band_h), 3),
                "depth_m": round(float(band_d), 3),
                "x_center": round(float(cx), 3),
                "z_center": round(float((z_lo + z_hi) / 2), 3),
            })

    return elements


def save_element_ply(points: np.ndarray, bbox: list[float], output_path: Path):
    """Save element points within bbox as PLY."""
    mask = (
        (points[:, 0] >= bbox[0]) & (points[:, 0] <= bbox[3]) &
        (points[:, 1] >= bbox[1]) & (points[:, 1] <= bbox[4]) &
        (points[:, 2] >= bbox[2]) & (points[:, 2] <= bbox[5])
    )
    elem_pts = points[mask]
    if len(elem_pts) == 0:
        return

    output_path.parent.mkdir(parents=True, exist_ok=True)
    n = len(elem_pts)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(f"ply\nformat ascii 1.0\nelement vertex {n}\n")
        f.write("property float x\nproperty float y\nproperty float z\nend_header\n")
        for p in elem_pts:
            f.write(f"{p[0]:.6f} {p[1]:.6f} {p[2]:.6f}\n")


def main():
    parser = argparse.ArgumentParser(description="Extract elements from LiDAR scans")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=REPO_ROOT / "assets" / "scanned_elements")
    parser.add_argument("--types", type=str, default=None,
                        help="Comma-separated element types (default: all)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    args.output.mkdir(parents=True, exist_ok=True)

    element_types = args.types.split(",") if args.types else None

    if args.input.is_file():
        scan_files = [args.input]
    else:
        scan_files = sorted(args.input.glob("*.ply"))

    all_elements = []
    for scan in scan_files:
        pts = load_points(scan)
        if len(pts) == 0:
            continue
        elements = extract_elements_from_scan(pts, element_types)
        print(f"  {scan.name}: {len(elements)} elements")
        for elem in elements:
            elem["source_scan"] = scan.name
            all_elements.append(elem)

    # Save catalog
    catalog_path = args.output / "element_catalog.json"
    catalog_path.write_text(json.dumps(all_elements, indent=2), encoding="utf-8")
    print(f"\nExtracted {len(all_elements)} elements -> {catalog_path}")

    # Summary by type
    from collections import Counter
    type_counts = Counter(e["type"] for e in all_elements)
    for t, c in type_counts.most_common():
        print(f"  {t}: {c}")


if __name__ == "__main__":
    main()
