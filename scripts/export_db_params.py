#!/usr/bin/env python3
"""Step 1: Export building parameters from PostGIS to JSON skeletons.

Pulls real measurements, HCD data, and coordinates from the kensington
database. Produces one param JSON per building in params/, ready for
photo analysis enrichment and Blender generation.

Replaces generate_hcd_params.py — uses actual city data instead of
typology-based guesses.

Usage:
    python export_db_params.py [--output params/] [--street "Augusta Ave"]
    python export_db_params.py --address "22 Lippincott St"
"""

import argparse
import json
import re
import sys
from pathlib import Path

try:
    import psycopg2
    import psycopg2.extras
except ImportError:
    print("[ERROR] psycopg2 not installed. Run: pip install psycopg2-binary")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Database connection
# ---------------------------------------------------------------------------

from db_config import DB_CONFIG, get_connection

PARAMS_DIR = Path(__file__).parent.parent / "params"

QUERY = """
SELECT
    "ADDRESS_FULL",
    ba_street,
    ba_street_number,
    ba_building_type,
    ba_stories,
    ba_facade_material,
    ba_condition_rating,
    ba_condition_issues,
    ba_has_structural_concern,
    ba_storefront_status,
    ba_is_vacant,
    ba_signage,
    ba_business_category,
    ba_heritage_features,
    ba_heritage_count,
    ba_street_presence,
    ba_risk_score,
    "GENERAL_USE",
    "LAND_USE_CATEGORY",
    "COMMERCIAL_USE_TYPE",
    "BUSINESS_NAME",
    "ZN_ZONE_CODE",
    "BLDG_HEIGHT_MAX_M",
    "BLDG_HEIGHT_AVG_M",
    "BLDG_FOOTPRINT_SQM",
    "LOT_WIDTH_FT",
    "LOT_DEPTH_FT",
    "PB_LOT_AREA_SQM",
    "LOT_COVERAGE_PCT",
    "GFA_TOTAL_SQM",
    "FSI",
    "FRONT_SETBACK",
    "LOTS_SHARING_FOOTPRINT",
    "ARCHITECTURAL_STYLE",
    "CONSTRUCTION_PERIOD",
    "CONSTRUCTION_DECADE",
    "DEVELOPMENT_PHASE",
    "MORPHOLOGICAL_ZONE",
    "STREET_CHARACTER",
    "HR_REGISTER_STATUS",
    "HR_PROTECTION_LEVEL",
    "HCD_PLAN_INDEX_NUM",
    "HCD_SUB_AREA",
    "HCD_TYPOLOGY",
    "HCD_CONSTRUCTION_DATE",
    "HCD_CONTRIBUTING",
    "HCD_STATEMENT_FULL",
    "DWELLING_UNITS",
    "RESIDENTIAL_FLOORS",
    ST_X(geom) as lon,
    ST_Y(geom) as lat
FROM building_assessment
WHERE geom IS NOT NULL
"""


# ---------------------------------------------------------------------------
# Conversion helpers
# ---------------------------------------------------------------------------

FT_TO_M = 0.3048


def safe_float(val, default=None):
    if val is None:
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def safe_int(val, default=None):
    if val is None:
        return default
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


def normalize_text(val):
    """Normalize optional text for robust comparisons."""
    return (val or "").strip().lower()


def is_yes(val):
    """Interpret common yes-like values from DB text fields."""
    return normalize_text(val) in {"yes", "y", "true", "1"}


def clamp(val, low, high):
    """Clamp a numeric value to a safe range."""
    return max(low, min(high, val))


def add_inference_note(notes, message):
    """Record a non-duplicated provenance note for inferred fields."""
    if message and message not in notes:
        notes.append(message)


def normalize_facade_material(raw):
    """Map DB facade material values to stable generator-friendly labels."""
    m = normalize_text(raw)
    if not m:
        return "Brick"
    if "brick" in m:
        return "Brick"
    if "stucco" in m or "render" in m:
        return "Stucco"
    if "wood" in m or "clapboard" in m:
        return "Clapboard"
    if "vinyl" in m:
        return "Vinyl siding"
    if "stone" in m:
        return "Stone"
    if "concrete" in m or "cement" in m:
        return "Concrete"
    if "glass" in m:
        return "Glass"
    if "mixed" in m:
        return "Mixed masonry"
    if "other" in m:
        return "Brick"
    return str(raw).strip().title()


def default_facade_colour(material):
    """Provide a reasonable colour description from normalized material."""
    m = normalize_text(material)
    if "brick" in m:
        return "red brick"
    if "stucco" in m:
        return "off-white stucco"
    if "clapboard" in m or "wood" in m:
        return "painted wood"
    if "vinyl" in m:
        return "light vinyl"
    if "stone" in m:
        return "buff stone"
    if "concrete" in m:
        return "grey concrete"
    if "glass" in m:
        return "glass and metal"
    if "mixed" in m:
        return "mixed masonry"
    return "neutral"


def infer_has_storefront(storefront_status, commercial_use, general_use):
    """Infer storefront presence from status first, then land-use signals."""
    status = normalize_text(storefront_status)
    if status in {"active", "vacant"}:
        return True
    if status in {"converted_residential"}:
        return False

    com = normalize_text(commercial_use)
    if com and com not in {"n/a", "na", "none", "null"}:
        return True

    gu = normalize_text(general_use)
    if gu in {"commercial", "mixed use"}:
        return True

    return False


def parse_heritage_features(text):
    """Parse semicolon-delimited heritage features into a list."""
    if not text:
        return []
    return [f.strip() for f in text.split(";") if f.strip()]


def parse_setback(text):
    """Convert setback category to metres."""
    if not text:
        return 0.0
    if "0 m" in text or "lot line" in text:
        return 0.0
    if "0–1" in text or "0-1" in text:
        return 0.5
    if "2–4" in text or "2-4" in text:
        return 3.0
    return 1.0


def clean_typology(raw):
    """Extract the primary typology from complex multi-address HCD entries."""
    if not raw:
        return ""
    # Many entries have address-specific notes in parens — take the first clause
    # e.g. "Commercial (42 Kensington Avenue), Converted House-form (44...)"
    # Normalize to just the primary typology
    parts = raw.split(",")
    clean_parts = []
    for part in parts:
        # Strip address references in parens
        cleaned = re.sub(r"\([^)]*\)", "", part).strip().strip(",").strip()
        if cleaned and cleaned not in clean_parts:
            clean_parts.append(cleaned)
    # Take meaningful parts (skip very short address-only fragments)
    meaningful = [p for p in clean_parts if len(p) > 2]
    return ", ".join(meaningful[:3]) if meaningful else raw.strip()


def infer_floor_heights(stories, total_height, has_storefront):
    """Estimate per-floor heights from total height and storey count."""
    if not stories or stories < 1:
        return [3.0]
    if not total_height or total_height <= 0:
        # Use defaults
        if has_storefront:
            if stories == 1:
                return [3.8]
            return [3.8] + [2.8] * (stories - 1)
        if stories == 1:
            return [3.2]
        return [3.1] + [2.8] * (stories - 1)

    avg = total_height / stories
    heights = []
    for i in range(stories):
        if i == 0 and has_storefront:
            # Commercial ground floor is taller
            heights.append(round(min(avg * 1.3, 4.5), 1))
        elif i == 0:
            heights.append(round(min(avg * 1.1, 3.5), 1))
        elif i == stories - 1 and stories >= 3:
            # Top floor often shorter (especially half-storey / attic)
            heights.append(round(avg * 0.85, 1))
        else:
            heights.append(round(avg, 1))

    # Adjust to match total
    current_sum = sum(heights)
    if current_sum > 0 and abs(current_sum - total_height) > 0.5:
        factor = total_height / current_sum
        heights = [round(h * factor, 1) for h in heights]

    return heights


def infer_total_height(height_avg, height_max, stories, has_storefront):
    """Choose a conservative wall height with provenance for fallbacks."""
    if height_avg and height_avg > 0:
        return height_avg, None
    if height_max and height_max > 0:
        return height_max, "total_height_m inferred from BLDG_HEIGHT_MAX_M because BLDG_HEIGHT_AVG_M was missing"

    per_floor = 3.8 if has_storefront else 3.1
    return stories * per_floor, f"total_height_m inferred from {stories} storey default at {per_floor:.1f}m per floor"


def infer_facade_width(lot_width_ft, footprint_sqm, typology, general_use, has_storefront):
    """Infer facade width from the best available measurement."""
    lot_width_m = round(lot_width_ft * FT_TO_M, 1) if lot_width_ft and lot_width_ft > 0 else None
    typo = normalize_text(typology)
    use = normalize_text(general_use)
    commercialish = has_storefront or use in {"commercial", "mixed use"} or "commercial" in typo

    if lot_width_m and lot_width_m > 0:
        width = lot_width_m
        if "detached" in typo and "semi-detached" not in typo:
            width = round(width * 0.85, 1)
        return clamp(width, 4.0, 12.0), None

    if footprint_sqm and footprint_sqm > 0:
        ratio = 0.42 if commercialish else 0.34
        raw_width = (footprint_sqm * ratio) ** 0.5
        if "detached" in typo and "semi-detached" not in typo:
            raw_width *= 0.9
        rounded = round(raw_width, 1)
        width = clamp(rounded, 4.2 if not commercialish else 5.2, 12.0)
        note = "facade_width_m inferred from BLDG_FOOTPRINT_SQM because LOT_WIDTH_FT was missing"
        if width != rounded:
            note += f" (clamped from {rounded:.1f}m)"
        return width, note

    width = 6.0 if commercialish else 5.5
    return width, f"facade_width_m defaulted from use/typology because LOT_WIDTH_FT and BLDG_FOOTPRINT_SQM were missing"


def infer_facade_depth(lot_depth_ft, footprint_sqm, facade_width_m, general_use, has_storefront, lot_coverage_pct):
    """Infer facade depth from the best available measurement."""
    lot_depth_m = round(lot_depth_ft * FT_TO_M, 1) if lot_depth_ft and lot_depth_ft > 0 else None
    use = normalize_text(general_use)
    commercialish = has_storefront or use in {"commercial", "mixed use"}
    coverage = lot_coverage_pct / 100.0 if lot_coverage_pct and lot_coverage_pct > 0 else None

    if footprint_sqm and footprint_sqm > 0 and facade_width_m and facade_width_m > 0:
        depth = round(footprint_sqm / facade_width_m, 1)
        if lot_depth_m and lot_depth_m > 0:
            depth = min(depth, lot_depth_m)
        return clamp(depth, 6.0, 24.0), "facade_depth_m derived from BLDG_FOOTPRINT_SQM and facade_width_m because LOT_DEPTH_FT was missing or unusable"

    if lot_depth_m and lot_depth_m > 0:
        if coverage is None:
            coverage = 0.78 if commercialish else 0.68
        depth = round(lot_depth_m * coverage, 1)
        return clamp(depth, 6.0, lot_depth_m), "facade_depth_m inferred from LOT_DEPTH_FT and coverage because BLDG_FOOTPRINT_SQM was missing"

    if footprint_sqm and footprint_sqm > 0 and facade_width_m and facade_width_m > 0:
        raw_depth = round(footprint_sqm / facade_width_m, 1)
        depth = clamp(raw_depth, 6.0, 24.0)
        note = "facade_depth_m inferred from BLDG_FOOTPRINT_SQM because LOT_DEPTH_FT was missing"
        if depth != raw_depth:
            note += f" (clamped from {raw_depth:.1f}m)"
        return depth, note

    depth = max(facade_width_m * (2.1 if commercialish else 2.4), 8.0 if commercialish else 7.5)
    return round(clamp(depth, 7.5, 24.0), 1), "facade_depth_m defaulted from use/typology because LOT_DEPTH_FT and BLDG_FOOTPRINT_SQM were missing"


def infer_roof_type(typology, style):
    """Infer roof type from HCD typology and architectural style."""
    combined = f"{typology} {style}".lower()
    if "bay-and-gable" in combined or "bay and gable" in combined:
        return "Cross-gable"
    if "ontario cottage" in combined:
        return "Gable"
    if "commercial" in combined:
        return "Flat"
    if "mansard" in combined:
        return "Mansard"
    if "hip" in combined:
        return "Hip"
    if "gable" in combined:
        return "Gable"
    if "row" in combined:
        return "Flat"
    return "Gable"


def infer_windows_per_floor(stories, facade_width_m, has_storefront):
    """Estimate window count per floor from facade width."""
    if not stories or stories < 1:
        return [2]

    # Rough: one window bay per ~2.5m of facade width
    bays = max(1, round(facade_width_m / 2.5)) if facade_width_m else 2

    wpf = []
    for i in range(stories):
        if i == 0 and has_storefront:
            wpf.append(0)  # storefront replaces windows
        elif i == 0:
            wpf.append(bays)
        elif i == stories - 1 and stories >= 3:
            wpf.append(max(1, bays - 1))  # attic/half storey
        else:
            wpf.append(bays)

    return wpf


def condition_label(rating):
    """Convert 1-5 rating to label."""
    if rating is None:
        return "fair"
    if rating >= 4:
        return "good"
    if rating >= 3:
        return "fair"
    return "poor"


# ---------------------------------------------------------------------------
# Build param dict from DB row
# ---------------------------------------------------------------------------

def row_to_params(row):
    """Convert a database row to a building parameter JSON dict."""
    address = row["ADDRESS_FULL"] or ""
    stories = max(1, safe_int(row["ba_stories"], 2))
    height_max = safe_float(row["BLDG_HEIGHT_MAX_M"])
    height_avg = safe_float(row["BLDG_HEIGHT_AVG_M"])
    lot_width_ft = safe_float(row["LOT_WIDTH_FT"])
    lot_depth_ft = safe_float(row["LOT_DEPTH_FT"])
    footprint_sqm = safe_float(row["BLDG_FOOTPRINT_SQM"])
    facade_material = normalize_facade_material(row["ba_facade_material"])
    storefront_status = normalize_text(row["ba_storefront_status"])
    general_use = row["GENERAL_USE"] or ""
    commercial_use = row["COMMERCIAL_USE_TYPE"] or ""
    has_storefront = infer_has_storefront(
        storefront_status,
        commercial_use,
        general_use,
    )
    heritage_features = parse_heritage_features(row["ba_heritage_features"])
    typology = clean_typology(row["HCD_TYPOLOGY"] or "")
    style = row["ARCHITECTURAL_STYLE"] or ""
    setback = parse_setback(row["FRONT_SETBACK"])
    inference_notes = []

    # Building width: for row/semi-detached, building fills most of the lot width
    # For detached, building is narrower (setbacks on sides)
    facade_width_m, width_note = infer_facade_width(
        lot_width_ft,
        footprint_sqm,
        typology,
        general_use,
        has_storefront,
    )
    if width_note:
        add_inference_note(inference_notes, width_note)

    # Building depth: estimate from footprint area / width, or lot depth * coverage
    facade_depth_m, depth_note = infer_facade_depth(
        lot_depth_ft,
        footprint_sqm,
        facade_width_m,
        general_use,
        has_storefront,
        safe_float(row["LOT_COVERAGE_PCT"]),
    )
    if depth_note:
        add_inference_note(inference_notes, depth_note)

    # Height: use avg height for wall/eave height (max includes peaks/chimneys)
    total_height, height_note = infer_total_height(
        height_avg,
        height_max,
        stories,
        has_storefront,
    )
    if height_note:
        add_inference_note(inference_notes, height_note)

    floor_heights = infer_floor_heights(stories, total_height, has_storefront)
    roof_type = infer_roof_type(typology, style)
    wpf = infer_windows_per_floor(stories, facade_width_m, has_storefront)

    # Roof pitch from type
    roof_pitches = {
        "Gable": 40, "Cross-gable": 45, "Hip": 30,
        "Mansard": 70, "Flat": 0, "Gambrel": 55, "Shed": 15,
    }
    roof_pitch = roof_pitches.get(roof_type, 35)

    # Heritage features → booleans
    feat_str = " ".join(heritage_features).lower()
    has_bay = "bay_window" in feat_str or "bay window" in feat_str
    has_cornice = "cornice" in feat_str
    has_turret = "turret" in feat_str
    has_decorative_brick = "decorative_brick" in feat_str or "decorative brick" in feat_str

    params = {
        "building_name": address,

        # Massing (from real city data)
        "floors": stories,
        "floor_heights_m": floor_heights,
        "total_height_m": round(total_height, 2),
        "facade_width_m": facade_width_m,
        "facade_depth_m": facade_depth_m,

        # Site
        "site": {
            "lon": row["lon"],
            "lat": row["lat"],
            "street": row["ba_street"] or "",
            "street_number": safe_int(row["ba_street_number"]),
            "setback_m": setback,
            "lot_area_sqm": safe_float(row["PB_LOT_AREA_SQM"]),
            "footprint_sqm": footprint_sqm,
            "lot_coverage_pct": safe_float(row["LOT_COVERAGE_PCT"]),
            "lots_sharing_footprint": safe_int(row["LOTS_SHARING_FOOTPRINT"], 1),
        },

        # Roof
        "roof_type": roof_type,
        "roof_pitch_deg": roof_pitch,
        "roof_features": [],

        # Facade
        "facade_material": facade_material,
        "facade_colour": default_facade_colour(facade_material),  # Will be refined by photo analysis

        # Fenestration (estimated, refined by photo analysis)
        "windows_per_floor": wpf,
        "window_type": "Double-hung sash",
        "window_width_m": 0.85,
        "window_height_m": 1.3,

        # Doors (estimated)
        "door_count": 1,

        # Commercial
        "has_storefront": has_storefront,

        # Condition
        "condition": condition_label(row["ba_condition_rating"]),

        # Heritage data
        "hcd_data": {
            "typology": typology,
            "construction_date": row["HCD_CONSTRUCTION_DATE"] or "",
            "architectural_style": style,
            "construction_period": row["CONSTRUCTION_PERIOD"] or "",
            "construction_decade": safe_int(row["CONSTRUCTION_DECADE"]),
            "sub_area": row["HCD_SUB_AREA"] or "",
            "contributing": row["HCD_CONTRIBUTING"] or "",
            "hcd_plan_index": safe_int(row["HCD_PLAN_INDEX_NUM"]),
            "statement_of_contribution": row["HCD_STATEMENT_FULL"] or "",
            "building_features": heritage_features,
            "heritage_register": row["HR_REGISTER_STATUS"] or "",
            "protection_level": safe_int(row["HR_PROTECTION_LEVEL"]),
        },

        # Urban context
        "context": {
            "building_type": row["ba_building_type"] or "",
            "general_use": row["GENERAL_USE"] or "",
            "land_use": row["LAND_USE_CATEGORY"] or "",
            "commercial_use": row["COMMERCIAL_USE_TYPE"] or "",
            "business_name": row["BUSINESS_NAME"] or "",
            "business_category": row["ba_business_category"] or "",
            "zoning": row["ZN_ZONE_CODE"] or "",
            "is_vacant": is_yes(row["ba_is_vacant"]),
            "street_character": row["STREET_CHARACTER"] or "",
            "morphological_zone": row["MORPHOLOGICAL_ZONE"] or "",
            "development_phase": row["DEVELOPMENT_PHASE"] or "",
        },

        # Assessment data
        "assessment": {
            "condition_rating": safe_int(row["ba_condition_rating"]),
            "condition_issues": row["ba_condition_issues"] or "",
            "structural_concern": is_yes(row["ba_has_structural_concern"]),
            "risk_score": safe_int(row["ba_risk_score"]),
            "signage": row["ba_signage"] or "",
            "street_presence": row["ba_street_presence"] or "",
        },

        # Measurements from city data
        "city_data": {
            "height_max_m": safe_float(row["BLDG_HEIGHT_MAX_M"]),
            "height_avg_m": safe_float(row["BLDG_HEIGHT_AVG_M"]),
            "footprint_sqm": footprint_sqm,
            "gfa_sqm": safe_float(row["GFA_TOTAL_SQM"]),
            "fsi": safe_float(row["FSI"]),
            "lot_width_ft": lot_width_ft,
            "lot_depth_ft": lot_depth_ft,
            "dwelling_units": safe_int(row["DWELLING_UNITS"]),
            "residential_floors": row["RESIDENTIAL_FLOORS"] or "",
            "heritage_feature_count": safe_int(row["ba_heritage_count"]),
        },

        # Metadata
        "_meta": {
            "address": address,
            "source": "postgis_export",
            "db": "kensington",
            "inference_notes": inference_notes,
        },
    }

    # Bay window from heritage features
    if has_bay:
        params["bay_window"] = {
            "present": True,
            "type": "Three-sided projecting bay" if "bay-and-gable" in typology.lower() else "Projecting bay",
            "floors": [0, 1] if stories >= 2 else [0],
            "width_m": round(facade_width_m * 0.4, 1),
            "projection_m": 0.6,
        }

    # Turret
    if has_turret:
        params["roof_features"].append("turret")

    # Decorative brick
    if has_decorative_brick:
        params.setdefault("decorative_elements", {})["decorative_brickwork"] = {
            "present": True,
        }

    # Cornice
    if has_cornice:
        params["cornice"] = {
            "present": True,
            "type": "decorative",
            "height_mm": 300,
            "projection_mm": 180,
            "colour_hex": "#D4C9A8",
        }

    # Storefront detail
    if has_storefront:
        if storefront_status not in {"active", "vacant"}:
            add_inference_note(
                inference_notes,
                "has_storefront inferred from COMMERCIAL_USE_TYPE/GENERAL_USE because ba_storefront_status was missing or non-storefront",
            )
        storefront_status_out = storefront_status or "inferred_from_use"
        storefront_status_source = "db_status" if storefront_status in {"active", "vacant", "converted_residential"} else "inferred_from_use"
        params["storefront"] = {
            "type": "Commercial ground floor",
            "status": storefront_status_out,
            "status_source": storefront_status_source,
            "width_m": round(facade_width_m * 0.85, 1),
            "height_m": floor_heights[0] if floor_heights else 3.5,
        }

    return params


# ---------------------------------------------------------------------------
# Safe filename
# ---------------------------------------------------------------------------

def address_to_filename(address):
    """Convert address to safe filename."""
    name = address.replace(" ", "_").replace(",", "").replace(".", "")
    name = re.sub(r"[^\w\-]", "_", name)
    name = re.sub(r"_+", "_", name).strip("_")
    return f"{name}.json"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Export building params from PostGIS")
    parser.add_argument("--output", default="params", help="Output directory")
    parser.add_argument("--street", default=None, help="Filter to one street")
    parser.add_argument("--address", default=None, help="Export single address")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing param files")
    args = parser.parse_args()

    out_dir = Path(__file__).parent.parent / args.output
    out_dir.mkdir(parents=True, exist_ok=True)

    # Build WHERE clause with parameterized queries
    where_clauses = []
    query_params = []
    if args.street:
        where_clauses.append("AND ba_street = %s")
        query_params.append(args.street)
    if args.address:
        where_clauses.append('AND "ADDRESS_FULL" = %s')
        query_params.append(args.address)

    query = QUERY + " ".join(where_clauses) + "\nORDER BY ba_street, ba_street_number"

    conn = get_connection()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(query, query_params if query_params else None)
        rows = cur.fetchall()
        cur.close()
    except Exception:
        conn.close()
        raise
    conn.close()

    print(f"=== PostGIS Export ===")
    print(f"Buildings: {len(rows)}")
    print(f"Output: {out_dir}/")
    print()

    exported = 0
    skipped = 0
    errors = 0

    for row in rows:
        address = row["ADDRESS_FULL"]
        if not address:
            errors += 1
            continue

        filename = address_to_filename(address)
        filepath = out_dir / filename

        if filepath.exists() and not args.overwrite:
            skipped += 1
            continue

        try:
            params = row_to_params(row)
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(params, f, indent=2, ensure_ascii=False)
                f.write("\n")
            exported += 1
        except Exception as e:
            print(f"  [ERROR] {address}: {e}")
            errors += 1

    print(f"Exported: {exported}")
    print(f"Skipped (existing): {skipped}")
    if errors:
        print(f"Errors: {errors}")
    print(f"Total param files: {len(list(out_dir.glob('*.json')))}")


if __name__ == "__main__":
    main()

