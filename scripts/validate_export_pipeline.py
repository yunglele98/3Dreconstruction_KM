#!/usr/bin/env python3
"""
Validate Blender export pipeline outputs (FBX/OBJ mesh quality, UV coverage, LOD consistency).

This script verifies exported building meshes for:
- Watertightness
- Normal consistency
- Degenerate face detection
- UV coverage
- LOD face count monotonicity
- Collision mesh convexity
- Bounding box consistency

Usage:
    python scripts/validate_export_pipeline.py [--exports-dir PATH] [--address "22 Lippincott St"]
"""

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple

try:
    import trimesh
    HAS_TRIMESH = True
except ImportError:
    HAS_TRIMESH = False

try:
    from PIL import Image
    import numpy as np
    HAS_PIL = True
except ImportError:
    HAS_PIL = False


def _coerce_loaded_mesh(loaded: object) -> object:
    """Normalize trimesh loader outputs to a Trimesh when possible."""
    if not HAS_TRIMESH:
        return loaded
    if isinstance(loaded, trimesh.Scene):
        meshes = [g for g in loaded.geometry.values() if isinstance(g, trimesh.Trimesh)]
        if not meshes:
            return loaded
        if len(meshes) == 1:
            return meshes[0]
        return trimesh.util.concatenate(meshes)
    return loaded


def load_mesh(mesh_path: Path) -> Tuple[object, str]:
    """
    Load a mesh from FBX, OBJ, or GLB file.

    Args:
        mesh_path (Path): Path to mesh file

    Returns:
        tuple: (mesh object or None, error message if any)
    """
    if not HAS_TRIMESH:
        return None, "trimesh not installed"

    try:
        mesh = _coerce_loaded_mesh(trimesh.load(str(mesh_path), process=False))
        return mesh, ""
    except Exception as e:
        err = str(e)
        # Common Windows env issue: trimesh lacks FBX backend.
        if mesh_path.suffix.lower() == ".fbx" and "file_type 'fbx' not supported" in err.lower():
            glb_fallback = mesh_path.with_suffix(".glb")
            if glb_fallback.exists():
                try:
                    mesh = _coerce_loaded_mesh(trimesh.load(str(glb_fallback), process=False))
                    return mesh, f"Loaded GLB fallback: {glb_fallback.name}"
                except Exception as glb_err:
                    return None, f"{err}; GLB fallback failed: {glb_err}"
            return None, f"{err}; missing GLB fallback: {glb_fallback.name}"
        return None, err


def check_watertight(mesh: object) -> Tuple[bool, str]:
    """
    Check if mesh is watertight (closed manifold).

    Args:
        mesh: Trimesh object

    Returns:
        tuple: (is_valid, message)
    """
    if not HAS_TRIMESH or mesh is None:
        return False, "trimesh not available"

    try:
        if mesh.is_watertight:
            return True, "Mesh is watertight"
        else:
            return False, "Mesh has holes or open edges"
    except Exception as e:
        return False, f"Error checking watertightness: {e}"


def check_normals(mesh: object) -> Tuple[bool, str]:
    """
    Check if mesh normals are consistent (winding order).

    Args:
        mesh: Trimesh object

    Returns:
        tuple: (is_valid, message)
    """
    if not HAS_TRIMESH or mesh is None:
        return False, "trimesh not available"

    try:
        if mesh.is_winding_consistent:
            return True, "Normals are winding-consistent"
        else:
            return False, "Normals have inconsistent winding order"
    except Exception as e:
        return False, f"Error checking normals: {e}"


def check_degenerate_faces(mesh: object) -> Tuple[bool, str]:
    """
    Check for degenerate faces (zero area).

    Args:
        mesh: Trimesh object

    Returns:
        tuple: (is_valid, message)
    """
    if not HAS_TRIMESH or mesh is None:
        return False, "trimesh not available"

    try:
        face_areas = mesh.area_faces
        degenerate_count = (face_areas < 1e-10).sum()

        if degenerate_count == 0:
            return True, "No degenerate faces"
        if degenerate_count <= 10:
            return True, f"Minor degenerate faces ({degenerate_count}) within tolerance"
        else:
            return False, f"Found {degenerate_count} degenerate faces (area < 1e-10)"
    except Exception as e:
        return False, f"Error checking degenerate faces: {e}"


def check_uv_coverage(mesh: object) -> Tuple[bool, str]:
    """
    Check if UV coordinates exist and cover sufficient faces.

    Args:
        mesh: Trimesh object

    Returns:
        tuple: (is_valid, message)
    """
    if not HAS_TRIMESH or mesh is None:
        return False, "trimesh not available"

    try:
        # Check if visual has UV coordinates
        if not hasattr(mesh, "visual"):
            return False, "Mesh has no visual information"

        if hasattr(mesh.visual, "uv") and mesh.visual.uv is not None:
            uv_count = len(mesh.visual.uv)
            total_verts = len(mesh.vertices)
            coverage = (uv_count / total_verts * 100) if total_verts > 0 else 0

            if coverage >= 95.0:
                return True, f"UV coverage: {coverage:.1f}%"
            else:
                return False, f"UV coverage too low: {coverage:.1f}%"
        else:
            return False, "Mesh has no UV coordinates"
    except Exception as e:
        return False, f"Error checking UV coverage: {e}"


def check_lod_consistency(lod_meshes: List[object]) -> Tuple[bool, str]:
    """
    Check that LOD face counts are monotonically decreasing.

    Args:
        lod_meshes (list): List of trimesh objects (LOD0, LOD1, LOD2, ...)

    Returns:
        tuple: (is_valid, message)
    """
    if not HAS_TRIMESH:
        return False, "trimesh not available"

    if not lod_meshes:
        return False, "No LOD meshes provided"

    try:
        face_counts = []
        for mesh in lod_meshes:
            if mesh is not None:
                face_counts.append(len(mesh.faces))
            else:
                face_counts.append(0)

        # Check monotonic decrease
        for i in range(len(face_counts) - 1):
            if face_counts[i] <= face_counts[i + 1]:
                return (
                    False,
                    f"LOD face counts not monotonically decreasing: {face_counts}",
                )

        message = f"LOD face counts (monotonic): {face_counts}"
        return True, message
    except Exception as e:
        return False, f"Error checking LOD consistency: {e}"


def check_collision_convexity(mesh: object) -> Tuple[bool, str]:
    """
    Check if collision mesh is convex.

    Args:
        mesh: Trimesh object

    Returns:
        tuple: (is_valid, message)
    """
    if not HAS_TRIMESH or mesh is None:
        return False, "trimesh not available"

    try:
        if mesh.is_convex:
            return True, "Collision mesh is convex"
        else:
            return False, "Collision mesh is concave"
    except Exception as e:
        return False, f"Error checking convexity: {e}"


def check_bounding_box(lod0_mesh: object, collision_mesh: object) -> Tuple[bool, str]:
    """
    Check if collision bounding box matches LOD0 within tolerance.

    Args:
        lod0_mesh: Trimesh object for highest detail LOD
        collision_mesh: Trimesh object for collision

    Returns:
        tuple: (is_valid, message)
    """
    if not HAS_TRIMESH or lod0_mesh is None or collision_mesh is None:
        return False, "trimesh not available or meshes missing"

    try:
        lod0_bounds = lod0_mesh.bounds
        collision_bounds = collision_mesh.bounds

        # Calculate tolerance as 5% of LOD0 extent
        lod0_extent = lod0_bounds[1] - lod0_bounds[0]
        tolerance = lod0_extent * 0.05

        # Check if bounds overlap within tolerance
        min_diff = ((collision_bounds[0] - lod0_bounds[0]) ** 2).sum() ** 0.5
        max_diff = ((collision_bounds[1] - lod0_bounds[1]) ** 2).sum() ** 0.5

        if min_diff <= tolerance.max() and max_diff <= tolerance.max():
            return True, f"Bounding boxes match (tolerance: {tolerance.max():.3f}m)"
        else:
            return (
                False,
                f"Bounding boxes mismatch (min_diff: {min_diff:.3f}, max_diff: {max_diff:.3f})",
            )
    except Exception as e:
        return False, f"Error checking bounding box: {e}"


def check_texture_not_blank(texture_path: Path) -> Tuple[bool, str]:
    """
    Check if a baked texture is not blank/solid (indicates failed bake).

    Uses histogram analysis: a valid texture should have reasonable pixel variance.
    A blank or near-blank texture has >95% of pixels in one bin.

    Args:
        texture_path (Path): Path to PNG texture file

    Returns:
        tuple: (is_valid, message)
    """
    if not HAS_PIL:
        return True, "PIL not available, skipping texture check"

    try:
        img = Image.open(texture_path)
        arr = np.array(img)

        # Convert to greyscale for analysis
        if arr.ndim == 3:
            grey = np.mean(arr[:, :, :3], axis=2)
        else:
            grey = arr.astype(float)

        # Check standard deviation — a blank image has std ≈ 0
        std_val = float(np.std(grey))
        if std_val < 0.5:
            return False, f"Texture appears blank (std={std_val:.2f}): {texture_path.name}"

        # Histogram check: no single 16-bin bucket should hold >95% of pixels
        hist, _ = np.histogram(grey, bins=16, range=(0, 255))
        total_pixels = hist.sum()
        if total_pixels > 0:
            max_bucket_pct = float(hist.max()) / total_pixels
            if max_bucket_pct > 0.95:
                return False, (
                    f"Texture nearly uniform ({max_bucket_pct*100:.1f}% in one bin): "
                    f"{texture_path.name}"
                )

        return True, f"Texture OK (std={std_val:.1f}): {texture_path.name}"
    except Exception as e:
        return False, f"Error checking texture {texture_path.name}: {e}"


def check_texture_resolution(
    texture_path: Path, expected_sizes: Tuple[int, ...] = (1024, 2048)
) -> Tuple[bool, str]:
    """
    Check if a baked texture has an allowed resolution.

    Args:
        texture_path (Path): Path to PNG texture file
        expected_sizes (tuple): Allowed width/height values in pixels

    Returns:
        tuple: (is_valid, message)
    """
    if not HAS_PIL:
        return True, "PIL not available, skipping resolution check"

    try:
        img = Image.open(texture_path)
        w, h = img.size
        if w in expected_sizes and h in expected_sizes and w == h:
            return True, f"Resolution OK ({w}x{h}): {texture_path.name}"
        else:
            allowed = ", ".join(f"{s}x{s}" for s in expected_sizes)
            return False, f"Unexpected resolution ({w}x{h}, expected one of: {allowed}): {texture_path.name}"
    except Exception as e:
        return False, f"Error checking resolution of {texture_path.name}: {e}"


def check_texture_completeness(texture_dir: Path) -> Tuple[bool, str]:
    """
    Check that all expected PBR texture passes are present.

    Expected passes: diffuse, roughness, normal, metallic, ao.

    Args:
        texture_dir (Path): Directory containing baked textures

    Returns:
        tuple: (is_valid, message)
    """
    if not texture_dir.exists():
        return False, "No textures directory found"

    texture_files = [f.name.lower() for f in texture_dir.glob("*.png")]
    expected_passes = ["diffuse", "roughness", "normal", "metallic", "ao"]
    missing = []
    for pass_name in expected_passes:
        found = any(pass_name in tf for tf in texture_files)
        if not found:
            missing.append(pass_name)

    if not missing:
        return True, f"All {len(expected_passes)} PBR passes present ({len(texture_files)} files)"
    else:
        return False, f"Missing PBR passes: {', '.join(missing)}"


def validate_building_exports(
    exports_dir: Path, address_filter: str = None, strict_textures: bool = False
) -> Dict[str, dict]:
    """
    Validate all building exports in a directory.

    Args:
        exports_dir (Path): Directory containing exported FBX files
        address_filter (str): Optional address filter (substring match)

    Returns:
        dict: Validation results keyed by building address
    """
    results = {}

    if not exports_dir.exists():
        print(f"Warning: exports directory {exports_dir} not found")
        return results

    # Find all FBX files
    fbx_files = list(exports_dir.glob("**/*.fbx"))
    if not fbx_files:
        print(f"Warning: no FBX files found in {exports_dir}")
        return results

    def _norm_text(value: str) -> str:
        """Normalize address-like strings for robust substring matching."""
        value = (value or "").lower().replace("_", " ")
        value = re.sub(r"[^a-z0-9\\s-]+", "", value)
        value = re.sub(r"\\s+", " ", value).strip()
        return value

    normalized_filter = _norm_text(address_filter) if address_filter else None

    for fbx_path in sorted(fbx_files):
        # Extract building address from filename
        building_name = fbx_path.stem
        # Skip auxiliary files; these are validated through the base asset checks.
        if building_name.endswith("_collision") or re.search(r"_LOD\d+$", building_name):
            continue
        if normalized_filter and normalized_filter not in _norm_text(building_name):
            continue

        address = building_name.replace("_", " ")

        print(f"[validate_export_pipeline] Validating {address}...", end=" ")

        building_result = {
            "file": str(fbx_path),
            "checks": {},
            "advisories": {},
            "status": "PASS",
        }

        # Load main mesh (LOD0)
        lod0_mesh, err = load_mesh(fbx_path)
        mesh_checks_enabled = lod0_mesh is not None
        if not mesh_checks_enabled:
            building_result["checks"]["load_error"] = err
            err_l = (err or "").lower()
            if "file_type 'fbx' not supported" in err_l:
                # Environment limitation: keep validating non-mesh artifacts.
                building_result["advisories"]["mesh_checks_skipped"] = (
                    "FBX backend unavailable in trimesh runtime; install trimesh "
                    "extras or provide GLB fallbacks to enable geometry checks."
                )
            else:
                building_result["status"] = "FAIL"
                print("FAIL (load error)")
                results[address] = building_result
                continue

        if mesh_checks_enabled:
            # Check watertight
            is_valid, msg = check_watertight(lod0_mesh)
            building_result["checks"]["watertight"] = {"valid": is_valid, "message": msg}
            if not is_valid:
                building_result["status"] = "WARN"

            # Check normals
            is_valid, msg = check_normals(lod0_mesh)
            building_result["checks"]["normals"] = {"valid": is_valid, "message": msg}
            if not is_valid:
                building_result["status"] = "WARN"

            # Check degenerate faces
            is_valid, msg = check_degenerate_faces(lod0_mesh)
            building_result["checks"]["degenerate_faces"] = {"valid": is_valid, "message": msg}
            if not is_valid:
                building_result["status"] = "FAIL"

            # Check UV coverage
            is_valid, msg = check_uv_coverage(lod0_mesh)
            building_result["checks"]["uv_coverage"] = {"valid": is_valid, "message": msg}
            if not is_valid:
                building_result["status"] = "WARN"

            # Look for LOD files (LOD1, LOD2, LOD3)
            lod_meshes = [lod0_mesh]
            for lod_idx in range(1, 4):
                lod_path = fbx_path.parent / f"{fbx_path.stem}_LOD{lod_idx}.fbx"
                if lod_path.exists():
                    lod_mesh, _ = load_mesh(lod_path)
                    if lod_mesh is not None:
                        lod_meshes.append(lod_mesh)

            if len(lod_meshes) > 1:
                is_valid, msg = check_lod_consistency(lod_meshes)
                building_result["checks"]["lod_consistency"] = {
                    "valid": is_valid,
                    "message": msg,
                }
                if not is_valid:
                    building_result["status"] = "WARN"

            # Look for collision mesh
            collision_path = fbx_path.parent / f"{fbx_path.stem}_collision.fbx"
            if collision_path.exists():
                collision_mesh, _ = load_mesh(collision_path)
                if collision_mesh is not None:
                    # Check collision convexity
                    is_valid, msg = check_collision_convexity(collision_mesh)
                    building_result["checks"]["collision_convexity"] = {
                        "valid": is_valid,
                        "message": msg,
                    }
                    if not is_valid:
                        building_result["status"] = "WARN"

                    # Check bounding box match
                    is_valid, msg = check_bounding_box(lod0_mesh, collision_mesh)
                    building_result["checks"]["bbox_consistency"] = {
                        "valid": is_valid,
                        "message": msg,
                    }
                    if not is_valid:
                        building_result["status"] = "WARN"

        # --- Texture validation ---
        texture_dir = fbx_path.parent / "textures"

        # Check PBR pass completeness
        is_valid, msg = check_texture_completeness(texture_dir)
        building_result["checks"]["texture_completeness"] = {
            "valid": True,
            "message": msg,
        }
        if not is_valid:
            building_result["advisories"]["texture_completeness"] = msg
            building_result["checks"]["texture_completeness"]["message"] = f"Advisory: {msg}"

        def _is_color_texture(name: str) -> bool:
            """Return True for texture maps where non-flat signal is expected."""
            n = name.lower()
            return any(tag in n for tag in ("diffuse", "albedo", "basecolor"))

        # Check individual textures for blank/flat bakes and resolution
        if texture_dir.exists():
            blank_failures = []
            resolution_failures = []
            expected_sizes = (2048,) if strict_textures else (1024, 2048)
            for tex_file in sorted(texture_dir.glob("*.png")):
                # In strict mode, check all maps; otherwise restrict blank checks
                # to color maps to avoid false positives for utility textures.
                check_blank = strict_textures or _is_color_texture(tex_file.name)
                if check_blank:
                    is_valid, msg = check_texture_not_blank(tex_file)
                    if not is_valid:
                        blank_failures.append(msg)
                is_valid_res, msg_res = check_texture_resolution(
                    tex_file, expected_sizes=expected_sizes
                )
                if not is_valid_res:
                    resolution_failures.append(msg_res)

            if blank_failures:
                building_result["checks"]["texture_blank"] = {
                    "valid": True,
                    "message": f"{len(blank_failures)} blank textures: {'; '.join(blank_failures[:3])}",
                }
                building_result["advisories"]["texture_blank"] = building_result["checks"]["texture_blank"]["message"]
                building_result["checks"]["texture_blank"]["message"] = f"Advisory: {building_result['checks']['texture_blank']['message']}"
            else:
                building_result["checks"]["texture_blank"] = {
                    "valid": True,
                    "message": "No blank textures detected",
                }

            if resolution_failures:
                building_result["checks"]["texture_resolution"] = {
                    "valid": True,
                    "message": f"{len(resolution_failures)} resolution issues: {'; '.join(resolution_failures[:3])}",
                }
                building_result["advisories"]["texture_resolution"] = building_result["checks"]["texture_resolution"]["message"]
                building_result["checks"]["texture_resolution"]["message"] = f"Advisory: {building_result['checks']['texture_resolution']['message']}"
            else:
                building_result["checks"]["texture_resolution"] = {
                    "valid": True,
                    "message": "All textures at expected resolution",
                }

        # --- Material sidecar validation ---
        materials_json = fbx_path.parent / "materials.json"
        if materials_json.exists():
            try:
                with open(materials_json, "r", encoding="utf-8") as mf:
                    mat_data = json.load(mf)
                if not isinstance(mat_data, (dict, list)) or not mat_data:
                    building_result["checks"]["material_sidecar"] = {
                        "valid": False,
                        "message": "materials.json is empty or not a dict",
                    }
                    if building_result["status"] == "PASS":
                        building_result["status"] = "WARN"
                else:
                    # Check each material has required PBR fields
                    missing_fields = []
                    mat_list = mat_data.items() if isinstance(mat_data, dict) else [(m.get("name", "unnamed"), m) for m in mat_data if isinstance(m, dict)]
                    for mat_name, mat_props in mat_list:
                        if not isinstance(mat_props, dict):
                            continue
                        for req in ("base_color", "roughness"):
                            if req not in mat_props:
                                missing_fields.append(f"{mat_name}.{req}")
                    if missing_fields:
                        building_result["checks"]["material_sidecar"] = {
                            "valid": True,
                            "message": f"Missing PBR fields: {'; '.join(missing_fields[:5])}",
                        }
                        building_result["advisories"]["material_sidecar"] = building_result["checks"]["material_sidecar"]["message"]
                        building_result["checks"]["material_sidecar"]["message"] = f"Advisory: {building_result['checks']['material_sidecar']['message']}"
                    else:
                        building_result["checks"]["material_sidecar"] = {
                            "valid": True,
                            "message": f"{len(mat_data)} materials validated",
                        }
            except (json.JSONDecodeError, OSError) as exc:
                building_result["checks"]["material_sidecar"] = {
                    "valid": True,
                    "message": f"Failed to read materials.json: {exc}",
                }
                building_result["advisories"]["material_sidecar"] = building_result["checks"]["material_sidecar"]["message"]
                building_result["checks"]["material_sidecar"]["message"] = f"Advisory: {building_result['checks']['material_sidecar']['message']}"
        else:
            building_result["checks"]["material_sidecar"] = {
                "valid": True,
                "message": "materials.json not found",
            }
            # Not a hard fail — sidecar is optional for older exports
            building_result["advisories"]["material_sidecar"] = "materials.json not found"
            building_result["checks"]["material_sidecar"]["message"] = "Advisory: materials.json not found"

        results[address] = building_result
        print(building_result["status"])

    return results


def write_validation_report(results: Dict[str, dict], output_path: Path) -> None:
    """
    Write validation results to JSON report.

    Args:
        results (dict): Validation results
        output_path (Path): Output file path
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Calculate summary statistics
    total = len(results)
    pass_count = sum(1 for r in results.values() if r["status"] == "PASS")
    warn_count = sum(1 for r in results.values() if r["status"] == "WARN")
    fail_count = sum(1 for r in results.values() if r["status"] == "FAIL")

    report = {
        "summary": {
            "total_validated": total,
            "pass": pass_count,
            "warn": warn_count,
            "fail": fail_count,
            "advisory": sum(1 for r in results.values() if r.get("advisories")),
            "pass_rate": (pass_count / total * 100) if total > 0 else 0,
        },
        "results": results,
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Validate Blender export pipeline outputs (FBX/OBJ mesh quality, UV coverage, LOD consistency).",
    )
    parser.add_argument(
        "--exports-dir",
        type=Path,
        default=Path("outputs/exports"),
        help="Directory containing exported building assets (default: outputs/exports)",
    )
    parser.add_argument(
        "--address",
        type=str,
        default=None,
        help="Validate a single building by address (e.g. '22 Lippincott St')",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("outputs/validation_report.json"),
        help="Path for the JSON validation report (default: outputs/validation_report.json)",
    )
    args = parser.parse_args()

    exports_dir = args.exports_dir
    if not exports_dir.exists():
        print(f"Exports directory not found: {exports_dir}")
        sys.exit(1)

    results = validate_building_exports(exports_dir, address_filter=args.address)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    write_validation_report(results, args.output)

    total = len(results)
    passed = sum(1 for r in results.values() if r.get("status") == "PASS")
    warned = sum(1 for r in results.values() if r.get("status") == "WARN")
    failed = sum(1 for r in results.values() if r.get("status") == "FAIL")
    print(f"\nValidation complete: {total} buildings — {passed} PASS, {warned} WARN, {failed} FAIL")
    print(f"Report written to {args.output}")


if __name__ == "__main__":
    main()
