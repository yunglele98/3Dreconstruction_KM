#!/usr/bin/env python3
"""Generate a JSON manifest for Unity scene reconstruction and prefab setup.

This script produces a comprehensive manifest that Unity can consume to
reconstruct the Kensington Market scene with proper positioning, rotations,
materials, LOD groups, and street furniture placement.

Usage:
    python build_unity_prefab_manifest.py [--output outputs/exports/unity_manifest.json]

The script:
1. Loads site coordinates and converts from SRID 2952 to Unity coords
2. Scans FBX export directory for LOD and collision meshes
3. Builds material mapping from building parameters
4. Includes street furniture and tree placement data
5. Generates a complete manifest for Unity import
"""

import json
import re
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Tuple


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


def srid2952_to_unity(x: float, y: float, z: float = 0.0) -> Tuple[float, float, float]:
    """Convert SRID 2952 metres to Unity world coordinates.

    SRID 2952 uses X, Y horizontal metres. Unity uses X, Y, Z with Y as vertical axis.
    This conversion:
    - Keeps X as is (forward/backward in world)
    - Swaps Y and Z (Y becomes elevation in Unity, Z becomes side-to-side)
    - Converts to centimetres for finer precision

    Args:
        x: SRID X coordinate (metres)
        y: SRID Y coordinate (metres)
        z: SRID Z coordinate (metres, default 0)

    Returns:
        Tuple of (unity_x, unity_y, unity_z) in centimetres
    """
    # Convert metres to centimetres and swap axes
    unity_x = x * 100.0
    unity_y = z * 100.0  # Z becomes height (Y in Unity)
    unity_z = y * 100.0  # Y becomes depth (Z in Unity)
    return unity_x, unity_y, unity_z


def get_material_info(params: Optional[Dict]) -> Dict:
    """Extract material and colour information from building parameters.

    Args:
        params: Building parameter dict or None

    Returns:
        Dict with facade, roof, and trim material info
    """
    if not params:
        return {
            "facade": {"material": "brick", "colour_hex": "#B85A3A"},
            "roof": {"material": "asphalt", "colour_hex": "#5A5A5A"},
            "trim": {"colour_hex": "#3A2A20"},
        }

    facade_detail = params.get("facade_detail", {})
    colour_palette = params.get("colour_palette", {})

    return {
        "facade": {
            "material": (params.get("facade_material") or "brick").lower(),
            "colour_hex": facade_detail.get("brick_colour_hex")
            or colour_palette.get("facade")
            or "#B85A3A",
            "mortar_colour": facade_detail.get("mortar_colour") or "#B0A898",
        },
        "roof": {
            "material": (params.get("roof_material") or "asphalt").lower(),
            "colour_hex": colour_palette.get("roof") or "#5A5A5A",
        },
        "trim": {
            "colour_hex": colour_palette.get("trim") or "#3A2A20",
        },
        "accent": {
            "colour_hex": colour_palette.get("accent") or "#D4B896",
        },
    }


def scan_fbx_files(exports_dir: Path) -> Dict[str, Dict[str, Path]]:
    """Scan exports directory for FBX files and variants.

    Returns dict mapping address -> {fbx, lod_list, collision}
    """
    results = {}

    if not exports_dir.exists():
        print(f"Warning: exports directory {exports_dir} does not exist")
        return results

    for fbx_file in exports_dir.rglob("*.fbx"):
        basename = fbx_file.stem

        # Skip collision and LOD files
        if "_collision" in basename.lower() or re.search(r"_lod\d+$", basename.lower()):
            continue

        # Extract address from filename
        address = basename.replace("_export", "").replace("_", " ")
        results[address] = {"fbx": fbx_file, "lods": []}

        # Scan for LOD files
        for lod_num in range(4):
            lod_file = fbx_file.parent / f"{basename}_LOD{lod_num}.fbx"
            if not lod_file.exists():
                lod_file = fbx_file.parent / f"{basename}_lod{lod_num}.fbx"
            if lod_file.exists():
                results[address]["lods"].append(
                    {"lod": lod_num, "path": lod_file, "screen_size": [1.0, 0.5, 0.25, 0.1][lod_num]}
                )

        # Check for collision
        collision_file = fbx_file.parent / f"{basename}_collision.fbx"
        if collision_file.exists():
            results[address]["collision"] = collision_file

    return results


def load_gis_scene() -> Optional[Dict]:
    """Load GIS scene data for footprints and street furniture.

    Returns:
        Parsed gis_scene.json dict or None
    """
    gis_file = OUTPUTS_DIR / "gis_scene.json"
    if not gis_file.exists():
        print(f"Warning: {gis_file} not found")
        return None

    try:
        with open(gis_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"Warning: Failed to parse gis_scene.json: {e}")
        return None


def build_unity_manifest(
    site_coords: Dict[str, Dict[str, float]],
    fbx_files: Dict[str, Dict[str, Path]],
    exports_dir: Path,
    gis_data: Optional[Dict] = None,
) -> Dict:
    """Build complete Unity manifest.

    Args:
        site_coords: Site coordinates from JSON
        fbx_files: Scanned FBX files
        exports_dir: Path to exports directory (for relative paths)
        gis_data: Optional GIS scene data

    Returns:
        Complete manifest dict for Unity
    """
    manifest = {
        "metadata": {
            "project": "Kensington Market Building Heritage",
            "version": "1.0",
            "created": datetime.now().isoformat(),
            "coordinate_system": {
                "source": "SRID 2952 (NAD83 Ontario MTM Zone 10)",
                "origin_srid2952": [312672.94, 4834994.86],
                "target": "Unity",
                "units": "Centimeters",
                "up_axis": "Y",
                "conversion_note": "SRID2952 X,Y,Z -> Unity X,Y,Z with Y->Z, Z->Y swap",
            },
        },
        "buildings": [],
        "materials": {},
        "street_furniture": [],
        "trees": [],
        "stats": {
            "total_buildings": 0,
            "buildings_with_fbx": 0,
            "buildings_with_lods": 0,
            "buildings_with_collision": 0,
            "total_unique_materials": 0,
        },
    }

    materials_seen = set()

    # Process each building
    for address, fbx_dict in sorted(fbx_files.items()):
        if "fbx" not in fbx_dict:
            continue

        # Get coordinates
        coords = site_coords.get(address, {})
        x = coords.get("x", 0.0)
        y = coords.get("y", 0.0)
        z = 0.0
        rotation_deg = coords.get("rotation_deg", 0.0)

        # Convert to Unity coords
        unity_x, unity_y, unity_z = srid2952_to_unity(x, y, z)

        # Get building parameters for materials
        params = load_building_param(address)
        materials = get_material_info(params)

        # Track materials
        for material_type in ["facade", "roof", "trim"]:
            if material_type in materials:
                mat_key = f"{material_type}_{materials[material_type].get('colour_hex', '').replace('#', '')}"
                materials_seen.add(mat_key)

        # Build FBX path relative to exports dir
        fbx_path = fbx_dict["fbx"].relative_to(exports_dir)

        # Load materials.json sidecar if available (written by bake_utils)
        sidecar_path = fbx_dict["fbx"].parent / "materials.json"
        sidecar_materials = []
        if sidecar_path.exists():
            try:
                with open(sidecar_path, "r", encoding="utf-8") as sf:
                    sidecar_materials = json.load(sf)
            except (json.JSONDecodeError, OSError):
                pass

        # Build building entry
        building_entry = {
            "address": address,
            "position": {
                "x": unity_x,
                "y": unity_y,
                "z": unity_z,
                "rotation_deg": rotation_deg,
            },
            "fbx_path": str(fbx_path),
            "materials": materials,
        }
        if sidecar_materials:
            building_entry["material_properties"] = sidecar_materials

        # Add LODs if present
        if fbx_dict["lods"]:
            building_entry["lods"] = [
                {
                    "lod": lod["lod"],
                    "path": str(lod["path"].relative_to(exports_dir)),
                    "screen_size": lod["screen_size"],
                }
                for lod in sorted(fbx_dict["lods"], key=lambda x: x["lod"])
            ]
            manifest["stats"]["buildings_with_lods"] += 1

        # Add collision if present
        if "collision" in fbx_dict:
            building_entry["collision_mesh"] = str(
                fbx_dict["collision"].relative_to(exports_dir)
            )
            manifest["stats"]["buildings_with_collision"] += 1

        manifest["buildings"].append(building_entry)
        manifest["stats"]["total_buildings"] += 1
        manifest["stats"]["buildings_with_fbx"] += 1

    # Add material definitions
    for mat_key in sorted(materials_seen):
        # Parse material key format: "type_hexcolor"
        parts = mat_key.rsplit("_", 1)
        mat_type = parts[0] if len(parts) == 2 else "unknown"
        hex_color = f"#{parts[1]}" if len(parts) == 2 else "#CCCCCC"

        is_metal = any(kw in mat_key.lower() for kw in
                       ("metal", "copper", "tin", "steel", "gutter", "handrail",
                        "flashing", "alumin"))
        is_glass = "glass" in mat_key.lower()

        manifest["materials"][mat_key] = {
            "name": mat_key,
            "type": mat_type,
            "colour_hex": hex_color,
            "texture_paths": {
                "diffuse": f"textures/{mat_key}_diffuse.png",
                "normal": f"textures/{mat_key}_normal.png",
                "roughness": f"textures/{mat_key}_roughness.png",
                "metallic": f"textures/{mat_key}_metallic.png",
                "ambient_occlusion": f"textures/{mat_key}_ao.png",
            },
            "pbr_defaults": {
                "metallic": 0.8 if is_metal else 0.0,
                "smoothness_range": [0.55, 0.75] if is_metal else ([0.95, 0.98] if is_glass else [0.1, 0.4]),
                "alpha": 0.2 if is_glass else 1.0,
                "rendering_mode": "Transparent" if is_glass else "Opaque",
            },
        }

    manifest["stats"]["total_unique_materials"] = len(manifest["materials"])

    # Add GIS data if available
    if gis_data:
        # Add footprints as ground reference
        if "footprints" in gis_data:
            manifest["footprints"] = {
                "count": len(gis_data["footprints"]),
                "data": gis_data["footprints"][:100],  # Sample first 100
            }

        # Add massing shapes if available
        if "massing" in gis_data:
            manifest["massing"] = {
                "count": len(gis_data["massing"]),
                "sample_count": min(50, len(gis_data["massing"])),
            }

    return manifest


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Build Unity prefab manifest for scene reconstruction"
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
        default=OUTPUTS_DIR / "exports" / "unity_manifest.json",
        help="Output path for manifest JSON file",
    )
    args = parser.parse_args()

    print("Loading site coordinates...")
    site_coords = load_site_coordinates()
    print(f"  Loaded {len(site_coords)} building positions")

    print(f"Scanning exports directory: {args.exports_dir}")
    fbx_files = scan_fbx_files(args.exports_dir)
    print(f"  Found {len(fbx_files)} building FBX files")

    print("Loading GIS scene data...")
    gis_data = load_gis_scene()

    print("Building Unity manifest...")
    manifest = build_unity_manifest(site_coords, fbx_files, args.exports_dir, gis_data)

    # Ensure output directory exists
    args.output.parent.mkdir(parents=True, exist_ok=True)

    # Write manifest
    print(f"Writing manifest to {args.output}")
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    # Print summary
    print("\nSummary:")
    print(f"  Total buildings: {manifest['stats']['total_buildings']}")
    print(f"  Buildings with FBX: {manifest['stats']['buildings_with_fbx']}")
    print(f"  Buildings with LODs: {manifest['stats']['buildings_with_lods']}")
    print(f"  Buildings with collision: {manifest['stats']['buildings_with_collision']}")
    print(f"  Unique materials: {manifest['stats']['total_unique_materials']}")


if __name__ == "__main__":
    main()
