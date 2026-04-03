#!/usr/bin/env python3
"""Generate a human-readable reconstruction report across all COLMAP workspaces.

Aggregates per-building and block COLMAP workspaces into a single report
with quality rankings, street-level summaries, and recommendations.

Usage:
    python scripts/reconstruct/colmap_report.py
    python scripts/reconstruct/colmap_report.py --input point_clouds/colmap/ --blocks point_clouds/colmap_blocks/ --output outputs/colmap_report.json
"""

from __future__ import annotations

import argparse
import datetime
import json
import struct
import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
INPUT_DEFAULT = REPO_ROOT / "point_clouds" / "colmap"
BLOCKS_DEFAULT = REPO_ROOT / "point_clouds" / "colmap_blocks"
OUTPUT_DEFAULT = REPO_ROOT / "outputs" / "colmap_report.json"
PARAMS_DIR = REPO_ROOT / "params"

# COLMAP camera model parameter counts
CAMERA_MODEL_PARAMS = {
    0: 3, 1: 4, 2: 4, 3: 5, 4: 8, 5: 12,
    6: 12, 7: 5, 8: 4, 9: 5, 10: 12,
}


def _read_points3d_summary(path):
    """Read points3D.bin and return (count, mean_error, mean_track_length)."""
    if not path.exists():
        return 0, None, None
    try:
        errors = []
        tracks = []
        with open(path, "rb") as f:
            num = struct.unpack("<Q", f.read(8))[0]
            for _ in range(num):
                _pid = struct.unpack("<Q", f.read(8))[0]
                f.read(24)  # xyz
                f.read(3)   # rgb
                error = struct.unpack("<d", f.read(8))[0]
                tlen = struct.unpack("<Q", f.read(8))[0]
                f.read(tlen * 8)  # track entries
                errors.append(error)
                tracks.append(tlen)
        if errors:
            return num, sum(errors) / len(errors), sum(tracks) / len(tracks)
        return num, None, None
    except (struct.error, OSError):
        return 0, None, None


def _read_images_count(path):
    """Read images.bin and return count of registered images."""
    if not path.exists():
        return 0
    try:
        with open(path, "rb") as f:
            return struct.unpack("<Q", f.read(8))[0]
    except (struct.error, OSError):
        return 0


def _count_input_images(workspace):
    """Count image files in workspace/images/."""
    img_dir = workspace / "images"
    if not img_dir.exists():
        return 0
    return len([
        f for f in img_dir.iterdir()
        if f.is_file() and f.suffix.lower() in (".jpg", ".jpeg", ".png", ".tif", ".tiff")
    ])


def _count_ply_points(ply_path):
    """Count vertices in a PLY file header."""
    if not ply_path.exists():
        return None
    try:
        with open(ply_path, "rb") as f:
            for _ in range(64):
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


def _find_sparse_model(workspace):
    """Find the best sparse model dir in a workspace."""
    sparse_dir = workspace / "sparse"
    if not sparse_dir.exists():
        return None
    for child in sorted(sparse_dir.iterdir()):
        if child.is_dir() and (child / "cameras.bin").exists():
            return child
    if (sparse_dir / "cameras.bin").exists():
        return sparse_dir
    return None


def _infer_street(workspace_name):
    """Infer street name from workspace directory name."""
    param_file = PARAMS_DIR / f"{workspace_name}.json"
    if param_file.exists():
        try:
            data = json.loads(param_file.read_text(encoding="utf-8"))
            return (data.get("site", {}).get("street") or "").strip()
        except (json.JSONDecodeError, OSError):
            pass
    # Heuristic: remove leading number+underscore, take the rest
    parts = workspace_name.replace("_", " ").split()
    if len(parts) >= 2:
        for i, part in enumerate(parts):
            if not part.replace("-", "").isdigit():
                return " ".join(parts[i:])
    return workspace_name


def analyze_workspace_quick(workspace, is_block=False):
    """Quick analysis of a single workspace for the report."""
    name = workspace.name
    result = {
        "name": name,
        "type": "block" if is_block else "per_building",
        "path": str(workspace),
    }

    total_images = _count_input_images(workspace)
    result["total_images"] = total_images

    # Check for placeholder
    if (workspace / "placeholder.json").exists():
        result["status"] = "placeholder"
        return result

    # Find sparse model
    model_dir = _find_sparse_model(workspace)
    if not model_dir:
        result["status"] = "no_model"
        return result

    # Read model stats
    registered = _read_images_count(model_dir / "images.bin")
    num_points, mean_error, mean_track = _read_points3d_summary(
        model_dir / "points3D.bin"
    )

    result["registered_images"] = registered
    result["num_points3d"] = num_points
    if total_images > 0:
        result["registration_ratio"] = round(registered / total_images, 4)
    else:
        result["registration_ratio"] = 0.0
    if mean_error is not None:
        result["mean_reprojection_error"] = round(mean_error, 4)
    if mean_track is not None:
        result["mean_track_length"] = round(mean_track, 2)

    # Check PLY files
    for ply_name in ["sparse_cloud.ply", "fused.ply"]:
        ply = workspace / ply_name
        if ply.exists():
            key = ply_name.replace(".ply", "").replace(".", "_")
            result[f"has_{key}"] = True
            result[f"{key}_size_mb"] = round(
                ply.stat().st_size / (1024 * 1024), 2
            )

    # Quality tier
    reg = result.get("registration_ratio", 0)
    err = result.get("mean_reprojection_error", 999)
    if reg > 0.8 and err < 1.0:
        result["quality_tier"] = "high"
    elif reg > 0.5 and err < 2.0:
        result["quality_tier"] = "medium"
    else:
        result["quality_tier"] = "low"

    # Read block report if exists
    block_report = workspace / "block_report.json"
    if block_report.exists():
        try:
            br = json.loads(block_report.read_text(encoding="utf-8"))
            result["block_street"] = br.get("street", "")
            result["block_address_count"] = br.get("address_count", 0)
        except (json.JSONDecodeError, OSError):
            pass

    result["status"] = "success"
    if not is_block:
        result["street"] = _infer_street(name)

    return result


def find_workspaces(input_dir):
    """Find all COLMAP workspace directories."""
    if not input_dir.exists():
        return []
    return [
        d for d in sorted(input_dir.iterdir())
        if d.is_dir() and (
            (d / "images").exists()
            or (d / "sparse").exists()
            or (d / "database.db").exists()
            or (d / "placeholder.json").exists()
        )
    ]


def main():
    parser = argparse.ArgumentParser(
        description="Generate a consolidated COLMAP reconstruction report."
    )
    parser.add_argument("--input", type=Path, default=INPUT_DEFAULT,
                        help="Per-building COLMAP workspaces directory")
    parser.add_argument("--blocks", type=Path, default=BLOCKS_DEFAULT,
                        help="Block-level COLMAP workspaces directory")
    parser.add_argument("--output", type=Path, default=OUTPUT_DEFAULT,
                        help="Output report JSON path")
    args = parser.parse_args()

    # Collect all workspaces
    per_building = find_workspaces(args.input)
    block_ws = find_workspaces(args.blocks)

    print(f"Per-building workspaces: {len(per_building)} in {args.input}")
    print(f"Block workspaces: {len(block_ws)} in {args.blocks}")

    if not per_building and not block_ws:
        print("No COLMAP workspaces found.")
        return

    # Analyze all
    all_results = []
    for ws in per_building:
        r = analyze_workspace_quick(ws, is_block=False)
        all_results.append(r)
    for ws in block_ws:
        r = analyze_workspace_quick(ws, is_block=True)
        all_results.append(r)

    # Counts
    success = [r for r in all_results if r["status"] == "success"]
    placeholders = [r for r in all_results if r["status"] == "placeholder"]
    no_model = [r for r in all_results if r["status"] == "no_model"]

    tier_counts = defaultdict(int)
    for r in success:
        tier_counts[r.get("quality_tier", "unknown")] += 1

    # Sort successful by quality
    tier_order = {"high": 0, "medium": 1, "low": 2}
    success.sort(key=lambda r: (
        tier_order.get(r.get("quality_tier", "low"), 3),
        -r.get("num_points3d", 0),
    ))

    # Top/bottom 10
    top_10 = success[:10]
    worst_10 = success[-10:][::-1] if len(success) >= 10 else success[::-1]

    # Street-level summary
    street_stats = defaultdict(lambda: {
        "per_building_count": 0,
        "has_block": False,
        "success_count": 0,
        "placeholder_count": 0,
        "total_points": 0,
    })
    for r in all_results:
        if r["type"] == "block":
            street = r.get("block_street", r["name"])
            street_stats[street]["has_block"] = True
            if r["status"] == "success":
                street_stats[street]["total_points"] += r.get("num_points3d", 0)
        else:
            street = r.get("street", "Unknown")
            street_stats[street]["per_building_count"] += 1
            if r["status"] == "success":
                street_stats[street]["success_count"] += 1
                street_stats[street]["total_points"] += r.get("num_points3d", 0)
            elif r["status"] == "placeholder":
                street_stats[street]["placeholder_count"] += 1

    street_summary = []
    for street, stats in sorted(street_stats.items()):
        street_summary.append({"street": street, **stats})

    # Recommendations
    recommendations = {
        "need_block_colmap": [],
        "need_more_photos": [],
    }
    for street, stats in street_stats.items():
        if not stats["has_block"] and stats["per_building_count"] >= 5:
            recommendations["need_block_colmap"].append(street)
        if stats["placeholder_count"] > stats["success_count"]:
            recommendations["need_more_photos"].append(street)

    report = {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "summary": {
            "total_workspaces": len(all_results),
            "per_building_count": len(per_building),
            "block_count": len(block_ws),
            "success": len(success),
            "placeholder": len(placeholders),
            "no_model": len(no_model),
            "by_quality_tier": dict(tier_counts),
        },
        "top_10_quality": [
            {
                "name": r["name"],
                "type": r["type"],
                "quality_tier": r.get("quality_tier"),
                "num_points3d": r.get("num_points3d", 0),
                "registration_ratio": r.get("registration_ratio", 0),
                "mean_reprojection_error": r.get("mean_reprojection_error"),
            }
            for r in top_10
        ],
        "worst_10_quality": [
            {
                "name": r["name"],
                "type": r["type"],
                "quality_tier": r.get("quality_tier"),
                "num_points3d": r.get("num_points3d", 0),
                "registration_ratio": r.get("registration_ratio", 0),
                "mean_reprojection_error": r.get("mean_reprojection_error"),
            }
            for r in worst_10
        ],
        "street_summary": street_summary,
        "recommendations": recommendations,
        "all_workspaces": all_results,
    }

    # Print summary
    print(f"\n{'='*60}")
    print("COLMAP Reconstruction Report")
    print(f"{'='*60}")
    print(f"Total workspaces: {len(all_results)}")
    print(f"  Per-building: {len(per_building)}")
    print(f"  Block: {len(block_ws)}")
    print(f"  Success: {len(success)}")
    print(f"  Placeholder: {len(placeholders)}")
    print(f"  No model: {len(no_model)}")
    print(f"\nBy quality tier:")
    for tier in ["high", "medium", "low"]:
        print(f"  {tier}: {tier_counts.get(tier, 0)}")

    if top_10:
        print(f"\nTop {len(top_10)} highest quality:")
        for r in top_10:
            err = r.get("mean_reprojection_error", "n/a")
            err_str = f"{err:.3f}" if isinstance(err, float) else str(err)
            print(f"  [{r.get('quality_tier', '?'):>6}] {r['name']:<35} "
                  f"pts={r.get('num_points3d', 0):>8} "
                  f"reg={r.get('registration_ratio', 0):.2f} "
                  f"err={err_str}")

    if worst_10:
        print(f"\nTop {len(worst_10)} needing attention:")
        for r in worst_10:
            err = r.get("mean_reprojection_error", "n/a")
            err_str = f"{err:.3f}" if isinstance(err, float) else str(err)
            print(f"  [{r.get('quality_tier', '?'):>6}] {r['name']:<35} "
                  f"pts={r.get('num_points3d', 0):>8} "
                  f"reg={r.get('registration_ratio', 0):.2f} "
                  f"err={err_str}")

    if recommendations["need_block_colmap"]:
        print("\nStreets recommended for block COLMAP:")
        for s in recommendations["need_block_colmap"]:
            print(f"  - {s}")

    if recommendations["need_more_photos"]:
        print("\nStreets needing more photos:")
        for s in recommendations["need_more_photos"]:
            print(f"  - {s}")

    # Write report
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"\nWrote {args.output}")


if __name__ == "__main__":
    main()
