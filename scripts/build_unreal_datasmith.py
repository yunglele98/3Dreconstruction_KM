#!/usr/bin/env python3
"""Generate a Datasmith-compatible XML scene description for Unreal Engine import.

This script converts the Kensington Market Blender building outputs into Unreal
Datasmith format, enabling import with full material and LOD data preservation.

Usage:
    python build_unreal_datasmith.py [--exports-dir outputs/exports/] \
        [--output outputs/exports/kensington_scene.udatasmith]

The script:
1. Loads site coordinates from params/_site_coordinates.json
2. Scans outputs/exports/ for FBX files and LOD variants
3. Generates Datasmith XML with StaticMeshActors, LODGroups, and collision meshes
4. Writes manifest JSON summarizing all actors and materials
"""

import argparse
import json
import re
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Tuple, Optional


SCRIPT_DIR = Path(__file__).parent
PROJECT_DIR = SCRIPT_DIR.parent
PARAMS_DIR = PROJECT_DIR / "params"
OUTPUTS_DIR = PROJECT_DIR / "outputs"


def load_site_coordinates() -> Dict[str, Dict[str, float]]:
    """Load building positions and rotations from site coordinates file.

    Returns:
        Dict mapping address -> {x, y, rotation_deg, ...}
    """
    coords_file = PARAMS_DIR / "_site_coordinates.json"
    if not coords_file.exists():
        print(f"Warning: {coords_file} not found, using empty coordinates")
        return {}

    with open(coords_file, "r", encoding="utf-8") as f:
        return json.load(f)


def load_building_param(address: str) -> Optional[Dict]:
    """Load a single building parameter file by address.

    Args:
        address: Building address (e.g., "100 Bellevue Ave")

    Returns:
        Parsed JSON dict or None if file not found
    """
    # Convert address to filename format: spaces -> underscores, handle special chars
    safe_name = address.replace(" ", "_").replace("/", "-")
    param_file = PARAMS_DIR / f"{safe_name}.json"

    if not param_file.exists():
        return None

    try:
        with open(param_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"Warning: Failed to parse {param_file}: {e}")
        return None


def get_facade_material_name(params: Dict) -> str:
    """Extract facade material name from building parameters.

    Args:
        params: Building parameter dict

    Returns:
        Material name for use in Datasmith (e.g., "brick_red", "stucco_cream")
    """
    facade_material = (params.get("facade_material") or "brick").lower()

    # Try to get specific colour
    facade_detail = params.get("facade_detail", {})
    brick_colour = (facade_detail.get("brick_colour_hex") or "").lower()

    if brick_colour and brick_colour.startswith("#"):
        # Return hex-based name
        return f"{facade_material}_{brick_colour[1:6]}"

    # Fallback to generic material
    return facade_material


def get_roof_material_name(params: Dict) -> str:
    """Extract roof material name from building parameters.

    Args:
        params: Building parameter dict

    Returns:
        Material name for roof (e.g., "slate_grey", "shingle_red")
    """
    roof_colour = (params.get("roof_colour") or "grey").lower()
    roof_material = (params.get("roof_material") or "asphalt").lower()

    # Clean up common variations
    roof_colour = roof_colour.replace(" ", "_")
    roof_material = roof_material.replace(" ", "_")

    return f"{roof_material}_{roof_colour}"


def scan_exports_dir(exports_dir: Path) -> Dict[str, Dict[str, Path]]:
    """Scan exports directory for FBX files and their variants.

    Returns dict mapping address -> {fbx, lod0, lod1, lod2, lod3, collision}
    """
    results = {}

    if not exports_dir.exists():
        print(f"Warning: exports directory {exports_dir} does not exist")
        return results

    # Find all .fbx files (non-LOD)
    for fbx_file in exports_dir.rglob("*.fbx"):
        basename = fbx_file.stem

        # Skip collision and LOD files here, handle separately
        if "_collision" in basename.lower() or re.search(r"_lod\d+$", basename.lower()):
            continue

        # Try to extract address from filename
        # Format: e.g., "100_Bellevue_Ave.fbx" or "100_Bellevue_Ave_export.fbx"
        address = basename.replace("_export", "").replace("_", " ")

        results[address] = {"fbx": fbx_file}

        # Check for LOD variants
        for lod_num in range(4):
            lod_file = fbx_file.parent / f"{basename}_LOD{lod_num}.fbx"
            if not lod_file.exists():
                lod_file = fbx_file.parent / f"{basename}_lod{lod_num}.fbx"
            if lod_file.exists():
                results[address][f"lod{lod_num}"] = lod_file

        # Check for collision mesh
        collision_file = fbx_file.parent / f"{basename}_collision.fbx"
        if collision_file.exists():
            results[address]["collision"] = collision_file

    return results


def safe_xml_string(text: str) -> str:
    """Escape special XML characters in text.

    Args:
        text: Raw text to escape

    Returns:
        XML-safe version of text
    """
    if not isinstance(text, str):
        text = str(text)
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def build_datasmith_xml(
    site_coords: Dict[str, Dict[str, float]],
    exports_dir: Path,
    fbx_files: Dict[str, Dict[str, Path]],
) -> Tuple[str, Dict]:
    """Build Datasmith XML content and manifest.

    Args:
        site_coords: Site coordinates dict from JSON
        exports_dir: Path to exports directory
        fbx_files: Scanned FBX files dict

    Returns:
        Tuple of (XML string, manifest dict)
    """
    manifest = {
        "scene_info": {
            "name": "Kensington Market Buildings",
            "origin_srid2952": [312672.94, 4834994.86],
            "unit": "Centimeters",
            "created": datetime.now().isoformat(),
        },
        "actors": [],
        "materials": {},
        "stats": {
            "total_buildings": 0,
            "buildings_with_fbx": 0,
            "buildings_with_lods": 0,
        },
    }

    xml_lines = [
        '<?xml version="1.0" encoding="utf-8"?>',
        '<DatasmithUnrealScene>',
        "  <Scene>",
        f'    <Name>{safe_xml_string("Kensington Market")}</Name>',
        "  </Scene>",
    ]

    # Track unique materials
    materials_seen = set()

    for address, fbx_dict in sorted(fbx_files.items()):
        if "fbx" not in fbx_dict:
            continue

        # Get coordinates for this building
        coords = site_coords.get(address, {})
        x = coords.get("x", 0.0) * 100.0  # Convert to cm
        y = coords.get("y", 0.0) * 100.0
        z = 0.0
        rotation = coords.get("rotation_deg", 0.0)

        # Get building params for material info
        params = load_building_param(address)
        facade_mat = get_facade_material_name(params) if params else "brick_default"
        roof_mat = get_roof_material_name(params) if params else "slate_grey"

        materials_seen.add(facade_mat)
        materials_seen.add(roof_mat)

        # Create actor name (sanitize address)
        actor_name = safe_xml_string(address.replace(" ", "_"))

        # Build actor element
        fbx_path = fbx_dict["fbx"].relative_to(exports_dir)
        xml_lines.append(f'  <StaticMeshActor Name="{actor_name}">')
        xml_lines.append("    <RelativeTransform>")
        xml_lines.append(f"      <Translation X=\"{x:.2f}\" Y=\"{y:.2f}\" Z=\"{z:.2f}\"/>")
        xml_lines.append(f"      <Rotation Roll=\"0.0\" Pitch=\"0.0\" Yaw=\"{rotation:.2f}\"/>")
        xml_lines.append("      <Scale X=\"1.0\" Y=\"1.0\" Z=\"1.0\"/>")
        xml_lines.append("    </RelativeTransform>")
        xml_lines.append(f'    <MeshReference>{safe_xml_string(str(fbx_path))}</MeshReference>')

        # Add LOD group if LODs exist
        if any(f"lod{i}" in fbx_dict for i in range(4)):
            xml_lines.append("    <LODGroup>")
            screen_sizes = [1.0, 0.5, 0.25, 0.1]
            for lod_num in range(4):
                if f"lod{lod_num}" in fbx_dict:
                    lod_path = fbx_dict[f"lod{lod_num}"].relative_to(exports_dir)
                    xml_lines.append(
                        f'      <LOD Index="{lod_num}" ScreenSize="{screen_sizes[lod_num]}">'
                    )
                    xml_lines.append(
                        f'        <MeshReference>{safe_xml_string(str(lod_path))}</MeshReference>'
                    )
                    xml_lines.append("      </LOD>")
            xml_lines.append("    </LODGroup>")

        # Add collision mesh
        if "collision" in fbx_dict:
            collision_path = fbx_dict["collision"].relative_to(exports_dir)
            xml_lines.append("    <Collision>")
            xml_lines.append(
                f'      <CollisionMesh>{safe_xml_string(str(collision_path))}</CollisionMesh>'
            )
            xml_lines.append("      <Type>SimpleCollision</Type>")
            xml_lines.append("    </Collision>")

        xml_lines.append("  </StaticMeshActor>")

        # Load materials.json sidecar if available (written by bake_utils)
        sidecar_path = fbx_dict["fbx"].parent / "materials.json"
        sidecar_materials = []
        if sidecar_path.exists():
            try:
                with open(sidecar_path, "r", encoding="utf-8") as sf:
                    sidecar_materials = json.load(sf)
            except (json.JSONDecodeError, OSError):
                pass

        # Add to manifest
        actor_info = {
            "name": address,
            "actor_name": actor_name,
            "position": {"x": x, "y": y, "z": z},
            "rotation_deg": rotation,
            "fbx_path": str(fbx_path),
            "materials": [facade_mat, roof_mat],
        }
        if sidecar_materials:
            actor_info["material_properties"] = sidecar_materials
        if any(f"lod{i}" in fbx_dict for i in range(4)):
            actor_info["lods"] = [
                str(fbx_dict[f"lod{i}"].relative_to(exports_dir))
                for i in range(4)
                if f"lod{i}" in fbx_dict
            ]
        if "collision" in fbx_dict:
            actor_info["collision_mesh"] = str(fbx_dict["collision"].relative_to(exports_dir))

        manifest["actors"].append(actor_info)
        manifest["stats"]["total_buildings"] += 1
        manifest["stats"]["buildings_with_fbx"] += 1
        if any(f"lod{i}" in fbx_dict for i in range(4)):
            manifest["stats"]["buildings_with_lods"] += 1

    # Add material definitions with full PBR metadata
    for mat_name in sorted(materials_seen):
        is_metal = any(kw in mat_name.lower() for kw in
                       ("metal", "copper", "tin", "steel", "gutter", "handrail",
                        "flashing", "alumin"))
        is_glass = "glass" in mat_name.lower()

        mat_entry = {
            "name": mat_name,
            "texture_paths": {
                "diffuse": f"textures/{mat_name}_diffuse.png",
                "normal": f"textures/{mat_name}_normal.png",
                "roughness": f"textures/{mat_name}_roughness.png",
                "metallic": f"textures/{mat_name}_metallic.png",
                "ao": f"textures/{mat_name}_ao.png",
            },
            "pbr_defaults": {
                "metallic": 0.8 if is_metal else (0.0 if not is_glass else 0.0),
                "roughness_range": [0.25, 0.45] if is_metal else ([0.02, 0.05] if is_glass else [0.6, 0.9]),
                "has_ao": True,
                "has_displacement": False,
                "alpha": 0.2 if is_glass else 1.0,
                "transmission": 0.75 if is_glass else 0.0,
            },
        }
        manifest["materials"][mat_name] = mat_entry

    xml_lines.append("</DatasmithUnrealScene>")

    return "\n".join(xml_lines), manifest


def main():
    parser = argparse.ArgumentParser(
        description="Build Datasmith XML scene for Unreal Engine import"
    )
    parser.add_argument(
        "--exports-dir",
        type=Path,
        default=OUTPUTS_DIR / "exports",
        help="Path to exports directory containing FBX files",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=OUTPUTS_DIR / "exports" / "kensington_scene.udatasmith",
        help="Output path for Datasmith XML file",
    )
    args = parser.parse_args()

    print("Loading site coordinates...")
    site_coords = load_site_coordinates()
    print(f"  Loaded {len(site_coords)} building positions")

    print(f"Scanning exports directory: {args.exports_dir}")
    fbx_files = scan_exports_dir(args.exports_dir)
    print(f"  Found {len(fbx_files)} building FBX files")

    print("Building Datasmith XML...")
    xml_content, manifest = build_datasmith_xml(site_coords, args.exports_dir, fbx_files)

    # Ensure output directory exists
    args.output.parent.mkdir(parents=True, exist_ok=True)

    # Write Datasmith XML
    print(f"Writing Datasmith XML to {args.output}")
    with open(args.output, "w", encoding="utf-8") as f:
        f.write(xml_content)

    # Write manifest JSON
    manifest_path = args.output.parent / "unreal_import_manifest.json"
    print(f"Writing manifest to {manifest_path}")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    # Print summary
    print("\nSummary:")
    print(f"  Total buildings: {manifest['stats']['total_buildings']}")
    print(f"  Buildings with FBX: {manifest['stats']['buildings_with_fbx']}")
    print(f"  Buildings with LODs: {manifest['stats']['buildings_with_lods']}")
    print(f"  Unique materials: {len(manifest['materials'])}")


if __name__ == "__main__":
    main()
