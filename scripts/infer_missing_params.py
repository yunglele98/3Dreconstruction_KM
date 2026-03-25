#!/usr/bin/env python3
"""Infer remaining parameters the generator needs but nobody provides.

Fills 7 gap keys: colour_palette, dormer, eave_overhang_mm,
ground_floor_arches, roof_material, volumes, and hcd_data stub.

Run LAST in the enrichment pipeline, after all other enrichment scripts.

Usage:
    python infer_missing_params.py
"""

import json
import re
from pathlib import Path

PARAMS_DIR = Path(__file__).parent.parent / "params"


# ---------------------------------------------------------------------------
# Era detection
# ---------------------------------------------------------------------------

def detect_era(data: dict) -> str:
    """Extract approximate era from any available source."""
    # Check hcd_data first
    hcd = data.get("hcd_data", {})
    if isinstance(hcd, dict):
        date = hcd.get("construction_date", "")
        if date:
            return str(date)

    # Check overall_style for era hints
    style = str(data.get("overall_style", "")).lower()
    if "victorian" in style:
        return "1889-1903"
    if "edwardian" in style:
        return "1904-1913"
    if "georgian" in style:
        return "pre-1889"

    # Check year_built_approx
    year = data.get("year_built_approx", "")
    if year:
        return str(year)

    return "1889-1903"  # Kensington Market default


def detect_style(data: dict) -> str:
    """Get overall architectural style."""
    return str(data.get("overall_style") or "Vernacular").lower()


# ---------------------------------------------------------------------------
# 1. colour_palette
# ---------------------------------------------------------------------------

FACADE_HEX_MAP = {
    "red": "#B85A3A",
    "red-orange": "#C4603A",
    "dark red": "#8B3A2A",
    "brown": "#7A5C44",
    "buff": "#D4B896",
    "yellow": "#C8B060",
    "cream": "#E8D8B0",
    "orange": "#C87040",
    "grey": "#8A8A8A",
    "white": "#E8E0D4",
    "painted": "#D8D0C0",
}

TRIM_BY_ERA = {
    "pre-1889": "#3A2A20",
    "1889": "#3A2A20",
    "1904": "#2A2A2A",
    "1914": "#4A4A4A",
    "1931": "#F0EDE8",
}

ROOF_HEX_MAP = {
    "asphalt": "#5A5A5A",
    "slate": "#4A5A5A",
    "shingle": "#5A5A5A",
    "metal": "#6A6A6A",
    "copper": "#5A8A6A",
    "tar": "#3A3A3A",
    "red": "#8A3A2A",
    "green": "#3A5A3A",
    "brown": "#6A5040",
}


def infer_facade_hex(material: str, colour: str) -> str:
    combined = f"{colour} {material}".lower()
    for key, hex_val in FACADE_HEX_MAP.items():
        if key in combined:
            return hex_val
    if "brick" in combined:
        return "#B85A3A"
    if "stucco" in combined or "render" in combined:
        return "#D8D0C0"
    if "stone" in combined:
        return "#C8B898"
    return "#B85A3A"


def infer_trim_hex(era: str) -> str:
    era_lower = era.lower()
    for key, hex_val in TRIM_BY_ERA.items():
        if key in era_lower:
            return hex_val
    return "#E8E0D0"


def infer_roof_hex(material: str) -> str:
    m = material.lower()
    for key, hex_val in ROOF_HEX_MAP.items():
        if key in m:
            return hex_val
    return "#5A5A5A"


def infer_colour_palette(data: dict) -> bool:
    """Build unified colour_palette from facade, era, and roof data."""
    if "colour_palette" in data and isinstance(data["colour_palette"], dict):
        palette = data["colour_palette"]
        if len(palette) >= 3:
            return False  # already populated enough

    material = str(data.get("facade_material", "brick"))
    colour = str(data.get("facade_colour", ""))
    era = detect_era(data)
    roof_mat = str(data.get("roof_material", "asphalt shingles"))

    facade_hex = infer_facade_hex(material, colour)
    trim_hex = infer_trim_hex(era)
    roof_hex = infer_roof_hex(roof_mat)

    # Accent: slightly darker than trim for window sashes, railings
    accent_hex = trim_hex  # same as trim by default

    # Door colour: darker for Victorian, lighter for later
    style = detect_style(data)
    if "victorian" in style or "edwardian" in style:
        door_hex = "#3A2A20"
    else:
        door_hex = trim_hex

    data["colour_palette"] = {
        "facade_hex": facade_hex,
        "trim_hex": trim_hex,
        "roof_hex": roof_hex,
        "accent_hex": accent_hex,
        "door_hex": door_hex,
        "mortar_hex": "#C8C0B0",
    }
    return True


# ---------------------------------------------------------------------------
# 2. dormer
# ---------------------------------------------------------------------------

def infer_dormer(data: dict) -> bool:
    """Infer dormer config from roof_features if dormers are mentioned."""
    if "dormer" in data and isinstance(data["dormer"], dict):
        return False

    roof_features = data.get("roof_features", [])
    has_dormers = False

    if isinstance(roof_features, list):
        for feat in roof_features:
            feat_str = str(feat).lower() if not isinstance(feat, dict) else str(feat.get("type", "")).lower()
            if "dormer" in feat_str:
                has_dormers = True
                break

    if not has_dormers:
        return False

    roof_type = str(data.get("roof_type", "")).lower()
    width = data.get("facade_width_m", 5.0)

    # Dormer type by roof
    if "mansard" in roof_type:
        dormer_type = "Mansard dormer"
        count = max(2, int(width / 2.5))
    elif "gable" in roof_type:
        dormer_type = "Gable dormer"
        count = 1
    elif "hip" in roof_type:
        dormer_type = "Hip dormer"
        count = max(1, int(width / 3.0))
    else:
        dormer_type = "Shed dormer"
        count = 1

    data["dormer"] = {
        "present": True,
        "type": dormer_type,
        "count": count,
        "width_m": 1.0,
        "height_m": 1.2,
        "has_window": True,
    }
    return True


# ---------------------------------------------------------------------------
# 3. eave_overhang_mm
# ---------------------------------------------------------------------------

EAVE_BY_ROOF = {
    "gable": 300,
    "cross-gable": 300,
    "hip": 250,
    "mansard": 100,
    "gambrel": 300,
    "flat": 0,
    "parapet": 0,
    "shed": 200,
    "tower": 150,
}


def infer_eave_overhang(data: dict) -> bool:
    """Set eave overhang based on roof type."""
    if "eave_overhang_mm" in data:
        return False

    # Also check inside roof_detail
    rd = data.get("roof_detail", {})
    if isinstance(rd, dict) and "eave_overhang_mm" in rd:
        return False

    roof = str(data.get("roof_type", "gable")).lower()
    overhang = 300  # default
    for key, val in EAVE_BY_ROOF.items():
        if key in roof:
            overhang = val
            break

    data["eave_overhang_mm"] = overhang
    return True


# ---------------------------------------------------------------------------
# 4. ground_floor_arches
# ---------------------------------------------------------------------------

def infer_ground_floor_arches(data: dict) -> bool:
    """Infer arched ground-floor openings from window/door types."""
    if "ground_floor_arches" in data:
        return False

    window_type = str(data.get("window_type", "")).lower()
    door_type = ""
    doors = data.get("doors_detail", [])
    if isinstance(doors, list) and doors:
        door_type = str(doors[0].get("type", "")).lower() if isinstance(doors[0], dict) else ""

    has_arches = False
    arch_type = "segmental"

    if "arched" in window_type or "arched" in door_type:
        has_arches = True
        if "round" in window_type or "semicircular" in window_type:
            arch_type = "round"
        elif "pointed" in window_type or "gothic" in window_type:
            arch_type = "pointed"

    # Check decorative elements for voussoirs/arches
    dec = data.get("decorative_elements", {})
    if isinstance(dec, dict):
        hoods = dec.get("window_hoods", {})
        if isinstance(hoods, dict) and hoods.get("present", hoods.get("arch_type")):
            has_arches = True
            arch_type = hoods.get("arch_type", arch_type)

    if not has_arches:
        return False

    wpf = data.get("windows_per_floor", [])
    ground_windows = wpf[0] if isinstance(wpf, list) and wpf else 2

    data["ground_floor_arches"] = {
        "present": True,
        "arch_type": arch_type,
        "count": ground_windows,
        "spring_height_ratio": 0.7,
    }
    return True


# ---------------------------------------------------------------------------
# 5. roof_material
# ---------------------------------------------------------------------------

ROOF_MATERIAL_BY_ERA = {
    "pre-1889": "Slate shingles",
    "1889": "Slate shingles",
    "1904": "Grey asphalt shingles",
    "1914": "Grey asphalt shingles",
    "1931": "Grey asphalt shingles",
}

ROOF_MATERIAL_BY_TYPE = {
    "flat": "Built-up tar and gravel",
    "parapet": "Built-up tar and gravel",
    "mansard": "Slate shingles",
}


def infer_roof_material(data: dict) -> bool:
    """Infer roof material from era and roof type."""
    if "roof_material" in data and data["roof_material"]:
        return False

    roof_type = str(data.get("roof_type", "")).lower()
    era = detect_era(data)

    # Check roof type first (flat/parapet have specific materials)
    for key, mat in ROOF_MATERIAL_BY_TYPE.items():
        if key in roof_type:
            data["roof_material"] = mat
            return True

    # Fall back to era
    era_lower = era.lower()
    for key, mat in ROOF_MATERIAL_BY_ERA.items():
        if key in era_lower:
            data["roof_material"] = mat
            return True

    data["roof_material"] = "Grey asphalt shingles"
    return True


# ---------------------------------------------------------------------------
# 6. volumes (multi-volume buildings)
# ---------------------------------------------------------------------------

def infer_volumes(data: dict) -> bool:
    """Set empty volumes list if not specified. Generator uses facade_width + depth for single-volume."""
    if "volumes" in data:
        return False
    data["volumes"] = []
    return True


# ---------------------------------------------------------------------------
# 7. hcd_data stub
# ---------------------------------------------------------------------------

def ensure_hcd_data(data: dict) -> bool:
    """Create minimal hcd_data stub if missing, so downstream scripts don't error."""
    if "hcd_data" in data and isinstance(data["hcd_data"], dict):
        return False

    style = detect_style(data)
    era = detect_era(data)

    # Infer typology from agent observations
    has_storefront = data.get("has_storefront", False)
    bay = data.get("bay_window", {})
    has_bay = isinstance(bay, dict) and bay.get("present", False)
    roof = str(data.get("roof_type", "")).lower()
    floors = data.get("floors", 2)

    if has_storefront:
        typology = "commercial"
    elif has_bay and "gable" in roof:
        typology = "house-form, row, bay-and-gable"
    elif floors >= 4:
        typology = "multi-residential"
    elif "victorian" in style or "edwardian" in style:
        typology = "house-form, row"
    else:
        typology = "house-form"

    data["hcd_data"] = {
        "typology": typology,
        "construction_date": era,
        "source": "inferred_from_photo_analysis",
    }
    return True


# ---------------------------------------------------------------------------
# Bonus: roof_colour from roof_material
# ---------------------------------------------------------------------------

def ensure_roof_colour(data: dict) -> bool:
    """Set roof_colour hex from roof_material if missing."""
    if "roof_colour" in data and data["roof_colour"]:
        return False

    mat = str(data.get("roof_material", "asphalt")).lower()
    data["roof_colour"] = infer_roof_hex(mat)
    return True


# ---------------------------------------------------------------------------
# Bonus: facade_depth_m
# ---------------------------------------------------------------------------

def ensure_facade_depth(data: dict) -> bool:
    """Set building depth if still missing after enrichment."""
    if "facade_depth_m" in data:
        return False

    width = data.get("facade_width_m", 6.0)
    building_type = str(data.get("building_type", "")).lower()

    if "commercial" in building_type:
        data["facade_depth_m"] = max(12.0, width * 1.5)
    elif width <= 5.0:
        data["facade_depth_m"] = 10.0
    elif width <= 8.0:
        data["facade_depth_m"] = 10.0
    else:
        data["facade_depth_m"] = max(10.0, width * 1.2)

    return True


# ---------------------------------------------------------------------------
# Bonus: roof_detail completeness
# ---------------------------------------------------------------------------

def ensure_roof_detail(data: dict) -> bool:
    """Ensure roof_detail has minimum required fields."""
    rd = data.get("roof_detail")
    if not isinstance(rd, dict):
        rd = {}
        data["roof_detail"] = rd

    changed = False

    if "eave_overhang_mm" not in rd:
        rd["eave_overhang_mm"] = data.get("eave_overhang_mm", 300)
        changed = True

    roof_type = str(data.get("roof_type", "")).lower()

    # Gable details
    if "gable" in roof_type:
        if "gable_window" not in rd:
            rd["gable_window"] = {
                "present": False,
            }
            changed = True

    # Bargeboard for gable roofs
    if "gable" in roof_type and "bargeboard" not in rd:
        style = detect_style(data)
        if "victorian" in style:
            rd["bargeboard"] = {
                "present": True,
                "style": "decorative",
                "colour_hex": data.get("colour_palette", {}).get("trim_hex", "#4A3324"),
            }
            changed = True

    return changed


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def infer_file(filepath: Path) -> tuple[bool, str]:
    """Fill remaining gaps in a single param file."""
    with open(filepath, encoding="utf-8") as f:
        data = json.load(f)

    if data.get("skipped"):
        return False, "non-building (skipped)"

    meta = data.get("_meta", {})
    if meta.get("gaps_filled"):
        return False, "already processed"

    orig = json.dumps(data)

    inferences = []
    if ensure_hcd_data(data):
        inferences.append("hcd_data_stub")
    if infer_roof_material(data):
        inferences.append("roof_material")
    if ensure_roof_colour(data):
        inferences.append("roof_colour")
    if infer_colour_palette(data):
        inferences.append("colour_palette")
    if infer_dormer(data):
        inferences.append("dormer")
    if infer_eave_overhang(data):
        inferences.append("eave_overhang")
    if infer_ground_floor_arches(data):
        inferences.append("ground_floor_arches")
    if infer_volumes(data):
        inferences.append("volumes")
    if ensure_facade_depth(data):
        inferences.append("facade_depth")
    if ensure_roof_detail(data):
        inferences.append("roof_detail")

    if not inferences:
        return False, "no gaps"

    meta["gaps_filled"] = True
    meta["inferences_applied"] = inferences
    data["_meta"] = meta

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")

    return True, ", ".join(inferences)


def main():
    files = sorted(PARAMS_DIR.glob("*.json"))
    files = [f for f in files if not f.name.startswith("_")]

    filled = 0
    skipped = 0
    for f in files:
        changed, msg = infer_file(f)
        if changed:
            filled += 1
            print(f"  [INFERRED] {f.name}: {msg}")
        else:
            skipped += 1

    print(f"\nDone: {filled} gap-filled, {skipped} skipped (of {len(files)} total)")


if __name__ == "__main__":
    main()
