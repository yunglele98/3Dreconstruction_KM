#!/usr/bin/env python3
"""Extract architectural elements from per-building meshes.

Uses segmentation masks to identify and extract individual elements
(windows, doors, cornices, etc.) from photogrammetric meshes.

Usage:
    python scripts/reconstruct/extract_elements.py --meshes meshes/per_building/ --segmentation segmentation/
    python scripts/reconstruct/extract_elements.py --meshes meshes/per_building/ --address "22 Lippincott St"
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
ELEMENT_TYPES = ["window", "door", "cornice", "storefront", "column", "bay_window",
                 "chimney", "dormer", "bracket", "quoin", "string_course"]


def load_mesh_points(ply_path: Path) -> np.ndarray:
    """Load point cloud from PLY file."""
    points = []
    in_data = False
    with open(ply_path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if line == "end_header":
                in_data = True
                continue
            if in_data:
                parts = line.split()
                if len(parts) >= 3:
                    try:
                        points.append([float(parts[0]), float(parts[1]), float(parts[2])])
                    except ValueError:
                        pass
    return np.array(points, dtype=np.float32) if points else np.zeros((0, 3))


def segment_by_height(points: np.ndarray, floor_heights: list[float]) -> dict[str, np.ndarray]:
    """Segment point cloud by floor height bands.

    Returns dict mapping floor labels to point arrays.
    """
    segments = {}
    z_base = 0.0
    for i, fh in enumerate(floor_heights):
        mask = (points[:, 2] >= z_base) & (points[:, 2] < z_base + fh)
        label = f"floor_{i}" if i > 0 else "ground"
        segments[label] = points[mask]
        z_base += fh

    # Roof segment (above all floors)
    mask = points[:, 2] >= z_base
    segments["roof"] = points[mask]

    return segments


def extract_facade_plane(points: np.ndarray, axis: int = 1,
                         tolerance: float = 0.3) -> np.ndarray:
    """Extract points near the facade plane (front face).

    Assumes facade is roughly aligned with one axis.
    """
    if len(points) == 0:
        return points
    # Find the mode of the axis (most common value = facade plane)
    hist, edges = np.histogram(points[:, axis], bins=50)
    peak_idx = np.argmax(hist)
    plane_val = (edges[peak_idx] + edges[peak_idx + 1]) / 2
    mask = np.abs(points[:, axis] - plane_val) < tolerance
    return points[mask]


def cluster_openings(facade_points: np.ndarray, min_gap: float = 0.3) -> list[dict]:
    """Detect window/door openings as gaps in the facade point cloud.

    Openings appear as regions with fewer points (holes in the facade).
    """
    if len(facade_points) < 10:
        return []

    # Project to 2D (x, z for front facade)
    xz = facade_points[:, [0, 2]]

    # Create a 2D density grid
    x_min, z_min = xz.min(axis=0)
    x_max, z_max = xz.max(axis=0)
    grid_size = 0.1  # 10cm resolution
    nx = max(1, int((x_max - x_min) / grid_size))
    nz = max(1, int((z_max - z_min) / grid_size))

    if nx > 500 or nz > 500:
        return []  # Too large

    grid = np.zeros((nz, nx), dtype=np.int32)
    for pt in xz:
        ix = min(int((pt[0] - x_min) / grid_size), nx - 1)
        iz = min(int((pt[1] - z_min) / grid_size), nz - 1)
        grid[iz, ix] += 1

    # Openings are connected regions of zeros
    openings = []
    visited = np.zeros_like(grid, dtype=bool)
    threshold = 2  # cells with <= threshold points are "empty"

    for z in range(nz):
        for x in range(nx):
            if visited[z, x] or grid[z, x] > threshold:
                continue
            # Flood fill to find connected empty region
            region = []
            stack = [(z, x)]
            while stack:
                cz, cx = stack.pop()
                if cz < 0 or cz >= nz or cx < 0 or cx >= nx:
                    continue
                if visited[cz, cx] or grid[cz, cx] > threshold:
                    continue
                visited[cz, cx] = True
                region.append((cx, cz))
                stack.extend([(cz+1, cx), (cz-1, cx), (cz, cx+1), (cz, cx-1)])

            if len(region) < 4:
                continue

            xs = [r[0] for r in region]
            zs = [r[1] for r in region]
            w_cells = max(xs) - min(xs) + 1
            h_cells = max(zs) - min(zs) + 1
            w_m = w_cells * grid_size
            h_m = h_cells * grid_size

            # Classify by size
            if 0.4 < w_m < 2.0 and 0.6 < h_m < 2.5:
                element_type = "window"
            elif 0.6 < w_m < 1.5 and h_m > 1.8:
                element_type = "door"
            elif w_m > 2.0 and h_m > 2.0:
                element_type = "storefront"
            else:
                element_type = "opening"

            openings.append({
                "type": element_type,
                "x_m": x_min + min(xs) * grid_size,
                "z_m": z_min + min(zs) * grid_size,
                "width_m": round(w_m, 2),
                "height_m": round(h_m, 2),
                "area_cells": len(region),
            })

    return openings


def extract_elements(mesh_path: Path, params: dict) -> dict:
    """Extract architectural elements from a building mesh.

    Args:
        mesh_path: Path to building PLY file.
        params: Building parameter dict.

    Returns:
        Dict with extracted elements per type.
    """
    points = load_mesh_points(mesh_path)
    if len(points) == 0:
        return {"error": "empty mesh", "elements": []}

    floor_heights = params.get("floor_heights_m", [3.0, 3.0])

    # Segment by floor
    floor_segments = segment_by_height(points, floor_heights)

    # Extract facade plane
    facade = extract_facade_plane(points)

    # Detect openings
    openings = cluster_openings(facade)

    # Compute element stats
    element_summary = {
        "total_points": len(points),
        "facade_points": len(facade),
        "floor_segments": {k: len(v) for k, v in floor_segments.items()},
        "detected_openings": len(openings),
        "elements": openings,
    }

    return element_summary


def main():
    parser = argparse.ArgumentParser(description="Extract elements from building meshes")
    parser.add_argument("--meshes", type=Path, default=REPO_ROOT / "meshes" / "per_building")
    parser.add_argument("--params", type=Path, default=REPO_ROOT / "params")
    parser.add_argument("--output", type=Path, default=REPO_ROOT / "assets" / "elements" / "metadata")
    parser.add_argument("--address", type=str, default=None)
    args = parser.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)
    stats = {"processed": 0, "elements_found": 0}

    for ply_file in sorted(args.meshes.glob("*.ply")):
        stem = ply_file.stem
        if args.address and args.address.lower().replace(" ", "_") not in stem.lower():
            continue

        param_file = args.params / f"{stem}.json"
        params = {}
        if param_file.exists():
            params = json.loads(param_file.read_text(encoding="utf-8"))

        result = extract_elements(ply_file, params)
        out_path = args.output / f"{stem}_elements.json"
        out_path.write_text(json.dumps(result, indent=2), encoding="utf-8")

        stats["processed"] += 1
        stats["elements_found"] += result.get("detected_openings", 0)
        print(f"  {stem}: {result.get('detected_openings', 0)} openings, "
              f"{result.get('total_points', 0)} points")

    print(f"\nElement extraction: {stats}")


if __name__ == "__main__":
    main()
