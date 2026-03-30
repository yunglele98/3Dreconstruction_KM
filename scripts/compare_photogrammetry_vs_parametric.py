#!/usr/bin/env python3
"""Compare photogrammetric meshes (OpenMVS .ply) against parametric Blender models.

Validates dimensional accuracy by computing:
- Bounding box dimensions (width, height, depth)
- Hausdorff distance (one-directional and symmetric)
- Volume comparison (if watertight)
- Surface area comparison
- Centroid offset

Outputs per-building JSON comparisons and an HTML summary report.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np

try:
    import trimesh
except ImportError:
    print("ERROR: trimesh library not found. Install with: pip install trimesh")
    sys.exit(1)


ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUTS_DIR = ROOT_DIR / "outputs"
DEFAULT_PHOTOGRAMMETRY_DIR = DEFAULT_OUTPUTS_DIR / "photogrammetry"
DEFAULT_PARAMETRIC_DIR = DEFAULT_OUTPUTS_DIR / "full"
DEFAULT_COMPARISON_DIR = DEFAULT_OUTPUTS_DIR / "comparison"


def normalize_address(address: str) -> str:
    """Convert address to filename format (spaces → underscores)."""
    return address.strip().replace(" ", "_")


def find_mesh_file(directory: Path, address: str, pattern: str) -> Path | None:
    """Find mesh file in directory matching address and pattern."""
    if not directory.exists():
        return None

    # Try direct address-based lookup
    base_name = normalize_address(address)
    candidates = [
        directory / base_name / f"{pattern}.ply",
        directory / f"{base_name}_{pattern}.ply",
        directory / base_name / f"{pattern}.ply",
    ]

    for candidate in candidates:
        if candidate.exists():
            return candidate

    # Fallback: search for any .ply file in subdirectory
    address_dir = directory / base_name
    if address_dir.exists():
        ply_files = list(address_dir.glob("*.ply"))
        if ply_files:
            # Prefer scene_dense_mesh_texture.ply over scene_dense_mesh.ply
            for ply in ply_files:
                if "texture" in ply.name.lower():
                    return ply
            return ply_files[0]

    return None


def load_mesh(mesh_path: Path) -> trimesh.Trimesh | None:
    """Load mesh from .ply file safely."""
    try:
        mesh = trimesh.load(str(mesh_path), process=False)
        return mesh
    except Exception as e:
        print(f"  WARNING: Failed to load {mesh_path}: {e}")
        return None


def compute_bbox_dims(mesh: trimesh.Trimesh) -> dict[str, float]:
    """Compute bounding box dimensions."""
    bounds = mesh.bounds
    dims = bounds[1] - bounds[0]
    return {
        "width_m": float(dims[0]),
        "height_m": float(dims[1]),
        "depth_m": float(dims[2]),
    }


def compute_centroid(mesh: trimesh.Trimesh) -> dict[str, float]:
    """Compute mesh centroid."""
    centroid = mesh.centroid
    return {
        "x": float(centroid[0]),
        "y": float(centroid[1]),
        "z": float(centroid[2]),
    }


def compute_hausdorff_distance(mesh1: trimesh.Trimesh, mesh2: trimesh.Trimesh) -> dict[str, float | None]:
    """Compute Hausdorff distance between two meshes."""
    try:
        # One-directional: max distance from mesh1 to mesh2
        distances_1_to_2 = trimesh.proximity.distance.directed_hausdorff(mesh1, mesh2)
        max_1_to_2 = float(np.max(distances_1_to_2))

        # One-directional: max distance from mesh2 to mesh1
        distances_2_to_1 = trimesh.proximity.distance.directed_hausdorff(mesh2, mesh1)
        max_2_to_1 = float(np.max(distances_2_to_1))

        # Symmetric: max of both directions
        symmetric = max(max_1_to_2, max_2_to_1)

        # Mean distance for a softer metric
        mean_1_to_2 = float(np.mean(distances_1_to_2))
        mean_2_to_1 = float(np.mean(distances_2_to_1))

        return {
            "hausdorff_1_to_2_m": max_1_to_2,
            "hausdorff_2_to_1_m": max_2_to_1,
            "hausdorff_symmetric_m": symmetric,
            "mean_distance_1_to_2_m": mean_1_to_2,
            "mean_distance_2_to_1_m": mean_2_to_1,
        }
    except Exception as e:
        print(f"  WARNING: Hausdorff distance computation failed: {e}")
        return {
            "hausdorff_1_to_2_m": None,
            "hausdorff_2_to_1_m": None,
            "hausdorff_symmetric_m": None,
            "mean_distance_1_to_2_m": None,
            "mean_distance_2_to_1_m": None,
        }


def compute_volume(mesh: trimesh.Trimesh) -> float | None:
    """Compute mesh volume if watertight, else None."""
    try:
        if mesh.is_watertight:
            return float(mesh.volume)
    except Exception:
        pass
    return None


def compute_surface_area(mesh: trimesh.Trimesh) -> float:
    """Compute mesh surface area."""
    try:
        return float(mesh.area)
    except Exception:
        return 0.0


def compare_dimensions(dims1: dict, dims2: dict, threshold: float = 0.1) -> tuple[bool, dict]:
    """Compare bbox dimensions with tolerance threshold."""
    differences = {}
    all_match = True

    for key in ["width_m", "height_m", "depth_m"]:
        v1 = dims1.get(key, 0)
        v2 = dims2.get(key, 0)
        if v1 == 0 or v2 == 0:
            pct_diff = float("inf")
        else:
            pct_diff = abs(v1 - v2) / max(v1, v2)

        differences[key] = {
            "photogrammetry_m": v1,
            "parametric_m": v2,
            "difference_m": abs(v1 - v2),
            "difference_pct": pct_diff * 100,
            "within_threshold": pct_diff <= threshold,
        }

        if pct_diff > threshold:
            all_match = False

    return all_match, differences


def compare_building(
    address: str,
    photogrammetry_dir: Path,
    parametric_dir: Path,
    threshold: float,
) -> dict[str, Any]:
    """Compare meshes for a single building."""
    result: dict[str, Any] = {
        "address": address,
        "timestamp": None,
        "photogrammetry_mesh": None,
        "parametric_mesh": None,
        "comparison": None,
        "status": "missing_data",
    }

    # Find mesh files
    photo_path = find_mesh_file(photogrammetry_dir, address, "scene_dense_mesh_texture")
    if not photo_path:
        photo_path = find_mesh_file(photogrammetry_dir, address, "scene_dense_mesh")

    param_path = find_mesh_file(parametric_dir, address, "")

    if not photo_path:
        result["photogrammetry_mesh"] = "NOT FOUND"
        return result

    if not param_path:
        result["parametric_mesh"] = "NOT FOUND"
        return result

    # Load meshes
    photo_mesh = load_mesh(photo_path)
    param_mesh = load_mesh(param_path)

    if photo_mesh is None or param_mesh is None:
        result["photogrammetry_mesh"] = str(photo_path) if photo_path else None
        result["parametric_mesh"] = str(param_path) if param_path else None
        result["status"] = "load_error"
        return result

    # Compute metrics
    photo_bbox = compute_bbox_dims(photo_mesh)
    param_bbox = compute_bbox_dims(param_mesh)

    dims_match, dim_details = compare_dimensions(photo_bbox, param_bbox, threshold)

    photo_volume = compute_volume(photo_mesh)
    param_volume = compute_volume(param_mesh)
    volume_ratio = None
    if photo_volume and param_volume and param_volume > 0:
        volume_ratio = photo_volume / param_volume

    photo_area = compute_surface_area(photo_mesh)
    param_area = compute_surface_area(param_mesh)
    area_ratio = None
    if photo_area > 0 and param_area > 0:
        area_ratio = photo_area / param_area

    hausdorff = compute_hausdorff_distance(photo_mesh, param_mesh)

    photo_centroid = compute_centroid(photo_mesh)
    param_centroid = compute_centroid(param_mesh)
    centroid_offset = {
        "dx": param_centroid["x"] - photo_centroid["x"],
        "dy": param_centroid["y"] - photo_centroid["y"],
        "dz": param_centroid["z"] - photo_centroid["z"],
        "distance": float(
            np.sqrt(
                (param_centroid["x"] - photo_centroid["x"]) ** 2
                + (param_centroid["y"] - photo_centroid["y"]) ** 2
                + (param_centroid["z"] - photo_centroid["z"]) ** 2
            )
        ),
    }

    result["photogrammetry_mesh"] = str(photo_path)
    result["parametric_mesh"] = str(param_path)
    result["comparison"] = {
        "bounding_box": {
            "photogrammetry": photo_bbox,
            "parametric": param_bbox,
            "dimension_differences": dim_details,
            "dimensions_match": dims_match,
        },
        "volume": {
            "photogrammetry_m3": photo_volume,
            "parametric_m3": param_volume,
            "ratio_photo_to_param": volume_ratio,
        },
        "surface_area": {
            "photogrammetry_m2": photo_area,
            "parametric_m2": param_area,
            "ratio_photo_to_param": area_ratio,
        },
        "hausdorff_distance": hausdorff,
        "centroid": {
            "photogrammetry": photo_centroid,
            "parametric": param_centroid,
            "offset": centroid_offset,
        },
    }

    # Determine status
    if dims_match and (hausdorff.get("hausdorff_symmetric_m") is None or hausdorff["hausdorff_symmetric_m"] < 0.5):
        result["status"] = "good_match"
    elif dims_match or (hausdorff.get("hausdorff_symmetric_m") is not None and hausdorff["hausdorff_symmetric_m"] < 1.0):
        result["status"] = "moderate_match"
    else:
        result["status"] = "poor_match"

    return result


def generate_html_report(comparisons: list[dict], summary: dict, output_path: Path) -> None:
    """Generate HTML summary report."""
    html_parts = [
        """<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Photogrammetry vs Parametric Model Comparison</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 20px; background: #f5f5f5; }
        h1 { color: #333; }
        .summary { background: white; padding: 20px; margin: 20px 0; border-radius: 5px; }
        .summary-stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 20px; }
        .stat-box { background: #f9f9f9; padding: 15px; border-left: 4px solid #007bff; }
        .stat-label { font-size: 0.9em; color: #666; }
        .stat-value { font-size: 1.8em; font-weight: bold; color: #333; }
        table { width: 100%; border-collapse: collapse; background: white; margin: 20px 0; }
        th { background: #333; color: white; padding: 12px; text-align: left; }
        td { padding: 10px 12px; border-bottom: 1px solid #ddd; }
        tr:hover { background: #f5f5f5; }
        .status-good { background: #d4edda; color: #155724; font-weight: bold; }
        .status-moderate { background: #fff3cd; color: #856404; font-weight: bold; }
        .status-poor { background: #f8d7da; color: #721c24; font-weight: bold; }
        .status-missing { background: #e2e3e5; color: #383d41; font-weight: bold; }
        .metric { font-size: 0.9em; color: #666; }
    </style>
</head>
<body>
    <h1>Photogrammetry vs Parametric Model Comparison Report</h1>
    <div class="summary">
        <h2>Summary Statistics</h2>
        <div class="summary-stats">
"""
    ]

    # Add summary stats
    stats = summary.get("aggregate", {})
    total = stats.get("total_compared", 0)
    good = stats.get("good_matches", 0)
    moderate = stats.get("moderate_matches", 0)
    poor = stats.get("poor_matches", 0)
    missing = stats.get("missing_data", 0)

    html_parts.append(f'            <div class="stat-box">')
    html_parts.append('                <div class="stat-label">Total Compared</div>')
    html_parts.append(f'                <div class="stat-value">{total}</div>')
    html_parts.append("            </div>")

    html_parts.append(f'            <div class="stat-box">')
    html_parts.append('                <div class="stat-label">Good Matches</div>')
    html_parts.append(f'                <div class="stat-value" style="color: #28a745;">{good}</div>')
    html_parts.append("            </div>")

    html_parts.append(f'            <div class="stat-box">')
    html_parts.append('                <div class="stat-label">Moderate Matches</div>')
    html_parts.append(f'                <div class="stat-value" style="color: #ffc107;">{moderate}</div>')
    html_parts.append("            </div>")

    html_parts.append(f'            <div class="stat-box">')
    html_parts.append('                <div class="stat-label">Poor Matches</div>')
    html_parts.append(f'                <div class="stat-value" style="color: #dc3545;">{poor}</div>')
    html_parts.append("            </div>")

    html_parts.append(f'            <div class="stat-box">')
    html_parts.append('                <div class="stat-label">Missing Data</div>')
    html_parts.append(f'                <div class="stat-value" style="color: #6c757d;">{missing}</div>')
    html_parts.append("            </div>")

    html_parts.append("""        </div>
    </div>
    <table>
        <thead>
            <tr>
                <th>Address</th>
                <th>Status</th>
                <th>Hausdorff Distance (m)</th>
                <th>Width Diff (%)</th>
                <th>Height Diff (%)</th>
                <th>Depth Diff (%)</th>
                <th>Volume Ratio</th>
            </tr>
        </thead>
        <tbody>
""")

    for comp in comparisons:
        address = comp.get("address", "Unknown")
        status = comp.get("status", "unknown")
        status_class = f"status-{status}"

        # Extract metrics
        comparison = comp.get("comparison", {})
        hausdorff_sym = None
        width_diff = None
        height_diff = None
        depth_diff = None
        volume_ratio = None

        if comparison:
            hd = comparison.get("hausdorff_distance", {})
            hausdorff_sym = hd.get("hausdorff_symmetric_m")

            dims = comparison.get("bounding_box", {}).get("dimension_differences", {})
            width_diff = dims.get("width_m", {}).get("difference_pct")
            height_diff = dims.get("height_m", {}).get("difference_pct")
            depth_diff = dims.get("depth_m", {}).get("difference_pct")

            volume_ratio = comparison.get("volume", {}).get("ratio_photo_to_param")

        hausdorff_str = f"{hausdorff_sym:.3f}" if hausdorff_sym is not None else "N/A"
        width_str = f"{width_diff:.1f}" if width_diff is not None else "N/A"
        height_str = f"{height_diff:.1f}" if height_diff is not None else "N/A"
        depth_str = f"{depth_diff:.1f}" if depth_diff is not None else "N/A"
        volume_str = f"{volume_ratio:.3f}" if volume_ratio is not None else "N/A"

        html_parts.append(f'            <tr class="{status_class}">')
        html_parts.append(f"                <td>{address}</td>")
        html_parts.append(f"                <td>{status.replace('_', ' ').title()}</td>")
        html_parts.append(f"                <td class='metric'>{hausdorff_str}</td>")
        html_parts.append(f"                <td class='metric'>{width_str}</td>")
        html_parts.append(f"                <td class='metric'>{height_str}</td>")
        html_parts.append(f"                <td class='metric'>{depth_str}</td>")
        html_parts.append(f"                <td class='metric'>{volume_str}</td>")
        html_parts.append("            </tr>")

    html_parts.append("""        </tbody>
    </table>
</body>
</html>
""")

    output_path.write_text("\n".join(html_parts), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare photogrammetric meshes (OpenMVS) against parametric Blender models."
    )
    parser.add_argument(
        "--address",
        type=str,
        help="Single building address to compare (e.g., 'Toronto Fire Station 315')",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Compare all buildings with available meshes",
    )
    parser.add_argument(
        "--photogrammetry-dir",
        type=Path,
        default=DEFAULT_PHOTOGRAMMETRY_DIR,
        help=f"Directory containing photogrammetric meshes (default: {DEFAULT_PHOTOGRAMMETRY_DIR})",
    )
    parser.add_argument(
        "--parametric-dir",
        type=Path,
        default=DEFAULT_PARAMETRIC_DIR,
        help=f"Directory containing parametric meshes (default: {DEFAULT_PARAMETRIC_DIR})",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_COMPARISON_DIR,
        help=f"Directory for comparison output (default: {DEFAULT_COMPARISON_DIR})",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.1,
        help="Dimension match tolerance as fraction (default: 0.1 = 10%%)",
    )

    args = parser.parse_args()

    # Validate arguments
    if not args.address and not args.all:
        parser.print_help()
        sys.exit(1)

    # Create output directory
    args.output_dir.mkdir(parents=True, exist_ok=True)

    comparisons: list[dict] = []

    if args.address:
        # Single address
        print(f"Comparing: {args.address}")
        result = compare_building(
            args.address,
            args.photogrammetry_dir,
            args.parametric_dir,
            args.threshold,
        )
        comparisons.append(result)
        print(f"  Status: {result['status']}")
    else:
        # All buildings
        print("Scanning for photogrammetric meshes...")
        if not args.photogrammetry_dir.exists():
            print(f"ERROR: Photogrammetry directory not found: {args.photogrammetry_dir}")
            sys.exit(1)

        photo_subdirs = [d for d in args.photogrammetry_dir.iterdir() if d.is_dir()]
        print(f"Found {len(photo_subdirs)} building directories")

        for i, building_dir in enumerate(sorted(photo_subdirs), 1):
            address = building_dir.name.replace("_", " ")
            print(f"[{i}/{len(photo_subdirs)}] Comparing: {address}")
            result = compare_building(
                address,
                args.photogrammetry_dir,
                args.parametric_dir,
                args.threshold,
            )
            comparisons.append(result)
            print(f"  Status: {result['status']}")

    # Generate summary
    summary: dict[str, Any] = {
        "threshold": args.threshold,
        "total_compared": len(comparisons),
        "aggregate": {
            "good_matches": sum(1 for c in comparisons if c["status"] == "good_match"),
            "moderate_matches": sum(1 for c in comparisons if c["status"] == "moderate_match"),
            "poor_matches": sum(1 for c in comparisons if c["status"] == "poor_match"),
            "missing_data": sum(1 for c in comparisons if c["status"] == "missing_data"),
            "load_error": sum(1 for c in comparisons if c["status"] == "load_error"),
        },
        "buildings": comparisons,
    }

    # Write per-building comparisons
    for comp in comparisons:
        address = normalize_address(comp["address"])
        comp_file = args.output_dir / f"{address}_comparison.json"
        comp_file.write_text(json.dumps(comp, indent=2), encoding="utf-8")

    # Write summary
    summary_file = args.output_dir / "comparison_summary.json"
    summary_file.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"\nWrote summary to: {summary_file}")

    # Generate HTML report
    html_file = args.output_dir / "comparison_report.html"
    generate_html_report(comparisons, summary, html_file)
    print(f"Wrote HTML report to: {html_file}")

    # Print summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Total buildings compared: {summary['total_compared']}")
    print(f"Good matches: {summary['aggregate']['good_matches']}")
    print(f"Moderate matches: {summary['aggregate']['moderate_matches']}")
    print(f"Poor matches: {summary['aggregate']['poor_matches']}")
    print(f"Missing data: {summary['aggregate']['missing_data']}")
    print(f"Load errors: {summary['aggregate']['load_error']}")


if __name__ == "__main__":
    main()
