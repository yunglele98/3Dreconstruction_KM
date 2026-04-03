#!/usr/bin/env python3
"""Fuse LiDAR point cloud observations into building parameter files.

Reads per-building .laz/.las clips from Stage 2 and extracts precise
total_height_m and roof_pitch estimates from point cloud statistics.
Results are written into each param's `lidar_observations` dict, and
"lidar" is appended to `_meta.fusion_applied`.

Usage:
    python scripts/enrich/fuse_lidar.py
    python scripts/enrich/fuse_lidar.py --lidar data/lidar/building/ --params params/
"""

import argparse
import json
import math
import os
import struct
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _atomic_write_json(filepath, data, ensure_ascii=False):
    """Write JSON atomically via temp file + rename to prevent corruption."""
    filepath = Path(filepath)
    with tempfile.NamedTemporaryFile(
        mode="w", dir=filepath.parent, delete=False,
        suffix=".tmp", encoding="utf-8",
    ) as tmp:
        json.dump(data, tmp, indent=2, ensure_ascii=ensure_ascii)
        tmp.write("\n")
        tmp_path = Path(tmp.name)
    os.replace(str(tmp_path), str(filepath))


def _sanitize_address(filename):
    """Convert param filename to address key: strip .json, replace _ with space."""
    return Path(filename).stem.replace("_", " ")


def _address_to_stem(address):
    """Convert address string to filename stem (spaces to underscores)."""
    return address.replace(" ", "_")


def _find_lidar_clip(lidar_dir, address):
    """Find a matching .laz or .las file for an address."""
    stem = _address_to_stem(address)
    for ext in (".laz", ".las"):
        candidate = lidar_dir / f"{stem}{ext}"
        if candidate.exists():
            return candidate
    # Case-insensitive search
    stem_lower = stem.lower()
    for f in lidar_dir.iterdir():
        if f.suffix.lower() in (".laz", ".las") and f.stem.lower() == stem_lower:
            return f
    return None


def _read_las_header_stats(las_path):
    """Read basic Z statistics from a LAS/LAZ file header.

    Parses the LAS 1.2+ public header block to extract min/max Z values
    and point count. This avoids needing laspy/pdal dependencies.
    Returns dict with z_min, z_max, point_count, or None on failure.
    """
    try:
        with open(las_path, "rb") as f:
            # LAS file signature
            sig = f.read(4)
            if sig != b"LASF":
                return None

            # Skip to point count (offset 107 for LAS 1.2)
            f.seek(0)
            header = f.read(375)  # Read enough for LAS 1.2+ header

            if len(header) < 235:
                return None

            # Version major/minor at offset 24-25
            version_major = struct.unpack("B", header[24:25])[0]
            version_minor = struct.unpack("B", header[25:26])[0]

            # Number of point records at offset 107 (legacy, 4 bytes)
            point_count = struct.unpack("<I", header[107:111])[0]

            # X/Y/Z scale factors at offset 131 (3 doubles)
            x_scale, y_scale, z_scale = struct.unpack("<3d", header[131:155])

            # X/Y/Z offsets at offset 155 (3 doubles)
            x_offset, y_offset, z_offset = struct.unpack("<3d", header[155:179])

            # Max X, Min X, Max Y, Min Y, Max Z, Min Z at offset 179 (6 doubles)
            max_x, min_x, max_y, min_y, max_z, min_z = struct.unpack(
                "<6d", header[179:227]
            )

            return {
                "z_min": round(min_z, 3),
                "z_max": round(max_z, 3),
                "x_min": round(min_x, 3),
                "x_max": round(max_x, 3),
                "y_min": round(min_y, 3),
                "y_max": round(max_y, 3),
                "point_count": point_count,
                "version": f"{version_major}.{version_minor}",
            }
    except Exception:
        return None


def _estimate_from_lidar(stats):
    """Estimate building measurements from LiDAR point cloud header stats."""
    if not stats:
        return {}

    observations = {}

    # Total height from Z range
    z_range = stats["z_max"] - stats["z_min"]
    if z_range > 0:
        observations["total_height_m"] = round(z_range, 2)

    # Footprint dimensions from X/Y range
    x_range = stats["x_max"] - stats["x_min"]
    y_range = stats["y_max"] - stats["y_min"]
    if x_range > 0:
        observations["footprint_width_m"] = round(x_range, 2)
    if y_range > 0:
        observations["footprint_depth_m"] = round(y_range, 2)

    # Rough roof pitch estimate: if height > half of shorter dimension,
    # assume a pitched roof. Estimate angle from height/run ratio of
    # the top ~20% of the Z range vs half the shorter plan dimension.
    if z_range > 0 and x_range > 0 and y_range > 0:
        shorter_plan = min(x_range, y_range)
        # Assume top 20% of Z range is roof
        roof_rise = z_range * 0.2
        roof_run = shorter_plan / 2.0
        if roof_run > 0:
            pitch_rad = math.atan2(roof_rise, roof_run)
            pitch_deg = math.degrees(pitch_rad)
            if 5.0 < pitch_deg < 60.0:
                observations["roof_pitch_estimate_deg"] = round(pitch_deg, 1)

    observations["point_count"] = stats["point_count"]
    observations["z_min"] = stats["z_min"]
    observations["z_max"] = stats["z_max"]

    return observations


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def fuse_lidar(lidar_dir, params_dir):
    """Fuse LiDAR data into all matching param files."""
    lidar_dir = Path(lidar_dir)
    params_dir = Path(params_dir)

    fused = 0
    skipped_no_data = 0
    skipped_already = 0
    skipped_other = 0

    for param_file in sorted(params_dir.glob("*.json")):
        # Skip metadata files
        if param_file.name.startswith("_"):
            skipped_other += 1
            continue

        with open(param_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Skip non-building entries
        if data.get("skipped"):
            skipped_other += 1
            continue

        # Check idempotency
        meta = data.setdefault("_meta", {})
        fusion_applied = meta.setdefault("fusion_applied", [])
        if "lidar" in fusion_applied:
            skipped_already += 1
            continue

        # Find matching LiDAR clip
        address = _sanitize_address(param_file.name)
        lidar_file = _find_lidar_clip(lidar_dir, address)
        if lidar_file is None:
            skipped_no_data += 1
            continue

        stats = _read_las_header_stats(lidar_file)
        observations = _estimate_from_lidar(stats)
        if not observations:
            skipped_no_data += 1
            continue

        observations["source_file"] = lidar_file.name

        # Write into params
        data["lidar_observations"] = observations
        fusion_applied.append("lidar")

        _atomic_write_json(param_file, data)
        fused += 1

    print(f"Fused {fused} buildings, skipped {skipped_no_data} (no data), "
          f"skipped {skipped_already} (already fused)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Fuse LiDAR point cloud observations into building params"
    )
    parser.add_argument(
        "--lidar", type=Path, default=REPO_ROOT / "data" / "lidar" / "building",
        help="Directory containing per-building .laz/.las clips (default: data/lidar/building/)"
    )
    parser.add_argument(
        "--params", type=Path, default=REPO_ROOT / "params",
        help="Directory containing building param JSON files (default: params/)"
    )
    args = parser.parse_args()
    fuse_lidar(args.lidar, args.params)
