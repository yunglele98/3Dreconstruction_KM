"""Merge deep Baldwin St facade analysis into param files, then promote to generator fields.

Combines merge + promote steps in one pass.
"""

import json
import re
import sys
from pathlib import Path

# Reuse the promote functions
sys.path.insert(0, str(Path(__file__).parent))
from promote_deep_to_generator import (
    promote_roof, promote_floor_heights, promote_windows,
    promote_facade, promote_decorative, promote_storefront,
    promote_depth, promote_doors, load_db_geometry
)

PARAMS_DIR = Path(__file__).resolve().parent.parent / "params"
DOCS_DIR = Path(__file__).resolve().parent.parent / "docs"


def normalize_address(addr):
    if not addr:
        return ""
    addr = addr.strip()
    addr = re.sub(r'\s*\(.*?\)', '', addr)
    if '/' in addr:
        addr = addr.split('/')[0].strip()
    return addr.strip()


def find_param_file(address):
    if not address:
        return None
    fname = address.replace(" ", "_") + ".json"
    p = PARAMS_DIR / fname
    if p.exists():
        return p
    for f in PARAMS_DIR.iterdir():
        if f.name.lower() == fname.lower():
            return f
    prefix = address.replace(" ", "_")
    for f in PARAMS_DIR.iterdir():
        if f.name.startswith(prefix + "_") and f.suffix == ".json":
            return f
    m = re.match(r"(\d+)-(\d+)\s+(.*)", address)
    if m:
        for num in [m.group(1), m.group(2)]:
            base = f"{num} {m.group(3)}"
            result = find_param_file(base)
            if result:
                return result
    # Try with ~prefix removed
    if address.startswith("~"):
        return find_param_file(address[1:].strip())
    return None


def merge_deep_into_param(param_data, deep_entry):
    """Add deep_facade_analysis section."""
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
    return param_data


def main():
    # Load all 3 Baldwin batches
    all_entries = []
    for i in range(1, 4):
        path = DOCS_DIR / f"baldwin_st_deep_batch{i}.json"
        with open(path) as f:
            data = json.load(f)
        if isinstance(data, list):
            all_entries.extend(data)
        elif isinstance(data, dict):
            for k, v in data.items():
                if isinstance(v, list):
                    all_entries.extend(v)
                    break
    print(f"Loaded {len(all_entries)} Baldwin St deep analysis entries")

    merged = 0
    promoted = 0
    not_found = []
    skipped = 0
    total_changes = 0

    for entry in all_entries:
        addr_raw = entry.get("address", "")
        addr = normalize_address(addr_raw)

        if not addr or "streetscape" in addr_raw.lower() or "alley" in addr_raw.lower() \
           or "lane" in addr_raw.lower() or "rear" in addr_raw.lower() \
           or "parking" in addr_raw.lower() or "payphone" in addr_raw.lower() \
           or "vacant lot" in addr_raw.lower() or "mural" in addr_raw.lower():
            skipped += 1
            continue

        if not entry.get("facade_material") and not entry.get("storeys"):
            skipped += 1
            continue

        param_file = find_param_file(addr)
        if not param_file:
            not_found.append(addr)
            continue

        try:
            with open(param_file, encoding="utf-8") as f:
                param_data = json.load(f)

            if param_data.get("skipped"):
                skipped += 1
                continue

            # Step 1: Merge deep analysis
            param_data = merge_deep_into_param(param_data, entry)
            merged += 1

            # Step 2: Promote to generator fields
            deep = param_data["deep_facade_analysis"]
            changes = []
            changes.extend(promote_roof(param_data, deep))
            changes.extend(promote_floor_heights(param_data, deep))
            changes.extend(promote_windows(param_data, deep))
            changes.extend(promote_facade(param_data, deep))
            changes.extend(promote_decorative(param_data, deep))
            changes.extend(promote_storefront(param_data, deep))
            changes.extend(promote_depth(param_data, deep))
            changes.extend(promote_doors(param_data, deep))

            if changes:
                meta = param_data.get("_meta", {})
                meta["deep_facade_analysis_applied"] = True
                meta["geometry_revised"] = True
                meta["geometry_revision_ts"] = "2026-03-26"
                meta["geometry_changes"] = changes
                param_data["_meta"] = meta
                promoted += 1
                total_changes += len(changes)

            with open(param_file, "w", encoding="utf-8") as f:
                json.dump(param_data, f, indent=2, ensure_ascii=False)

            print(f"  + {addr} <- {entry.get('filename', '?')} ({len(changes)} changes)")

        except Exception as e:
            print(f"  X {addr}: {e}")

    print(f"\n{'='*60}")
    print(f"BALDWIN ST MERGE + PROMOTE COMPLETE")
    print(f"  Deep analysis merged: {merged}")
    print(f"  Geometry promoted: {promoted}")
    print(f"  Total field changes: {total_changes}")
    print(f"  Skipped (non-facade): {skipped}")
    print(f"  Not found: {len(not_found)}")
    if not_found:
        for a in not_found:
            print(f"    - {a}")


if __name__ == "__main__":
    main()
