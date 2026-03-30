#!/usr/bin/env python3
"""Translate agent vision output into generator-compatible param structures.

Agent photo analysis produces flat keys (booleans, strings, counts).
The Blender generator expects structured dicts. This script bridges the gap.

Run FIRST in the enrichment pipeline, before enrich_skeletons.py.

Usage:
    python translate_agent_params.py
"""

import json
import os
import tempfile
from pathlib import Path


def _atomic_write_json(filepath, data, ensure_ascii=True):
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
# Cornice: string → dict
# ---------------------------------------------------------------------------

CORNICE_TEMPLATES = {
    "none": {},
    "simple": {
        "present": True,
        "type": "simple",
        "height_mm": 200,
        "projection_mm": 100,
        "colour_hex": "#D4C9A8",
    },
    "decorative": {
        "present": True,
        "type": "decorative",
        "height_mm": 350,
        "projection_mm": 200,
        "colour_hex": "#D4C9A8",
    },
    "bracketed": {
        "present": True,
        "type": "bracketed",
        "height_mm": 400,
        "projection_mm": 250,
        "brackets": {"spacing_m": 0.5, "depth_mm": 120},
        "colour_hex": "#D4C9A8",
    },
    "dentil": {
        "present": True,
        "type": "dentil",
        "height_mm": 300,
        "projection_mm": 180,
        "dentil_spacing_mm": 60,
        "colour_hex": "#D4C9A8",
    },
}


def translate_cornice(data: dict) -> bool:
    """Convert cornice string to structured dict."""
    cornice = data.get("cornice")
    if not isinstance(cornice, str):
        return False
    template = CORNICE_TEMPLATES.get(cornice.lower(), {})
    if template:
        data["cornice"] = template.copy()
    else:
        data["cornice"] = {
            "present": True,
            "type": cornice,
            "height_mm": 250,
            "projection_mm": 150,
            "colour_hex": "#D4C9A8",
        }
    return True


# ---------------------------------------------------------------------------
# Bay windows: int count → structured dict
# ---------------------------------------------------------------------------

def translate_bay_windows(data: dict) -> bool:
    """Convert bay_windows (int count) to bay_window (structured dict)."""
    count = data.get("bay_windows")
    if not isinstance(count, int) or count <= 0:
        return False
    if "bay_window" in data and isinstance(data["bay_window"], dict):
        return False  # already structured

    width = data.get("facade_width_m", 5.0)
    floors = data.get("floors", 2)

    data["bay_window"] = {
        "present": True,
        "count": count,
        "type": "Three-sided projecting bay",
        "width_m": round(min(2.6, max(1.8, width * 0.4)), 1),
        "projection_m": 0.6,
        "floors": list(range(min(floors, 2))),
    }
    return True


# ---------------------------------------------------------------------------
# Doors: flat fields → doors_detail list
# ---------------------------------------------------------------------------

def translate_doors(data: dict) -> bool:
    """Convert door_count/type/width/height to doors_detail list."""
    if "doors_detail" in data and data["doors_detail"]:
        return False

    count = data.get("door_count")
    if not isinstance(count, int) or count <= 0:
        return False

    door_type = data.get("door_type", "single")
    door_w = data.get("door_width_m", 0.85)
    door_h = data.get("door_height_m", 2.1)

    # Map agent door type strings to descriptive types
    type_map = {
        "single": "Single-leaf panelled door",
        "double": "Double-leaf panelled door",
        "storefront": "Commercial storefront door",
        "recessed": "Recessed entry door",
        "arched": "Arched-head door",
    }
    door_type_str = type_map.get(door_type.lower(), door_type) if isinstance(door_type, str) else "Single-leaf panelled door"

    details = []
    for i in range(count):
        if count == 1:
            pos = "center"
        elif i == 0:
            pos = "left"
        else:
            pos = "right"

        door = {
            "id": f"door_{i}",
            "type": door_type_str,
            "position": pos,
            "width_m": door_w,
            "height_m": door_h,
        }

        # Add transom for taller ground floors
        floor_heights = data.get("floor_heights_m", [3.0])
        gh = floor_heights[0] if floor_heights else 3.0
        if gh >= 3.2:
            door["transom"] = {
                "present": True,
                "height_m": 0.4,
                "type": "glazed",
            }

        details.append(door)

    data["doors_detail"] = details
    return True


# ---------------------------------------------------------------------------
# Decorative booleans → decorative_elements dict entries
# ---------------------------------------------------------------------------

DECORATIVE_BOOLEAN_MAP = {
    "quoins": {
        "present": True,
        "strip_width_mm": 200,
        "projection_mm": 15,
        "colour_hex": "#D4C9A8",
    },
    "pilasters": {
        "present": True,
        "width_mm": 180,
        "projection_mm": 40,
        "colour_hex": "#D4C9A8",
    },
    "string_course": {
        "present": True,
        "width_mm": 140,
        "projection_mm": 25,
        "colour_hex": "#D4C9A8",
    },
    "decorative_lintels": {
        "present": True,
        "arch_type": "flat",
        "colour_hex": "#D4C9A8",
    },
}

# Agent key → decorative_elements sub-key
DECORATIVE_KEY_REMAP = {
    "string_course": "string_courses",
    "decorative_lintels": "window_hoods",
    "quoins": "quoins",
    "pilasters": "pilasters",
}


def translate_decorative_booleans(data: dict) -> bool:
    """Promote top-level boolean decorative flags into decorative_elements dict."""
    dec = data.get("decorative_elements", {})
    if not isinstance(dec, dict):
        dec = {}

    changed = False
    for agent_key, template in DECORATIVE_BOOLEAN_MAP.items():
        value = data.get(agent_key)
        if value is True:
            target_key = DECORATIVE_KEY_REMAP.get(agent_key, agent_key)
            if target_key not in dec:
                dec[target_key] = template.copy()
                changed = True

    if changed:
        data["decorative_elements"] = dec
    return changed


# ---------------------------------------------------------------------------
# Storefront: description → structured dict
# ---------------------------------------------------------------------------

def translate_storefront(data: dict) -> bool:
    """Convert storefront_description to structured storefront dict."""
    if not data.get("has_storefront"):
        return False
    if "storefront" in data and isinstance(data["storefront"], dict):
        return False

    width = data.get("facade_width_m", 6.0)
    floor_heights = data.get("floor_heights_m", [3.5])
    gh = floor_heights[0] if floor_heights else 3.5
    desc = data.get("storefront_description", "")

    recessed = False
    if isinstance(desc, str) and "recess" in desc.lower():
        recessed = True

    data["storefront"] = {
        "type": "Commercial ground floor",
        "width_m": round(width * 0.85, 1),
        "height_m": round(gh * 0.75, 1),
        "bulkhead_height_m": 0.4,
        "glazing": {
            "type": "Plate glass",
            "panel_count": max(2, int(width / 2.0)),
            "frame_colour_hex": "#2A2A2A",
        },
        "recessed_entry": recessed,
        "description": desc if desc else None,
    }
    return True


# ---------------------------------------------------------------------------
# Balconies: agent fields → structured (future-proofing)
# ---------------------------------------------------------------------------

def translate_balconies(data: dict) -> bool:
    """Convert balconies/balcony_type to structured dict."""
    count = data.get("balconies")
    if not isinstance(count, int) or count <= 0:
        return False
    if "balcony_detail" in data:
        return False

    btype = data.get("balcony_type", "juliet")
    type_map = {
        "none": None,
        "juliet": {"type": "juliet", "width_m": 1.2, "railing_height_m": 1.0},
        "projecting": {"type": "projecting", "width_m": 2.0, "depth_m": 1.2, "railing_height_m": 1.0},
        "recessed": {"type": "recessed", "width_m": 2.0, "depth_m": 1.5, "railing_height_m": 1.0},
    }

    template = type_map.get(btype.lower() if isinstance(btype, str) else "juliet")
    if template is None:
        return False

    template["count"] = count
    data["balcony_detail"] = template
    return True


# ---------------------------------------------------------------------------
# Overall style → useful downstream hints
# ---------------------------------------------------------------------------

def translate_style_hints(data: dict) -> bool:
    """Propagate overall_style into fields enrichment scripts can use."""
    style = data.get("overall_style", "")
    if not isinstance(style, str) or not style:
        return False

    changed = False

    # Ensure building_type exists for typology inference
    if "building_type" not in data:
        style_lower = style.lower()
        if "commercial" in style_lower:
            data["building_type"] = "commercial"
        elif "industrial" in style_lower:
            data["building_type"] = "industrial"
        elif "victorian" in style_lower or "edwardian" in style_lower:
            data["building_type"] = "residential"
        changed = True

    return changed


# ---------------------------------------------------------------------------
# Flatten photo_observations into top-level fields
# ---------------------------------------------------------------------------

# Fields in photo_observations that should promote to top-level
PROMOTE_FIELDS = {
    "facade_colour_observed": "facade_colour",
    "windows_per_floor": "windows_per_floor",
    "window_type": "window_type",
    "window_width_m": "window_width_m",
    "window_height_m": "window_height_m",
    "window_arrangement": "window_arrangement",
    "door_count": "door_count",
    "door_type": "door_type",
    "door_width_m": "door_width_m",
    "door_height_m": "door_height_m",
    "cornice": "cornice",
    "bay_windows": "bay_windows",
    "balconies": "balconies",
    "balcony_type": "balcony_type",
    "quoins": "quoins",
    "pilasters": "pilasters",
    "string_course": "string_course",
    "decorative_lintels": "decorative_lintels",
    "overall_style": "overall_style",
    "roof_type_observed": "roof_type",
    "roof_features": "roof_features",
    "has_storefront_observed": "has_storefront",
    "storefront_description": "storefront_description",
    "confidence": "confidence",
    "notes": "notes",
    "condition": "condition",
    "facade_material_observed": "facade_material",
    "porch_present": "porch_present",
    "porch_type": "porch_type",
    "chimneys": "chimney_count",
    "ground_floor_arches": "ground_floor_arch_type",
    "ground_floor_arch_count": "ground_floor_arch_count",
}

# Fields from photo_observations that should NEVER overwrite DB values
PROTECTED_FIELDS = {
    "total_height_m", "facade_width_m", "facade_depth_m",
}


def flatten_photo_observations(data: dict) -> bool:
    """Promote photo_observations fields to top-level for downstream processing."""
    obs = data.get("photo_observations")
    if not isinstance(obs, dict):
        return False

    changed = False
    for obs_key, target_key in PROMOTE_FIELDS.items():
        if obs_key not in obs:
            continue
        value = obs[obs_key]
        if value is None:
            continue
        if target_key in PROTECTED_FIELDS:
            continue

        # Photo observations (March 2026) take priority for visual fields
        # but don't overwrite DB-sourced structural data
        source = data.get("_meta", {}).get("source", "")
        if source == "postgis_export" and target_key in data:
            # Skip keys that DB already has real data for (non-visual)
            non_visual_db_keys = {"floors", "has_storefront", "roof_type"}
            if target_key in non_visual_db_keys:
                continue
        data[target_key] = value
        changed = True

    return changed


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def translate_file(filepath: Path) -> tuple[bool, str]:
    """Translate a single agent-output param file."""
    with open(filepath, encoding="utf-8") as f:
        data = json.load(f)

    # Skip non-building and already-translated files
    if data.get("skipped"):
        return False, "non-building (skipped)"

    meta = data.get("_meta", {})
    if meta.get("translated"):
        return False, "already translated"

    orig = json.dumps(data)

    translations = []

    # First: flatten photo_observations into top-level fields
    if flatten_photo_observations(data):
        translations.append("photo_obs")

    # Then: translate flat fields to structured dicts
    if translate_cornice(data):
        translations.append("cornice")
    if translate_bay_windows(data):
        translations.append("bay_window")
    if translate_doors(data):
        translations.append("doors_detail")
    if translate_decorative_booleans(data):
        translations.append("decorative")
    if translate_storefront(data):
        translations.append("storefront")
    if translate_balconies(data):
        translations.append("balcony")
    if translate_style_hints(data):
        translations.append("style_hints")

    if not translations:
        return False, "no translations needed"

    meta["translated"] = True
    meta["translations_applied"] = translations
    data["_meta"] = meta

    _atomic_write_json(filepath, data)

    return True, ", ".join(translations)


def main():
    files = sorted(PARAMS_DIR.glob("*.json"))
    files = [f for f in files if not f.name.startswith("_")]

    translated = 0
    skipped = 0
    for f in files:
        changed, msg = translate_file(f)
        if changed:
            translated += 1
            print(f"  [TRANSLATED] {f.name}: {msg}")
        else:
            skipped += 1

    print(f"\nDone: {translated} translated, {skipped} skipped (of {len(files)} total)")


if __name__ == "__main__":
    main()
