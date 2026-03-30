"""
Generate collision meshes (convex hulls) from full-detail Blender building files.

Process:
1. Load .blend, select all meshes
2. Join meshes into one object
3. Decimate to 10% to simplify
4. Apply convex hull via bmesh.ops.convex_hull()
5. Export as FBX + metadata JSON

Runs inside Blender:
    blender --background --python scripts/generate_collision_mesh.py -- \\
        --blend outputs/full/22_Lippincott_St.blend

Batch mode:
    blender --background --python scripts/generate_collision_mesh.py -- \\
        --source-dir outputs/full/ \\
        [--skip-existing]

Output: <address>_collision.fbx + <address>_collision_meta.json per building.
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
DEFAULT_OUTPUT_DIR = REPO_ROOT / "outputs" / "exports" / "collision"


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments from after -- separator."""
    argv = sys.argv
    if "--" in argv:
        argv = argv[argv.index("--") + 1 :]
    else:
        argv = []

    parser = argparse.ArgumentParser(
        description="Generate collision meshes (convex hulls) for buildings"
    )
    parser.add_argument(
        "--blend",
        type=str,
        help="Path to single .blend file",
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
        help="Output directory for collision mesh exports",
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="Skip if collision mesh already exists",
    )

    return parser.parse_args(argv)


def clear_scene() -> None:
    """Remove all objects from the scene."""
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)


def get_bounding_box(obj: bpy.types.Object) -> tuple[Vector, Vector]:
    """Get min and max bounding box corners."""
    if obj.type != "MESH":
        return Vector(), Vector()

    bbox_corners = [Vector(corner) for corner in obj.bound_box]
    min_x = min(c.x for c in bbox_corners)
    max_x = max(c.x for c in bbox_corners)
    min_y = min(c.y for c in bbox_corners)
    max_y = max(c.y for c in bbox_corners)
    min_z = min(c.z for c in bbox_corners)
    max_z = max(c.z for c in bbox_corners)
    return Vector((min_x, min_y, min_z)), Vector((max_x, max_y, max_z))


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


def join_meshes() -> bpy.types.Object | None:
    """
    Join all mesh objects in the scene into a single object.

    Returns: The joined mesh object, or None if no meshes found.
    """
    mesh_objects = [obj for obj in bpy.data.objects if obj.type == "MESH"]

    if not mesh_objects:
        return None

    if len(mesh_objects) == 1:
        obj = mesh_objects[0]
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        return obj

    # Select all meshes
    for obj in mesh_objects:
        obj.select_set(True)

    # Set active to first mesh
    bpy.context.view_layer.objects.active = mesh_objects[0]

    # Join
    bpy.ops.object.join()
    return bpy.context.active_object


def decimate_mesh(obj: bpy.types.Object, ratio: float = 0.1) -> None:
    """Apply decimate modifier to a mesh object."""
    if obj.type != "MESH":
        return

    mod = obj.modifiers.new(name="Decimate_Collision", type="DECIMATE")
    mod.ratio = ratio

    # Apply
    try:
        with bpy.context.temp_override(object=obj):
            bpy.ops.object.modifier_apply(modifier=mod.name)
    except RuntimeError:
        print(f"  Warning: Could not apply decimate modifier")


def remove_party_wall_vertices(
    bm: bmesh.types.BMesh,
    min_x: float,
    max_x: float,
    inset: float = 0.05,
    party_left: bool = False,
    party_right: bool = False,
) -> int:
    """
    Remove vertices on party wall sides before convex hull computation.

    Args:
        bm: BMesh object
        min_x, max_x: X bounds of the mesh
        inset: Inset distance from edge (default 0.05 = 5cm)
        party_left: Remove left side vertices if True
        party_right: Remove right side vertices if True

    Returns: Number of vertices removed
    """
    verts_to_delete = []
    left_threshold = -(max_x - min_x) / 2 + inset
    right_threshold = (max_x - min_x) / 2 - inset

    for vert in bm.verts:
        if party_left and vert.co.x < left_threshold:
            verts_to_delete.append(vert)
        elif party_right and vert.co.x > right_threshold:
            verts_to_delete.append(vert)

    # Delete marked vertices
    for vert in verts_to_delete:
        bm.verts.remove(vert)

    return len(verts_to_delete)


def compute_convex_hull(
    obj: bpy.types.Object,
    party_left: bool = False,
    party_right: bool = False,
) -> bool:
    """
    Compute convex hull for a mesh object using bmesh.

    If party_left or party_right is True, removes vertices on that side
    before computing the convex hull to avoid overlapping collision geometry
    with adjacent buildings.

    Returns: True if successful, False otherwise.
    """
    if obj.type != "MESH":
        return False

    try:
        mesh = obj.data

        # Create bmesh from mesh
        bm = bmesh.new()
        bm.from_mesh(mesh)

        # Ensure all vertices are in the bmesh
        bm.verts.ensure_lookup_table()

        # Remove party wall vertices if needed
        removed_count = 0
        if party_left or party_right:
            # Get bounds to compute inset thresholds
            min_x = min(v.co.x for v in bm.verts)
            max_x = max(v.co.x for v in bm.verts)
            removed_count = remove_party_wall_vertices(
                bm, min_x, max_x, inset=0.05, party_left=party_left, party_right=party_right
            )
            if removed_count > 0:
                print(
                    f"  Removed {removed_count} vertices from party wall(s) "
                    f"(left={party_left}, right={party_right})"
                )

        # Compute convex hull
        verts_in = list(bm.verts)
        bmesh.ops.convex_hull(bm, input=verts_in)

        # Write back to mesh
        bm.to_mesh(mesh)
        bm.free()

        # Ensure normals are correct
        mesh.update()
        return True

    except Exception as e:
        print(f"  Error computing convex hull: {e}")
        return False


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


def load_param_file(address: str) -> dict[str, Any] | None:
    """
    Load the parameter JSON file for a building by address.

    Args:
        address: Building address (e.g., "22 Lippincott St")

    Returns: Parsed param dict, or None if not found
    """
    param_path = REPO_ROOT / "params" / f"{address.replace(' ', '_')}.json"
    if not param_path.exists():
        return None

    try:
        with open(param_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"  Warning: Could not load param file {param_path}: {e}")
        return None


def process_building(
    blend_path: Path,
    output_dir: Path,
    skip_existing: bool = False,
) -> bool:
    """
    Process a single building file, generating collision mesh.

    Handles party walls by removing collision geometry on shared sides.

    Returns: True if successful, False otherwise.
    """
    # Extract address from filename
    stem = blend_path.stem
    address = stem.replace("_", " ")

    # Check skip-existing
    collision_path = output_dir / f"{address}_collision.fbx"
    if skip_existing and collision_path.exists():
        print(f"  Skipping {address} (collision mesh exists)")
        return True

    print(f"Processing {address}...")

    # Load param file to check for party walls
    params = load_param_file(address)
    party_left = False
    party_right = False
    if params:
        party_left = params.get("party_wall_left", False)
        party_right = params.get("party_wall_right", False)
        if party_left or party_right:
            print(f"  Party walls detected: left={party_left}, right={party_right}")

    # Load blend file
    try:
        bpy.ops.wm.open_mainfile(filepath=str(blend_path))
    except Exception as e:
        print(f"  Error loading {blend_path}: {e}")
        return False

    try:
        # Count initial geometry
        initial_verts, initial_faces = 0, 0
        for obj in bpy.data.objects:
            if obj.type == "MESH":
                v, f = count_mesh_elements(obj)
                initial_verts += v
                initial_faces += f

        print(f"  Initial: {initial_verts} verts, {initial_faces} faces")

        # Apply all modifiers
        for obj in bpy.data.objects:
            if obj.type == "MESH":
                apply_all_modifiers(obj)

        # Join all meshes
        joined = join_meshes()
        if joined is None:
            print(f"  Error: No meshes found in {blend_path}")
            return False

        print(f"  Joined meshes into: {joined.name}")

        # Decimate to 10%
        decimate_mesh(joined, ratio=0.1)
        decimated_verts, decimated_faces = count_mesh_elements(joined)
        print(f"  After decimate: {decimated_verts} verts, {decimated_faces} faces")

        # Compute convex hull (with party wall handling)
        if not compute_convex_hull(joined, party_left=party_left, party_right=party_right):
            print(f"  Error: Could not compute convex hull")
            return False

        hull_verts, hull_faces = count_mesh_elements(joined)
        print(f"  Convex hull: {hull_verts} verts, {hull_faces} faces")

        # Get bounding box before export
        min_bound, max_bound = get_bounding_box(joined)
        bbox_size = [
            max_bound.x - min_bound.x,
            max_bound.y - min_bound.y,
            max_bound.z - min_bound.z,
        ]

        # Select for export
        joined.select_set(True)
        bpy.context.view_layer.objects.active = joined

        # Export FBX
        output_dir.mkdir(parents=True, exist_ok=True)
        export_fbx(collision_path)
        print(f"  Exported: {collision_path}")

        # Write metadata
        metadata: dict[str, Any] = {
            "address": address,
            "source_blend": str(blend_path),
            "vertex_count": hull_verts,
            "face_count": hull_faces,
            "bounding_box": {
                "min": [float(min_bound.x), float(min_bound.y), float(min_bound.z)],
                "max": [float(max_bound.x), float(max_bound.y), float(max_bound.z)],
                "size": bbox_size,
            },
            "is_convex": True,
            "party_walls": {
                "left": party_left,
                "right": party_right,
            },
            "process_stats": {
                "initial_verts": initial_verts,
                "initial_faces": initial_faces,
                "decimated_verts": decimated_verts,
                "decimated_faces": decimated_faces,
            },
        }

        meta_path = output_dir / f"{address}_collision_meta.json"
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2)

        print(f"  Wrote metadata: {meta_path}")
        return True

    except Exception as e:
        print(f"  Error processing {address}: {e}")
        import traceback

        traceback.print_exc()
        return False


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

        success = process_building(blend_path, output_dir, args.skip_existing)
        sys.exit(0 if success else 1)

    elif args.source_dir:
        # Batch mode
        source_dir = Path(args.source_dir)
        if not source_dir.exists():
            print(f"Error: Source directory not found: {source_dir}")
            sys.exit(1)

        blend_files = sorted(source_dir.glob("*.blend"))
        processed = 0

        for blend_path in blend_files:
            if process_building(blend_path, output_dir, args.skip_existing):
                processed += 1

        print(f"\nProcessed {processed}/{len(blend_files)} buildings")

    else:
        print("Error: Must specify either --blend or --source-dir")
        sys.exit(1)


if __name__ == "__main__":
    main()
