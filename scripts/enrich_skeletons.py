#!/usr/bin/env python3
"""Enrich HCD skeleton JSON files with typology-driven defaults.

Reads each skeleton in params/, infers missing fields from HCD data,
typology, era, and facade geometry, then writes enriched versions back.
Skips files that were photo-analyzed (source != "hcd_plan_only").
"""

import json
import math
import os
import re
import tempfile
from pathlib import Path


def _atomic_write_json(filepath, data, ensure_ascii=False):
    """Write JSON atomically via temp file + rename to prevent corruption."""
    filepath = Path(filepath)
    with tempfile.NamedTemporaryFile(
        mode="w", dir=filepath.parent, delete=False,
        suffix=".tmp", encoding="utf-8",
    ) as tmp:
        json.dump(data, tmp, indent=2, ensure_ascii=ensure_ascii)
        tmp.write("\n")
        tmp_path = Path(tmp.name)
    os.replace(str(tmp_path), str(filepath))


PARAMS_DIR = Path(__file__).parent.parent / "params"

# ---------------------------------------------------------------------------
# Colour inference
# ---------------------------------------------------------------------------

BRICK_COLOURS = {
    "red": "#B85A3A",
    "red-orange": "#C4603A",
    "dark red": "#8B3A2A",
    "brown": "#7A5C44",
    "buff": "#D4B896",
    "yellow": "#C8B060",
    "cream": "#E8D8B0",
    "orange": "#C87040",
    "grey": "#8A8A8A",
    "gray": "#8A8A8A",
    "white": "#E8E0D4",
    "painted": "#D8D0C0",
    "concrete": "#A8A8A8",
    "stone": "#C8B898",
    "metal": "#7A7A7A",
    "glass": "#A0C0D0",
}

TRIM_COLOURS_BY_ERA = {
    "pre-1889": "#3A2A20",      # dark brown wood
    "1889-1903": "#3A2A20",
    "1904-1913": "#2A2A2A",     # near-black
    "1914-1930": "#4A4A4A",     # dark grey
    "1931-1949": "#F0EDE8",     # cream/white
    "default": "#E8E0D0",
}

ROOF_COLOURS = {
    "grey": "#5A5A5A",
    "gray": "#5A5A5A",
    "dark grey": "#3A3A3A",
    "black": "#2A2A2A",
    "slate": "#4A5A5A",
    "dark slate": "#3A4A4A",
    "brown": "#6A5040",
    "red": "#8A3A2A",
    "green": "#3A5A3A",
    "asphalt": "#5A5A5A",
}


def infer_facade_hex(material_str):
    """Infer facade hex from material description."""
    if not material_str:
        return None
    m = material_str.lower()
    # Check explicit colour/material keywords first
    for key, hex_val in BRICK_COLOURS.items():
        if key in m:
            return hex_val
    
    if "brick" in m:
        return "#B85A3A"  # default red brick
    if "stucco" in m or "render" in m:
        return "#D8D0C0"
    if "concrete" in m or "cement" in m:
        return "#A8A8A8"
    if "stone" in m:
        return "#C8B898"
    if "metal" in m:
        return "#7A7A7A"
    if "glass" in m:
        return "#A0C0D0"
        
    return "#B85A3A"


def infer_roof_hex(material_str):
    """Infer roof hex from material description."""
    m = material_str.lower()
    for key, hex_val in ROOF_COLOURS.items():
        if key in m:
            return hex_val
    return "#5A5A5A"


def get_era(params):
    """Extract construction era string."""
    hcd = params.get("hcd_data", {})
    if not isinstance(hcd, dict):
        hcd = {}
    date = hcd.get("construction_date") or params.get("year_built_approx") or ""
    return str(date)


def get_trim_hex(params):
    """Infer trim colour from era."""
    era = get_era(params).lower()
    for key, hex_val in TRIM_COLOURS_BY_ERA.items():
        if key in era:
            return hex_val
    return TRIM_COLOURS_BY_ERA["default"]


# ---------------------------------------------------------------------------
# Typology inference
# ---------------------------------------------------------------------------

def get_typology(params):
    """Extract typology keywords."""
    hcd = params.get("hcd_data", {})
    if not isinstance(hcd, dict):
        hcd = {}
    typ = (hcd.get("typology") or "").lower()
    style = (params.get("overall_style") or "").lower()
    btype = (params.get("building_type") or "").lower()
    return f"{typ} {style} {btype}"


def has_feature(params, *keywords):
    """Check if HCD features mention any keyword."""
    hcd = params.get("hcd_data", {})
    features = hcd.get("building_features", [])
    feat_str = " ".join(str(f) for f in features).lower()
    typ = get_typology(params)
    combined = f"{feat_str} {typ}"
    return any(kw in combined for kw in keywords)


# ---------------------------------------------------------------------------
# Enrichment functions
# ---------------------------------------------------------------------------

def enrich_facade(params):
    """Add facade_colour and facade_detail if missing."""
    mat = params.get("facade_material", "brick")
    if "facade_colour" not in params:
        params["facade_colour"] = mat

    if "facade_detail" not in params or not params["facade_detail"]:
        hex_val = infer_facade_hex(mat)
        bond = "running bond"
        if "flemish" in mat.lower():
            bond = "flemish bond"
        params["facade_detail"] = {
            "brick_colour_hex": hex_val,
            "bond_pattern": bond,
            "mortar_colour": "Light grey",
            "mortar_joint_width_mm": 10,
        }
        # Add trim colour
        params["facade_detail"]["trim_colour_hex"] = get_trim_hex(params)


def enrich_depth(params):
    """Add facade_depth_m if missing."""
    if "facade_depth_m" not in params:
        floors = params.get("floors", 2)
        width = params.get("facade_width_m", 6.0)
        if width is None:
            return params
        # Typical Toronto Victorian: depth ≈ 1.5-2x width
        if width <= 5.0:
            params["facade_depth_m"] = 10.0
        elif width <= 8.0:
            params["facade_depth_m"] = 10.0
        else:
            params["facade_depth_m"] = max(10.0, width * 1.2)


def enrich_windows(params):
    """Add windows_detail from windows_per_floor if missing."""
    if "windows_detail" in params and params["windows_detail"]:
        return

    wpf = params.get("windows_per_floor", [2])
    fh = params.get("floor_heights_m", [3.0])
    width = params.get("facade_width_m", 6.0)
    win_type = params.get("window_type", "Double-hung sash")
    trim_hex = get_trim_hex(params)

    # Infer arch type from HCD features
    arch_type = "flat"
    if has_feature(params, "segmental"):
        arch_type = "segmental"
    elif has_feature(params, "round arch", "semicircular"):
        arch_type = "round"
    elif has_feature(params, "pointed", "gothic"):
        arch_type = "pointed"

    floor_names = ["Ground floor", "Second floor", "Third floor", "Attic / gable"]
    details = []
    for i, count in enumerate(wpf):
        if count <= 0:
            continue
        floor_h = fh[i] if i < len(fh) else 2.8
        # Window sizing: height ≈ 45% of floor height, width from facade
        win_h = round(floor_h * 0.45, 1)
        win_w = round(min(0.9, (width * 0.7) / max(count, 1)), 1)

        # Attic windows are smaller
        if i >= params.get("floors", 2):
            win_h = 0.6
            win_w = 0.5

        # Sill height: ~35% up the floor
        sill_h = round(floor_h * 0.35, 1)
        if i == 0:
            sill_h = round(floor_h * 0.3, 1)  # ground floor lower

        floor_label = floor_names[i] if i < len(floor_names) else f"Floor {i+1}"

        win_spec = {
            "floor": floor_label,
            "windows": [{
                "count": count,
                "type": win_type,
                "width_m": win_w,
                "height_m": win_h,
                "sill_height_m": sill_h,
                "frame_colour": trim_hex,
                "glazing": "1-over-1" if "sash" in win_type.lower() else "single pane",
            }]
        }

        # Add arch info if not flat
        if arch_type != "flat" and i < 2:  # arches on lower floors
            win_spec["windows"][0]["arch_type"] = arch_type

        details.append(win_spec)

    params["windows_detail"] = details

    # Also set scalar defaults the generator reads
    if "window_width_m" not in params:
        params["window_width_m"] = 0.85
    if "window_height_m" not in params:
        params["window_height_m"] = 1.3


def enrich_doors(params):
    """Add doors_detail from door_count if missing."""
    if "doors_detail" in params and params["doors_detail"]:
        return

    count = params.get("door_count", 1)
    trim_hex = get_trim_hex(params)
    floor_h = params.get("floor_heights_m", [3.0])
    gh = floor_h[0] if floor_h else 3.0

    details = []
    for i in range(count):
        pos = "center"
        if count == 1:
            # Single door: right side for bay-and-gable, center otherwise
            if has_feature(params, "bay-and-gable", "bay and gable"):
                pos = "right"
        elif i == 0:
            pos = "left"
        else:
            pos = "right"

        door = {
            "id": f"door_{i}",
            "type": "Single-leaf panelled door",
            "position": pos,
            "width_m": 0.85,
            "height_m": round(min(2.1, gh * 0.7), 2),
            "colour_hex": trim_hex,
        }

        # Transom for taller ground floors
        if gh >= 3.2:
            door["transom"] = {
                "present": True,
                "height_m": 0.4,
                "type": "glazed"
            }

        details.append(door)

    params["doors_detail"] = details


def enrich_porch(params):
    """Add porch config if HCD suggests one and it's missing."""
    porch = params.get("porch", {})
    if isinstance(porch, dict) and porch.get("present"):
        # Already has porch — fill in missing details
        width = params.get("facade_width_m", 6.0)
        trim_hex = get_trim_hex(params)
        porch.setdefault("width_m", width)
        porch.setdefault("depth_m", 1.8)
        porch.setdefault("height_m", 2.8)
        porch.setdefault("floor_height_above_grade_m", 0.5)
        porch.setdefault("posts", {
            "count": max(2, int(width / 2.5) + 1),
            "style": "turned" if "victorian" in get_typology(params) else "simple",
            "diameter_m": 0.12,
            "colour_hex": trim_hex,
        })
        porch.setdefault("railing", {
            "present": True,
            "height_m": 0.85,
            "baluster_spacing_m": 0.12,
            "colour_hex": trim_hex,
        })
        porch.setdefault("steps", {
            "count": 3,
            "width_m": min(1.2, width * 0.3),
            "position": "center",
        })
        params["porch"] = porch
        return

    # Infer porch from HCD/typology
    if has_feature(params, "porch", "veranda", "stoop", "covered entry"):
        width = params.get("facade_width_m", 6.0)
        trim_hex = get_trim_hex(params)
        params["porch"] = {
            "present": True,
            "type": "Open front porch",
            "width_m": width,
            "depth_m": 1.8,
            "height_m": 2.8,
            "floor_height_above_grade_m": 0.5,
            "posts": {
                "count": max(2, int(width / 2.5) + 1),
                "style": "turned" if "victorian" in get_typology(params) else "simple",
                "diameter_m": 0.12,
                "colour_hex": trim_hex,
            },
            "railing": {
                "present": True,
                "height_m": 0.85,
                "baluster_spacing_m": 0.12,
                "colour_hex": trim_hex,
            },
            "steps": {
                "count": 3,
                "width_m": min(1.2, width * 0.3),
                "position": "center",
            },
        }


def enrich_storefront(params):
    """Fill in storefront details if has_storefront=true."""
    if not params.get("has_storefront"):
        return
    sf = params.get("storefront", {})
    if isinstance(sf, dict) and sf.get("width_m"):
        return  # already populated

    width = params.get("facade_width_m", 6.0)
    fh = params.get("floor_heights_m", [3.0])
    gh = fh[0] if fh else 3.0

    params["storefront"] = {
        "width_m": round(width * 0.85, 1),
        "height_m": round(gh * 0.75, 1),
        "bulkhead_height_m": 0.4,
        "glazing": {
            "type": "Plate glass",
            "panel_count": max(2, int(width / 2.0)),
            "frame_colour_hex": "#2A2A2A",
        },
        "recessed_entry": has_feature(params, "recessed"),
    }


def enrich_bay_window(params):
    """Fill in bay window details if present but sparse."""
    bw = params.get("bay_window", {})
    if not isinstance(bw, dict) or not bw.get("present", False):
        # Check typology for bay-and-gable
        if has_feature(params, "bay-and-gable", "bay and gable", "projecting bay"):
            width = params.get("facade_width_m", 5.0)
            params["bay_window"] = {
                "present": True,
                "type": "Three-sided projecting bay",
                "width_m": round(width * 0.4, 1),
                "projection_m": 0.6,
                "floors": [0, 1],
            }
        return

    # Fill in missing details on existing bay
    width = params.get("facade_width_m", 5.0)
    bw.setdefault("width_m", round(width * 0.4, 1))
    bw.setdefault("projection_m", 0.6)
    bw.setdefault("floors", [0, 1])
    bw.setdefault("type", "Three-sided projecting bay")
    params["bay_window"] = bw


def enrich_decorative(params):
    """Populate decorative_elements from HCD features."""
    dec = params.get("decorative_elements", {})
    if not isinstance(dec, dict):
        dec = {}

    trim_hex = get_trim_hex(params)
    facade_hex = infer_facade_hex(params.get("facade_material", "brick"))

    # String courses
    if "string_courses" not in dec and has_feature(params, "string course", "horizontal band", "belt course"):
        dec["string_courses"] = {
            "colour_hex": "#D4C9A8",
            "height_mm": 80,
            "projection_mm": 25,
            "count": 1,
        }

    # Cornice
    if "cornice" not in dec and has_feature(params, "cornice", "ornament"):
        dec["cornice"] = {
            "height_mm": 300,
            "projection_mm": 180,
            "colour_hex": "#D4C9A8",
        }

    # Brackets
    if "brackets" not in dec and has_feature(params, "bracket", "corbel"):
        dec["brackets"] = {
            "spacing_m": 0.6,
            "depth_mm": 120,
            "colour_hex": trim_hex,
        }

    # Quoins
    if "quoins" not in dec and has_feature(params, "quoin", "corner pilaster"):
        dec["quoins"] = {
            "colour_hex": "#D4C9A8",
            "width_mm": 200,
            "spacing_m": 0.4,
        }

    # Bargeboard for gable buildings
    roof = (params.get("roof_type") or "").lower()
    if "bargeboard" not in dec and "gable" in roof:
        dec["bargeboard"] = {
            "colour_hex": trim_hex,
            "style": "decorative" if has_feature(params, "decorative", "fretwork") else "simple",
        }

    # Voussoirs / window hoods
    if "window_hoods" not in dec and has_feature(params, "voussoir", "arched opening", "segmental"):
        arch_type = "segmental"
        if has_feature(params, "round"):
            arch_type = "round"
        elif has_feature(params, "flat"):
            arch_type = "flat"
        dec["window_hoods"] = {
            "arch_type": arch_type,
            "colour_hex": facade_hex,
        }

    # Bay window shape (if bay exists)
    bw = params.get("bay_window", {})
    if isinstance(bw, dict) and bw.get("present"):
        dec.setdefault("bay_window_shape", "canted")
        dec.setdefault("bay_window_storeys", len(bw.get("floors", [0, 1])))

    params["decorative_elements"] = dec


def enrich_roof(params):
    """Add roof colour and detail if missing."""
    mat = params.get("roof_material") or "Grey asphalt shingles"
    if "roof_colour" not in params:
        params["roof_colour"] = infer_roof_hex(mat)

    if "roof_detail" not in params:
        params["roof_detail"] = {
            "eave_overhang_mm": 300,
        }

    roof = (params.get("roof_type") or "").lower()
    if "flat" in roof and "parapet_height_m" not in params:
        params["parapet_height_m"] = 0.6


def enrich_chimneys(params):
    """Add chimney for pre-1930 residential buildings."""
    if "chimneys" in params:
        return
    era = get_era(params).lower()
    typ = get_typology(params)
    if any(kw in typ for kw in ["institutional", "commercial", "modern"]):
        return
    if "1931" in era or "1949" in era:
        return
    # Most pre-1930 Toronto houses had chimneys
    if any(kw in era for kw in ["pre-1889", "1889", "1904", "1914"]):
        width = params.get("facade_width_m", 6.0)
        params["chimneys"] = {
            "count": 1,
            "position": "right_rear",
            "width_m": 0.6,
            "depth_m": 0.4,
            "height_above_ridge_m": 0.8,
            "material": "brick",
            "colour_hex": infer_facade_hex(params.get("facade_material", "brick")),
        }


def enrich_party_walls(params):
    """Infer party walls from lots_sharing_footprint and typology."""
    if "party_wall_left" in params and "party_wall_right" in params:
        return

    site = params.get("site", {})
    sharing = site.get("lots_sharing_footprint", 1) if isinstance(site, dict) else 1
    sharing = sharing or 1  # handle None
    typ = get_typology(params)

    if sharing >= 2 or "row" in typ:
        # Row house or shared footprint — party walls on both sides
        params.setdefault("party_wall_left", True)
        params.setdefault("party_wall_right", True)
    elif "semi-detached" in typ or "semi detached" in typ:
        # Semi-detached — one party wall
        params.setdefault("party_wall_left", True)
        params.setdefault("party_wall_right", False)
    elif "detached" in typ:
        params.setdefault("party_wall_left", False)
        params.setdefault("party_wall_right", False)
    else:
        # Default: assume row for Kensington Market
        if sharing >= 2:
            params.setdefault("party_wall_left", True)
            params.setdefault("party_wall_right", True)
        else:
            params.setdefault("party_wall_left", False)
            params.setdefault("party_wall_right", False)


def enrich_setback(params):
    """Ensure setback is numeric from site data."""
    if "street_setback_m" in params:
        return

    site = params.get("site", {})
    if isinstance(site, dict) and "setback_m" in site:
        params["street_setback_m"] = site["setback_m"]
    else:
        # Default for Kensington: small front garden
        params["street_setback_m"] = 2.0


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def enrich_file(filepath):
    """Enrich a single param JSON file by filling missing fields."""
    with open(filepath, encoding="utf-8") as f:
        params = json.load(f)

    # Skip files that were explicitly marked as skipped (non-building photos)
    if params.get("skipped"):
        return False, "non-building (skipped)"

    # Check _meta.enriched flag for idempotency
    meta = params.get("_meta", {})
    if meta.get("enriched"):
        return False, "already enriched"
    
    # Store initial state for change detection (if no _meta.enriched flag is present)
    orig_params_dump = json.dumps(params, indent=2, ensure_ascii=False)

    enrichments_applied = []

    # Run all enrichments (only if the field is missing or requires initial setup)
    if "party_wall_left" not in params or "party_wall_right" not in params:
        enrich_party_walls(params)
        enrichments_applied.append("party_walls")
    if "facade_depth_m" not in params:
        enrich_depth(params)
        enrichments_applied.append("depth")
    if "facade_detail" not in params or not params.get("facade_detail"):
        enrich_facade(params)
        enrichments_applied.append("facade")
    if "roof_colour" not in params or "roof_detail" not in params or (params.get("roof_type","").lower() == "flat" and "parapet_height_m" not in params):
        enrich_roof(params)
        enrichments_applied.append("roof")
    if "windows_detail" not in params or not params.get("windows_detail"):
        enrich_windows(params)
        enrichments_applied.append("windows")
    if "doors_detail" not in params or not params.get("doors_detail"):
        enrich_doors(params)
        enrichments_applied.append("doors")
    if "porch" not in params or (isinstance(params.get("porch"), dict) and not params["porch"].get("present")):
        enrich_porch(params)
        enrichments_applied.append("porch")
    if params.get("has_storefront") and ("storefront" not in params or not params.get("storefront")):
        enrich_storefront(params)
        enrichments_applied.append("storefront")
    if "bay_window" not in params or (isinstance(params.get("bay_window"), dict) and not params["bay_window"].get("present")):
        enrich_bay_window(params)
        enrichments_applied.append("bay_window")
    if not params.get("decorative_elements"): # check if it's an empty dict or missing
        enrich_decorative(params)
        if params.get("decorative_elements") and len(params["decorative_elements"]) > 0:
            enrichments_applied.append("decorative")
    if "chimneys" not in params: # This enrichment adds a full dict, so check for absence
        enrich_chimneys(params)
        if "chimneys" in params and isinstance(params["chimneys"], dict):
            enrichments_applied.append("chimneys")
    if "street_setback_m" not in params:
        enrich_setback(params)
        enrichments_applied.append("setback")

    # After all enrichments, check if the object has actually changed
    new_params_dump = json.dumps(params, indent=2, ensure_ascii=False)

    if orig_params_dump == new_params_dump:
        return False, "no changes needed"

    # Update metadata
    source = meta.get("source", meta.get("agent", ""))
    if source in ("hcd_plan_only", "hcd_plan_skeleton"):
        params["confidence"] = min(0.6, params.get("confidence", 0.4) + 0.15)
    else:
        # Agent/photo-analyzed files already have higher confidence; smaller bump
        params["confidence"] = min(0.9, params.get("confidence", 0.6) + 0.05)
    
    meta["enriched"] = True
    meta["enrichment_source"] = "enrich_skeletons.py (typology-driven defaults)"
    meta["enrichments_applied"] = enrichments_applied # Store what was applied
    params["_meta"] = meta

    _atomic_write_json(filepath, params)

    return True, ", ".join(enrichments_applied) if enrichments_applied else "minor adjustments"


def main():
    files = sorted(PARAMS_DIR.glob("*.json"))
    files = [f for f in files if not f.name.startswith("_")]

    enriched_count = 0
    skipped_count = 0
    no_changes_needed_count = 0 # Track files that were not enriched but also not explicitly skipped

    for f in files:
        changed, msg = enrich_file(f)
        if changed:
            enriched_count += 1
            print(f"  [ENRICHED] {f.name}: {msg}")
        elif msg == "non-building (skipped)":
            skipped_count += 1
        elif msg == "already enriched":
            skipped_count += 1 # Count as skipped if already enriched via flag
        else: # "no changes needed"
            no_changes_needed_count += 1

    print(f"\nDone: {enriched_count} enriched, {no_changes_needed_count} unchanged, {skipped_count} skipped (of {len(files)} total)")


if __name__ == "__main__":
    main()
