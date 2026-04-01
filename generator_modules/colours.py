"""Colour resolution utilities for the Kensington Market building generator.

Pure Python — no Blender (bpy) dependency. Safe to import and test outside
Blender's Python environment.

Extracted from generate_building.py to enable:
  - Independent unit testing
  - Reuse by enrichment/QA scripts
  - Cleaner generator module boundaries
"""


def hex_to_rgb(hex_str):
    """Convert hex colour string to (r, g, b) floats in [0,1]."""
    hex_str = hex_str.lstrip('#')
    if len(hex_str) != 6:
        return (0.5, 0.5, 0.5)
    r = int(hex_str[0:2], 16) / 255.0
    g = int(hex_str[2:4], 16) / 255.0
    b = int(hex_str[4:6], 16) / 255.0
    return (r, g, b)


# ---------------------------------------------------------------------------
# Colour name → hex mapping
# ---------------------------------------------------------------------------

COLOUR_NAME_MAP = {
    "red-orange": "#B85A3A",
    "red_orange": "#B85A3A",
    "dark_red_brown": "#6B3A2E",
    "dark_red_burgundy_maroon": "#5A2020",
    "dark_forest_green": "#2D4A2D",
    "dark_green": "#2D4A2D",
    "turquoise_teal": "#3FBFBF",
    "grey_tan": "#9E9585",
    "red_brown": "#8B5A3A",
    "cream_buff": "#D4C9A8",
    "buff_tan": "#C8B88A",
    "white": "#F0F0F0",
    "grey_blue": "#5A6A7A",
    "dark_brown_stained": "#3E2A1A",
    "dark_brown": "#4A2E1A",
    "dark_grey_black": "#2E2E2E",
    "dark_grey": "#3A3A3A",
    "blue": "#4070B0",
    "red": "#C03030",
    "bright_red": "#CC2020",
    "dark_bronze": "#4A3A2A",
    "dark_alumin": "#3A3A3A",
    "natural": "#B89060",
    "black": "#1A1A1A",
    "sandstone": "#C8B88A",
    "buff_brick": "#C9A46A",
    "buff": "#D4C9A8",
    "tan": "#BFA07A",
    "cream": "#E8E0D0",
    "bronze": "#5C4632",
    "charcoal": "#2F3238",
    "olive_green": "#5D6F3A",
    "brick": "#B85A3A",
    "red_brick": "#B85A3A",
}


def colour_name_to_hex(name):
    """Map common colour names to hex values."""
    normalized = name.lower().replace(" ", "_")

    if normalized in COLOUR_NAME_MAP:
        return COLOUR_NAME_MAP[normalized]

    # Try to find partial match
    for key, val in COLOUR_NAME_MAP.items():
        if key in normalized:
            return val

    if "dark" in normalized and ("brown" in normalized or "wood" in normalized):
        return "#4A3020"
    if "dark" in normalized and ("grey" in normalized or "gray" in normalized or "black" in normalized):
        return "#2F3238"
    if "buff" in normalized or "sand" in normalized:
        return "#C8B88A"
    if "cream" in normalized or "stone" in normalized:
        return "#D8CFBF"
    if "red" in normalized and "brick" in normalized:
        return "#B85A3A"
    return "#808080"


def infer_hex_from_text(*texts, default="#808080"):
    """Infer a representative colour hex from one or more descriptive strings."""
    merged = " ".join(str(t) for t in texts if t).lower()
    if not merged:
        return default
    result = colour_name_to_hex(merged)
    if result == "#808080" and default != "#808080":
        return default
    return result


def get_stone_hex(*texts, default="#C8C0B0"):
    """Infer a stone/trim colour from descriptive text."""
    merged = " ".join(str(t) for t in texts if t).lower()
    if "buff" in merged or "sand" in merged or "tan" in merged:
        return "#C8B88A"
    if "cream" in merged or "light" in merged:
        return "#E8E0D0"
    if "grey" in merged or "gray" in merged:
        return "#B8B2A8"
    if "red brick" in merged:
        return "#B85A3A"
    return default


# ---------------------------------------------------------------------------
# Param-based colour resolution
# ---------------------------------------------------------------------------

def get_roof_hex(params):
    """Extract roof colour hex from params, checking multiple locations."""
    rd = params.get("roof_detail", {})
    if isinstance(rd, dict):
        h = rd.get("colour_hex", "")
        if h and h.startswith("#"):
            return h
        hip = rd.get("hip_element", {})
        if isinstance(hip, dict):
            h = hip.get("colour_hex", "")
            if h and h.startswith("#"):
                return h

    rc = str(params.get("roof_colour", "")).lower()
    if rc:
        if "dark" in rc:
            return "#3A3A3A"
        elif "grey" in rc or "gray" in rc:
            return "#5A5A5A"
        elif "red" in rc or "brown" in rc:
            return "#6B3A2E"

    rm = str(params.get("roof_material", "")).lower()
    if "dark" in rm and ("grey" in rm or "black" in rm):
        return "#3A3A3A"
    elif "grey" in rm or "gray" in rm:
        return "#5A5A5A"
    elif "red" in rm:
        return "#7A4030"
    elif "copper" in rm or "green" in rm:
        return "#4A6A50"

    return "#4A4A4A"


def get_facade_hex(params):
    """Extract facade colour hex from params."""
    facade_hex = None
    facade_detail = params.get("facade_detail", {})
    if isinstance(facade_detail, dict):
        facade_hex = facade_detail.get("brick_colour_hex")
    if not facade_hex:
        fc = params.get("facade_colour", "red-orange")
        if isinstance(fc, str) and fc.startswith("#"):
            facade_hex = fc
        else:
            facade_hex = infer_hex_from_text(
                fc, params.get("facade_material", "brick"), default="#B85A3A"
            )
    return facade_hex


def get_trim_hex(params):
    """Get trim colour hex from params."""
    cp = params.get("colour_palette", {})
    if isinstance(cp, dict):
        trim = cp.get("trim", {})
        if isinstance(trim, dict):
            return trim.get("hex_approx", infer_hex_from_text(trim, default="#F0F0F0"))
    fd = params.get("facade_detail", {})
    if isinstance(fd, dict):
        tc = fd.get("trim_colour", "")
        if isinstance(tc, str):
            return infer_hex_from_text(tc, default="#F0F0F0")
    dec = params.get("decorative_elements", {})
    if isinstance(dec, dict):
        scheme = dec.get("trim_colour_scheme", {})
        if isinstance(scheme, dict):
            return infer_hex_from_text(scheme.get("primary_trim", ""), default="#F0F0F0")
    return "#F0F0F0"


def get_accent_hex(params):
    """Get accent colour hex from colour_palette, falling back to stone default."""
    cp = params.get("colour_palette", {})
    if isinstance(cp, dict):
        accent = cp.get("accent", {})
        if isinstance(accent, dict):
            h = accent.get("hex_approx", "")
            if h and h.startswith("#"):
                return h
    return "#D4C9A8"


def get_stone_element_hex(params, element_dict=None, default="#D4C9A8"):
    """Resolve colour for stone decorative elements (voussoirs, string courses, etc.).

    Priority: element dict → colour_palette.accent → hardcoded default.
    """
    if isinstance(element_dict, dict):
        h = element_dict.get("colour_hex", "")
        if h and h.startswith("#"):
            return h
    return get_accent_hex(params)


def get_condition_roughness_bias(params):
    """Return roughness bias based on building condition.

    poor → +0.08 (more weathered), good → -0.04 (cleaner surfaces).
    """
    condition = (params.get("condition") or "fair").lower()
    rating = params.get("assessment", {})
    if isinstance(rating, dict):
        cr = rating.get("condition_rating")
        if isinstance(cr, (int, float)):
            if cr <= 2:
                condition = "poor"
            elif cr >= 4:
                condition = "good"
    return {"good": -0.04, "fair": 0.0, "poor": 0.08}.get(condition, 0.0)


def get_condition_saturation_shift(params):
    """Return saturation multiplier based on building condition.

    poor → 0.85 (desaturated/faded), good → 1.0.
    """
    condition = (params.get("condition") or "fair").lower()
    return {"good": 1.0, "fair": 0.95, "poor": 0.85}.get(condition, 0.95)


# ---------------------------------------------------------------------------
# HCD (Heritage Conservation District) helpers
# ---------------------------------------------------------------------------

def get_era_defaults(params):
    """Return material/style defaults based on HCD construction date."""
    hcd = params.get('hcd_data', {})
    date_str = hcd.get('construction_date', '')
    defaults = {
        'brick_colour': (0.45, 0.18, 0.10, 1.0),
        'mortar_colour': (0.85, 0.82, 0.75, 1.0),
        'trim_style': 'simple',
        'window_arch': 'flat',
    }
    if 'Pre-1889' in date_str:
        defaults['brick_colour'] = (0.5, 0.15, 0.08, 1.0)
        defaults['trim_style'] = 'ornate'
        defaults['window_arch'] = 'segmental'
    elif '1890' in date_str or '1903' in date_str or '1904' in date_str or '1913' in date_str:
        defaults['trim_style'] = 'moderate'
        defaults['window_arch'] = 'mixed'
    elif '1914' in date_str or '1930' in date_str:
        defaults['trim_style'] = 'restrained'
        defaults['window_arch'] = 'flat'
    return defaults


def get_typology_hints(params):
    """Return geometry hints based on HCD building typology."""
    hcd = params.get('hcd_data', {})
    typology = hcd.get('typology', '').lower()
    hints = {
        'has_party_wall_left': False,
        'has_party_wall_right': False,
        'is_bay_and_gable': False,
        'is_ontario_cottage': False,
        'expected_floors': None,
    }
    if 'row' in typology:
        hints['has_party_wall_left'] = True
        hints['has_party_wall_right'] = True
    elif 'semi-detached' in typology:
        hints['has_party_wall_left'] = True
    if 'bay-and-gable' in typology:
        hints['is_bay_and_gable'] = True
    if 'ontario cottage' in typology:
        hints['is_ontario_cottage'] = True
        hints['expected_floors'] = 1
    if 'institutional' in typology:
        hints['expected_floors'] = 3
    return hints


def get_utility_anchor_height(params):
    """Calculate realistic utility wire anchor height (mid-facade spaghetti)."""
    total_h = params.get("total_height_m", 9.0)
    return params.get("utility_anchor_height_m", total_h * 0.7)
