"""
Generate 4 LOD levels (LOD0-LOD3) from full-detail Blender building files.

LOD0: Full detail original (apply modifiers, export as-is).
LOD1: 50% face reduction via decimate.
LOD2: 15% faces, delete decorative elements, simplify windows.
LOD3: Box massing only (single grey cube).

Runs inside Blender:
    blender --background --python scripts/generate_lods.py -- \\
        --blend outputs/full/22_Lippincott_St.blend \\
        [--output-dir outputs/exports/lods/]

Batch mode:
    blender --background --python scripts/generate_lods.py -- \\
        --source-dir outputs/full/ \\
        [--limit 10] [--skip-existing]

Output: FBX files + <address>_lod_manifest.json per building.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import bmesh
import bpy
from mathutils import Vector


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = REPO_ROOT / "outputs" / "exports" / "lods"

# LOD-appropriate texture resolution tiers (pixels per side).
# LOD0 gets full resolution, each subsequent level halves.
# LOD3 (box massing) needs no baked textures.
LOD_TEXTURE_TIERS = {
    0: 2048,  # Full detail
    1: 1024,  # 50% geometry → half-res textures
    2: 512,   # 15% geometry → quarter-res textures
    3: 0,     # Box massing — no texture needed
}

# Decorative element prefixes to remove in LOD2
DECORATIVE_PREFIXES = {
    "cornice_",
    "bracket_",
    "voussoir_",
    "quoin_",
    "string_course_",
    "finial_",
    "bargeboard_",
    "corbel_",
    "gable_bracket_",
    "string_",
}

WINDOW_PREFIXES = {"frame_", "glass_"}


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments from after -- separator."""
    argv = sys.argv
    if "--" in argv:
        argv = argv[argv.index("--") + 1 :]
    else:
        argv = []

    parser = argparse.ArgumentParser(
        description="Generate LOD levels for Blender building files"
    )
    parser.add_argument(
        "--blend",
        type=str,
        help="Path to single .blend file (mutually exclusive with --source-dir)",
    )
    parser.add_argument(
        "--source-dir",
        type=str,
        help="Directory of .blend files to process",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=str(DEFAULT_OUTPUT_DIR),
        help="Output directory for LOD exports",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Process only first N files (batch mode)",
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="Skip if LOD0 already exists",
    )
    parser.add_argument(
        "--base-texture-size",
        type=int,
        default=2048,
        help="LOD0 texture resolution; lower LODs scale down automatically (default: 2048)",
    )

    return parser.parse_args(argv)


def clear_scene() -> None:
    """Remove all objects from the scene."""
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)


def count_mesh_elements(obj: bpy.types.Object) -> tuple[int, int]:
    """Count vertices and faces in a mesh object."""
    if obj.type != "MESH":
        return 0, 0

    mesh = obj.data
    return len(mesh.vertices), len(mesh.polygons)


def apply_all_modifiers(obj: bpy.types.Object) -> None:
    """Apply all modifiers on an object."""
    for mod in obj.modifiers:
        try:
            with bpy.context.temp_override(object=obj):
                bpy.ops.object.modifier_apply(modifier=mod.name)
        except RuntimeError:
            print(f"  Warning: Could not apply modifier {mod.name}")


def get_object_bounding_box(obj: bpy.types.Object) -> tuple[Vector, Vector]:
    """Get min and max bounding box corners for an object."""
    bbox_corners = [Vector(corner) for corner in obj.bound_box]
    min_x = min(c.x for c in bbox_corners)
    max_x = max(c.x for c in bbox_corners)
    min_y = min(c.y for c in bbox_corners)
    max_y = max(c.y for c in bbox_corners)
    min_z = min(c.z for c in bbox_corners)
    max_z = max(c.z for c in bbox_corners)
    return Vector((min_x, min_y, min_z)), Vector((max_x, max_y, max_z))


def create_box_massing(min_bound: Vector, max_bound: Vector) -> bpy.types.Object:
    """Create a single box mesh at given bounding box."""
    center = (min_bound + max_bound) / 2
    scale_x = (max_bound.x - min_bound.x) / 2
    scale_y = (max_bound.y - min_bound.y) / 2
    scale_z = (max_bound.z - min_bound.z) / 2

    bpy.ops.mesh.primitive_cube_add(size=1, location=center)
    box = bpy.context.active_object
    box.scale = (scale_x, scale_y, scale_z)
    bpy.ops.object.transform_apply(scale=True)

    # Assign grey material
    mat = bpy.data.materials.new(name="LOD3_Massing")
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (0.4, 0.4, 0.4, 1.0)
    bsdf.inputs["Roughness"].default_value = 0.8

    box.data.materials.append(mat)
    return box


def export_fbx(
    output_path: Path,
    axis_forward: str = "-Y",
    axis_up: str = "Z",
    global_scale: float = 1.0,
) -> None:
    """Export selected objects to FBX."""
    kwargs = dict(
        filepath=str(output_path),
        use_selection=True,
        axis_forward=axis_forward,
        axis_up=axis_up,
        global_scale=global_scale,
        bake_anim=False,
    )
    try:
        bpy.ops.export_scene.fbx(**kwargs, use_default_deform=False)
    except TypeError:
        bpy.ops.export_scene.fbx(**kwargs)


def generate_lod0(
    output_dir: Path, address: str
) -> tuple[int, int, str]:
    """
    LOD0: Full detail, apply modifiers, export.

    Returns: (vertex_count, face_count, output_path)
    """
    # Select and apply all modifiers
    for obj in bpy.data.objects:
        if obj.type == "MESH":
            apply_all_modifiers(obj)

    # Select all meshes
    for obj in bpy.data.objects:
        if obj.type == "MESH":
            obj.select_set(True)
        else:
            obj.select_set(False)

    # Count elements
    total_verts, total_faces = 0, 0
    for obj in bpy.data.objects:
        if obj.type == "MESH" and obj.select_get():
            v, f = count_mesh_elements(obj)
            total_verts += v
            total_faces += f

    # Export
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{address}_LOD0.fbx"
    export_fbx(output_path)

    return total_verts, total_faces, str(output_path)


def generate_lod1(
    output_dir: Path, address: str
) -> tuple[int, int, str]:
    """
    LOD1: 50% face reduction via decimate.

    Returns: (vertex_count, face_count, output_path)
    """
    # Reload original blend
    for obj in bpy.data.objects:
        if obj.type == "MESH":
            obj.select_set(True)

    # Apply decimate modifier (ratio=0.5)
    for obj in bpy.data.objects:
        if obj.type == "MESH":
            mod = obj.modifiers.new(name="Decimate_LOD1", type="DECIMATE")
            mod.ratio = 0.5
            apply_all_modifiers(obj)

    # Count and select
    total_verts, total_faces = 0, 0
    for obj in bpy.data.objects:
        if obj.type == "MESH":
            obj.select_set(True)
            v, f = count_mesh_elements(obj)
            total_verts += v
            total_faces += f

    # Export
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{address}_LOD1.fbx"
    export_fbx(output_path)

    return total_verts, total_faces, str(output_path)


def generate_lod2(
    output_dir: Path, address: str
) -> tuple[int, int, str]:
    """
    LOD2: 15% faces, delete decorative, simplify windows.

    Returns: (vertex_count, face_count, output_path)
    """
    # Delete decorative element objects
    to_delete = []
    for obj in bpy.data.objects:
        if obj.type == "MESH":
            for prefix in DECORATIVE_PREFIXES:
                if obj.name.lower().startswith(prefix):
                    to_delete.append(obj)
                    break

    for obj in to_delete:
        bpy.data.objects.remove(obj, do_unlink=True)

    # Simplify window objects: replace with flat planes
    for obj in list(bpy.data.objects):
        if obj.type == "MESH":
            for prefix in WINDOW_PREFIXES:
                if obj.name.lower().startswith(prefix):
                    # Record position and dimensions
                    min_bound, max_bound = get_object_bounding_box(obj)
                    center = (min_bound + max_bound) / 2
                    width = max_bound.x - min_bound.x
                    height = max_bound.z - min_bound.z
                    depth = max_bound.y - min_bound.y
                    obj_name = obj.name

                    # Delete old object
                    bpy.data.objects.remove(obj, do_unlink=True)

                    # Create simple plane
                    bpy.ops.mesh.primitive_plane_add(
                        size=1, location=center
                    )
                    plane = bpy.context.active_object
                    plane.name = f"{obj_name}_simplified"
                    plane.scale = (
                        width / 2,
                        depth / 2,
                        height / 2,
                    )
                    bpy.ops.object.transform_apply(scale=True)
                    break

    # Apply decimate (ratio=0.15)
    for obj in bpy.data.objects:
        if obj.type == "MESH":
            mod = obj.modifiers.new(name="Decimate_LOD2", type="DECIMATE")
            mod.ratio = 0.15
            apply_all_modifiers(obj)

    # Count and select
    total_verts, total_faces = 0, 0
    for obj in bpy.data.objects:
        if obj.type == "MESH":
            obj.select_set(True)
            v, f = count_mesh_elements(obj)
            total_verts += v
            total_faces += f

    # Export
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{address}_LOD2.fbx"
    export_fbx(output_path)

    return total_verts, total_faces, str(output_path)


def generate_lod3(
    output_dir: Path, address: str
) -> tuple[int, int, str]:
    """
    LOD3: Box massing only (single grey cube).

    Returns: (vertex_count, face_count, output_path)
    """
    # Find bounding box of original geometry
    min_bounds, max_bounds = None, None
    for obj in bpy.data.objects:
        if obj.type == "MESH":
            min_b, max_b = get_object_bounding_box(obj)
            if min_bounds is None:
                min_bounds, max_bounds = min_b, max_b
            else:
                min_bounds = Vector(
                    (
                        min(min_bounds.x, min_b.x),
                        min(min_bounds.y, min_b.y),
                        min(min_bounds.z, min_b.z),
                    )
                )
                max_bounds = Vector(
                    (
                        max(max_bounds.x, max_b.x),
                        max(max_bounds.y, max_b.y),
                        max(max_bounds.z, max_b.z),
                    )
                )

    clear_scene()

    if min_bounds is not None and max_bounds is not None:
        box = create_box_massing(min_bounds, max_bounds)
        box.select_set(True)
        v, f = count_mesh_elements(box)
    else:
        # Fallback: create unit cube
        bpy.ops.mesh.primitive_cube_add(size=1)
        box = bpy.context.active_object
        mat = bpy.data.materials.new(name="LOD3_Massing")
        mat.use_nodes = True
        bsdf = mat.node_tree.nodes["Principled BSDF"]
        bsdf.inputs["Base Color"].default_value = (0.4, 0.4, 0.4, 1.0)
        box.data.materials.append(mat)
        box.select_set(True)
        v, f = count_mesh_elements(box)

    # Export
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{address}_LOD3.fbx"
    export_fbx(output_path)

    return v, f, str(output_path)


def process_building(
    blend_path: Path, output_dir: Path, skip_existing: bool = False,
    base_texture_size: int = 2048,
) -> bool:
    """
    Process a single building file, generating all 4 LOD levels.

    Returns: True if successful, False otherwise.
    """
    # Extract address from filename
    stem = blend_path.stem
    address = stem.replace("_", " ")

    # Check skip-existing
    lod0_path = output_dir / f"{address}_LOD0.fbx"
    if skip_existing and lod0_path.exists():
        print(f"  Skipping {address} (LOD0 exists)")
        return True

    print(f"Processing {address}...")

    # Load blend file
    try:
        bpy.ops.wm.open_mainfile(filepath=str(blend_path))
    except Exception as e:
        print(f"  Error loading {blend_path}: {e}")
        return False

    results = []

    # Generate each LOD
    try:
        print(f"  Generating LOD0...")
        v0, f0, p0 = generate_lod0(output_dir, address)
        results.append({"level": 0, "fbx_path": p0, "face_count": f0, "vertex_count": v0})
        print(f"    LOD0: {v0} verts, {f0} faces")

        # Reload for next LOD
        bpy.ops.wm.open_mainfile(filepath=str(blend_path))

        print(f"  Generating LOD1...")
        v1, f1, p1 = generate_lod1(output_dir, address)
        results.append({"level": 1, "fbx_path": p1, "face_count": f1, "vertex_count": v1})
        print(f"    LOD1: {v1} verts, {f1} faces ({f1/f0*100:.1f}%)")

        # Reload for next LOD
        bpy.ops.wm.open_mainfile(filepath=str(blend_path))

        print(f"  Generating LOD2...")
        v2, f2, p2 = generate_lod2(output_dir, address)
        results.append({"level": 2, "fbx_path": p2, "face_count": f2, "vertex_count": v2})
        print(f"    LOD2: {v2} verts, {f2} faces ({f2/f0*100:.1f}%)")

        # Reload for next LOD
        bpy.ops.wm.open_mainfile(filepath=str(blend_path))

        print(f"  Generating LOD3...")
        v3, f3, p3 = generate_lod3(output_dir, address)
        results.append({"level": 3, "fbx_path": p3, "face_count": f3, "vertex_count": v3})
        print(f"    LOD3: {v3} verts, {f3} faces ({f3/f0*100:.1f}%)")

    except Exception as e:
        print(f"  Error generating LODs: {e}")
        return False

    # Compute per-LOD texture resolution tiers
    for entry in results:
        lod_level = entry["level"]
        tier_ratio = LOD_TEXTURE_TIERS.get(lod_level, 0)
        if tier_ratio == 0:
            entry["texture_size"] = 0
        else:
            # Scale from base: LOD0=base, LOD1=base/2, LOD2=base/4
            scale_factor = tier_ratio / LOD_TEXTURE_TIERS[0]
            entry["texture_size"] = max(64, int(base_texture_size * scale_factor))

    # Write manifest
    manifest: dict[str, Any] = {
        "address": address,
        "source_blend": str(blend_path),
        "base_texture_size": base_texture_size,
        "lod_levels": results,
    }
    manifest_path = output_dir / f"{address}_lod_manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    print(f"  Wrote manifest: {manifest_path}")
    return True


def main() -> None:
    """Main entry point."""
    args = parse_args()

    output_dir = Path(args.output_dir)

    if args.blend:
        # Single file mode
        blend_path = Path(args.blend)
        if not blend_path.exists():
            print(f"Error: Blend file not found: {blend_path}")
            sys.exit(1)

        success = process_building(blend_path, output_dir, args.skip_existing,
                                   base_texture_size=args.base_texture_size)
        sys.exit(0 if success else 1)

    elif args.source_dir:
        # Batch mode
        source_dir = Path(args.source_dir)
        if not source_dir.exists():
            print(f"Error: Source directory not found: {source_dir}")
            sys.exit(1)

        blend_files = sorted(source_dir.glob("*.blend"))
        if args.limit:
            blend_files = blend_files[: args.limit]

        processed = 0
        for blend_path in blend_files:
            if process_building(blend_path, output_dir, args.skip_existing,
                                base_texture_size=args.base_texture_size):
                processed += 1

        print(f"\nProcessed {processed}/{len(blend_files)} buildings")

    else:
        print("Error: Must specify either --blend or --source-dir")
        sys.exit(1)


if __name__ == "__main__":
    main()
