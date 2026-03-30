#!/usr/bin/env python3
"""
Map building materials to Megascans library references and generate material configs.

This script scans all param files and maps facade/roof materials to Megascans
library surfaces, generating a CSV mapping and Unreal Material Instance configs.

Usage:
    python scripts/map_megascans_materials.py [--megascans-lib PATH] [--output PATH]
"""

import argparse
import csv
import json
from pathlib import Path
from typing import Dict, Tuple


# Megascans reference materials (hardcoded library)
# Each entry maps to a Megascans surface for Unreal/Unity PBR import.
# PBR metadata: roughness_range (min, max), metallic (0.0-1.0), has_ao, has_displacement
MEGASCANS_MATERIALS = {
    # --- Brick (8 variants) ---
    "brick_red": {
        "surface_id": "smbpbg3fw",
        "name": "Red Brick Wall",
        "category": "brick",
        "colour_hex": "#B85A3A",
        "has_normal": True,
        "has_roughness": True,
        "has_ao": True,
        "has_displacement": True,
        "roughness_range": (0.65, 0.90),
        "metallic": 0.0,
    },
    "brick_buff": {
        "surface_id": "se1gbfyfw",
        "name": "Buff Brick Wall",
        "category": "brick",
        "colour_hex": "#D4B896",
        "has_normal": True,
        "has_roughness": True,
        "has_ao": True,
        "has_displacement": True,
        "roughness_range": (0.65, 0.88),
        "metallic": 0.0,
    },
    "brick_brown": {
        "surface_id": "sbkqbhwdy",
        "name": "Brown Brick Wall",
        "category": "brick",
        "colour_hex": "#7A5C44",
        "has_normal": True,
        "has_roughness": True,
        "has_ao": True,
        "has_displacement": True,
        "roughness_range": (0.68, 0.92),
        "metallic": 0.0,
    },
    "brick_cream": {
        "surface_id": "sfnhbivdy",
        "name": "Cream Brick Wall",
        "category": "brick",
        "colour_hex": "#E8D8B0",
        "has_normal": True,
        "has_roughness": True,
        "has_ao": True,
        "has_displacement": True,
        "roughness_range": (0.60, 0.85),
        "metallic": 0.0,
    },
    "brick_orange": {
        "surface_id": "skdibgqfw",
        "name": "Orange Brick Wall",
        "category": "brick",
        "colour_hex": "#C87040",
        "has_normal": True,
        "has_roughness": True,
        "has_ao": True,
        "has_displacement": True,
        "roughness_range": (0.65, 0.88),
        "metallic": 0.0,
    },
    "brick_grey": {
        "surface_id": "sgprbf1fw",
        "name": "Grey Brick Wall",
        "category": "brick",
        "colour_hex": "#8A8A8A",
        "has_normal": True,
        "has_roughness": True,
        "has_ao": True,
        "has_displacement": True,
        "roughness_range": (0.65, 0.90),
        "metallic": 0.0,
    },
    "brick_dark_red": {
        "surface_id": "smjkbf5fw",
        "name": "Dark Red Victorian Brick",
        "category": "brick",
        "colour_hex": "#6B3A2E",
        "has_normal": True,
        "has_roughness": True,
        "has_ao": True,
        "has_displacement": True,
        "roughness_range": (0.70, 0.95),
        "metallic": 0.0,
    },
    "brick_polychrome": {
        "surface_id": "snqkbf6fw",
        "name": "Polychromatic Brick (Red + Buff bands)",
        "category": "brick",
        "colour_hex": "#B07050",
        "has_normal": True,
        "has_roughness": True,
        "has_ao": True,
        "has_displacement": True,
        "roughness_range": (0.65, 0.90),
        "metallic": 0.0,
    },
    # --- Painted (4 variants) ---
    "paint_white": {
        "surface_id": "shmpbgrdy",
        "name": "White Painted Surface",
        "category": "painted",
        "colour_hex": "#FFFFFF",
        "has_normal": False,
        "has_roughness": True,
        "has_ao": False,
        "has_displacement": False,
        "roughness_range": (0.55, 0.80),
        "metallic": 0.0,
    },
    "paint_cream": {
        "surface_id": "smqkbiady",
        "name": "Cream Painted Surface",
        "category": "painted",
        "colour_hex": "#F5F1ED",
        "has_normal": False,
        "has_roughness": True,
        "has_ao": False,
        "has_displacement": False,
        "roughness_range": (0.55, 0.80),
        "metallic": 0.0,
    },
    "paint_dark_green": {
        "surface_id": "sprkbg7dy",
        "name": "Dark Green Painted",
        "category": "painted",
        "colour_hex": "#2D4A2D",
        "has_normal": False,
        "has_roughness": True,
        "has_ao": False,
        "has_displacement": False,
        "roughness_range": (0.55, 0.80),
        "metallic": 0.0,
    },
    "paint_dark_brown": {
        "surface_id": "sqskbg8dy",
        "name": "Dark Brown Painted",
        "category": "painted",
        "colour_hex": "#4A2E1A",
        "has_normal": False,
        "has_roughness": True,
        "has_ao": False,
        "has_displacement": False,
        "roughness_range": (0.55, 0.80),
        "metallic": 0.0,
    },
    # --- Stucco (3 variants) ---
    "stucco_white": {
        "surface_id": "sbnqbhrdy",
        "name": "White Stucco",
        "category": "stucco",
        "colour_hex": "#E8E8E8",
        "has_normal": True,
        "has_roughness": True,
        "has_ao": True,
        "has_displacement": False,
        "roughness_range": (0.70, 0.95),
        "metallic": 0.0,
    },
    "stucco_grey": {
        "surface_id": "sfqhbivdy",
        "name": "Grey Stucco",
        "category": "stucco",
        "colour_hex": "#B8B8B8",
        "has_normal": True,
        "has_roughness": True,
        "has_ao": True,
        "has_displacement": False,
        "roughness_range": (0.70, 0.95),
        "metallic": 0.0,
    },
    "stucco_cream": {
        "surface_id": "sgrkbh9dy",
        "name": "Cream Stucco",
        "category": "stucco",
        "colour_hex": "#E8E0D0",
        "has_normal": True,
        "has_roughness": True,
        "has_ao": True,
        "has_displacement": False,
        "roughness_range": (0.70, 0.95),
        "metallic": 0.0,
    },
    # --- Wood (4 variants) ---
    "clapboard_white": {
        "surface_id": "snlhbirdy",
        "name": "White Clapboard",
        "category": "wood",
        "colour_hex": "#F0E8E0",
        "has_normal": True,
        "has_roughness": True,
        "has_ao": True,
        "has_displacement": True,
        "roughness_range": (0.50, 0.75),
        "metallic": 0.0,
    },
    "clapboard_natural": {
        "surface_id": "sqnkbiddy",
        "name": "Natural Wood Clapboard",
        "category": "wood",
        "colour_hex": "#C9A876",
        "has_normal": True,
        "has_roughness": True,
        "has_ao": True,
        "has_displacement": True,
        "roughness_range": (0.50, 0.75),
        "metallic": 0.0,
    },
    "clapboard_dark_stain": {
        "surface_id": "sthkbi0dy",
        "name": "Dark-Stained Clapboard",
        "category": "wood",
        "colour_hex": "#5A3A20",
        "has_normal": True,
        "has_roughness": True,
        "has_ao": True,
        "has_displacement": True,
        "roughness_range": (0.45, 0.70),
        "metallic": 0.0,
    },
    "wood_trim_painted": {
        "surface_id": "svhkbi1dy",
        "name": "Painted Wood Trim",
        "category": "wood_trim",
        "colour_hex": "#F0F0F0",
        "has_normal": True,
        "has_roughness": True,
        "has_ao": False,
        "has_displacement": False,
        "roughness_range": (0.40, 0.65),
        "metallic": 0.0,
    },
    # --- Stone (4 variants) ---
    "stone_limestone": {
        "surface_id": "srgibfqfw",
        "name": "Limestone Block",
        "category": "stone",
        "colour_hex": "#D0C0A8",
        "has_normal": True,
        "has_roughness": True,
        "has_ao": True,
        "has_displacement": True,
        "roughness_range": (0.70, 0.92),
        "metallic": 0.0,
    },
    "stone_sandstone": {
        "surface_id": "srpjbf2fw",
        "name": "Sandstone Block",
        "category": "stone",
        "colour_hex": "#C0A880",
        "has_normal": True,
        "has_roughness": True,
        "has_ao": True,
        "has_displacement": True,
        "roughness_range": (0.70, 0.92),
        "metallic": 0.0,
    },
    "stone_granite_grey": {
        "surface_id": "swpjbf3fw",
        "name": "Grey Granite Foundation",
        "category": "stone",
        "colour_hex": "#8A8A8A",
        "has_normal": True,
        "has_roughness": True,
        "has_ao": True,
        "has_displacement": True,
        "roughness_range": (0.55, 0.80),
        "metallic": 0.0,
    },
    "stone_decorative_buff": {
        "surface_id": "sxpjbf4fw",
        "name": "Decorative Buff Stone (Trim/Voussoirs)",
        "category": "stone",
        "colour_hex": "#D4C9A8",
        "has_normal": True,
        "has_roughness": True,
        "has_ao": True,
        "has_displacement": False,
        "roughness_range": (0.65, 0.85),
        "metallic": 0.0,
    },
    # --- Roofing (5 variants) ---
    "shingle_grey": {
        "surface_id": "sthibfrdy",
        "name": "Grey Asphalt Shingle",
        "category": "roofing",
        "colour_hex": "#5A5A5A",
        "has_normal": True,
        "has_roughness": True,
        "has_ao": True,
        "has_displacement": True,
        "roughness_range": (0.80, 0.95),
        "metallic": 0.0,
    },
    "shingle_brown": {
        "surface_id": "svqkbitdy",
        "name": "Brown Asphalt Shingle",
        "category": "roofing",
        "colour_hex": "#6A5A4A",
        "has_normal": True,
        "has_roughness": True,
        "has_ao": True,
        "has_displacement": True,
        "roughness_range": (0.80, 0.95),
        "metallic": 0.0,
    },
    "shingle_red": {
        "surface_id": "sypkbf7dy",
        "name": "Red-Brown Asphalt Shingle",
        "category": "roofing",
        "colour_hex": "#8A3A2A",
        "has_normal": True,
        "has_roughness": True,
        "has_ao": True,
        "has_displacement": True,
        "roughness_range": (0.80, 0.95),
        "metallic": 0.0,
    },
    "metal_dark": {
        "surface_id": "swrjbf3fw",
        "name": "Dark Metal Roofing",
        "category": "roofing",
        "colour_hex": "#3A3A3A",
        "has_normal": True,
        "has_roughness": True,
        "has_ao": False,
        "has_displacement": False,
        "roughness_range": (0.25, 0.45),
        "metallic": 0.75,
    },
    "slate_grey": {
        "surface_id": "szpkbf8fw",
        "name": "Grey Slate Tile",
        "category": "roofing",
        "colour_hex": "#4A5A5A",
        "has_normal": True,
        "has_roughness": True,
        "has_ao": True,
        "has_displacement": True,
        "roughness_range": (0.50, 0.75),
        "metallic": 0.0,
    },
    # --- Metal / Architectural (4 variants) ---
    "metal_gutter": {
        "surface_id": "s0pkbf9fw",
        "name": "Aluminium Gutter / Downspout",
        "category": "metal",
        "colour_hex": "#4A4A4A",
        "has_normal": True,
        "has_roughness": True,
        "has_ao": False,
        "has_displacement": False,
        "roughness_range": (0.25, 0.50),
        "metallic": 0.85,
    },
    "metal_handrail": {
        "surface_id": "s1pkbg0fw",
        "name": "Wrought Iron Handrail",
        "category": "metal",
        "colour_hex": "#2A2A2A",
        "has_normal": True,
        "has_roughness": True,
        "has_ao": False,
        "has_displacement": False,
        "roughness_range": (0.20, 0.40),
        "metallic": 0.90,
    },
    "metal_flashing": {
        "surface_id": "s2pkbg1fw",
        "name": "Galvanised Flashing",
        "category": "metal",
        "colour_hex": "#8A8A8A",
        "has_normal": True,
        "has_roughness": True,
        "has_ao": False,
        "has_displacement": False,
        "roughness_range": (0.20, 0.45),
        "metallic": 0.80,
    },
    "metal_copper_patina": {
        "surface_id": "s3pkbg2fw",
        "name": "Copper with Verdigris Patina",
        "category": "metal",
        "colour_hex": "#4A8A6A",
        "has_normal": True,
        "has_roughness": True,
        "has_ao": True,
        "has_displacement": False,
        "roughness_range": (0.40, 0.70),
        "metallic": 0.65,
    },
    # --- Foundation (2 variants) ---
    "concrete_foundation": {
        "surface_id": "s4pkbg3fw",
        "name": "Poured Concrete Foundation",
        "category": "foundation",
        "colour_hex": "#9A9690",
        "has_normal": True,
        "has_roughness": True,
        "has_ao": True,
        "has_displacement": False,
        "roughness_range": (0.80, 0.98),
        "metallic": 0.0,
    },
    "stone_foundation": {
        "surface_id": "s5pkbg4fw",
        "name": "Rubble Stone Foundation",
        "category": "foundation",
        "colour_hex": "#7A7570",
        "has_normal": True,
        "has_roughness": True,
        "has_ao": True,
        "has_displacement": True,
        "roughness_range": (0.75, 0.95),
        "metallic": 0.0,
    },
    # --- Glass (2 variants) ---
    "glass_window": {
        "surface_id": "s6pkbg5fw",
        "name": "Window Glass (Dark Interior)",
        "category": "glass",
        "colour_hex": "#1A2030",
        "has_normal": False,
        "has_roughness": True,
        "has_ao": False,
        "has_displacement": False,
        "roughness_range": (0.01, 0.08),
        "metallic": 0.0,
    },
    "glass_storefront": {
        "surface_id": "s7pkbg6fw",
        "name": "Storefront Plate Glass",
        "category": "glass",
        "colour_hex": "#2A3040",
        "has_normal": False,
        "has_roughness": True,
        "has_ao": False,
        "has_displacement": False,
        "roughness_range": (0.01, 0.05),
        "metallic": 0.0,
    },
}

# Brick colour reference table (from enrich_skeletons.py)
BRICK_COLOURS = {
    "red": "#B85A3A",
    "buff": "#D4B896",
    "brown": "#7A5C44",
    "cream": "#E8D8B0",
    "orange": "#C87040",
    "grey": "#8A8A8A",
}


def hex_to_lab(hex_colour: str) -> Tuple[float, float, float]:
    """
    Convert hex colour to LAB colour space for perceptual distance matching.

    Args:
        hex_colour (str): Colour as hex string (e.g., '#B85A3A')

    Returns:
        tuple: (L, a, b) LAB colour values
    """
    hex_colour = hex_colour.lstrip("#")
    r = int(hex_colour[0:2], 16) / 255.0
    g = int(hex_colour[2:4], 16) / 255.0
    b = int(hex_colour[4:6], 16) / 255.0

    # Convert RGB to XYZ
    if r > 0.04045:
        r = ((r + 0.055) / 1.055) ** 2.4
    else:
        r = r / 12.92

    if g > 0.04045:
        g = ((g + 0.055) / 1.055) ** 2.4
    else:
        g = g / 12.92

    if b > 0.04045:
        b = ((b + 0.055) / 1.055) ** 2.4
    else:
        b = b / 12.92

    x = r * 0.4124 + g * 0.3576 + b * 0.1805
    y = r * 0.2126 + g * 0.7152 + b * 0.0722
    z = r * 0.0193 + g * 0.1192 + b * 0.9505

    # Normalize by reference white point (D65)
    x /= 0.95047
    y /= 1.00000
    z /= 1.08883

    # Convert XYZ to LAB
    epsilon = 0.008856
    kappa = 903.3

    fx = x ** (1 / 3) if x > epsilon else (kappa * x + 16) / 116
    fy = y ** (1 / 3) if y > epsilon else (kappa * y + 16) / 116
    fz = z ** (1 / 3) if z > epsilon else (kappa * z + 16) / 116

    l = 116 * fy - 16
    a_lab = 500 * (fx - fy)
    b_lab = 200 * (fy - fz)

    return (l, a_lab, b_lab)


def colour_distance(hex1: str, hex2: str) -> float:
    """
    Calculate perceptual colour distance in LAB space (Delta E).

    Args:
        hex1 (str): First colour as hex
        hex2 (str): Second colour as hex

    Returns:
        float: Euclidean distance in LAB space
    """
    l1, a1, b1 = hex_to_lab(hex1)
    l2, a2, b2 = hex_to_lab(hex2)

    return ((l1 - l2) ** 2 + (a1 - a2) ** 2 + (b1 - b2) ** 2) ** 0.5


def find_closest_megascans_brick(brick_hex: str) -> str:
    """
    Find closest Megascans brick material by colour distance.

    Args:
        brick_hex (str): Brick colour as hex

    Returns:
        str: Material key (e.g., 'brick_red')
    """
    brick_materials = {k: v for k, v in MEGASCANS_MATERIALS.items() if v["category"] == "brick"}

    if not brick_materials:
        return "brick_red"

    closest = min(
        brick_materials.items(),
        key=lambda item: colour_distance(brick_hex, item[1]["colour_hex"]),
    )

    return closest[0]


def find_closest_megascans_material(colour_hex: str, category: str) -> str:
    """
    Find closest Megascans material by colour and category.

    Args:
        colour_hex (str): Colour as hex
        category (str): Material category (painted, stucco, wood, roofing, etc.)

    Returns:
        str: Material key
    """
    candidates = {k: v for k, v in MEGASCANS_MATERIALS.items() if v["category"] == category}

    if not candidates:
        # Fallback to any available material
        return list(MEGASCANS_MATERIALS.keys())[0]

    closest = min(
        candidates.items(),
        key=lambda item: colour_distance(colour_hex, item[1]["colour_hex"]),
    )

    return closest[0]


def collect_building_materials(params_dir: Path) -> Dict[str, dict]:
    """
    Scan all param files and collect material assignments.

    Args:
        params_dir (Path): Directory containing param JSON files

    Returns:
        dict: {address: {facade_material, brick_hex, roof_material, ...}}
    """
    materials = {}

    for param_file in params_dir.glob("*.json"):
        if param_file.name.startswith("_"):
            continue

        try:
            with open(param_file, "r", encoding="utf-8") as f:
                params = json.load(f)

            if params.get("skipped"):
                continue

            address = params.get("site", {}).get("street_number", "")
            if not address:
                address = params.get("building_name", param_file.stem)

            facade_material = (
                (params.get("facade_material") or "").lower().strip() or "brick"
            )
            brick_hex = (
                params.get("facade_detail", {}).get("brick_colour_hex")
                or params.get("facade_colour")
                or "#B85A3A"
            )
            roof_colour = params.get("roof_colour") or "#5A5A5A"

            # Trim colour from colour_palette or facade_detail
            cp = params.get("colour_palette", {})
            trim_hex = "#F0F0F0"
            if isinstance(cp, dict):
                trim_d = cp.get("trim", {})
                if isinstance(trim_d, dict):
                    trim_hex = trim_d.get("hex_approx", trim_hex)
            fd = params.get("facade_detail", {})
            if isinstance(fd, dict) and trim_hex == "#F0F0F0":
                tc = fd.get("trim_colour_hex", "")
                if isinstance(tc, str) and tc.startswith("#"):
                    trim_hex = tc

            # Foundation colour (stone vs concrete)
            foundation_hex = "#9A9690"
            hcd = params.get("hcd_data", {})
            if isinstance(hcd, dict):
                date_str = (hcd.get("construction_date") or "").lower()
                if "pre-1889" in date_str or "1889" in date_str:
                    foundation_hex = "#7A7570"  # rubble stone for pre-Victorian

            # Condition for weathering metadata
            condition = (params.get("condition") or "fair").lower()

            roof_material = (params.get("roof_material") or "").lower().strip()

            materials[address] = {
                "file": param_file.name,
                "facade_material": facade_material,
                "brick_hex": brick_hex,
                "roof_colour": roof_colour,
                "roof_material": roof_material,
                "trim_hex": trim_hex,
                "foundation_hex": foundation_hex,
                "condition": condition,
            }

        except Exception as e:
            print(f"Warning: error reading {param_file.name}: {e}")
            continue

    return materials


def map_materials_to_megascans(materials: Dict[str, dict]) -> Dict[str, dict]:
    """
    Map building materials to Megascans library.

    Args:
        materials (dict): Building materials by address

    Returns:
        dict: {address: {megascans_facade_id, megascans_roof_id, ...}}
    """
    mappings = {}

    for address, mat_data in materials.items():
        facade_material = mat_data["facade_material"]
        brick_hex = mat_data["brick_hex"]
        roof_colour = mat_data["roof_colour"]
        trim_hex = mat_data.get("trim_hex", "#F0F0F0")
        foundation_hex = mat_data.get("foundation_hex", "#9A9690")
        condition = mat_data.get("condition", "fair")

        # Map facade material
        if facade_material in ("brick", ""):
            megascans_facade_key = find_closest_megascans_brick(brick_hex)
        elif facade_material in ("paint", "painted"):
            megascans_facade_key = find_closest_megascans_material(
                brick_hex, "painted"
            )
        elif facade_material == "stucco":
            megascans_facade_key = find_closest_megascans_material(
                brick_hex, "stucco"
            )
        elif facade_material == "clapboard":
            megascans_facade_key = find_closest_megascans_material(
                brick_hex, "wood"
            )
        elif facade_material == "stone":
            megascans_facade_key = find_closest_megascans_material(
                brick_hex, "stone"
            )
        else:
            megascans_facade_key = "brick_red"

        # Map roof material
        megascans_roof_key = find_closest_megascans_material(roof_colour, "roofing")

        # Map trim material (painted wood trim or stone decorative)
        megascans_trim_key = find_closest_megascans_material(trim_hex, "wood_trim")
        if not megascans_trim_key or megascans_trim_key not in MEGASCANS_MATERIALS:
            megascans_trim_key = find_closest_megascans_material(trim_hex, "stone")

        # Map foundation material
        megascans_foundation_key = find_closest_megascans_material(
            foundation_hex, "foundation"
        )
        if megascans_foundation_key not in MEGASCANS_MATERIALS:
            megascans_foundation_key = "concrete_foundation"

        megascans_facade = MEGASCANS_MATERIALS[megascans_facade_key]
        megascans_roof = MEGASCANS_MATERIALS[megascans_roof_key]
        megascans_trim = MEGASCANS_MATERIALS.get(megascans_trim_key, {})
        megascans_foundation = MEGASCANS_MATERIALS.get(megascans_foundation_key, {})

        # Condition-based roughness bias (poor → higher roughness, good → lower)
        roughness_bias = {"good": -0.05, "fair": 0.0, "poor": 0.10}.get(condition, 0.0)

        # Map architectural detail materials by prefix
        # These map Blender mat_ names to Megascans categories for sidecar export
        roof_material = mat_data.get("roof_material", "")
        copper_kw = ("copper", "verdigris", "patina")
        detail_mappings = {}
        detail_mappings["window_frame"] = megascans_trim_key  # wood or metal trim
        detail_mappings["porch_post"] = megascans_trim_key  # painted wood
        detail_mappings["turned_post"] = megascans_trim_key  # painted wood
        detail_mappings["bargeboard"] = megascans_trim_key  # decorative wood
        detail_mappings["fascia"] = megascans_trim_key  # wood trim
        detail_mappings["lattice"] = megascans_trim_key  # painted wood
        detail_mappings["porch_step"] = megascans_foundation_key  # stone
        detail_mappings["chimney_cap"] = megascans_foundation_key  # stone
        detail_mappings["watertable"] = megascans_foundation_key  # stone
        detail_mappings["coping"] = megascans_foundation_key  # stone
        detail_mappings["cornice"] = megascans_foundation_key  # stone
        detail_mappings["lintel"] = megascans_foundation_key  # stone
        detail_mappings["awning"] = "canvas_fabric"  # fabric/canvas
        if any(kw in str(roof_material).lower() for kw in copper_kw):
            detail_mappings["gutter"] = "metal_copper_patina"
            detail_mappings["roof"] = "metal_copper_patina"
        else:
            detail_mappings["gutter"] = megascans_roof_key

        mappings[address] = {
            "facade_material": facade_material,
            "brick_hex": brick_hex,
            "roof_colour": roof_colour,
            "condition": condition,
            "roughness_bias": roughness_bias,
            "megascans_facade_key": megascans_facade_key,
            "megascans_facade_id": megascans_facade["surface_id"],
            "megascans_facade_name": megascans_facade["name"],
            "megascans_facade_category": megascans_facade["category"],
            "megascans_facade_metallic": megascans_facade.get("metallic", 0.0),
            "megascans_facade_roughness": megascans_facade.get("roughness_range", (0.6, 0.9)),
            "megascans_roof_key": megascans_roof_key,
            "megascans_roof_id": megascans_roof["surface_id"],
            "megascans_roof_name": megascans_roof["name"],
            "megascans_roof_metallic": megascans_roof.get("metallic", 0.0),
            "megascans_trim_key": megascans_trim_key,
            "megascans_trim_id": megascans_trim.get("surface_id", ""),
            "megascans_trim_name": megascans_trim.get("name", ""),
            "megascans_foundation_key": megascans_foundation_key,
            "megascans_foundation_id": megascans_foundation.get("surface_id", ""),
            "detail_material_mappings": detail_mappings,
            "file": mat_data["file"],
        }

    return mappings


def write_mapping_csv(mappings: Dict[str, dict], output_path: Path) -> None:
    """
    Write material mappings to CSV.

    Args:
        mappings (dict): Material mappings
        output_path (Path): Output CSV file path
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = [
        "address",
        "param_file",
        "facade_material",
        "brick_hex",
        "condition",
        "roughness_bias",
        "megascans_facade_key",
        "megascans_facade_id",
        "megascans_facade_name",
        "megascans_facade_category",
        "megascans_facade_metallic",
        "roof_colour",
        "megascans_roof_key",
        "megascans_roof_id",
        "megascans_roof_name",
        "megascans_roof_metallic",
        "megascans_trim_key",
        "megascans_trim_id",
        "megascans_foundation_key",
        "megascans_foundation_id",
    ]

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for address, mapping in sorted(mappings.items(), key=lambda x: str(x[0])):
            row = {"address": address, "param_file": mapping["file"]}
            for field in fieldnames:
                if field in ("address", "param_file"):
                    continue
                val = mapping.get(field, "")
                if isinstance(val, tuple):
                    val = f"{val[0]:.2f}-{val[1]:.2f}"
                row[field] = val
            writer.writerow(row)


def generate_unreal_material_instances(mappings: Dict[str, dict], output_dir: Path) -> None:
    """
    Generate Unreal Material Instance configuration files.

    Args:
        mappings (dict): Material mappings
        output_dir (Path): Output directory for configs
    """
    unreal_dir = output_dir / "unreal_materials"
    unreal_dir.mkdir(parents=True, exist_ok=True)

    # Group by unique facade + roof combinations
    unique_combos = {}
    for address, mapping in mappings.items():
        key = (mapping["megascans_facade_id"], mapping["megascans_roof_id"])
        if key not in unique_combos:
            unique_combos[key] = {
                "addresses": [],
                "facade": mapping,
                "roof_id": mapping["megascans_roof_id"],
            }
        unique_combos[key]["addresses"].append(address)

    # Generate Unreal MI JSON for each combination
    for combo_idx, (key, combo) in enumerate(unique_combos.items()):
        facade_id, roof_id = key
        facade_key = combo["facade"]["megascans_facade_key"]
        roof_key = combo["facade"]["megascans_roof_key"]

        facade_mat = MEGASCANS_MATERIALS.get(facade_key, {})
        roof_mat = MEGASCANS_MATERIALS.get(roof_key, {})

        mi_name = f"MI_{facade_key}_{roof_key}"
        mi_config = {
            "material_instance_name": mi_name,
            "base_material": "M_BuildingFacade",
            "parameters": {
                "facade_megascans_id": facade_id,
                "facade_megascans_name": combo["facade"]["megascans_facade_name"],
                "facade_roughness_range": facade_mat.get("roughness_range", (0.6, 0.9)),
                "facade_metallic": facade_mat.get("metallic", 0.0),
                "facade_has_ao": facade_mat.get("has_ao", False),
                "facade_has_displacement": facade_mat.get("has_displacement", False),
                "roof_megascans_id": roof_id,
                "roof_megascans_name": combo["facade"]["megascans_roof_name"],
                "roof_roughness_range": roof_mat.get("roughness_range", (0.8, 0.95)),
                "roof_metallic": roof_mat.get("metallic", 0.0),
                "facade_colour_override": combo["facade"].get(
                    "brick_hex", "#CCCCCC"
                ),
                "applied_to_buildings": len(combo["addresses"]),
            },
            "sample_addresses": combo["addresses"][:5],
        }

        mi_path = unreal_dir / f"{mi_name}.json"
        with open(mi_path, "w", encoding="utf-8") as f:
            json.dump(mi_config, f, indent=2)

    print(
        f"[map_megascans_materials] Generated {len(unique_combos)} "
        f"Unreal Material Instance configs"
    )


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--megascans-lib",
        type=Path,
        help="Path to Megascans library (optional, for future use)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output CSV file path",
    )

    args = parser.parse_args()

    script_dir = Path(__file__).parent
    project_root = script_dir.parent
    params_dir = project_root / "params"

    if args.output:
        output_path = args.output
    else:
        output_path = project_root / "outputs" / "exports" / "megascans_mapping.csv"

    print("[map_megascans_materials] Scanning param files...")
    materials = collect_building_materials(params_dir)
    print(f"[map_megascans_materials] Found {len(materials)} buildings")

    print("[map_megascans_materials] Mapping to Megascans library...")
    mappings = map_materials_to_megascans(materials)

    print("[map_megascans_materials] Writing CSV mapping...")
    write_mapping_csv(mappings, output_path)
    print(f"[map_megascans_materials] Wrote {output_path}")

    print("[map_megascans_materials] Generating Unreal Material Instances...")
    output_dir = output_path.parent
    generate_unreal_material_instances(mappings, output_dir)

    # Summary statistics
    facade_categories = {}
    roof_categories = {}

    for mapping in mappings.values():
        facade_cat = mapping["megascans_facade_category"]
        roof_cat = MEGASCANS_MATERIALS[mapping["megascans_roof_key"]]["category"]

        facade_categories[facade_cat] = facade_categories.get(facade_cat, 0) + 1
        roof_categories[roof_cat] = roof_categories.get(roof_cat, 0) + 1

    print("[map_megascans_materials] Summary:")
    print(f"  - Total buildings: {len(mappings)}")
    print("  - Facade material distribution:")
    for cat, count in sorted(facade_categories.items()):
        print(f"      {cat}: {count}")
    print("  - Roof material distribution:")
    for cat, count in sorted(roof_categories.items()):
        print(f"      {cat}: {count}")
    print("[map_megascans_materials] Complete")


if __name__ == "__main__":
    main()
