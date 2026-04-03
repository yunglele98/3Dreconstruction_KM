#!/usr/bin/env python3
"""Clip block-level photogrammetric mesh into per-building meshes.

After run_photogrammetry_block.py produces a street-level point cloud/mesh,
this script clips it into individual building meshes using PostGIS footprints
or bounding boxes from params.

Usage:
    python scripts/reconstruct/clip_block_mesh.py --block-mesh meshes/blocks/Augusta_Ave.obj --footprints postgis
    python scripts/reconstruct/clip_block_mesh.py --block-mesh meshes/blocks/Augusta_Ave.obj --footprints params
    python scripts/reconstruct/clip_block_mesh.py --block-ply point_clouds/colmap_blocks/Augusta_Ave/fused.ply --footprints params
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PARAMS_DIR = REPO_ROOT / "params"
OUTPUT_DIR = REPO_ROOT / "meshes" / "per_building"

ORIGIN_X = 312672.94
ORIGIN_Y = 4834994.86


def load_building_bounds(params_dir: Path, street_filter: str | None = None) -> list[dict]:
    """Load building bounding boxes from params."""
    bounds = []
    for f in sorted(params_dir.glob("*.json")):
        if f.name.startswith("_"):
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if data.get("skipped"):
            continue

        site = data.get("site", {})
        street = site.get("street", "")
        if street_filter and street_filter.lower() not in street.lower():
            continue

        lon = site.get("lon", 0)
        lat = site.get("lat", 0)
        width = data.get("facade_width_m", 5.0)
        depth = data.get("facade_depth_m", 10.0)
        height = data.get("total_height_m", 7.0)

        # Convert to local coords
        x = lon - ORIGIN_X if abs(lon) > 1000 else lon
        y = lat - ORIGIN_Y if abs(lat) > 1000 else lat

        address = data.get("_meta", {}).get("address") or data.get("building_name", f.stem)

        bounds.append({
            "address": address,
            "stem": f.stem,
            "x_min": x - width / 2,
            "x_max": x + width / 2,
            "y_min": y - depth / 2,
            "y_max": y + depth / 2,
            "z_min": 0,
            "z_max": height,
            "width": width,
            "depth": depth,
            "height": height,
        })

    return bounds


def load_ply(ply_path: Path) -> np.ndarray:
    """Load PLY point cloud as Nx3 numpy array (simple ASCII parser)."""
    points = []
    in_data = False
    vertex_count = 0

    with open(ply_path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if line.startswith("element vertex"):
                vertex_count = int(line.split()[-1])
            elif line == "end_header":
                in_data = True
                continue
            elif in_data:
                parts = line.split()
                if len(parts) >= 3:
                    try:
                        points.append([float(parts[0]), float(parts[1]), float(parts[2])])
                    except ValueError:
                        pass
                if len(points) >= vertex_count > 0:
                    break

    return np.array(points, dtype=np.float32) if points else np.zeros((0, 3), dtype=np.float32)


def clip_points(points: np.ndarray, bounds: dict) -> np.ndarray:
    """Clip point cloud to bounding box."""
    mask = (
        (points[:, 0] >= bounds["x_min"]) & (points[:, 0] <= bounds["x_max"]) &
        (points[:, 1] >= bounds["y_min"]) & (points[:, 1] <= bounds["y_max"]) &
        (points[:, 2] >= bounds["z_min"]) & (points[:, 2] <= bounds["z_max"])
    )
    return points[mask]


def save_ply(path: Path, points: np.ndarray):
    """Save Nx3 point cloud as ASCII PLY."""
    path.parent.mkdir(parents=True, exist_ok=True)
    n = len(points)
    with open(path, "w", encoding="utf-8") as f:
        f.write("ply\nformat ascii 1.0\n")
        f.write(f"element vertex {n}\n")
        f.write("property float x\nproperty float y\nproperty float z\n")
        f.write("end_header\n")
        for p in points:
            f.write(f"{p[0]:.6f} {p[1]:.6f} {p[2]:.6f}\n")


def clip_block(
    block_path: Path,
    params_dir: Path,
    output_dir: Path,
    street_filter: str | None = None,
) -> dict:
    """Clip a block point cloud into per-building clouds.

    Args:
        block_path: Path to block PLY file.
        params_dir: Building params directory.
        output_dir: Output directory for clipped PLYs.
        street_filter: Street name to filter buildings.

    Returns:
        Stats dict.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    points = load_ply(block_path)
    if len(points) == 0:
        return {"error": "Empty point cloud", "clipped": 0}

    bounds_list = load_building_bounds(params_dir, street_filter)
    stats = {"total_points": len(points), "buildings": len(bounds_list), "clipped": 0, "empty": 0}

    for bounds in bounds_list:
        clipped = clip_points(points, bounds)
        if len(clipped) < 10:
            stats["empty"] += 1
            continue

        out_path = output_dir / f"{bounds['stem']}.ply"
        save_ply(out_path, clipped)
        stats["clipped"] += 1

    return stats


def main():
    parser = argparse.ArgumentParser(description="Clip block mesh into per-building meshes")
    parser.add_argument("--block-ply", type=Path, required=True)
    parser.add_argument("--params", type=Path, default=PARAMS_DIR)
    parser.add_argument("--output", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--street", type=str, default=None)
    parser.add_argument("--footprints", choices=["params", "postgis"], default="params")
    args = parser.parse_args()

    stats = clip_block(args.block_ply, args.params, args.output, args.street)
    print(f"Clip block: {stats}")


if __name__ == "__main__":
    main()
