#!/usr/bin/env python3
"""Export complete Kensington Market scene to GLB or FBX format.

This script assembles all individual building .blend files into a single
unified scene with proper positioning, LODs, and ground reference.

Usage (inside Blender):
    blender --background --python export_full_scene.py -- [--format glb] \
        [--partition-by-block] [--output outputs/exports/kensington_full_scene.glb]

Options:
    --format glb|fbx        Export format (default: glb)
    --partition-by-block    Export separate files per street instead of one file
    --output PATH           Output file path
    --dry-run              Show planned operations without executing

The script:
1. Starts with empty Blender scene
2. Loads site coordinates from params/_site_coordinates.json
3. Appends all building collections from outputs/full/*.blend
4. Positions buildings using site coordinates (x, y offset + rotation)
5. Creates ground plane from footprint polygons (GIS scene data)
6. Exports as single GLB/FBX or partitioned by street
"""

import argparse
import json
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Tuple

# Blender imports
import bpy
import bmesh
from mathutils import Vector, Euler, Matrix


SCRIPT_DIR = Path(__file__).parent
PROJECT_DIR = SCRIPT_DIR.parent
PARAMS_DIR = PROJECT_DIR / "params"
OUTPUTS_DIR = PROJECT_DIR / "outputs"
OUTPUTS_FULL_DIR = OUTPUTS_DIR / "full"
OUTPUTS_EXPORTS_DIR = OUTPUTS_DIR / "exports"


def load_site_coordinates() -> Dict[str, Dict[str, float]]:
    """Load building positions and rotations from site coordinates file."""
    coords_file = PARAMS_DIR / "_site_coordinates.json"
    if not coords_file.exists():
        print(f"Warning: {coords_file} not found")
        return {}

    with open(coords_file, "r", encoding="utf-8") as f:
        return json.load(f)


def load_building_param(address: str) -> Optional[Dict]:
    """Load a single building parameter file by address."""
    safe_name = address.replace(" ", "_").replace("/", "-")
    param_file = PARAMS_DIR / f"{safe_name}.json"

    if not param_file.exists():
        return None

    try:
        with open(param_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def load_gis_scene() -> Optional[Dict]:
    """Load GIS scene data for footprints."""
    gis_file = OUTPUTS_DIR / "gis_scene.json"
    if not gis_file.exists():
        print(f"Warning: {gis_file} not found")
        return None

    try:
        with open(gis_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def clear_scene():
    """Remove all objects from the scene."""
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)

    # Clear unused data
    for coll in bpy.data.collections:
        bpy.data.collections.remove(coll)


def append_building_from_blend(blend_path: Path, building_name: str) -> Optional[List]:
    """Append all objects from a building .blend file.

    Args:
        blend_path: Path to .blend file
        building_name: Name of the building (for collection)

    Returns:
        List of appended objects or None if failed
    """
    if not blend_path.exists():
        print(f"  Warning: {blend_path} not found")
        return None

    try:
        # Link all objects from the building collection
        with bpy.data.libraries.load(str(blend_path), link=False) as (data_from, data_to):
            # Copy all collections
            data_to.collections = data_from.collections

        appended_objects = []
        for collection in data_to.collections:
            bpy.context.scene.collection.children.link(collection)
            appended_objects.extend(collection.objects)

        return appended_objects

    except Exception as e:
        print(f"  Error appending {blend_path}: {e}")
        return None


def position_building_objects(
    objects: List, x: float, y: float, rotation_deg: float
) -> None:
    """Position and rotate a list of objects.

    Args:
        objects: List of Blender objects
        x: X position (metres)
        y: Y position (metres)
        rotation_deg: Rotation in degrees around Z axis
    """
    # Convert rotation to radians
    import math

    rotation_rad = math.radians(rotation_deg)

    for obj in objects:
        # Store original local position
        obj.location = Vector((x, y, obj.location.z))

        # Apply rotation around Z axis
        obj.rotation_euler = Euler((0, 0, rotation_rad), "XYZ")


def create_ground_plane_from_footprints(gis_data: Dict, collection_name: str = "Ground"):
    """Create a ground plane mesh from footprint polygons.

    Args:
        gis_data: GIS scene data dict
        collection_name: Name for the ground collection
    """
    if "footprints" not in gis_data:
        print("  Warning: No footprints in GIS data")
        return

    footprints = gis_data["footprints"][:100]  # Use first 100 to avoid huge meshes

    # Create a new mesh and object
    mesh = bpy.data.meshes.new("ground_plane")
    obj = bpy.data.objects.new("ground_plane", mesh)

    # Create collection for ground
    ground_coll = bpy.data.collections.new(collection_name)
    bpy.context.scene.collection.children.link(ground_coll)
    ground_coll.objects.link(obj)

    # Build mesh from footprints
    bm = bmesh.new()

    for footprint in footprints:
        rings = footprint.get("rings", [])
        if not rings:
            continue

        # Take the first ring (exterior boundary)
        ring = rings[0]
        if len(ring) < 3:
            continue

        # Add vertices for this ring
        verts = []
        for x, y in ring[:-1]:  # Skip last point (closes polygon)
            vert = bm.verts.new((x, y, 0.0))
            verts.append(vert)

        # Create face from vertices
        if len(verts) >= 3:
            try:
                bm.faces.new(verts)
            except Exception:
                pass  # Skip invalid faces

    bm.to_mesh(mesh)
    bm.free()
    mesh.update()

    # Set material to grey
    mat = bpy.data.materials.new("ground_material")
    mat.use_nodes = True
    mat.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (
        0.7,
        0.7,
        0.7,
        1.0,
    )
    obj.data.materials.append(mat)

    print(f"  Created ground plane with {len(footprints)} footprints")


def export_glb(output_path: Path) -> bool:
    """Export scene as GLB with Draco compression.

    Args:
        output_path: Path to write .glb file

    Returns:
        True if successful
    """
    try:
        bpy.ops.export_scene.glb(
            filepath=str(output_path),
            use_draco_mesh_compression=True,
            draco_mesh_compression_level=7,
            export_format="GLB",
        )
        print(f"  Exported GLB: {output_path}")
        return True
    except Exception as e:
        print(f"  Error exporting GLB: {e}")
        return False


def export_fbx(output_path: Path) -> bool:
    """Export scene as FBX.

    Args:
        output_path: Path to write .fbx file

    Returns:
        True if successful
    """
    try:
        bpy.ops.export_scene.fbx(
            filepath=str(output_path),
            axis_forward="-Y",
            axis_up="Z",
            global_scale=1.0,
            use_mesh_modifiers=True,
        )
        print(f"  Exported FBX: {output_path}")
        return True
    except Exception as e:
        print(f"  Error exporting FBX: {e}")
        return False


def get_building_street(building_name: str, site_coords: Dict[str, Dict]) -> Optional[str]:
    """Get the street name for a building from site coordinates or params.

    Args:
        building_name: Building address
        site_coords: Site coordinates dict

    Returns:
        Street name or None
    """
    # Try to get from site coordinates first (if it was added there)
    if building_name in site_coords:
        coord = site_coords[building_name]
        if "street" in coord:
            return coord["street"]

    # Try to get from building parameters
    params = load_building_param(building_name)
    if params and "site" in params:
        return params["site"].get("street")

    # Extract from address if possible (last part)
    parts = building_name.rsplit(" ", 1)
    if len(parts) == 2:
        return parts[1]

    return None


def main():
    # Parse command-line arguments after --
    argv = sys.argv
    if "--" in argv:
        argv = argv[argv.index("--") + 1 :]
    else:
        argv = []

    parser = argparse.ArgumentParser(description="Export full Kensington Market scene")
    parser.add_argument(
        "--format",
        choices=["glb", "fbx"],
        default="glb",
        help="Export format",
    )
    parser.add_argument(
        "--partition-by-block",
        action="store_true",
        help="Export separate files per street",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=OUTPUTS_EXPORTS_DIR / "kensington_full_scene.glb",
        help="Output file path",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show planned operations without executing",
    )

    args = parser.parse_args(argv)

    print("=" * 70)
    print("Kensington Market Full Scene Export")
    print("=" * 70)

    # Load data
    print("\nLoading data...")
    site_coords = load_site_coordinates()
    print(f"  Loaded {len(site_coords)} site coordinates")

    gis_data = load_gis_scene()
    if gis_data:
        print(f"  Loaded GIS scene data")

    # Scan for building .blend files
    print(f"\nScanning {OUTPUTS_FULL_DIR}...")
    blend_files = sorted(OUTPUTS_FULL_DIR.glob("*.blend"))
    # Filter to only the main .blend files (not .blend1 backups)
    blend_files = [f for f in blend_files if not f.name.endswith(".blend1")]
    print(f"  Found {len(blend_files)} building .blend files")

    if args.dry_run:
        print("\nDry-run mode: planning operations only")
        print(f"  Would process {len(blend_files)} buildings")
        print(f"  Would export to: {args.output}")
        return

    # Clear scene
    print("\nClearing Blender scene...")
    clear_scene()

    # Load buildings
    print("\nLoading buildings...")
    buildings_loaded = 0
    buildings_by_street = {}

    for idx, blend_file in enumerate(blend_files, 1):
        # Extract building name from filename (remove .blend)
        building_name = blend_file.stem

        # Get coordinates
        coords = site_coords.get(building_name, {})
        x = coords.get("x", 0.0)
        y = coords.get("y", 0.0)
        rotation_deg = coords.get("rotation_deg", 0.0)

        # Append building
        objects = append_building_from_blend(blend_file, building_name)
        if objects:
            position_building_objects(objects, x, y, rotation_deg)
            buildings_loaded += 1

            # Track by street if partitioning
            if args.partition_by_block:
                street = get_building_street(building_name, site_coords) or "Unknown"
                if street not in buildings_by_street:
                    buildings_by_street[street] = []
                buildings_by_street[street].append(building_name)

        # Progress indicator
        if idx % 100 == 0:
            print(f"  Loaded {idx}/{len(blend_files)} buildings...")

    print(f"  Total buildings loaded: {buildings_loaded}")

    # Create ground plane
    if gis_data:
        print("\nCreating ground plane from footprints...")
        create_ground_plane_from_footprints(gis_data)

    # Ensure output directory exists
    args.output.parent.mkdir(parents=True, exist_ok=True)

    # Export
    print(f"\nExporting scene as {args.format.upper()}...")

    if args.partition_by_block:
        print(f"Exporting {len(buildings_by_street)} separate files by street...")
        for street in sorted(buildings_by_street.keys()):
            # Create subdirectory for this street
            street_dir = args.output.parent / "blocks"
            street_dir.mkdir(exist_ok=True)

            # Safe filename for street
            safe_street = street.replace(" ", "_").replace("/", "-")
            output_file = street_dir / f"{safe_street}.{args.format}"

            print(f"  Exporting {street}...")

            if args.format == "glb":
                export_glb(output_file)
            else:
                export_fbx(output_file)

    else:
        # Single file export
        if args.format == "glb":
            export_glb(args.output)
        else:
            export_fbx(args.output)

    # Write manifest
    manifest = {
        "timestamp": datetime.now().isoformat(),
        "format": args.format.upper(),
        "buildings_loaded": buildings_loaded,
        "output_path": str(args.output),
        "coordinate_system": {
            "source": "SRID 2952 (NAD83 Ontario MTM Zone 10)",
            "origin": [312672.94, 4834994.86],
            "units": "metres",
        },
        "export_settings": {
            "partitioned_by_block": args.partition_by_block,
        },
    }

    if args.partition_by_block:
        manifest["streets"] = list(buildings_by_street.keys())
        manifest["buildings_by_street"] = {
            street: len(addrs) for street, addrs in buildings_by_street.items()
        }

    manifest_path = args.output.parent / "export_manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    print(f"\nManifest written to {manifest_path}")
    print("\nExport complete!")


if __name__ == "__main__":
    main()
