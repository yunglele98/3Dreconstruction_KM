#!/usr/bin/env python3
"""Deep analysis of a single COLMAP sparse model for manual inspection.

Reads COLMAP binary model files (cameras.bin, images.bin, points3D.bin)
and reports detailed statistics: camera intrinsics, per-image registration,
pose graph, point cloud distribution, and coverage completeness.

Falls back to text format (.txt) if binary files are not found.

Usage:
    python scripts/reconstruct/analyze_sparse_model.py --model point_clouds/colmap/22_Lippincott_St/sparse/0/
    python scripts/reconstruct/analyze_sparse_model.py --model point_clouds/colmap/22_Lippincott_St/sparse/0/ --output sparse_analysis.json
"""

from __future__ import annotations

import argparse
import json
import math
import struct
import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# COLMAP camera model names and parameter counts
CAMERA_MODELS = {
    0: ("SIMPLE_PINHOLE", 3),
    1: ("PINHOLE", 4),
    2: ("SIMPLE_RADIAL", 4),
    3: ("RADIAL", 5),
    4: ("OPENCV", 8),
    5: ("OPENCV_FISHEYE", 12),
    6: ("FULL_OPENCV", 12),
    7: ("FOV", 5),
    8: ("SIMPLE_RADIAL_FISHEYE", 4),
    9: ("RADIAL_FISHEYE", 5),
    10: ("THIN_PRISM_FISHEYE", 12),
}


# ---------------------------------------------------------------------------
# Binary parsers
# ---------------------------------------------------------------------------

def read_cameras_bin(path):
    """Parse COLMAP cameras.bin."""
    cameras = {}
    if not path.exists():
        return cameras
    try:
        with open(path, "rb") as f:
            num = struct.unpack("<Q", f.read(8))[0]
            for _ in range(num):
                cid = struct.unpack("<I", f.read(4))[0]
                mid = struct.unpack("<i", f.read(4))[0]
                w = struct.unpack("<Q", f.read(8))[0]
                h = struct.unpack("<Q", f.read(8))[0]
                model_name, np = CAMERA_MODELS.get(mid, ("UNKNOWN", 4))
                params = list(struct.unpack(f"<{np}d", f.read(8 * np)))
                cameras[cid] = {
                    "camera_id": cid,
                    "model": model_name,
                    "model_id": mid,
                    "width": w,
                    "height": h,
                    "params": params,
                    "focal_length": params[0] if params else None,
                }
    except (struct.error, OSError) as e:
        print(f"  WARNING: Failed to parse cameras.bin: {e}")
    return cameras


def read_images_bin(path):
    """Parse COLMAP images.bin, return dict image_id -> image info."""
    images = {}
    if not path.exists():
        return images
    try:
        with open(path, "rb") as f:
            num = struct.unpack("<Q", f.read(8))[0]
            for _ in range(num):
                iid = struct.unpack("<I", f.read(4))[0]
                qw, qx, qy, qz = struct.unpack("<4d", f.read(32))
                tx, ty, tz = struct.unpack("<3d", f.read(24))
                cid = struct.unpack("<I", f.read(4))[0]
                name_bytes = b""
                while True:
                    ch = f.read(1)
                    if ch == b"\x00" or ch == b"":
                        break
                    name_bytes += ch
                name = name_bytes.decode("utf-8", errors="replace")
                n2d = struct.unpack("<Q", f.read(8))[0]
                matched = 0
                point3d_ids = []
                for _ in range(n2d):
                    _x, _y = struct.unpack("<2d", f.read(16))
                    p3id = struct.unpack("<q", f.read(8))[0]
                    if p3id != -1:
                        matched += 1
                        point3d_ids.append(p3id)
                images[iid] = {
                    "image_id": iid,
                    "name": name,
                    "camera_id": cid,
                    "qvec": [qw, qx, qy, qz],
                    "tvec": [tx, ty, tz],
                    "num_points2d": n2d,
                    "num_matched": matched,
                    "point3d_ids": point3d_ids,
                }
    except (struct.error, OSError) as e:
        print(f"  WARNING: Failed to parse images.bin: {e}")
    return images


def read_points3d_bin(path):
    """Parse COLMAP points3D.bin, return dict point_id -> point info."""
    points = {}
    if not path.exists():
        return points
    try:
        with open(path, "rb") as f:
            num = struct.unpack("<Q", f.read(8))[0]
            for _ in range(num):
                pid = struct.unpack("<Q", f.read(8))[0]
                x, y, z = struct.unpack("<3d", f.read(24))
                r, g, b = struct.unpack("<3B", f.read(3))
                error = struct.unpack("<d", f.read(8))[0]
                tlen = struct.unpack("<Q", f.read(8))[0]
                track = []
                for _ in range(tlen):
                    img_id = struct.unpack("<I", f.read(4))[0]
                    pt2d_idx = struct.unpack("<I", f.read(4))[0]
                    track.append((img_id, pt2d_idx))
                points[pid] = {
                    "xyz": [x, y, z],
                    "rgb": [r, g, b],
                    "error": error,
                    "track_length": tlen,
                    "track_image_ids": [t[0] for t in track],
                }
    except (struct.error, OSError) as e:
        print(f"  WARNING: Failed to parse points3D.bin: {e}")
    return points


# ---------------------------------------------------------------------------
# Text format parsers (fallback)
# ---------------------------------------------------------------------------

def read_cameras_txt(path):
    """Parse COLMAP cameras.txt."""
    cameras = {}
    if not path.exists():
        return cameras
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split()
                cid = int(parts[0])
                model_name = parts[1]
                w = int(parts[2])
                h = int(parts[3])
                params = [float(x) for x in parts[4:]]
                cameras[cid] = {
                    "camera_id": cid,
                    "model": model_name,
                    "width": w,
                    "height": h,
                    "params": params,
                    "focal_length": params[0] if params else None,
                }
    except (OSError, ValueError) as e:
        print(f"  WARNING: Failed to parse cameras.txt: {e}")
    return cameras


def read_images_txt(path):
    """Parse COLMAP images.txt."""
    images = {}
    if not path.exists():
        return images
    try:
        with open(path, encoding="utf-8") as f:
            lines = [l.strip() for l in f if l.strip() and not l.startswith("#")]
        i = 0
        while i < len(lines) - 1:
            parts = lines[i].split()
            iid = int(parts[0])
            qw, qx, qy, qz = float(parts[1]), float(parts[2]), float(parts[3]), float(parts[4])
            tx, ty, tz = float(parts[5]), float(parts[6]), float(parts[7])
            cid = int(parts[8])
            name = parts[9]
            # Next line has 2D points
            pts_line = lines[i + 1].split()
            n2d = len(pts_line) // 3
            matched = 0
            point3d_ids = []
            for j in range(n2d):
                p3id = int(float(pts_line[j * 3 + 2]))
                if p3id != -1:
                    matched += 1
                    point3d_ids.append(p3id)
            images[iid] = {
                "image_id": iid,
                "name": name,
                "camera_id": cid,
                "qvec": [qw, qx, qy, qz],
                "tvec": [tx, ty, tz],
                "num_points2d": n2d,
                "num_matched": matched,
                "point3d_ids": point3d_ids,
            }
            i += 2
    except (OSError, ValueError, IndexError) as e:
        print(f"  WARNING: Failed to parse images.txt: {e}")
    return images


def read_points3d_txt(path):
    """Parse COLMAP points3D.txt."""
    points = {}
    if not path.exists():
        return points
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split()
                pid = int(parts[0])
                x, y, z = float(parts[1]), float(parts[2]), float(parts[3])
                r, g, b = int(parts[4]), int(parts[5]), int(parts[6])
                error = float(parts[7])
                track_parts = parts[8:]
                tlen = len(track_parts) // 2
                track_image_ids = [int(track_parts[k * 2]) for k in range(tlen)]
                points[pid] = {
                    "xyz": [x, y, z],
                    "rgb": [r, g, b],
                    "error": error,
                    "track_length": tlen,
                    "track_image_ids": track_image_ids,
                }
    except (OSError, ValueError, IndexError) as e:
        print(f"  WARNING: Failed to parse points3D.txt: {e}")
    return points


# ---------------------------------------------------------------------------
# Analysis functions
# ---------------------------------------------------------------------------

def camera_position_from_image(img):
    """Compute camera center in world coordinates from qvec + tvec."""
    q = img["qvec"]  # [qw, qx, qy, qz]
    t = img["tvec"]  # [tx, ty, tz]
    # Rotation matrix from quaternion
    qw, qx, qy, qz = q
    r00 = 1 - 2 * (qy * qy + qz * qz)
    r01 = 2 * (qx * qy - qz * qw)
    r02 = 2 * (qx * qz + qy * qw)
    r10 = 2 * (qx * qy + qz * qw)
    r11 = 1 - 2 * (qx * qx + qz * qz)
    r12 = 2 * (qy * qz - qx * qw)
    r20 = 2 * (qx * qz - qy * qw)
    r21 = 2 * (qy * qz + qx * qw)
    r22 = 1 - 2 * (qx * qx + qy * qy)
    # Camera center = -R^T * t
    cx = -(r00 * t[0] + r10 * t[1] + r20 * t[2])
    cy = -(r01 * t[0] + r11 * t[1] + r21 * t[2])
    cz = -(r02 * t[0] + r12 * t[1] + r22 * t[2])
    return [cx, cy, cz]


def compute_baselines(images):
    """Compute baseline distances between all camera pairs."""
    positions = {}
    for iid, img in images.items():
        positions[iid] = camera_position_from_image(img)

    baselines = []
    ids = sorted(positions.keys())
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            p1 = positions[ids[i]]
            p2 = positions[ids[j]]
            dist = math.sqrt(sum((a - b) ** 2 for a, b in zip(p1, p2)))
            baselines.append({
                "image_a": images[ids[i]]["name"],
                "image_b": images[ids[j]]["name"],
                "distance": round(dist, 4),
            })
    return baselines, positions


def compute_covisibility(images):
    """Compute which images share 3D points (covisibility graph)."""
    # Build point -> images mapping from image point3d_ids
    point_to_images = defaultdict(set)
    for iid, img in images.items():
        for pid in img.get("point3d_ids", []):
            point_to_images[pid].add(iid)

    # Count shared points between image pairs
    pair_counts = defaultdict(int)
    for pid, img_ids in point_to_images.items():
        img_list = sorted(img_ids)
        for i in range(len(img_list)):
            for j in range(i + 1, len(img_list)):
                pair_counts[(img_list[i], img_list[j])] += 1

    covis = []
    for (a, b), count in sorted(pair_counts.items(), key=lambda x: -x[1]):
        covis.append({
            "image_a": images[a]["name"],
            "image_b": images[b]["name"],
            "shared_points": count,
        })
    return covis


def compute_density_grid(points, grid_size=10):
    """Divide point cloud bbox into grid and count points per cell."""
    if not points:
        return {}
    coords = [p["xyz"] for p in points.values()]
    xs = [c[0] for c in coords]
    ys = [c[1] for c in coords]
    zs = [c[2] for c in coords]
    x_min, x_max = min(xs), max(xs)
    y_min, y_max = min(ys), max(ys)
    z_min, z_max = min(zs), max(zs)

    dx = max(x_max - x_min, 0.001) / grid_size
    dy = max(y_max - y_min, 0.001) / grid_size
    dz = max(z_max - z_min, 0.001) / grid_size

    grid = defaultdict(int)
    for c in coords:
        ix = min(int((c[0] - x_min) / dx), grid_size - 1)
        iy = min(int((c[1] - y_min) / dy), grid_size - 1)
        iz = min(int((c[2] - z_min) / dz), grid_size - 1)
        grid[(ix, iy, iz)] += 1

    total_cells = grid_size ** 3
    occupied = len(grid)
    counts = list(grid.values())
    max_count = max(counts) if counts else 0
    min_count = min(counts) if counts else 0
    avg_count = sum(counts) / len(counts) if counts else 0

    return {
        "grid_size": grid_size,
        "total_cells": total_cells,
        "occupied_cells": occupied,
        "occupancy_ratio": round(occupied / total_cells, 4),
        "min_points_per_cell": min_count,
        "max_points_per_cell": max_count,
        "avg_points_per_cell": round(avg_count, 1),
    }


def compute_color_distribution(points, num_buckets=6):
    """Compute HSV hue histogram from point colors."""
    hue_buckets = [0] * num_buckets
    bucket_names = ["red", "yellow", "green", "cyan", "blue", "magenta"]
    for p in points.values():
        r, g, b = p["rgb"]
        # Simple RGB to hue
        r_f, g_f, b_f = r / 255.0, g / 255.0, b / 255.0
        c_max = max(r_f, g_f, b_f)
        c_min = min(r_f, g_f, b_f)
        delta = c_max - c_min
        if delta < 0.01:
            # Grey/neutral, skip or put in red bucket
            continue
        if c_max == r_f:
            hue = 60 * (((g_f - b_f) / delta) % 6)
        elif c_max == g_f:
            hue = 60 * ((b_f - r_f) / delta + 2)
        else:
            hue = 60 * ((r_f - g_f) / delta + 4)
        bucket_idx = min(int(hue / 60), num_buckets - 1)
        hue_buckets[bucket_idx] += 1

    total = sum(hue_buckets)
    return {
        bucket_names[i]: {
            "count": hue_buckets[i],
            "pct": round(hue_buckets[i] / total * 100, 1) if total else 0,
        }
        for i in range(num_buckets)
    }


def analyze_model(model_dir, expected_images=None):
    """Full analysis of a single COLMAP sparse model."""
    model_dir = Path(model_dir)
    result = {
        "model_dir": str(model_dir),
        "format": None,
    }

    # Detect format (binary preferred)
    has_bin = (model_dir / "cameras.bin").exists()
    has_txt = (model_dir / "cameras.txt").exists()

    if has_bin:
        result["format"] = "binary"
        cameras = read_cameras_bin(model_dir / "cameras.bin")
        images = read_images_bin(model_dir / "images.bin")
        points = read_points3d_bin(model_dir / "points3D.bin")
    elif has_txt:
        result["format"] = "text"
        cameras = read_cameras_txt(model_dir / "cameras.txt")
        images = read_images_txt(model_dir / "images.txt")
        points = read_points3d_txt(model_dir / "points3D.txt")
    else:
        result["format"] = None
        result["error"] = "No cameras.bin or cameras.txt found"
        return result

    # --- Camera intrinsics ---
    camera_summary = []
    for cid, cam in sorted(cameras.items()):
        entry = {
            "camera_id": cid,
            "model": cam.get("model", f"id={cam.get('model_id')}"),
            "resolution": f"{cam['width']}x{cam['height']}",
            "focal_length": cam["focal_length"],
        }
        if len(cam["params"]) > 1:
            entry["all_params"] = [round(p, 4) for p in cam["params"]]
        camera_summary.append(entry)
    result["cameras"] = camera_summary

    # --- Image registration ---
    registered_names = set()
    image_details = []
    for iid, img in sorted(images.items()):
        registered_names.add(img["name"])
        image_details.append({
            "name": img["name"],
            "camera_id": img["camera_id"],
            "num_observations": img["num_points2d"],
            "num_matched_3d": img["num_matched"],
            "match_ratio": round(
                img["num_matched"] / img["num_points2d"], 4
            ) if img["num_points2d"] > 0 else 0,
        })
    image_details.sort(key=lambda x: -x["num_matched_3d"])

    result["registered_images"] = {
        "count": len(images),
        "images": image_details,
    }

    # If expected images provided, find which failed
    if expected_images:
        failed = sorted(set(expected_images) - registered_names)
        result["registration_failures"] = failed
        result["registration_ratio"] = round(
            len(images) / len(expected_images), 4
        ) if expected_images else 0

    # --- Pose graph (baselines) ---
    if len(images) <= 50:
        # Only compute all pairs for small models
        baselines, positions = compute_baselines(images)
        if baselines:
            dists = [b["distance"] for b in baselines]
            result["baselines"] = {
                "count": len(baselines),
                "min_distance": round(min(dists), 4),
                "max_distance": round(max(dists), 4),
                "mean_distance": round(sum(dists) / len(dists), 4),
                "pairs": baselines[:20],  # top 20 only
            }
    else:
        # For large models, just compute stats
        _baselines, positions = compute_baselines(images)
        if _baselines:
            dists = [b["distance"] for b in _baselines]
            result["baselines"] = {
                "count": len(_baselines),
                "min_distance": round(min(dists), 4),
                "max_distance": round(max(dists), 4),
                "mean_distance": round(sum(dists) / len(dists), 4),
                "note": "Pair list omitted for large model (>50 images)",
            }

    # --- Covisibility graph ---
    covis = compute_covisibility(images)
    if covis:
        result["covisibility"] = {
            "total_pairs": len(covis),
            "top_10": covis[:10],
        }

    # --- Point cloud stats ---
    result["point_cloud"] = {"total_points": len(points)}
    if points:
        errors = [p["error"] for p in points.values()]
        track_lengths = [p["track_length"] for p in points.values()]
        sorted_errors = sorted(errors)

        coords = [p["xyz"] for p in points.values()]
        xs = [c[0] for c in coords]
        ys = [c[1] for c in coords]
        zs = [c[2] for c in coords]

        result["point_cloud"].update({
            "mean_reprojection_error": round(sum(errors) / len(errors), 4),
            "median_reprojection_error": round(
                sorted_errors[len(sorted_errors) // 2], 4
            ),
            "p95_reprojection_error": round(
                sorted_errors[int(len(sorted_errors) * 0.95)], 4
            ),
            "mean_track_length": round(
                sum(track_lengths) / len(track_lengths), 2
            ),
            "bbox": {
                "min": [round(min(xs), 3), round(min(ys), 3), round(min(zs), 3)],
                "max": [round(max(xs), 3), round(max(ys), 3), round(max(zs), 3)],
                "extent": [
                    round(max(xs) - min(xs), 3),
                    round(max(ys) - min(ys), 3),
                    round(max(zs) - min(zs), 3),
                ],
            },
        })

        # Density grid
        result["point_cloud"]["density_grid"] = compute_density_grid(points)

        # Color distribution
        result["point_cloud"]["color_distribution"] = compute_color_distribution(points)

    return result


def main():
    parser = argparse.ArgumentParser(
        description="Deep analysis of a single COLMAP sparse model."
    )
    parser.add_argument("--model", type=Path, required=True,
                        help="Path to COLMAP sparse model directory (e.g. sparse/0/)")
    parser.add_argument("--output", type=Path, default=None,
                        help="Output JSON path (default: alongside model as sparse_analysis.json)")
    parser.add_argument("--expected-images", type=Path, default=None,
                        help="Directory of input images to check registration completeness")
    args = parser.parse_args()

    if not args.model.exists():
        print(f"ERROR: Model directory not found: {args.model}")
        sys.exit(1)

    # Collect expected image names if provided
    expected = None
    if args.expected_images and args.expected_images.exists():
        expected = [
            f.name for f in args.expected_images.iterdir()
            if f.is_file() and f.suffix.lower() in (".jpg", ".jpeg", ".png", ".tif", ".tiff")
        ]
    else:
        # Try to find images dir as sibling
        candidate = args.model.parent.parent / "images"
        if candidate.exists():
            expected = [
                f.name for f in candidate.iterdir()
                if f.is_file() and f.suffix.lower() in (".jpg", ".jpeg", ".png", ".tif", ".tiff")
            ]

    print(f"Analyzing sparse model: {args.model}")
    result = analyze_model(args.model, expected_images=expected)

    if "error" in result:
        print(f"ERROR: {result['error']}")
        sys.exit(1)

    # Determine output path
    if args.output:
        out_path = args.output
    else:
        out_path = args.model / "sparse_analysis.json"

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"Wrote {out_path}")

    # Print summary
    fmt = result.get("format", "?")
    n_cam = len(result.get("cameras", []))
    n_img = result.get("registered_images", {}).get("count", 0)
    n_pts = result.get("point_cloud", {}).get("total_points", 0)
    err = result.get("point_cloud", {}).get("mean_reprojection_error", "n/a")
    print(f"\n  Format: {fmt}")
    print(f"  Cameras: {n_cam}")
    print(f"  Registered images: {n_img}")
    if expected:
        n_fail = len(result.get("registration_failures", []))
        print(f"  Registration failures: {n_fail}/{len(expected)}")
    print(f"  3D points: {n_pts}")
    print(f"  Mean reprojection error: {err}")

    covis = result.get("covisibility", {})
    if covis:
        print(f"  Covisibility pairs: {covis.get('total_pairs', 0)}")

    baselines = result.get("baselines", {})
    if baselines:
        print(f"  Baseline range: {baselines.get('min_distance', '?')} - "
              f"{baselines.get('max_distance', '?')} "
              f"(mean: {baselines.get('mean_distance', '?')})")

    density = result.get("point_cloud", {}).get("density_grid", {})
    if density:
        print(f"  Density grid occupancy: {density.get('occupancy_ratio', '?')} "
              f"({density.get('occupied_cells', '?')}/{density.get('total_cells', '?')} cells)")


if __name__ == "__main__":
    main()
