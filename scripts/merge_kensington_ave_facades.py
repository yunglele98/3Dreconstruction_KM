"""
Merge Kensington Ave facade analysis into param files.

Reads docs/kensington_ave_facade_analysis.json (from photo analysis)
and docs/kensington_ave_db_data.json (from PostGIS), then merges
visual observations into the corresponding params/*.json files.

Rules (from CLAUDE.md / AGENT_PROMPT.md):
  NEVER overwrite: total_height_m, facade_width_m, facade_depth_m, site.*, city_data.*, hcd_data.*
  ALWAYS update: facade_colour, windows_per_floor, window_type, door_count, condition,
                 roof_features, chimneys, porch_present, cornice, bay_windows
  Update only if clearly different: facade_material, roof_type, has_storefront, floors
  Results go into photo_observations nested dict
"""

import csv
import json
import re
import sys
from datetime import datetime
from pathlib import Path

PARAMS_DIR = Path(__file__).resolve().parent.parent / "params"
DOCS_DIR = Path(__file__).resolve().parent.parent / "docs"
PHOTO_INDEX = Path(__file__).resolve().parent.parent / "PHOTOS KENSINGTON" / "csv" / "photo_address_index.csv"
FACADE_ANALYSIS = DOCS_DIR / "kensington_ave_facade_analysis.json"
DB_DATA = DOCS_DIR / "kensington_ave_db_data.json"

TIMESTAMP = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

# Hex colour map for common descriptions
COLOUR_HEX = {
    "red": "#B85A3A", "red-brown": "#B85A3A", "warm red": "#B85A3A",
    "buff": "#D4B896", "yellow": "#D4B896", "cream": "#E8D8B0",
    "brown": "#7A5C44", "dark brown": "#5A3A2A",
    "orange": "#C87040", "grey": "#8A8A8A", "gray": "#8A8A8A",
    "white": "#F0EDE8", "blue": "#4A6A8A", "green": "#4A6A4A",
    "pink": "#C87080", "magenta": "#A04060",
    "grey-blue": "#6A7A8A", "blue-grey": "#6A7A8A",
    "dark grey": "#5A5A5A", "olive": "#6A6A3A",
}


def load_photo_index():
    """Load photo_address_index.csv → {filename: address_string}."""
    index = {}
    with open(PHOTO_INDEX, encoding="utf-8") as f:
        reader = csv.reader(f)
        for row in reader:
            if len(row) >= 2:
                index[row[0].strip()] = row[1].strip()
    return index


def parse_address_from_csv(csv_address):
    """Extract the primary street number + street from CSV address field.

    Examples:
      '10 Kensington Ave (Urban Catwalk)' → '10 Kensington Ave'
      '2a Kensington Ave (El Rey Mezcal Bar)' → '2a Kensington Ave'
      '54-56 Kensington Ave (...)' → '54-56 Kensington Ave'
      '7 Kensington Ave (Dreamland) / 5-3 Kensington...' → '7 Kensington Ave'
    """
    if "Kensington Ave" not in csv_address:
        return None
    # Take first address before any '/'
    first = csv_address.split("/")[0].strip()
    # Extract number + street
    m = re.match(r"(\d+[a-zA-Z]?(?:-\d+)?)\s+(Kensington Ave)", first)
    if m:
        return f"{m.group(1)} Kensington Ave"
    return None


def find_param_file(address):
    """Find the param JSON file for a given address like '10 Kensington Ave'."""
    if not address:
        return None
    # Normalize: '10 Kensington Ave' → '10_Kensington_Ave.json'
    fname = address.replace(" ", "_") + ".json"
    path = PARAMS_DIR / fname
    if path.exists():
        return path
    # Try case-insensitive search
    fname_lower = fname.lower()
    for p in PARAMS_DIR.iterdir():
        if p.name.lower() == fname_lower:
            return p
    # Try prefix match for agent-created files with business names appended
    prefix = address.replace(" ", "_")
    for p in PARAMS_DIR.iterdir():
        if p.name.startswith(prefix + "_") and p.suffix == ".json":
            return p
    # Try first number of range for base param file
    m = re.match(r"(\d+)-\d+\s+(.*)", address)
    if m:
        base_addr = f"{m.group(1)} {m.group(2)}"
        base_path = PARAMS_DIR / (base_addr.replace(" ", "_") + ".json")
        if base_path.exists():
            return base_path
    return None


def extract_brick_hex(brick_colour_str):
    """Convert a brick colour description to hex."""
    if not brick_colour_str:
        return None
    s = brick_colour_str.lower()
    # Check for explicit hex
    m = re.search(r"#[0-9a-fA-F]{6}", brick_colour_str)
    if m:
        return m.group(0)
    # Match against known colours
    for key, hex_val in COLOUR_HEX.items():
        if key in s:
            return hex_val
    return None


def merge_facade_into_params(param_path, facade, photo_filename, csv_address):
    """Merge a single facade analysis entry into a param file."""
    with open(param_path, encoding="utf-8") as f:
        params = json.load(f)

    if params.get("skipped"):
        return False, "skipped entry"

    changed = False

    # --- photo_observations (always safe to update) ---
    obs = params.get("photo_observations", {})
    if not isinstance(obs, dict):
        obs = {}

    obs["facade_analysis_agent"] = "claude-opus-4-6-facade-analysis"
    obs["facade_analysis_timestamp"] = TIMESTAMP
    obs["facade_analysis_photo"] = photo_filename
    obs["facade_analysis_address"] = csv_address

    # Storeys
    storeys = facade.get("storeys")
    if storeys and storeys != "N/A":
        if isinstance(storeys, str):
            m = re.match(r"(\d+)", storeys)
            if m:
                obs["storeys_observed"] = int(m.group(1))
        elif isinstance(storeys, (int, float)):
            obs["storeys_observed"] = int(storeys)

    # Facade material
    mat = facade.get("facade_material")
    if mat and mat != "N/A":
        obs["facade_material_observed"] = mat

    # Brick colour
    brick = facade.get("brick_colour")
    if brick and brick != "N/A":
        obs["brick_colour_observed"] = brick
        hex_val = extract_brick_hex(brick)
        if hex_val:
            obs["brick_colour_hex_observed"] = hex_val

    # Condition
    cond = facade.get("condition")
    if cond:
        obs["condition_observed"] = cond

    # Windows
    windows = facade.get("windows", {})
    if isinstance(windows, dict):
        obs["windows_observed"] = windows

    # Doors
    doors = facade.get("doors")
    if doors and doors != "N/A":
        obs["doors_observed"] = doors

    # Roof
    roof = facade.get("roof_type")
    if roof and roof != "N/A":
        obs["roof_type_observed"] = roof

    # Decorative elements
    dec = facade.get("decorative_elements")
    if dec and dec != "N/A" and dec != "none" and dec != "minimal":
        obs["decorative_elements_observed"] = dec

    # Storefront
    sf = facade.get("storefront_details")
    if sf and sf != "N/A":
        obs["storefront_description"] = sf

    # Signage
    sig = facade.get("signage")
    if sig and sig != "N/A":
        obs["signage_observed"] = sig

    # Party walls
    pw = facade.get("party_walls")
    if pw:
        obs["party_walls_observed"] = pw

    # Colour palette from analysis
    cp = facade.get("colour_palette", {})
    if isinstance(cp, dict) and cp:
        obs["colour_palette_observed"] = cp

    # Bond pattern
    bond = facade.get("bond_pattern")
    if bond and bond != "N/A":
        obs["bond_pattern_observed"] = bond

    # Photo quality note
    pq = facade.get("photo_quality")
    if pq:
        obs["photo_quality"] = pq

    params["photo_observations"] = obs
    changed = True

    # --- Update ALWAYS-update fields (only if photo data is better than what exists) ---

    # facade_colour: always update from photo if we have a good observation
    facade_colour = facade.get("brick_colour") or facade.get("facade_material")
    if facade_colour and facade_colour != "N/A":
        colour_parts = []
        if facade.get("brick_colour") and facade["brick_colour"] != "N/A":
            colour_parts.append(facade["brick_colour"])
        if facade.get("facade_material") and facade["facade_material"] != "N/A":
            colour_parts.append(facade["facade_material"])
        combined = "; ".join(colour_parts)
        if combined and combined != params.get("facade_colour"):
            params["facade_colour"] = combined
            changed = True

    # condition: update if observed
    if cond and "good" in cond.lower():
        params["condition"] = "good"
    elif cond and "poor" in cond.lower():
        params["condition"] = "poor"
    elif cond and "fair" in cond.lower():
        params["condition"] = "fair"

    # brick_colour_hex in facade_detail
    brick_hex = extract_brick_hex(facade.get("brick_colour", ""))
    if brick_hex:
        fd = params.get("facade_detail", {})
        if not isinstance(fd, dict):
            fd = {}
        if not fd.get("brick_colour_hex"):
            fd["brick_colour_hex"] = brick_hex
            params["facade_detail"] = fd
            changed = True

    # bond_pattern in facade_detail
    if bond and bond != "N/A":
        fd = params.get("facade_detail", {})
        if not isinstance(fd, dict):
            fd = {}
        if not fd.get("bond_pattern"):
            fd["bond_pattern"] = bond
            params["facade_detail"] = fd
            changed = True

    # decorative_elements: merge observed into existing
    if dec and dec != "N/A" and dec != "none" and dec != "minimal":
        de = params.get("decorative_elements", {})
        if not isinstance(de, dict):
            de = {}
        dec_lower = dec.lower()
        if "bargeboard" in dec_lower and "bargeboard" not in de:
            de["bargeboard"] = {"colour_hex": params.get("colour_palette", {}).get("trim", "#F0EDE8"), "style": "decorative"}
            changed = True
        if "string course" in dec_lower and "string_courses" not in de:
            de["string_courses"] = {"present": True}
            changed = True
        if "bay window" in dec_lower and "bay_window_shape" not in de:
            de["bay_window_shape"] = "canted"
            de["bay_window_storeys"] = 1
            changed = True
        if "cornice" in dec_lower and "cornice" not in de:
            de["cornice"] = {"present": True}
            changed = True
        if "quoin" in dec_lower and "quoins" not in de:
            de["quoins"] = {"present": True}
            changed = True
        if de:
            params["decorative_elements"] = de

    # --- Update _meta ---
    meta = params.get("_meta", {})
    if not isinstance(meta, dict):
        meta = {}
    facade_analysis = meta.get("facade_analysis_applied", [])
    facade_analysis.append(f"kensington_ave_facades_{TIMESTAMP}")
    meta["facade_analysis_applied"] = facade_analysis
    params["_meta"] = meta

    # Write back
    with open(param_path, "w", encoding="utf-8") as f:
        json.dump(params, f, indent=2, ensure_ascii=False)

    return True, "merged"


def merge_db_data_into_params(db_data):
    """Merge PostGIS query results (heights, footprints) into photo_observations
    for cross-reference. Only adds db_context sub-dict, never overwrites params."""
    ba = db_data.get("building_assessment", {})
    buildings = ba.get("data", []) if isinstance(ba, dict) else ba
    count = 0
    for b in buildings:
        addr = (b.get("ADDRESS_FULL") or b.get("address_full") or "").strip()
        if not addr:
            continue
        param_path = find_param_file(addr)
        if not param_path:
            continue
        with open(param_path, encoding="utf-8") as f:
            params = json.load(f)
        if params.get("skipped"):
            continue

        obs = params.get("photo_observations", {})
        if not isinstance(obs, dict):
            obs = {}

        # Add DB context for cross-reference during 3D reconstruction
        db_ctx = {}
        for key in ["ba_building_type", "ba_stories", "ba_facade_material",
                     "height_max_m", "height_avg_m",
                     "lot_width_ft", "lot_depth_ft",
                     "HCD_TYPOLOGY", "HCD_CONSTRUCTION_DATE",
                     "facade_colour_observed", "photo_condition",
                     "ba_condition_rating", "ba_storefront_status"]:
            val = b.get(key)
            if val is not None:
                db_ctx[key] = val

        if db_ctx:
            obs["db_context"] = db_ctx
            params["photo_observations"] = obs
            with open(param_path, "w", encoding="utf-8") as f:
                json.dump(params, f, indent=2, ensure_ascii=False)
            count += 1

    return count


def main():
    print("Loading facade analysis...")
    with open(FACADE_ANALYSIS, encoding="utf-8") as f:
        analysis = json.load(f)

    print("Loading photo index CSV...")
    photo_index = load_photo_index()

    print("Loading DB data...")
    with open(DB_DATA, encoding="utf-8") as f:
        db_data = json.load(f)

    facades = analysis.get("facades", {})
    print(f"Found {len(facades)} facade entries to process")

    # Build photo → address mapping for our photos
    photo_to_address = {}
    for filename in facades:
        csv_addr = photo_index.get(filename, "")
        parsed = parse_address_from_csv(csv_addr)
        photo_to_address[filename] = (csv_addr, parsed)

    # Group by address — pick best photo per address
    addr_photos = {}  # address → [(filename, facade_data, csv_address)]
    skipped = []
    no_address = []

    for filename, facade_data in facades.items():
        if facade_data.get("skip_for_3d"):
            skipped.append(filename)
            continue
        csv_addr, parsed_addr = photo_to_address.get(filename, ("", None))
        if not parsed_addr:
            no_address.append((filename, csv_addr))
            continue
        addr_photos.setdefault(parsed_addr, []).append((filename, facade_data, csv_addr))

    print(f"\nSkipped (non-facade): {len(skipped)}")
    print(f"No address match: {len(no_address)}")
    for fn, ca in no_address[:10]:
        print(f"  {fn} -> '{ca}'")
    print(f"Unique addresses to merge: {len(addr_photos)}")

    # Merge facade analysis
    merged = 0
    not_found = []
    errors = []

    for address, photos in sorted(addr_photos.items()):
        # Pick the best photo: prefer daytime, then highest quality note
        best = photos[0]
        for fn, fd, ca in photos:
            quality = (fd.get("photo_quality") or "").lower()
            if "daytime" in quality or "day" in quality:
                best = (fn, fd, ca)
                break
            if "good" in quality:
                best = (fn, fd, ca)

        filename, facade_data, csv_addr = best
        param_path = find_param_file(address)
        if not param_path:
            not_found.append(address)
            continue

        try:
            ok, msg = merge_facade_into_params(param_path, facade_data, filename, csv_addr)
            if ok:
                merged += 1
                print(f"  + {address} <- {filename}")
            else:
                print(f"  - {address}: {msg}")
        except Exception as e:
            errors.append((address, str(e)))
            print(f"  X {address}: {e}")

    # Merge DB context
    print(f"\nMerging DB context data...")
    db_merged = merge_db_data_into_params(db_data)
    print(f"  DB context added to {db_merged} files")

    # Summary
    print(f"\n{'='*60}")
    print(f"MERGE COMPLETE")
    print(f"  Facade analysis merged: {merged}")
    print(f"  DB context merged: {db_merged}")
    print(f"  Param file not found: {len(not_found)}")
    if not_found:
        for a in not_found:
            print(f"    - {a}")
    print(f"  Errors: {len(errors)}")
    if errors:
        for a, e in errors:
            print(f"    - {a}: {e}")

    # Write merge report
    report = {
        "timestamp": TIMESTAMP,
        "facade_photos_analyzed": len(facades),
        "skipped_non_facade": len(skipped),
        "no_address_match": len(no_address),
        "unique_addresses": len(addr_photos),
        "merged_successfully": merged,
        "db_context_merged": db_merged,
        "param_file_not_found": not_found,
        "errors": [{"address": a, "error": e} for a, e in errors],
        "no_address_details": [{"filename": fn, "csv_address": ca} for fn, ca in no_address],
    }
    report_path = DOCS_DIR / "kensington_ave_merge_report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print(f"\nReport saved: {report_path}")


if __name__ == "__main__":
    main()