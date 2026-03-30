"""Merge deep facade analysis (batches 1-3) into existing param JSON files.

Rules:
- NEVER overwrite: city_data, _meta dimensions, LiDAR heights, lot dimensions
- UPDATE: photo_observations (add/enrich), decorative_elements, facade_detail,
  bay_window, storefront, doors_detail, colour_palette, condition
- ADD NEW: deep_facade_analysis section with full reconstruction detail
"""

import json
import re
from pathlib import Path

PARAMS_DIR = Path("C:/Users/liam1/blender_buildings/params")
DOCS_DIR = Path("C:/Users/liam1/blender_buildings/docs")

def normalize_address(addr):
    """Normalize address for matching."""
    if not addr:
        return ""
    addr = addr.strip()
    # Remove business names in parens
    addr = re.sub(r'\s*\(.*?\)', '', addr)
    # Remove business names after dash
    addr = re.sub(r'\s*-\s*[A-Z].*$', '', addr)
    # Take first address if multiple separated by /
    if '/' in addr:
        addr = addr.split('/')[0].strip()
    return addr.strip()

def find_param_file(address):
    """Find matching param file for an address."""
    if not address:
        return None

    # Direct match
    fname = address.replace(" ", "_") + ".json"
    p = PARAMS_DIR / fname
    if p.exists():
        return p

    # Case-insensitive
    for f in PARAMS_DIR.iterdir():
        if f.name.lower() == fname.lower():
            return f

    # Prefix match (for files with business names appended)
    prefix = address.replace(" ", "_")
    for f in PARAMS_DIR.iterdir():
        if f.name.startswith(prefix + "_") and f.suffix == ".json":
            return f

    # Range address: try first number
    m = re.match(r"(\d+)-\d+\s+(.*)", address)
    if m:
        base = f"{m.group(1)} {m.group(2)}"
        result = find_param_file(base)
        if result:
            return result
        # Also try the range file with business name
        range_prefix = address.replace(" ", "_")
        for f in PARAMS_DIR.iterdir():
            if f.name.startswith(range_prefix + "_") and f.suffix == ".json":
                return f

    return None

def merge_deep_into_param(param_data, deep_entry):
    """Merge deep analysis data into a param file, respecting protected fields."""

    # 1. Add full deep_facade_analysis section (always overwrite - this is the new data)
    param_data["deep_facade_analysis"] = {
        "source_photo": deep_entry.get("filename"),
        "analysis_pass": "deep_v2",
        "timestamp": "2026-03-26",
        "storeys_observed": deep_entry.get("storeys"),
        "has_half_storey_gable": deep_entry.get("has_half_storey_gable"),
        "floor_height_ratios": deep_entry.get("floor_height_ratios"),
        "facade_material_observed": deep_entry.get("facade_material"),
        "brick_colour_hex": deep_entry.get("brick_colour_hex"),
        "brick_bond_observed": deep_entry.get("brick_bond"),
        "mortar_colour": deep_entry.get("mortar_colour"),
        "polychromatic_brick": deep_entry.get("polychromatic_brick"),
        "windows_detail": deep_entry.get("windows_detail"),
        "doors_observed": deep_entry.get("doors"),
        "roof_type_observed": deep_entry.get("roof_type"),
        "roof_pitch_deg": deep_entry.get("roof_pitch_deg"),
        "roof_material": deep_entry.get("roof_material"),
        "roof_colour_hex": deep_entry.get("roof_colour_hex"),
        "bargeboard": deep_entry.get("bargeboard"),
        "gable_window": deep_entry.get("gable_window"),
        "bay_window_observed": deep_entry.get("bay_window"),
        "storefront_observed": deep_entry.get("storefront"),
        "decorative_elements_observed": deep_entry.get("decorative_elements"),
        "party_wall_left": deep_entry.get("party_wall_left"),
        "party_wall_right": deep_entry.get("party_wall_right"),
        "colour_palette_observed": deep_entry.get("colour_palette"),
        "condition_observed": deep_entry.get("condition"),
        "condition_notes": deep_entry.get("condition_notes"),
        "depth_notes": deep_entry.get("depth_notes"),
    }

    # 2. Enrich facade_detail if present
    fd = param_data.get("facade_detail", {})
    if deep_entry.get("brick_colour_hex") and not fd.get("brick_colour_hex"):
        fd["brick_colour_hex"] = deep_entry["brick_colour_hex"]
    if deep_entry.get("brick_bond") and not fd.get("bond_pattern"):
        fd["bond_pattern"] = deep_entry["brick_bond"]
    if deep_entry.get("mortar_colour") and not fd.get("mortar_colour"):
        fd["mortar_colour"] = deep_entry["mortar_colour"]
    if fd:
        param_data["facade_detail"] = fd

    # 3. Enrich bay_window if deep analysis found one
    bw = deep_entry.get("bay_window")
    if bw and isinstance(bw, dict) and bw.get("present"):
        if not param_data.get("bay_window") or not param_data["bay_window"].get("present"):
            param_data["bay_window"] = {
                "present": True,
                "type": bw.get("type", "canted"),
                "floors": bw.get("floors_spanned", [1, 2]),
                "width_m": bw.get("width_m_est", 2.0),
                "projection_m": bw.get("projection_m_est", 0.6),
            }

    # 4. Enrich decorative_elements
    de_obs = deep_entry.get("decorative_elements")
    if de_obs and isinstance(de_obs, dict):
        de = param_data.get("decorative_elements", {})
        # Add observed elements that aren't already tracked
        if de_obs.get("cornice", {}).get("present") and "cornice" not in de:
            de["cornice"] = de_obs["cornice"]
        if de_obs.get("voussoirs", {}).get("present") and "voussoirs" not in de:
            de["voussoirs"] = de_obs["voussoirs"]
        if de_obs.get("string_courses") and "string_courses" not in de:
            de["string_courses"] = de_obs["string_courses"]
        if de_obs.get("quoins") and "quoins" not in de:
            de["quoins"] = True
        if de_obs.get("dentil_course") and "dentil_course" not in de:
            de["dentil_course"] = True
        if de_obs.get("brackets") and "brackets" not in de:
            de["brackets"] = True
        if de_obs.get("ornamental_shingles_in_gable") and "ornamental_shingles_in_gable" not in de:
            de["ornamental_shingles_in_gable"] = True
        if de:
            param_data["decorative_elements"] = de

    # 5. Enrich storefront
    sf_obs = deep_entry.get("storefront")
    if sf_obs and isinstance(sf_obs, dict):
        sf = param_data.get("storefront", {})
        if sf_obs.get("signage_text") and not sf.get("signage_text"):
            sf["signage_text"] = sf_obs["signage_text"]
        if sf_obs.get("awning") and not sf.get("awning"):
            sf["awning"] = sf_obs["awning"]
        if sf_obs.get("security_grille") and not sf.get("security_grille"):
            sf["security_grille"] = sf_obs["security_grille"]
        if sf_obs.get("width_pct") and not sf.get("width_pct"):
            sf["width_pct"] = sf_obs["width_pct"]
        if sf:
            param_data["storefront"] = sf

    # 6. Update colour_palette if not present
    cp = deep_entry.get("colour_palette")
    if cp and isinstance(cp, dict):
        if not param_data.get("colour_palette"):
            param_data["colour_palette"] = cp

    # 7. Update _meta
    meta = param_data.get("_meta", {})
    meta["deep_facade_analysis_applied"] = True
    meta["deep_facade_analysis_ts"] = "2026-03-26"
    param_data["_meta"] = meta

    return param_data


def main():
    # Load all 3 batches
    all_entries = []
    for i in range(1, 4):
        path = DOCS_DIR / f"kensington_ave_deep_batch{i}.json"
        with open(path) as f:
            data = json.load(f)
        if isinstance(data, list):
            all_entries.extend(data)
        elif isinstance(data, dict):
            for k, v in data.items():
                if isinstance(v, list):
                    all_entries.extend(v)
                    break

    print(f"Loaded {len(all_entries)} deep analysis entries")

    merged = 0
    skipped = 0
    not_found = []
    errors = []

    for entry in all_entries:
        addr_raw = entry.get("address", "")
        addr = normalize_address(addr_raw)

        if not addr or "streetscape" in addr_raw.lower() or "alley" in addr_raw.lower() or "canopy" in addr_raw.lower():
            skipped += 1
            continue

        # Skip entries that are just notes/placeholders
        if entry.get("note") and not entry.get("facade_material"):
            skipped += 1
            continue

        param_file = find_param_file(addr)
        if not param_file:
            not_found.append(addr)
            continue

        try:
            with open(param_file) as f:
                param_data = json.load(f)

            param_data = merge_deep_into_param(param_data, entry)

            with open(param_file, 'w') as f:
                json.dump(param_data, f, indent=2, ensure_ascii=False)

            merged += 1
            print(f"  + {addr} <- {entry.get('filename', '?')}")
        except Exception as e:
            errors.append((addr, str(e)))
            print(f"  X {addr}: {e}")

    print(f"\n{'='*60}")
    print(f"DEEP MERGE COMPLETE")
    print(f"  Merged: {merged}")
    print(f"  Skipped (non-facade/streetscape): {skipped}")
    print(f"  Not found: {len(not_found)}")
    if not_found:
        for a in not_found:
            print(f"    - {a}")
    print(f"  Errors: {len(errors)}")
    if errors:
        for a, e in errors:
            print(f"    - {a}: {e}")

    # Save report
    report = {
        "merged": merged,
        "skipped": skipped,
        "not_found": not_found,
        "errors": [{"address": a, "error": e} for a, e in errors],
    }
    with open(DOCS_DIR / "kensington_ave_deep_merge_report.json", "w") as f:
        json.dump(report, f, indent=2)
    print(f"\nReport: {DOCS_DIR / 'kensington_ave_deep_merge_report.json'}")


if __name__ == "__main__":
    main()
