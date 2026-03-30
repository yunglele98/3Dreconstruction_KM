"""
Batch export multiple Blender buildings to FBX format for Unreal Engine.

Processes a directory of .blend files, applying modifiers, baking textures,
and exporting to FBX format. Generates a manifest CSV with geometry and material
metadata suitable for Unreal Engine import.

Run headless in Blender:
    blender --background --python scripts/batch_export_unreal.py -- --source-dir outputs/full/ [--limit 10] [--match "Augusta"] [--skip-existing]

Output:
    outputs/exports/<address>/<address>.fbx
    outputs/exports/<address>/textures/*.png
    outputs/exports/<address>/export_meta.json
    outputs/exports/<address>/materials.json
    outputs/exports/manifest.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import tempfile
import time
import traceback
from pathlib import Path

import bpy

# Shared bake utilities (eliminates duplication with export_building_fbx.py)
sys.path.insert(0, str(Path(__file__).resolve().parent))
from bake_utils import (
    apply_all_modifiers,
    bake_all_materials,
    export_fbx,
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

    parser = argparse.ArgumentParser(description="Batch export Blender buildings to FBX for Unreal Engine")
    parser.add_argument("--source-dir", required=True, help="Directory containing .blend files")
    parser.add_argument("--limit", type=int, default=None, help="Maximum number of files to process")
    parser.add_argument("--match", default=None, help="Filter filenames by partial match")
    parser.add_argument("--skip-existing", action="store_true", help="Skip if export_meta.json already exists")
    parser.add_argument("--texture-size", type=int, default=2048, help="Texture resolution (default: 2048)")
    parser.add_argument("--dry-run", action="store_true", help="List files without processing")
    return parser.parse_args(argv)


def find_blend_files(source_dir: Path, match: str | None, limit: int | None) -> list[Path]:
    """Find all .blend files in source directory, with optional filtering."""
    print(f"Step 1: Scanning {source_dir}...")

    blend_files = []
    for blend_path in sorted(source_dir.glob("*.blend")):
        # Skip custom variants and backup files
        if blend_path.name.startswith("_") or blend_path.name.startswith("."):
            continue
        if blend_path.name.endswith(".blend1"):
            continue
        if "*custom*" in blend_path.name.lower():
            continue

        # Apply match filter
        if match and match.lower() not in blend_path.name.lower():
            continue

        blend_files.append(blend_path)

        # Apply limit
        if limit and len(blend_files) >= limit:
            break

    print(f"  Found {len(blend_files)} .blend files")
    return blend_files


def _atomic_write_json(filepath, data, ensure_ascii=False):
    """Write JSON atomically via temp file + rename to prevent corruption."""
    filepath = Path(filepath)
    filepath.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", dir=filepath.parent, delete=False,
        suffix=".tmp", encoding="utf-8",
    ) as tmp:
        json.dump(data, tmp, indent=2, ensure_ascii=ensure_ascii)
        tmp.write("\n")
        tmp_path = Path(tmp.name)
    os.replace(str(tmp_path), str(filepath))


def _write_error_log(export_dir: Path, address: str, error: str, tb: str):
    """Write a per-building error log for post-mortem debugging."""
    export_dir.mkdir(parents=True, exist_ok=True)
    error_data = {
        "address": address,
        "error": error,
        "traceback": tb,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    _atomic_write_json(export_dir / "export_error.json", error_data)


def process_blend_file(
    blend_path: Path,
    texture_size: int,
    skip_existing: bool,
) -> dict | None:
    """Process a single .blend file. Returns metadata dict or None if skipped."""
    address = extract_address_from_blend(blend_path)
    safe_address = sanitize_address(address)
    export_dir = EXPORTS_DIR / safe_address

    # Check if already exported
    if skip_existing and (export_dir / "export_meta.json").exists():
        print(f"    [SKIPPED] (already exported)")
        return None

    t0 = time.monotonic()
    try:
        print(f"    Loading {blend_path.name}...")
        bpy.ops.wm.open_mainfile(filepath=str(blend_path.resolve()))

        print(f"    Applying modifiers...")
        apply_all_modifiers()

        print(f"    Joining meshes by material...")
        join_meshes_by_material()

        print(f"    Baking textures...")
        bake_all_materials(texture_size, export_dir)

        print(f"    Exporting FBX...")
        fbx_path = export_fbx(address, export_dir)

        print(f"    Writing metadata...")
        metadata = write_export_metadata(address, export_dir, fbx_path, texture_size)

        print(f"    Writing material sidecar...")
        write_material_sidecar(export_dir)

        elapsed = time.monotonic() - t0
        print(f"    [OK] {address} in {elapsed:.1f}s")

        # Remove any prior error log on success
        error_log = export_dir / "export_error.json"
        if error_log.exists():
            error_log.unlink()

        return metadata

    except Exception as e:
        elapsed = time.monotonic() - t0
        tb = traceback.format_exc()
        print(f"    [ERROR] {address} after {elapsed:.1f}s: {e}")
        _write_error_log(export_dir, address, str(e), tb)
        # Reset Blender state so next file starts clean
        try:
            bpy.ops.wm.read_homefile(use_empty=True)
        except Exception:
            pass
        return None


def write_manifest_csv(all_metadata: list[dict]) -> Path:
    """Write manifest CSV with all exported buildings."""
    print("\nStep 3: Writing manifest CSV...")

    manifest_path = EXPORTS_DIR / "manifest.csv"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = [
        "address",
        "fbx_path",
        "texture_count",
        "texture_diffuse",
        "texture_normal",
        "texture_roughness",
        "texture_metallic",
        "texture_ao",
        "bbox_width",
        "bbox_height",
        "bbox_depth",
        "vertex_count",
        "face_count",
        "material_count",
        "export_timestamp",
    ]

    # Atomic write: write to temp, then rename
    tmp_manifest = manifest_path.with_suffix(".csv.tmp")
    with open(tmp_manifest, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for meta in all_metadata:
            bbox = meta["bounding_box"]

            # Check for specific texture files
            texture_flags = {tf: False for tf in ["diffuse", "normal", "roughness", "metallic", "ao"]}
            for tf in meta["texture_files"]:
                for key in texture_flags:
                    if key in tf.lower():
                        texture_flags[key] = True

            row = {
                "address": meta["address"],
                "fbx_path": meta["fbx_path"],
                "texture_count": meta["texture_count"],
                "texture_diffuse": "Yes" if texture_flags["diffuse"] else "No",
                "texture_normal": "Yes" if texture_flags["normal"] else "No",
                "texture_roughness": "Yes" if texture_flags["roughness"] else "No",
                "texture_metallic": "Yes" if texture_flags["metallic"] else "No",
                "texture_ao": "Yes" if texture_flags["ao"] else "No",
                "bbox_width": f"{bbox['width']:.2f}",
                "bbox_height": f"{bbox['height']:.2f}",
                "bbox_depth": f"{bbox['depth']:.2f}",
                "vertex_count": meta["vertex_count"],
                "face_count": meta["face_count"],
                "material_count": meta["material_count"],
                "export_timestamp": meta["export_timestamp"],
            }
            writer.writerow(row)

    os.replace(str(tmp_manifest), str(manifest_path))
    print(f"  Manifest written to {manifest_path}")
    return manifest_path


def main():
    """Main entry point."""
    args = parse_args()

    source_dir = Path(args.source_dir).resolve()

    print(f"\n{'='*70}")
    print(f"Batch Export to Unreal Engine")
    print(f"{'='*70}")
    print(f"Source directory: {source_dir}")
    print(f"Export directory: {EXPORTS_DIR}")
    print(f"Texture size: {args.texture_size}x{args.texture_size}")
    if args.match:
        print(f"Filter: {args.match}")
    if args.limit:
        print(f"Limit: {args.limit}")
    if args.skip_existing:
        print(f"Skip existing: Yes")
    print(f"{'='*70}\n")

    # Find .blend files
    blend_files = find_blend_files(source_dir, args.match, args.limit)

    if not blend_files:
        print("No .blend files found!")
        sys.exit(1)

    print(f"\nStep 2: Processing {len(blend_files)} buildings...\n")

    if args.dry_run:
        print("DRY RUN - Files to process:")
        for i, blend_path in enumerate(blend_files, 1):
            address = extract_address_from_blend(blend_path)
            print(f"  {i}. {address}")
        print(f"\nTotal: {len(blend_files)} files")
        return

    # Process each file
    all_metadata = []
    failed_addresses = []
    batch_t0 = time.monotonic()

    for i, blend_path in enumerate(blend_files, 1):
        address = extract_address_from_blend(blend_path)
        print(f"[{i}/{len(blend_files)}] {address}")

        metadata = process_blend_file(blend_path, args.texture_size, args.skip_existing)
        if metadata:
            all_metadata.append(metadata)
        else:
            failed_addresses.append(address)

    # Write manifest
    if all_metadata:
        write_manifest_csv(all_metadata)

    batch_elapsed = time.monotonic() - batch_t0
    n_ok = len(all_metadata)
    n_fail = len(failed_addresses)

    print(f"\n{'='*70}")
    print(f"Batch export complete!")
    print(f"Processed: {n_ok} buildings  |  Failed: {n_fail}  |  Time: {batch_elapsed:.0f}s")
    print(f"Export directory: {EXPORTS_DIR}")
    if failed_addresses:
        print(f"\nFailed addresses:")
        for addr in failed_addresses:
            print(f"  - {addr}")
    print(f"{'='*70}\n")


if __name__ == "__main__":
    main()
