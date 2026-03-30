"""
Export a single Blender building to FBX with baked textures.

Runs inside Blender's Python environment. Applies all modifiers, joins meshes by
material, bakes procedural materials to textures, and exports FBX with metadata.

Usage:
    blender --background outputs/full/22_Lippincott_St.blend --python scripts/export_building_fbx.py -- --address "22 Lippincott St" [--texture-size 2048]
    blender --background --python scripts/export_building_fbx.py -- --blend outputs/full/22_Lippincott_St.blend --address "22 Lippincott St"
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import bpy

# Shared bake utilities (eliminates duplication with batch_export_unreal.py)
sys.path.insert(0, str(Path(__file__).resolve().parent))
from bake_utils import (
    apply_all_modifiers,
    bake_all_materials,
    export_fbx,
    export_glb,
    extract_address_from_blend,
    join_meshes_by_material,
    sanitize_address,
    write_export_metadata,
    write_material_sidecar,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
EXPORTS_DIR = REPO_ROOT / "outputs" / "exports"


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments after -- separator."""
    argv = sys.argv
    if "--" in argv:
        argv = argv[argv.index("--") + 1 :]
    else:
        argv = []

    parser = argparse.ArgumentParser(description="Export Blender building to FBX with baked textures")
    parser.add_argument("--address", help="Building address (extracted from filename if not provided)")
    parser.add_argument("--blend", help="Path to .blend file (if not loaded via Blender CLI)")
    parser.add_argument("--texture-size", type=int, default=2048, help="Texture resolution (default: 2048)")
    parser.add_argument("--skip-glb", action="store_true", help="Skip GLB sidecar export")
    return parser.parse_args(argv)


def main():
    """Main entry point."""
    args = parse_args()

    # Load blend file if specified
    if args.blend:
        blend_path = Path(args.blend).resolve()
        if not blend_path.exists():
            print(f"Error: Blend file not found: {blend_path}")
            sys.exit(1)
        print(f"Loading {blend_path}...")
        bpy.ops.wm.open_mainfile(filepath=str(blend_path))

    # Determine address
    address = args.address
    if not address:
        if bpy.data.filepath:
            address = extract_address_from_blend(bpy.data.filepath)
        else:
            print("Error: --address required when no .blend file is loaded")
            sys.exit(1)

    safe_address = sanitize_address(address)
    export_dir = EXPORTS_DIR / safe_address

    print(f"\nExporting {address}")
    print(f"  Output: {export_dir}")
    print(f"  Texture size: {args.texture_size}x{args.texture_size}\n")

    # Step 1: Apply modifiers
    print("Step 1: Applying all modifiers...")
    apply_all_modifiers()

    # Step 2: Join meshes by material
    print("Step 2: Joining meshes by material...")
    join_meshes_by_material()

    # Step 3: Bake procedural materials to textures
    print("Step 3: Baking procedural materials to textures...")
    bake_all_materials(args.texture_size, export_dir)

    # Step 4: Export FBX
    print("Step 4: Exporting to FBX...")
    fbx_path = export_fbx(address, export_dir)
    print(f"  Exported to {fbx_path}")
    glb_path = None
    if not args.skip_glb:
        print("Step 4b: Exporting GLB sidecar...")
        glb_path = export_glb(address, export_dir)
        print(f"  Exported to {glb_path}")

    # Step 5: Write metadata
    print("Step 5: Writing metadata...")
    metadata = write_export_metadata(address, export_dir, fbx_path, args.texture_size, glb_path=glb_path)
    print(f"  Metadata written to {export_dir / 'export_meta.json'}")

    # Step 6: Write material property sidecar
    print("Step 6: Writing material properties sidecar...")
    sidecar_path = write_material_sidecar(export_dir)
    print(f"  Material properties written to {sidecar_path}")

    print(f"\nExport complete: {address}")
    print(f"  FBX: {fbx_path}")
    if glb_path:
        print(f"  GLB: {glb_path}")
    print(f"  Textures: {len(metadata.get('texture_files', []))} files")
    print(f"  Materials: {metadata.get('material_count', 0)}")


if __name__ == "__main__":
    main()
