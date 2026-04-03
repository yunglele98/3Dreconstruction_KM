#!/usr/bin/env python3
"""Fuse LiDAR point cloud data into building params.

Reads per-building LiDAR clips (.laz/.ply) and extracts precise
heights, roof geometry, and wall planes to refine params.

Usage:
    python scripts/enrich/fuse_lidar.py --lidar lidar/building/ --params params/
    python scripts/enrich/fuse_lidar.py --lidar lidar/building/ --params params/ --apply
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)
REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def load_point_cloud(path: Path) -> np.ndarray | None:
    """Load point cloud from PLY or LAZ file."""
    if path.suffix.lower() == ".ply":
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
        return np.array(points, dtype=np.float32) if points else None
    elif path.suffix.lower() in (".laz", ".las"):
        try:
            import laspy
            las = laspy.read(str(path))
            return np.stack([las.x, las.y, las.z], axis=1).astype(np.float32)
        except ImportError:
            logger.warning("laspy not installed, cannot read LAZ files")
            return None
    return None


def analyze_lidar(points: np.ndarray) -> dict:
    """Extract building measurements from LiDAR point cloud."""
    z = points[:, 2]
    z_ground = np.percentile(z, 2)
    z_roof = np.percentile(z, 98)
    z_eave = np.percentile(z, 90)

    height = float(z_roof - z_ground)
    eave_height = float(z_eave - z_ground)
    ridge_height = float(z_roof - z_eave)

    # Estimate roof type from height profile
    if ridge_height < 0.5:
        roof_type_est = "flat"
        roof_pitch_est = 0.0
    elif ridge_height < 2.0:
        roof_type_est = "hip"
        roof_pitch_est = 20.0
    else:
        roof_type_est = "gable"
        roof_pitch_est = 35.0

    # Estimate footprint from XY extent
    x_range = float(np.ptp(points[:, 0]))
    y_range = float(np.ptp(points[:, 1]))

    return {
        "height_m": round(height, 2),
        "eave_height_m": round(eave_height, 2),
        "ridge_height_m": round(float(z_roof - z_ground), 2),
        "roof_type_est": roof_type_est,
        "roof_pitch_est": round(roof_pitch_est, 1),
        "footprint_width_m": round(x_range, 2),
        "footprint_depth_m": round(y_range, 2),
        "point_count": len(points),
    }


def fuse_lidar_into_params(
    lidar_dir: Path, params_dir: Path, apply: bool = False
) -> dict:
    """Fuse LiDAR measurements into params. Only updates height if
    LiDAR measurement differs by > 1m from current value."""
    stats = {"updated": 0, "skipped": 0, "no_lidar": 0}

    for param_file in sorted(params_dir.glob("*.json")):
        if param_file.name.startswith("_"):
            continue
        try:
            data = json.loads(param_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if data.get("skipped"):
            continue

        meta = data.get("_meta", {})
        if "lidar" in (meta.get("fusion_applied") or []):
            stats["skipped"] += 1
            continue

        stem = param_file.stem
        lidar_path = None
        for ext in [".ply", ".laz", ".las"]:
            candidate = lidar_dir / f"{stem}{ext}"
            if candidate.exists():
                lidar_path = candidate
                break

        if not lidar_path:
            stats["no_lidar"] += 1
            continue

        points = load_point_cloud(lidar_path)
        if points is None or len(points) < 50:
            stats["no_lidar"] += 1
            continue

        analysis = analyze_lidar(points)

        # Only update height if LiDAR differs significantly (>1m)
        current_height = data.get("total_height_m", 0)
        if abs(analysis["height_m"] - current_height) > 1.0:
            data["total_height_m"] = analysis["height_m"]
            data["city_data"] = data.get("city_data", {})
            data["city_data"]["height_lidar_m"] = analysis["height_m"]

        # Store LiDAR analysis
        data["lidar_analysis"] = analysis

        if "_meta" not in data:
            data["_meta"] = {}
        if "fusion_applied" not in data["_meta"]:
            data["_meta"]["fusion_applied"] = []
        data["_meta"]["fusion_applied"].append("lidar")

        if apply:
            param_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        stats["updated"] += 1

    return stats


def main():
    parser = argparse.ArgumentParser(description="Fuse LiDAR into params")
    parser.add_argument("--lidar", type=Path, default=REPO_ROOT / "data" / "lidar" / "building")
    parser.add_argument("--params", type=Path, default=REPO_ROOT / "params")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    stats = fuse_lidar_into_params(args.lidar, args.params, args.apply)
    print(f"LiDAR fusion ({'APPLIED' if args.apply else 'DRY RUN'}): {stats}")


if __name__ == "__main__":
    main()
