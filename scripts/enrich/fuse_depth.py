#!/usr/bin/env python3
"""Fuse depth map observations into building parameter files.

Reads .npy depth maps from Stage 1 (Depth Anything v2) and extracts
estimated wall height, foundation height, and setback from depth
gradients. Results are written into each param's `depth_observations`
dict, and "depth" is appended to `_meta.fusion_applied`.

Usage:
    python scripts/enrich/fuse_depth.py
    python scripts/enrich/fuse_depth.py --depth-maps depth_maps/ --params params/
"""

import argparse
import json
import os
import re
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


def _find_depth_map(depth_dir, address):
    """Find a matching depth map .npy file for an address.

    Tries exact stem match first, then case-insensitive glob.
    """
    stem = _address_to_stem(address)
    # Direct match
    candidate = depth_dir / f"{stem}.npy"
    if candidate.exists():
        return candidate
    # Try case-insensitive search
    stem_lower = stem.lower()
    for f in depth_dir.glob("*.npy"):
        if f.stem.lower() == stem_lower:
            return f
    return None


def _read_npy_stats(npy_path):
    """Read basic stats from a .npy file (float32/float64) without numpy.

    Returns dict with min, max, mean, median_approx, or None on failure.
    """
    try:
        with open(npy_path, "rb") as f:
            # Read .npy header
            magic = f.read(6)
            if magic[:6] != b"\x93NUMPY":
                return None
            version_major = struct.unpack("B", f.read(1))[0]
            f.read(1)  # version minor
            if version_major == 1:
                header_len = struct.unpack("<H", f.read(2))[0]
            else:
                header_len = struct.unpack("<I", f.read(4))[0]
            header_str = f.read(header_len).decode("latin1")

            # Parse dtype and shape from header
            descr_match = re.search(r"'descr'\s*:\s*'([^']+)'", header_str)
            shape_match = re.search(r"'shape'\s*:\s*\(([^)]*)\)", header_str)
            if not descr_match or not shape_match:
                return None

            descr = descr_match.group(1)
            shape_str = shape_match.group(1).strip()
            if not shape_str:
                return None
            shape = tuple(int(s.strip()) for s in shape_str.split(",") if s.strip())
            total_elements = 1
            for s in shape:
                total_elements *= s

            if "<f4" in descr or "float32" in descr:
                fmt_char, elem_size = "f", 4
            elif "<f8" in descr or "float64" in descr:
                fmt_char, elem_size = "d", 8
            else:
                return None

            data_bytes = f.read(total_elements * elem_size)
            if len(data_bytes) < total_elements * elem_size:
                return None

            values = list(struct.unpack(f"<{total_elements}{fmt_char}", data_bytes))

        if not values:
            return None

        values_sorted = sorted(values)
        n = len(values_sorted)
        val_min = values_sorted[0]
        val_max = values_sorted[-1]
        val_mean = sum(values) / n
        val_median = values_sorted[n // 2]

        return {
            "min": round(val_min, 4),
            "max": round(val_max, 4),
            "mean": round(val_mean, 4),
            "median": round(val_median, 4),
            "pixel_count": n,
            "height": shape[0] if len(shape) >= 2 else shape[0],
            "width": shape[1] if len(shape) >= 2 else 1,
        }
    except Exception:
        return None


def _estimate_from_depth(stats):
    """Estimate building measurements from depth map statistics.

    Depth maps encode relative depth; we derive proportional estimates.
    """
    if not stats:
        return {}

    depth_range = stats["max"] - stats["min"]
    if depth_range <= 0:
        return {}

    observations = {}

    # Wall height estimate: proportional to depth range scaled to typical
    # 2-3 storey Kensington heights (6-10m)
    if depth_range > 0.01:
        observations["wall_height_estimate_m"] = round(depth_range * 10.0, 2)

    # Foundation height: typically the bottom ~5-10% of depth gradient
    if stats.get("height", 0) > 10:
        foundation_ratio = 0.08
        observations["foundation_height_estimate_m"] = round(
            depth_range * foundation_ratio * 10.0, 2
        )

    # Setback estimate from median depth vs min (closer = less setback)
    median_offset = stats["median"] - stats["min"]
    if depth_range > 0.01:
        setback_ratio = median_offset / depth_range
        observations["setback_estimate_m"] = round(setback_ratio * 3.0, 2)

    observations["depth_range"] = round(depth_range, 4)
    observations["depth_mean"] = stats["mean"]
    observations["depth_median"] = stats["median"]

    return observations


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def fuse_depth(depth_dir, params_dir):
    """Fuse depth map data into all matching param files."""
    depth_dir = Path(depth_dir)
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
        if "depth" in fusion_applied:
            skipped_already += 1
            continue

        # Find matching depth map
        address = _sanitize_address(param_file.name)
        depth_map = _find_depth_map(depth_dir, address)
        if depth_map is None:
            skipped_no_data += 1
            continue

        # Extract stats and derive observations
        stats = _read_npy_stats(depth_map)
        observations = _estimate_from_depth(stats)
        if not observations:
            skipped_no_data += 1
            continue

        observations["source_file"] = depth_map.name

        # Write into params
        data["depth_observations"] = observations
        fusion_applied.append("depth")

        _atomic_write_json(param_file, data)
        fused += 1

    print(f"Fused {fused} buildings, skipped {skipped_no_data} (no data), "
          f"skipped {skipped_already} (already fused)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Fuse depth map observations into building params"
    )
    parser.add_argument(
        "--depth-maps", type=Path, default=REPO_ROOT / "depth_maps",
        help="Directory containing .npy depth maps (default: depth_maps/)"
    )
    parser.add_argument(
        "--params", type=Path, default=REPO_ROOT / "params",
        help="Directory containing building param JSON files (default: params/)"
    )
    args = parser.parse_args()
    fuse_depth(args.depth_maps, args.params)
