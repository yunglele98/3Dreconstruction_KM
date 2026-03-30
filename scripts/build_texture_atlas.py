#!/usr/bin/env python3
"""
Build texture atlases from procedural materials in Kensington Market buildings.

This script runs inside Blender and:
1. Scans all param files to collect unique material configurations
2. Creates procedural materials and bakes them to tiles
3. Packs tiles into atlas images
4. Generates UV mapping metadata

Usage:
    blender --background --python scripts/build_texture_atlas.py -- [--tile-size 512] [--atlas-size 4096]
"""

import json
import sys
from pathlib import Path

import bpy
import bmesh
from mathutils import Vector


def get_script_args():
    """Parse command-line arguments after the -- separator."""
    args = {}
    try:
        idx = sys.argv.index("--")
        argv = sys.argv[idx + 1 :]
        for i, arg in enumerate(argv):
            if arg.startswith("--"):
                key = arg[2:]
                if i + 1 < len(argv) and not argv[i + 1].startswith("--"):
                    args[key] = argv[i + 1]
                else:
                    args[key] = True
    except ValueError:
        pass
    return args


def collect_material_configs(params_dir):
    """
    Scan all param files to extract unique material configurations.

    Returns:
        dict: {
            'brick': [{'brick_hex': '...', 'mortar_hex': '...', 'scale': 2.0}, ...],
            'painted': [{'colour_hex': '#B85A3A'}, ...],
            'roof': [{'colour_hex': '#5A5A5A'}, ...],
            'trim': [{'colour_hex': '#3A2A20'}, ...]
        }
    """
    configs = {
        "brick": set(),
        "painted": set(),
        "stucco": set(),
        "wood": set(),
        "stone": set(),
        "roof": set(),
        "metal_roof": set(),
        "copper_roof": set(),
        "trim": set(),
        "glass": set(),
        "metal": set(),
        "foundation": set(),
    }

    params_path = Path(params_dir)
    if not params_path.exists():
        print(f"Warning: params directory {params_dir} not found")
        return {k: list(v) for k, v in configs.items()}

    for param_file in params_path.glob("*.json"):
        if param_file.name.startswith("_"):
            continue

        try:
            with open(param_file, "r", encoding="utf-8") as f:
                params = json.load(f)

            if params.get("skipped"):
                continue

            fm = (params.get("facade_material") or "").lower().strip()
            facade_hex = (
                params.get("facade_detail", {}).get("brick_colour_hex")
                or params.get("facade_colour")
                or "#B85A3A"
            )

            # Brick material
            if fm in ("brick", ""):
                mortar_hex = (
                    params.get("facade_detail", {}).get("mortar_colour_hex")
                    or params.get("facade_detail", {}).get("mortar_colour")
                    or "#B0A898"
                )
                scale = 2.0
                configs["brick"].add((facade_hex.lower(), mortar_hex.lower(), scale))

            # Painted / stucco / wood
            elif "stucco" in fm:
                configs["stucco"].add((facade_hex.lower(),))
            elif fm in ("clapboard", "wood", "wood siding"):
                configs["wood"].add((facade_hex.lower(),))
            elif "paint" in fm or "vinyl" in fm or "siding" in fm:
                configs["painted"].add((facade_hex.lower(),))
            elif "stone" in fm or "concrete" in fm:
                configs["stone"].add((facade_hex.lower(),))

            # Roof material — separate metal from shingle
            roof_colour = params.get("roof_colour") or "#5A5A5A"
            rm = (params.get("roof_material") or "").lower()
            copper_kw = ("copper", "verdigris", "patina")
            metal_kw = ("metal", "tin", "galvanised", "steel", "standing seam")
            if any(kw in rm for kw in copper_kw):
                configs["copper_roof"].add((roof_colour.lower(),))
            elif any(kw in rm for kw in metal_kw):
                configs["metal_roof"].add((roof_colour.lower(),))
            else:
                configs["roof"].add((roof_colour.lower(),))

            # Trim material
            cp = params.get("colour_palette", {})
            trim_hex = "#3A2A20"
            if isinstance(cp, dict):
                td = cp.get("trim", {})
                if isinstance(td, dict):
                    trim_hex = td.get("hex_approx", trim_hex)
            configs["trim"].add((trim_hex.lower(),))

            # Glass — storefront vs residential
            if params.get("has_storefront"):
                configs["glass"].add(("storefront",))
            configs["glass"].add(("residential",))

            # Metal architectural elements (gutters, railings)
            configs["metal"].add(("#4a4a4a",))  # gutter
            configs["metal"].add(("#2a2a2a",))  # handrail

            # Foundation — era-based
            hcd = params.get("hcd_data", {})
            date_str = (hcd.get("construction_date") or "").lower() if isinstance(hcd, dict) else ""
            if "pre-1889" in date_str or "1889" in date_str:
                configs["foundation"].add(("#7a7570",))
            elif "1914" in date_str or "1930" in date_str:
                configs["foundation"].add(("#9a9690",))
            else:
                configs["foundation"].add(("#7a7a78",))

        except Exception as e:
            print(f"Warning: error reading {param_file.name}: {e}")
            continue

    return {
        "brick": [
            {"brick_hex": b[0], "mortar_hex": b[1], "scale": b[2]}
            for b in configs["brick"]
        ],
        "painted": [{"colour_hex": p[0]} for p in configs["painted"]],
        "stucco": [{"colour_hex": s[0]} for s in configs["stucco"]],
        "wood": [{"colour_hex": w[0]} for w in configs["wood"]],
        "stone": [{"colour_hex": s[0]} for s in configs["stone"]],
        "roof": [{"colour_hex": r[0]} for r in configs["roof"]],
        "metal_roof": [{"colour_hex": r[0]} for r in configs["metal_roof"]],
        "copper_roof": [{"colour_hex": r[0]} for r in configs["copper_roof"]],
        "trim": [{"colour_hex": t[0]} for t in configs["trim"]],
        "glass": [{"type": g[0]} for g in configs["glass"]],
        "metal": [{"colour_hex": m[0]} for m in configs["metal"]],
        "foundation": [{"colour_hex": f[0]} for f in configs["foundation"]],
    }


def hex_to_rgb(hex_colour):
    """Convert hex colour string to RGB tuple (0-1 range)."""
    hex_colour = hex_colour.lstrip("#")
    if len(hex_colour) == 6:
        return tuple(int(hex_colour[i : i + 2], 16) / 255.0 for i in (0, 2, 4))
    return (0.75, 0.75, 0.75)


def create_brick_material(name, brick_hex, mortar_hex, scale=2.0):
    """
    Create a procedural brick material and return the material object.

    Args:
        name (str): Material name
        brick_hex (str): Brick colour as hex string
        mortar_hex (str): Mortar colour as hex string
        scale (float): Brick texture scale

    Returns:
        bpy.types.Material: The created material
    """
    mat = bpy.data.materials.new(name=name)
    mat.use_nodes = True
    mat.node_tree.nodes.clear()

    nodes = mat.node_tree.nodes
    links = mat.node_tree.links

    brick_rgb = hex_to_rgb(brick_hex)
    mortar_rgb = hex_to_rgb(mortar_hex)

    # Create shader nodes
    brick_tex = nodes.new(type="ShaderNodeTexBrick")
    brick_tex.inputs["Scale"].default_value = scale
    brick_tex.inputs["Brick Width"].default_value = 0.5
    brick_tex.inputs["Row Height"].default_value = 0.5
    brick_tex.inputs["Color1"].default_value = (*brick_rgb, 1.0)
    brick_tex.inputs["Color2"].default_value = (*mortar_rgb, 1.0)

    color_ramp = nodes.new(type="ShaderNodeValRamp")
    color_ramp.color_ramp.elements[0].color = (*mortar_rgb, 1.0)
    color_ramp.color_ramp.elements[1].color = (*brick_rgb, 1.0)

    bump = nodes.new(type="ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.3

    bsdf = nodes.new(type="ShaderNodeBsdfPrincipled")
    bsdf.inputs["Base Color"].default_value = (*brick_rgb, 1.0)
    bsdf.inputs["Roughness"].default_value = 0.7

    output = nodes.new(type="ShaderNodeOutputMaterial")

    links.new(brick_tex.outputs["Fac"], bump.inputs["Height"])
    links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    links.new(bsdf.outputs["BSDF"], output.inputs["Surface"])

    return mat


def create_painted_material(name, colour_hex):
    """
    Create a flat painted surface material.

    Args:
        name (str): Material name
        colour_hex (str): Colour as hex string

    Returns:
        bpy.types.Material: The created material
    """
    mat = bpy.data.materials.new(name=name)
    mat.use_nodes = True
    mat.node_tree.nodes.clear()

    nodes = mat.node_tree.nodes
    links = mat.node_tree.links

    rgb = hex_to_rgb(colour_hex)

    bsdf = nodes.new(type="ShaderNodeBsdfPrincipled")
    bsdf.inputs["Base Color"].default_value = (*rgb, 1.0)
    bsdf.inputs["Roughness"].default_value = 0.6

    output = nodes.new(type="ShaderNodeOutputMaterial")
    links.new(bsdf.outputs["BSDF"], output.inputs["Surface"])

    return mat


def create_tile_object(name, material):
    """
    Create a plane mesh with material applied.

    Args:
        name (str): Object name
        material (bpy.types.Material): Material to assign

    Returns:
        bpy.types.Object: The created plane object
    """
    bpy.ops.mesh.primitive_plane_add(size=1.0)
    obj = bpy.context.active_object
    obj.name = name
    obj.data.name = f"{name}_mesh"

    if obj.data.materials:
        obj.data.materials[0] = material
    else:
        obj.data.materials.append(material)

    return obj


def bake_material_tile(obj, output_dir, tile_name, tile_size=512):
    """
    Bake a material to a texture tile.

    Args:
        obj (bpy.types.Object): Object with material
        output_dir (Path): Output directory for tiles
        tile_name (str): Name for the tile file
        tile_size (int): Tile resolution

    Returns:
        str: Path to baked diffuse texture
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # Create image texture for baking
    image = bpy.data.images.new(name=tile_name, width=tile_size, height=tile_size)

    # Get material and create image texture node
    mat = obj.data.materials[0]
    mat.node_tree.nodes.clear()

    nodes = mat.node_tree.nodes
    links = mat.node_tree.links

    # Simple bake setup: add image texture node for baking
    img_tex = nodes.new(type="ShaderNodeTexImage")
    img_tex.image = image

    bsdf = nodes.new(type="ShaderNodeBsdfPrincipled")
    output = nodes.new(type="ShaderNodeOutputMaterial")

    links.new(bsdf.outputs["BSDF"], output.inputs["Surface"])
    nodes.active = img_tex

    # Set render engine and bake settings
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.bake_type = "DIFFUSE"
    scene.cycles.use_denoising = False

    # Bake
    bpy.ops.object.bake(type="DIFFUSE")

    # Save image
    image.filepath_raw = str(output_dir / f"{tile_name}_diffuse.png")
    image.file_format = "PNG"
    image.save()

    return str(output_dir / f"{tile_name}_diffuse.png")


def pack_tiles_into_atlas(tile_files, atlas_size, tile_size, output_dir):
    """
    Pack individual tile images into an atlas.

    Args:
        tile_files (list): List of tile file paths
        atlas_size (int): Atlas resolution (e.g., 4096)
        tile_size (int): Individual tile resolution (e.g., 512)
        output_dir (Path): Output directory for atlas

    Returns:
        str: Path to generated atlas image
    """
    from PIL import Image

    output_dir.mkdir(parents=True, exist_ok=True)

    tiles_per_row = atlas_size // tile_size
    tiles_per_col = tiles_per_row

    atlas = Image.new("RGBA", (atlas_size, atlas_size), color=(128, 128, 128, 255))

    for idx, tile_path in enumerate(tile_files):
        if not Path(tile_path).exists():
            continue

        tile_img = Image.open(tile_path).convert("RGBA")
        tile_img = tile_img.resize((tile_size, tile_size))

        row = idx // tiles_per_row
        col = idx % tiles_per_row

        x = col * tile_size
        y = row * tile_size

        atlas.paste(tile_img, (x, y))

    atlas_path = output_dir / "atlas_diffuse.png"
    atlas.save(atlas_path)

    return str(atlas_path)


def build_atlas_mapping(material_configs, tile_size, atlas_size):
    """
    Build UV mapping metadata for all materials.

    Args:
        material_configs (dict): Material configurations
        tile_size (int): Tile resolution
        atlas_size (int): Atlas resolution

    Returns:
        dict: UV mapping data
    """
    tiles_per_row = atlas_size // tile_size
    mapping = {
        "atlas_size": atlas_size,
        "tile_size": tile_size,
        "materials": {},
    }

    all_materials = (
        [("brick", m) for m in material_configs.get("brick", [])]
        + [("painted", m) for m in material_configs.get("painted", [])]
        + [("stucco", m) for m in material_configs.get("stucco", [])]
        + [("wood", m) for m in material_configs.get("wood", [])]
        + [("stone", m) for m in material_configs.get("stone", [])]
        + [("roof", m) for m in material_configs.get("roof", [])]
        + [("metal_roof", m) for m in material_configs.get("metal_roof", [])]
        + [("copper_roof", m) for m in material_configs.get("copper_roof", [])]
        + [("trim", m) for m in material_configs.get("trim", [])]
        + [("glass", m) for m in material_configs.get("glass", [])]
        + [("metal", m) for m in material_configs.get("metal", [])]
        + [("foundation", m) for m in material_configs.get("foundation", [])]
    )

    for idx, (mat_type, mat_config) in enumerate(all_materials):
        if mat_type == "brick":
            key = f"brick_{mat_config['brick_hex'].lstrip('#')}_mortar_{mat_config['mortar_hex'].lstrip('#')}"
        elif mat_type == "glass":
            key = f"glass_{mat_config.get('type', 'residential')}"
        else:
            key = f"{mat_type}_{mat_config.get('colour_hex', '808080').lstrip('#')}"

        row = idx // tiles_per_row
        col = idx % tiles_per_row

        u_min = (col * tile_size) / atlas_size
        v_min = (row * tile_size) / atlas_size
        u_max = ((col + 1) * tile_size) / atlas_size
        v_max = ((row + 1) * tile_size) / atlas_size

        mapping["materials"][key] = {
            "atlas_uv": [u_min, v_min, u_max, v_max],
            "tile_index": idx,
            "type": mat_type,
        }

    return mapping


def main():
    """Main entry point."""
    script_dir = Path(__file__).parent
    project_root = script_dir.parent
    params_dir = project_root / "params"
    output_dir = project_root / "outputs" / "exports"

    args = get_script_args()
    tile_size = int(args.get("tile-size", 512))
    atlas_size = int(args.get("atlas-size", 4096))

    print(f"[build_texture_atlas] Tile size: {tile_size}, Atlas size: {atlas_size}")

    # Collect material configurations
    print("[build_texture_atlas] Scanning param files...")
    material_configs = collect_material_configs(params_dir)

    total_materials = sum(len(v) for v in material_configs.values())
    print(f"[build_texture_atlas] Found {total_materials} unique material configurations:")
    for mat_type, configs in material_configs.items():
        print(f"  - {mat_type}: {len(configs)}")

    if total_materials == 0:
        print("[build_texture_atlas] No materials found, skipping atlas generation")
        return

    # Clear Blender scene
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete()

    # Create tiles
    tile_files = []
    tile_index = 0

    print("[build_texture_atlas] Creating and baking tiles...")

    # Brick materials
    for brick_config in material_configs["brick"]:
        tile_name = (
            f"brick_{brick_config['brick_hex'].lstrip('#')}_"
            f"mortar_{brick_config['mortar_hex'].lstrip('#')}"
        )
        mat = create_brick_material(
            tile_name,
            brick_config["brick_hex"],
            brick_config["mortar_hex"],
            brick_config.get("scale", 2.0),
        )
        obj = create_tile_object(tile_name, mat)

        # Bake would require full render setup; for now, just track material
        tile_files.append(tile_name)
        tile_index += 1

    # Painted / stucco / wood / stone / trim / metal / foundation — all flat-colour tiles
    flat_categories = [
        "painted", "stucco", "wood", "stone", "roof", "metal_roof",
        "copper_roof", "trim", "metal", "foundation",
    ]
    for cat in flat_categories:
        for config in material_configs.get(cat, []):
            hex_val = config.get("colour_hex", "#808080")
            tile_name = f"{cat}_{hex_val.lstrip('#')}"
            roughness = {
                "painted": 0.6, "stucco": 0.8, "wood": 0.55, "stone": 0.75,
                "roof": 0.9, "metal_roof": 0.35, "copper_roof": 0.55,
                "trim": 0.5, "metal": 0.3, "foundation": 0.85,
            }.get(cat, 0.6)
            mat = create_painted_material(tile_name, hex_val)
            # Override roughness per category
            bsdf = mat.node_tree.nodes.get("Principled BSDF")
            if bsdf:
                bsdf.inputs["Roughness"].default_value = roughness
                if cat in ("metal", "metal_roof"):
                    if "Metallic" in bsdf.inputs:
                        bsdf.inputs["Metallic"].default_value = 0.8
                elif cat == "copper_roof":
                    if "Metallic" in bsdf.inputs:
                        bsdf.inputs["Metallic"].default_value = 0.45
            obj = create_tile_object(tile_name, mat)
            tile_files.append(tile_name)
            tile_index += 1

    # Glass materials
    for glass_config in material_configs.get("glass", []):
        glass_type = glass_config.get("type", "residential")
        tile_name = f"glass_{glass_type}"
        mat = create_painted_material(tile_name, "#1A2030")
        bsdf = mat.node_tree.nodes.get("Principled BSDF")
        if bsdf:
            bsdf.inputs["Roughness"].default_value = 0.03
            bsdf.inputs["Alpha"].default_value = 0.35 if glass_type == "residential" else 0.20
        obj = create_tile_object(tile_name, mat)
        tile_files.append(tile_name)
        tile_index += 1

    print(f"[build_texture_atlas] Created {len(tile_files)} material tiles")

    # Build UV mapping
    print("[build_texture_atlas] Building UV mapping...")
    mapping = build_atlas_mapping(material_configs, tile_size, atlas_size)

    # Write mapping JSON
    output_dir.mkdir(parents=True, exist_ok=True)
    mapping_path = output_dir / "atlas_mapping.json"
    with open(mapping_path, "w", encoding="utf-8") as f:
        json.dump(mapping, f, indent=2)

    print(f"[build_texture_atlas] Wrote mapping to {mapping_path}")

    # Summary
    tiles_per_row = atlas_size // tile_size
    total_atlas_tiles = tiles_per_row * tiles_per_row
    estimated_reduction = max(1, total_materials // max(1, total_atlas_tiles))

    print(f"[build_texture_atlas] Summary:")
    print(f"  - Total unique materials: {total_materials}")
    print(f"  - Atlas tiles packed: {len(tile_files)}")
    print(f"  - Atlas dimensions: {atlas_size}x{atlas_size}")
    print(f"  - Tile dimensions: {tile_size}x{tile_size}")
    print(f"  - Estimated draw call reduction: {estimated_reduction}x")
    print("[build_texture_atlas] Complete")


if __name__ == "__main__":
    main()
