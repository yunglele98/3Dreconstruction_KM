#!/usr/bin/env python3
"""Analyze COLMAP reconstruction quality for each completed workspace.

Parses sparse model binary files (cameras.bin, images.bin, points3D.bin)
and PLY files to compute quality metrics per workspace.

Usage:
    python scripts/reconstruct/analyze_colmap_quality.py --input point_clouds/colmap/ --output outputs/colmap_analysis/
    python scripts/reconstruct/analyze_colmap_quality.py --input point_clouds/colmap/ --output outputs/colmap_analysis/ --format csv
"""

from __future__ import annotations

import argparse
import csv
import json
import struct
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
INPUT_DEFAULT = REPO_ROOT / "point_clouds" / "colmap"
OUTPUT_DEFAULT = REPO_ROOT / "outputs" / "colmap_analysis"

# COLMAP camera model parameter counts (model_id -> num_double_params)
CAMERA_MODEL_PARAMS = {
    0: 3,   # SIMPLE_PINHOLE: f, cx, cy
    1: 4,   # PINHOLE: fx, fy, cx, cy
    2: 4,   # SIMPLE_RADIAL: f, cx, cy, k
    3: 5,   # RADIAL: f, cx, cy, k1, k2
    4: 8,   # OPENCV: fx, fy, cx, cy, k1, k2, p1, p2
    5: 12,  # OPENCV_FISHEYE
    6: 12,  # FULL_OPENCV
    7: 5,   # FOV: fx, fy, cx, cy, omega
    8: 4,   # SIMPLE_RADIAL_FISHEYE: f, cx, cy, k
    9: 5,   # RADIAL_FISHEYE: f, cx, cy, k1, k2
    10: 12, # THIN_PRISM_FISHEYE
}


def read_cameras_bin(path):
    """Parse COLMAP cameras.bin, return list of camera dicts."""
    cameras = []
    if not path.exists():
        return cameras
    try:
        with open(path, "rb") as f:
            num_cameras = struct.unpack("<Q", f.read(8))[0]
            for _ in range(num_cameras):
                camera_id = struct.unpack("<I", f.read(4))[0]
                model_id = struct.unpack("<i", f.read(4))[0]
                width = struct.unpack("<Q", f.read(8))[0]
                height = struct.unpack("<Q", f.read(8))[0]
                num_params = CAMERA_MODEL_PARAMS.get(model_id, 4)
                params = struct.unpack(f"<{num_params}d", f.read(8 * num_params))
                cameras.append({
                    "camera_id": camera_id,
                    "model_id": model_id,
                    "width": width,
                    "height": height,
                    "params": list(params),
                    "focal_length": params[0] if params else None,
                })
    except (struct.error, OSError) as e:
        print(f"  WARNING: Failed to parse cameras.bin: {e}")
    return cameras


def read_images_bin(path):
    """Parse COLMAP images.bin, return list of image dicts with match counts."""
    images = []
    if not path.exists():
        return images
    try:
        with open(path, "rb") as f:
            num_images = struct.unpack("<Q", f.read(8))[0]
            for _ in range(num_images):
                image_id = struct.unpack("<I", f.read(4))[0]
                qw, qx, qy, qz = struct.unpack("<4d", f.read(32))
                tx, ty, tz = struct.unpack("<3d", f.read(24))
                camera_id = struct.unpack("<I", f.read(4))[0]
                # Read null-terminated name
                name_bytes = b""
                while True:
                    ch = f.read(1)
                    if ch == b"\x00" or ch == b"":
                        break
                    name_bytes += ch
                name = name_bytes.decode("utf-8", errors="replace")
                # Read 2D points
                num_points2d = struct.unpack("<Q", f.read(8))[0]
                num_matched = 0
                for _ in range(num_points2d):
                    _x, _y = struct.unpack("<2d", f.read(16))
                    point3d_id = struct.unpack("<q", f.read(8))[0]
                    if point3d_id != -1:
                        num_matched += 1
                images.append({
                    "image_id": image_id,
                    "name": name,
                    "camera_id": camera_id,
                    "qvec": [qw, qx, qy, qz],
                    "tvec": [tx, ty, tz],
                    "num_points2d": num_points2d,
                    "num_matched": num_matched,
                })
    except (struct.error, OSError) as e:
        print(f"  WARNING: Failed to parse images.bin: {e}")
    return images


def read_points3d_bin(path):
    """Parse COLMAP points3D.bin, return list of point dicts."""
    points = []
    if not path.exists():
        return points
    try:
        with open(path, "rb") as f:
            num_points = struct.unpack("<Q", f.read(8))[0]
            for _ in range(num_points):
                point3d_id = struct.unpack("<Q", f.read(8))[0]
                x, y, z = struct.unpack("<3d", f.read(24))
                r, g, b = struct.unpack("<3B", f.read(3))
                error = struct.unpack("<d", f.read(8))[0]
                track_length = struct.unpack("<Q", f.read(8))[0]
                # Skip track entries (image_id uint32 + point2d_idx uint32 each)
                f.read(track_length * 8)
                points.append({
                    "point3d_id": point3d_id,
                    "xyz": [x, y, z],
                    "rgb": [r, g, b],
                    "error": error,
                    "track_length": track_length,
                })
    except (struct.error, OSError) as e:
        print(f"  WARNING: Failed to parse points3D.bin: {e}")
    return points


def count_ply_points(ply_path):
    """Count vertices in a PLY file by reading the header."""
    if not ply_path.exists():
        return None
    try:
        with open(ply_path, "rb") as f:
            for _ in range(64):  # header should be within first 64 lines
                line = f.readline()
                if not line:
                    break
                decoded = line.decode("ascii", errors="replace").strip()
                if decoded.startswith("element vertex"):
                    return int(decoded.split()[-1])
                if decoded == "end_header":
                    break
    except (OSError, ValueError):
        pass
    return None


def find_sparse_models(workspace):
    """Find sparse model directories within a workspace."""
    sparse_dir = workspace / "sparse"
    if not sparse_dir.exists():
        return []
    models = []
    # Check for numbered subdirs (sparse/0/, sparse/1/, etc.)
    for child in sorted(sparse_dir.iterdir()):
        if child.is_dir() and (child / "cameras.bin").exists():
            models.append(child)
    # Check if sparse dir itself contains the model files
    if not models and (sparse_dir / "cameras.bin").exists():
        models.append(sparse_dir)
    return models


def analyze_workspace(workspace):
    """Analyze a single COLMAP workspace, return quality metrics dict."""
    result = {
        "workspace": workspace.name,
        "path": str(workspace),
        "has_sparse": False,
        "has_dense_ply": False,
        "has_sparse_ply": False,
    }

    # Find sparse model
    models = find_sparse_models(workspace)
    if not models:
        result["status"] = "no_sparse_model"
        if (workspace / "placeholder.json").exists():
            result["status"] = "placeholder"
        return result

    # Use the first (typically best) model
    model_dir = models[0]
    result["has_sparse"] = True
    result["sparse_model"] = str(model_dir)
    result["num_sparse_models"] = len(models)

    # Count total images in workspace
    img_dir = workspace / "images"
    total_images = 0
    if img_dir.exists():
        total_images = len([
            f for f in img_dir.iterdir()
            if f.is_file() and f.suffix.lower() in (".jpg", ".jpeg", ".png", ".tif", ".tiff")
        ])
    result["total_images"] = total_images

    # Parse cameras
    cameras = read_cameras_bin(model_dir / "cameras.bin")
    result["num_cameras"] = len(cameras)
    if cameras:
        focal_lengths = [c["focal_length"] for c in cameras if c["focal_length"] is not None]
        if focal_lengths:
            result["focal_lengths"] = [round(fl, 2) for fl in focal_lengths]
            result["mean_focal_length"] = round(sum(focal_lengths) / len(focal_lengths), 2)

    # Parse images
    images = read_images_bin(model_dir / "images.bin")
    result["registered_images"] = len(images)

    if total_images > 0:
        result["registration_ratio"] = round(len(images) / total_images, 4)
    else:
        result["registration_ratio"] = 0.0

    # Parse 3D points
    points = read_points3d_bin(model_dir / "points3D.bin")
    result["num_points3d"] = len(points)

    if points:
        errors = [p["error"] for p in points]
        track_lengths = [p["track_length"] for p in points]
        result["mean_reprojection_error"] = round(sum(errors) / len(errors), 4)
        sorted_errors = sorted(errors)
        result["median_reprojection_error"] = round(sorted_errors[len(sorted_errors) // 2], 4)
        result["mean_track_length"] = round(sum(track_lengths) / len(track_lengths), 2)

        # Bounding box
        xs = [p["xyz"][0] for p in points]
        ys = [p["xyz"][1] for p in points]
        zs = [p["xyz"][2] for p in points]
        bbox_min = [min(xs), min(ys), min(zs)]
        bbox_max = [max(xs), max(ys), max(zs)]
        result["bbox_min"] = [round(v, 3) for v in bbox_min]
        result["bbox_max"] = [round(v, 3) for v in bbox_max]

        extent_x = bbox_max[0] - bbox_min[0]
        extent_y = bbox_max[1] - bbox_min[1]
        extent_z = bbox_max[2] - bbox_min[2]
        volume = max(extent_x, 0.001) * max(extent_y, 0.001) * max(extent_z, 0.001)
        result["bbox_extent"] = [round(extent_x, 3), round(extent_y, 3), round(extent_z, 3)]
        result["point_density"] = round(len(points) / volume, 1)

    # Check PLY files
    sparse_ply = workspace / "sparse_cloud.ply"
    dense_ply = workspace / "fused.ply"
    if sparse_ply.exists():
        result["has_sparse_ply"] = True
        result["sparse_ply_size_mb"] = round(sparse_ply.stat().st_size / (1024 * 1024), 2)
        count = count_ply_points(sparse_ply)
        if count is not None:
            result["sparse_ply_points"] = count
    if dense_ply.exists():
        result["has_dense_ply"] = True
        result["dense_ply_size_mb"] = round(dense_ply.stat().st_size / (1024 * 1024), 2)
        count = count_ply_points(dense_ply)
        if count is not None:
            result["dense_ply_points"] = count

    # Compute quality tier
    reg_ratio = result.get("registration_ratio", 0)
    mean_error = result.get("mean_reprojection_error", 999)
    if reg_ratio > 0.8 and mean_error < 1.0:
        result["quality_tier"] = "high"
    elif reg_ratio > 0.5 and mean_error < 2.0:
        result["quality_tier"] = "medium"
    else:
        result["quality_tier"] = "low"

    result["status"] = "analyzed"
    return result


def find_workspaces(input_dir):
    """Find all COLMAP workspaces under input_dir."""
    workspaces = []
    if not input_dir.exists():
        return workspaces
    for child in sorted(input_dir.iterdir()):
        if not child.is_dir():
            continue
        # A workspace has images/ or sparse/ or database.db or placeholder.json
        has_marker = (
            (child / "images").exists()
            or (child / "sparse").exists()
            or (child / "database.db").exists()
            or (child / "placeholder.json").exists()
        )
        if has_marker:
            workspaces.append(child)
    return workspaces


def main():
    parser = argparse.ArgumentParser(
        description="Analyze COLMAP reconstruction quality for each completed workspace."
    )
    parser.add_argument("--input", type=Path, default=INPUT_DEFAULT,
                        help="Directory containing COLMAP workspaces")
    parser.add_argument("--output", type=Path, default=OUTPUT_DEFAULT,
                        help="Output directory for analysis results")
    parser.add_argument("--format", choices=["json", "csv"], default="json",
                        help="Output format (default: json)")
    args = parser.parse_args()

    if not args.input.exists():
        print(f"ERROR: Input directory not found: {args.input}")
        sys.exit(1)

    workspaces = find_workspaces(args.input)
    if not workspaces:
        print(f"No COLMAP workspaces found in {args.input}")
        return

    print(f"Analyzing {len(workspaces)} COLMAP workspaces in {args.input}")

    results = []
    for ws in workspaces:
        print(f"  {ws.name}...", end=" ", flush=True)
        analysis = analyze_workspace(ws)
        results.append(analysis)
        tier = analysis.get("quality_tier", "-")
        status = analysis.get("status", "unknown")
        pts = analysis.get("num_points3d", 0)
        print(f"[{status}] tier={tier} points={pts}")

    # Sort by quality tier then registration ratio
    tier_order = {"high": 0, "medium": 1, "low": 2}
    results.sort(key=lambda r: (
        tier_order.get(r.get("quality_tier", "low"), 3),
        -r.get("registration_ratio", 0),
    ))

    # Summary
    tiers = {}
    statuses = {}
    for r in results:
        t = r.get("quality_tier", "n/a")
        tiers[t] = tiers.get(t, 0) + 1
        s = r.get("status", "unknown")
        statuses[s] = statuses.get(s, 0) + 1

    summary = {
        "total_workspaces": len(results),
        "by_quality_tier": tiers,
        "by_status": statuses,
    }

    print(f"\nSummary: {len(results)} workspaces")
    for tier, count in sorted(tiers.items()):
        print(f"  {tier}: {count}")

    # Write output
    args.output.mkdir(parents=True, exist_ok=True)

    if args.format == "json":
        output_data = {
            "summary": summary,
            "workspaces": results,
        }
        out_path = args.output / "colmap_quality_analysis.json"
        out_path.write_text(
            json.dumps(output_data, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"\nWrote {out_path}")
    else:
        # CSV format
        out_path = args.output / "colmap_quality_analysis.csv"
        fieldnames = [
            "workspace", "status", "quality_tier", "total_images",
            "registered_images", "registration_ratio", "num_points3d",
            "mean_reprojection_error", "mean_track_length", "point_density",
            "has_sparse_ply", "has_dense_ply", "sparse_ply_size_mb",
            "dense_ply_size_mb",
        ]
        with open(out_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for r in results:
                writer.writerow(r)
        print(f"\nWrote {out_path}")

        # Also write summary JSON
        summary_path = args.output / "colmap_quality_summary.json"
        summary_path.write_text(
            json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"Wrote {summary_path}")


if __name__ == "__main__":
    main()
