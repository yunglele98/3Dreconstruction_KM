#!/usr/bin/env python3
"""Generate skeleton building param JSON files from HCD Plan data.

Uses typology-based dimensional defaults derived from the 10 photo-analyzed
pilot buildings. These are reasonable estimates for Kensington Market's
Victorian/Edwardian housing stock.

Usage:
    python generate_hcd_params.py
"""

import json
from pathlib import Path
from datetime import datetime

PARAMS_DIR = Path(__file__).parent.parent / "params"

# ---------------------------------------------------------------------------
# Typology-based dimensional templates
# ---------------------------------------------------------------------------
# Derived from actual measurements of the 10 pilot buildings

TYPOLOGY_TEMPLATES = {
    "house-form, row": {
        "floors": 2.5,
        "floor_heights_m": [3.0, 2.8, 2.2],
        "total_height_m": 9.5,
        "facade_width_m": 5.0,
        "street_setback_m": 2.0,
        "roof_type": "Cross-gable",
        "roof_pitch_deg": 40,
        "roof_material": "Grey asphalt shingles",
        "facade_material": "Red brick",
        "windows_per_floor": [2, 2, 1],
        "window_type": "Double-hung sash",
        "door_count": 1,
        "has_bay_window": False,
        "has_porch": False,
        "has_storefront": False,
        "party_wall_left": True,
        "party_wall_right": True,
    },
    "house-form, row, bay-and-gable": {
        "floors": 2.5,
        "floor_heights_m": [3.0, 2.8, 2.2],
        "total_height_m": 9.5,
        "facade_width_m": 5.0,
        "street_setback_m": 2.0,
        "roof_type": "Cross-gable",
        "roof_pitch_deg": 45,
        "roof_material": "Grey asphalt shingles",
        "facade_material": "Red brick with decorative brickwork",
        "windows_per_floor": [2, 2, 1],
        "window_type": "Double-hung sash with segmental arches",
        "door_count": 1,
        "has_bay_window": True,
        "bay_window_floors": [0, 1],
        "has_porch": False,
        "has_storefront": False,
        "party_wall_left": True,
        "party_wall_right": True,
    },
    "house-form, semi-detached": {
        "floors": 2.5,
        "floor_heights_m": [3.0, 2.8, 2.2],
        "total_height_m": 9.5,
        "facade_width_m": 5.5,
        "street_setback_m": 3.0,
        "roof_type": "Cross-gable",
        "roof_pitch_deg": 40,
        "roof_material": "Grey asphalt shingles",
        "facade_material": "Red brick",
        "windows_per_floor": [2, 2, 1],
        "window_type": "Double-hung sash",
        "door_count": 1,
        "has_bay_window": False,
        "has_porch": False,
        "has_storefront": False,
        "party_wall_left": True,
        "party_wall_right": False,
    },
    "house-form, semi-detached, bay-and-gable": {
        "floors": 2.5,
        "floor_heights_m": [3.0, 2.8, 2.2],
        "total_height_m": 9.5,
        "facade_width_m": 5.5,
        "street_setback_m": 3.0,
        "roof_type": "Cross-gable",
        "roof_pitch_deg": 45,
        "roof_material": "Grey asphalt shingles",
        "facade_material": "Red brick with decorative brickwork",
        "windows_per_floor": [2, 2, 1],
        "window_type": "Double-hung sash with segmental arches",
        "door_count": 1,
        "has_bay_window": True,
        "bay_window_floors": [0, 1],
        "has_porch": False,
        "has_storefront": False,
        "party_wall_left": True,
        "party_wall_right": False,
    },
    "house-form, detached": {
        "floors": 2.5,
        "floor_heights_m": [3.0, 2.8, 2.2],
        "total_height_m": 9.5,
        "facade_width_m": 6.0,
        "street_setback_m": 4.0,
        "roof_type": "Cross-gable",
        "roof_pitch_deg": 40,
        "roof_material": "Grey asphalt shingles",
        "facade_material": "Red brick",
        "windows_per_floor": [2, 2, 1],
        "window_type": "Double-hung sash",
        "door_count": 1,
        "has_bay_window": False,
        "has_porch": True,
        "has_storefront": False,
        "party_wall_left": False,
        "party_wall_right": False,
    },
    "house-form, detached, bay-and-gable": {
        "floors": 2.5,
        "floor_heights_m": [3.0, 2.8, 2.2],
        "total_height_m": 9.5,
        "facade_width_m": 6.0,
        "street_setback_m": 4.0,
        "roof_type": "Cross-gable",
        "roof_pitch_deg": 45,
        "roof_material": "Grey asphalt shingles",
        "facade_material": "Red brick with decorative brickwork",
        "windows_per_floor": [2, 2, 1],
        "window_type": "Double-hung sash with segmental arches",
        "door_count": 1,
        "has_bay_window": True,
        "bay_window_floors": [0, 1],
        "has_porch": True,
        "has_storefront": False,
        "party_wall_left": False,
        "party_wall_right": False,
    },
    "house-form, detached, ontario cottage": {
        "floors": 1.5,
        "floor_heights_m": [2.8, 1.8],
        "total_height_m": 5.5,
        "facade_width_m": 6.0,
        "street_setback_m": 3.0,
        "roof_type": "Side gable with central front gable",
        "roof_pitch_deg": 45,
        "roof_material": "Grey asphalt shingles",
        "facade_material": "Brick or frame",
        "windows_per_floor": [2, 1],
        "window_type": "Double-hung sash",
        "door_count": 1,
        "has_bay_window": False,
        "has_porch": True,
        "has_storefront": False,
        "party_wall_left": False,
        "party_wall_right": False,
    },
    "converted house-form": {
        "floors": 2.5,
        "floor_heights_m": [3.2, 2.8, 2.2],
        "total_height_m": 9.5,
        "facade_width_m": 5.5,
        "street_setback_m": 0.0,
        "roof_type": "Cross-gable",
        "roof_pitch_deg": 40,
        "roof_material": "Grey asphalt shingles",
        "facade_material": "Brick with commercial ground floor alterations",
        "windows_per_floor": [0, 2, 1],
        "window_type": "Mixed - commercial ground, residential upper",
        "door_count": 1,
        "has_bay_window": False,
        "has_porch": False,
        "has_storefront": True,
        "party_wall_left": False,
        "party_wall_right": False,
    },
    "commercial": {
        "floors": 2,
        "floor_heights_m": [3.5, 3.0],
        "total_height_m": 7.5,
        "facade_width_m": 6.0,
        "street_setback_m": 0.0,
        "roof_type": "Flat with parapet",
        "roof_pitch_deg": 0,
        "roof_material": "Built-up flat roof",
        "facade_material": "Brick with commercial storefront",
        "windows_per_floor": [0, 2],
        "window_type": "Commercial plate glass ground, double-hung upper",
        "door_count": 1,
        "has_bay_window": False,
        "has_porch": False,
        "has_storefront": True,
        "party_wall_left": True,
        "party_wall_right": True,
    },
    "institutional": {
        "floors": 3,
        "floor_heights_m": [4.0, 3.5, 3.5],
        "total_height_m": 12.0,
        "facade_width_m": 20.0,
        "street_setback_m": 3.0,
        "roof_type": "Flat with parapet",
        "roof_pitch_deg": 0,
        "roof_material": "Built-up flat roof",
        "facade_material": "Brick with stone trim",
        "windows_per_floor": [5, 5, 5],
        "window_type": "Flat-headed with stone lintels",
        "door_count": 2,
        "has_bay_window": False,
        "has_porch": False,
        "has_storefront": False,
        "party_wall_left": False,
        "party_wall_right": False,
    },
    "multi-residential": {
        "floors": 3,
        "floor_heights_m": [3.5, 3.0, 3.0],
        "total_height_m": 10.5,
        "facade_width_m": 10.0,
        "street_setback_m": 2.0,
        "roof_type": "Flat with parapet",
        "roof_pitch_deg": 0,
        "roof_material": "Built-up flat roof",
        "facade_material": "Brick with stone quoining",
        "windows_per_floor": [3, 3, 3],
        "window_type": "Flat-headed with stone lintels and sills",
        "door_count": 1,
        "has_bay_window": False,
        "has_porch": False,
        "has_storefront": False,
        "party_wall_left": False,
        "party_wall_right": False,
    },
}


def get_era_style(construction_date):
    """Return style description based on construction era."""
    if "Pre-1889" in construction_date:
        return "Victorian Vernacular"
    elif "1889" in construction_date or "1890" in construction_date or "1903" in construction_date:
        return "Late Victorian"
    elif "1904" in construction_date or "1913" in construction_date:
        return "Edwardian / Late Victorian"
    elif "1914" in construction_date or "1930" in construction_date:
        return "Early Twentieth Century"
    elif "1878" in construction_date:
        return "Victorian"
    else:
        return "Victorian Vernacular"


def match_template(typology):
    """Find the best matching template for a given HCD typology string."""
    typ_lower = typology.lower()

    # Try exact match first
    if typ_lower in TYPOLOGY_TEMPLATES:
        return TYPOLOGY_TEMPLATES[typ_lower]

    # Try partial matches in order of specificity
    for key in sorted(TYPOLOGY_TEMPLATES.keys(), key=len, reverse=True):
        parts = key.split(", ")
        if all(p in typ_lower for p in parts):
            return TYPOLOGY_TEMPLATES[key]

    # Fallback: check for key terms
    if "ontario cottage" in typ_lower:
        return TYPOLOGY_TEMPLATES["house-form, detached, ontario cottage"]
    if "institutional" in typ_lower:
        return TYPOLOGY_TEMPLATES["institutional"]
    if "multi-residential" in typ_lower:
        return TYPOLOGY_TEMPLATES["multi-residential"]
    if "commercial" in typ_lower:
        return TYPOLOGY_TEMPLATES["commercial"]
    if "converted" in typ_lower:
        return TYPOLOGY_TEMPLATES["converted house-form"]
    if "bay-and-gable" in typ_lower:
        if "semi-detached" in typ_lower:
            return TYPOLOGY_TEMPLATES["house-form, semi-detached, bay-and-gable"]
        if "detached" in typ_lower:
            return TYPOLOGY_TEMPLATES["house-form, detached, bay-and-gable"]
        return TYPOLOGY_TEMPLATES["house-form, row, bay-and-gable"]
    if "row" in typ_lower:
        return TYPOLOGY_TEMPLATES["house-form, row"]
    if "semi-detached" in typ_lower:
        return TYPOLOGY_TEMPLATES["house-form, semi-detached"]
    if "detached" in typ_lower:
        return TYPOLOGY_TEMPLATES["house-form, detached"]

    # Ultimate fallback
    return TYPOLOGY_TEMPLATES["house-form, semi-detached"]


def make_address_filename(address):
    """Convert '12 Denison Square' to '12_Denison_Sq'."""
    addr = address.strip()
    # Common abbreviations
    addr = addr.replace(" Street", "_St")
    addr = addr.replace(" Avenue", "_Ave")
    addr = addr.replace(" Square", "_Sq")
    addr = addr.replace(" Place", "_Pl")
    addr = addr.replace(" Terrace", "_Terr")
    addr = addr.replace(" ", "_")
    # Handle special chars
    addr = addr.replace("/", "-")
    return addr


def infer_decorative_elements(features, typology):
    """Convert HCD feature phrases into structured generation hints."""
    decorative = {}
    roof_features = []
    windows_detail = []
    lower_features = [str(f).lower() for f in features]
    typ_lower = typology.lower()

    def has(*phrases):
        return any(any(p in feat for p in phrases) for feat in lower_features)

    if has("bargeboard"):
        decorative["bargeboard"] = {
            "present": True,
            "type": "decorative",
            "colour_hex": "#4A3324",
            "width_mm": 220,
        }

    if has("bracket", "brackets"):
        decorative["gable_brackets"] = {
            "type": "paired_scroll",
            "count": 4,
            "projection_mm": 220,
            "height_mm": 320,
            "colour_hex": "#4A3324",
        }

    if has("pediment", "pediments"):
        decorative["gable_pediment"] = {
            "present": True,
            "type": "triangular",
            "colour_hex": "#4A3324",
        }

    if has("string course", "string courses"):
        decorative["string_courses"] = {
            "present": True,
            "width_mm": 140,
            "projection_mm": 25,
            "colour_hex": "#D4C9A8",
        }

    if has("cornice"):
        decorative["cornice"] = {
            "present": True,
            "projection_mm": 180,
            "height_mm": 220,
            "colour_hex": "#D4C9A8",
        }

    if has("quoin", "quoining"):
        decorative["quoins"] = {
            "present": True,
            "strip_width_mm": 220,
            "projection_mm": 18,
            "colour_hex": "#D4C9A8",
        }

    if has("voussoir", "voussoirs"):
        decorative["stone_voussoirs"] = {
            "present": True,
            "colour_hex": "#D4C9A8",
        }

    if has("stone lintel", "stone lintels", "flat headed openings featuring stone lintels", "stone sills"):
        decorative["stone_lintels"] = {
            "present": True,
            "colour_hex": "#D4C9A8",
        }

    if has("polychromatic", "dichromat"):
        decorative["polychromatic_brickwork"] = {
            "present": True,
            "secondary_brick_hex": "#6E3322",
        }

    if has("shingle", "shingles in gable"):
        decorative["ornamental_shingles"] = {
            "present": True,
            "colour_hex": "#6B4C3B",
            "exposure_mm": 110,
        }

    if has("stained", "leaded glass transom", "leaded glass transoms"):
        decorative["stained_glass_transoms"] = {
            "present": True,
            "colour_palette": "amber_green_red",
        }

    if has("turret"):
        decorative["turreted_element"] = {"present": True}
        roof_features.append("tower")

    if has("segmentally arched openings", "segmental-arched", "segmentally arched"):
        decorative["window_hoods"] = {
            "present": True,
            "arch_type": "segmental",
            "colour_hex": "#D4C9A8",
        }
        windows_detail.append({
            "floor": "all_upper",
            "head_shape": "segmental_arch",
        })

    if has("bay window", "bay windows", "double-height bay", "double-height bays", "second storey bay windows"):
        bay_floors = [0, 1] if ("bay-and-gable" in typ_lower or has("double-height bay", "double-height bays")) else [0]
        decorative["bay_window_shape"] = "canted"
        decorative["bay_window_storeys"] = len(bay_floors)

    if has("commercial storefront", "storefront", "commercial glazing", "chamfered corner"):
        decorative["storefront_context"] = {"present": True}

    return decorative, roof_features, windows_detail


def generate_param_file(building):
    """Generate a skeleton param JSON for a single building."""
    address = building["address"]
    hcd_num = building["hcd_reference_number"]
    typology = building["typology"]
    construction_date = building["construction_date"]
    character_sub_area = building.get("character_sub_area", "n/a")
    hcd_page = building.get("hcd_page", 0)
    features = building.get("building_features", [])
    statement = building.get("statement_of_contribution", "")

    template = match_template(typology)
    style = get_era_style(construction_date)
    filename = make_address_filename(address) + ".json"

    # Build the param dict
    params = {
        "building_name": address,
        "year_built_approx": construction_date,
        "overall_style": f"{style}, {typology}",
        "building_type": f"Residential ({typology})",
        "condition": "Unknown - generated from HCD data without photo analysis",
        "confidence": 0.40,
        "source": "hcd_plan_only",

        "site": {
            "total_facade_width_m": template["facade_width_m"],
            "street_setback_m": template["street_setback_m"],
            "orientation": "Facade faces street",
            "context": f"Kensington Market HCD, Character Sub-Area: {character_sub_area}",
        },

        "floors": template["floors"],
        "floor_heights_m": template["floor_heights_m"],
        "total_height_m": template["total_height_m"],

        "roof_type": template["roof_type"],
        "roof_pitch_deg": template["roof_pitch_deg"],
        "roof_material": template["roof_material"],

        "facade_width_m": template["facade_width_m"],
        "facade_material": template["facade_material"],

        "windows_per_floor": template["windows_per_floor"],
        "window_type": template["window_type"],

        "door_count": template["door_count"],

        "has_storefront": template["has_storefront"],
    }

    # Add bay window if typology calls for it
    if template.get("has_bay_window"):
        params["bay_window"] = {
            "present": True,
            "type": "Three-sided projecting bay",
            "floors": template.get("bay_window_floors", [0, 1]),
            "width_m": 2.0,
            "projection_m": 0.6,
        }

    # Add porch if typology calls for it
    if template.get("has_porch"):
        params["porch"] = {
            "present": True,
            "type": "Open front porch",
            "width_m": template["facade_width_m"],
            "depth_m": 1.8,
            "height_m": 2.8,
        }

    # Add storefront if applicable
    if template.get("has_storefront"):
        params["storefront"] = {
            "type": "Commercial ground floor",
            "width_m": template["facade_width_m"],
            "height_m": template["floor_heights_m"][0],
        }

    decorative, roof_features, windows_detail = infer_decorative_elements(features, typology)

    for feat in features:
        fl = feat.lower()
        if "dormer" in fl or "dormers" in fl:
            roof_features.append("dormers")
        if "mansard" in fl:
            params["roof_type"] = "Mansard"
        if "bay window" in fl or "bay windows" in fl or "double-height bay" in fl or "double-height bays" in fl:
            if "bay_window" not in params:
                params["bay_window"] = {
                    "present": True,
                    "type": "Three-sided projecting bay" if "bay-and-gable" in typology.lower() else "Projecting bay",
                    "floors": [0, 1] if ("double-height" in fl or "bay-and-gable" in typology.lower()) else [0],
                    "width_m": 2.2,
                    "projection_m": 0.6,
                }

    if roof_features:
        params["roof_features"] = sorted(set(roof_features))

    if windows_detail:
        params["windows_detail"] = windows_detail

    if decorative:
        params["decorative_elements"] = decorative

    # HCD data section
    params["hcd_data"] = {
        "hcd_reference_number": hcd_num,
        "hcd_page": hcd_page,
        "character_sub_area": character_sub_area,
        "typology": typology,
        "construction_date": construction_date,
        "statement_of_contribution": statement,
        "building_features": features,
        "discrepancies": [],
    }

    # Meta section
    params["_meta"] = {
        "address": f"{address}, Toronto, ON",
        "neighbourhood": "Kensington Market",
        "heritage_designation": "Within Kensington Market Heritage Conservation District",
        "hcd_reference": f"HCD #{hcd_num}",
        "hcd_typology": typology,
        "hcd_construction_date": construction_date,
        "hcd_page": hcd_page,
        "model": "hcd_plan_skeleton",
        "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "notes": "Skeleton params generated from HCD Plan Vol.2 Appendix D. No photo analysis. confidence=0.40.",
    }

    return filename, params


# ---------------------------------------------------------------------------
# HCD building data extracted from Vol.2 Appendix D
# ---------------------------------------------------------------------------

HCD_BUILDINGS = [
    # Denison Avenue
    {
        "address": "155 Denison Avenue",
        "hcd_reference_number": 134,
        "hcd_page": 91,
        "character_sub_area": "n/a",
        "typology": "House-form, Semi-detached, Bay-and-Gable",
        "construction_date": "Pre-1889",
        "building_features": ["mirrored facades", "cross-gabled roofline", "double-height bays", "brick cladding", "flat headed openings"],
        "statement_of_contribution": "Pair of semi-detached houses retaining original Victorian features.",
    },
    {
        "address": "157 Denison Avenue",
        "hcd_reference_number": 135,
        "hcd_page": 91,
        "character_sub_area": "n/a",
        "typology": "House-form, Semi-detached, Bay-and-Gable",
        "construction_date": "Pre-1889",
        "building_features": ["mirrored facades", "cross-gabled roofline", "double-height bays", "brick cladding", "flat headed openings"],
        "statement_of_contribution": "Pair of semi-detached houses retaining original Victorian features.",
    },
    # Denison Square
    {
        "address": "12 Denison Square",
        "hcd_reference_number": 136,
        "hcd_page": 92,
        "character_sub_area": "n/a",
        "typology": "House-form, Semi-detached, Bay-and-Gable",
        "construction_date": "Pre-1889",
        "building_features": ["mirrored facades", "cross-gabled roofline", "double-height bays", "brick cladding", "polychromatic brickwork detailing", "decorative wooden gable brackets", "segmentally arched openings"],
        "statement_of_contribution": "Pair of semi-detached houses with polychromatic brickwork and decorative gable brackets.",
    },
    {
        "address": "14 Denison Square",
        "hcd_reference_number": 137,
        "hcd_page": 92,
        "character_sub_area": "n/a",
        "typology": "House-form, Semi-detached, Bay-and-Gable",
        "construction_date": "Pre-1889",
        "building_features": ["mirrored facades", "cross-gabled roofline", "double-height bays", "brick cladding", "polychromatic brickwork detailing", "decorative wooden gable brackets", "segmentally arched openings"],
        "statement_of_contribution": "Pair of semi-detached houses with polychromatic brickwork and decorative gable brackets.",
    },
    {
        "address": "16 Denison Square",
        "hcd_reference_number": 138,
        "hcd_page": 93,
        "character_sub_area": "n/a",
        "typology": "House-form, Semi-detached, Bay-and-Gable",
        "construction_date": "1890-1903",
        "building_features": ["cross-gabled roofline", "double-height bay", "decorative wooden gable brackets"],
        "statement_of_contribution": "Retains cross-gabled roofline, double-height bay, and gable brackets.",
    },
    {
        "address": "18 Denison Square",
        "hcd_reference_number": 139,
        "hcd_page": 93,
        "character_sub_area": "n/a",
        "typology": "House-form, Semi-detached, Bay-and-Gable",
        "construction_date": "1890-1903",
        "building_features": ["segmentally arched window openings", "brick voussoirs", "cladding"],
        "statement_of_contribution": "Retains segmentally arched openings with brick voussoirs.",
    },
    {
        "address": "22 Denison Square",
        "hcd_reference_number": 141,
        "hcd_page": 95,
        "character_sub_area": "n/a",
        "typology": "House-form, Row",
        "construction_date": "1904-1913",
        "building_features": ["shared roofline with prominent cross-gable", "second storey bay windows", "segmentally arched openings", "brick cladding", "decorative woodwork", "wood brackets", "shingles in gable"],
        "statement_of_contribution": "Row of three with Queen Anne Revival details. Retains decorative woodwork and gable shingles.",
    },
    {
        "address": "24 Denison Square",
        "hcd_reference_number": 142,
        "hcd_page": 95,
        "character_sub_area": "n/a",
        "typology": "House-form, Row",
        "construction_date": "1904-1913",
        "building_features": ["shared roofline with prominent cross-gable", "second storey bay windows", "segmentally arched openings", "brick cladding", "decorative woodwork", "wood brackets", "shingles in gable"],
        "statement_of_contribution": "Row of three with Queen Anne Revival details.",
    },
    {
        "address": "26 Denison Square",
        "hcd_reference_number": 143,
        "hcd_page": 95,
        "character_sub_area": "n/a",
        "typology": "House-form, Row",
        "construction_date": "1904-1913",
        "building_features": ["shared roofline with prominent cross-gable", "second storey bay windows", "segmentally arched openings", "brick cladding"],
        "statement_of_contribution": "Row of three with Queen Anne Revival details.",
    },
    # Dundas Street West
    {
        "address": "594 Dundas Street West",
        "hcd_reference_number": 145,
        "hcd_page": 96,
        "character_sub_area": "Market",
        "typology": "Commercial",
        "construction_date": "Pre-1889",
        "building_features": ["brick cladding", "decorative brickwork and stonework", "flat-headed and segmental-arched window and door openings", "leaded glass transoms", "ornamented cornice", "chamfered corner", "commercial storefront"],
        "statement_of_contribution": "Rare purpose-built Victorian commercial structure at gateway to Augusta Avenue. Associated with George Eakin Gibbard, founder of Canadian Pharmaceutical Association.",
    },
    # Fitzroy Terrace
    {
        "address": "3 Fitzroy Terrace",
        "hcd_reference_number": 146,
        "hcd_page": 97,
        "character_sub_area": "n/a",
        "typology": "House-form, Semi-detached",
        "construction_date": "Pre-1889",
        "building_features": ["shared roofline with centred gable"],
        "statement_of_contribution": "Workers' housing reflecting early development of the District.",
    },
    {
        "address": "3A Fitzroy Terrace",
        "hcd_reference_number": 147,
        "hcd_page": 97,
        "character_sub_area": "n/a",
        "typology": "House-form, Semi-detached",
        "construction_date": "Pre-1889",
        "building_features": ["shared roofline with centred gable"],
        "statement_of_contribution": "Workers' housing reflecting early development of the District.",
    },
    {
        "address": "5 Fitzroy Terrace",
        "hcd_reference_number": 148,
        "hcd_page": 98,
        "character_sub_area": "n/a",
        "typology": "House-form, Row",
        "construction_date": "1890-1903",
        "building_features": ["shared rooflines", "off-set first storey bay windows"],
        "statement_of_contribution": "Workers' row housing with Victorian features.",
    },
    {
        "address": "6 Fitzroy Terrace",
        "hcd_reference_number": 149,
        "hcd_page": 98,
        "character_sub_area": "n/a",
        "typology": "House-form, Row",
        "construction_date": "1890-1903",
        "building_features": ["shared rooflines", "off-set first storey bay windows"],
        "statement_of_contribution": "Workers' row housing with Victorian features.",
    },
    {
        "address": "7 Fitzroy Terrace",
        "hcd_reference_number": 150,
        "hcd_page": 98,
        "character_sub_area": "n/a",
        "typology": "House-form, Row",
        "construction_date": "1890-1903",
        "building_features": ["shared rooflines", "off-set first storey bay windows"],
        "statement_of_contribution": "Workers' row housing with Victorian features.",
    },
    {
        "address": "8 Fitzroy Terrace",
        "hcd_reference_number": 151,
        "hcd_page": 98,
        "character_sub_area": "n/a",
        "typology": "House-form, Detached",
        "construction_date": "1890-1903",
        "building_features": ["side gabled roofline", "ground floor bay window"],
        "statement_of_contribution": "Detached workers' housing with Victorian features.",
    },
    # Kensington Avenue (20-52)
    {
        "address": "20 Kensington Avenue",
        "hcd_reference_number": 184,
        "hcd_page": 110,
        "character_sub_area": "Market",
        "typology": "House-form, Semi-Detached, Bay-and-Gable",
        "construction_date": "Pre-1889",
        "building_features": ["mirrored facades", "cross-gabled roofline", "double-height bay windows", "round-arched attic windows", "segmentally arched fenestration", "decorative wooden bargeboard"],
        "statement_of_contribution": "Pair of semi-detached houses commercially modified but retaining Victorian features. 20 Kensington retains decorative wooden bargeboard.",
    },
    {
        "address": "22 Kensington Avenue",
        "hcd_reference_number": 186,
        "hcd_page": 110,
        "character_sub_area": "Market",
        "typology": "House-form, Semi-Detached, Bay-and-Gable",
        "construction_date": "Pre-1889",
        "building_features": ["mirrored facades", "cross-gabled roofline", "double-height bay windows", "round-arched attic windows", "segmentally arched fenestration"],
        "statement_of_contribution": "Pair of semi-detached houses commercially modified but retaining Victorian features.",
    },
    {
        "address": "21 Kensington Avenue",
        "hcd_reference_number": 185,
        "hcd_page": 111,
        "character_sub_area": "Market",
        "typology": "House-form, Row, Bay-and-Gable",
        "construction_date": "Pre-1889",
        "building_features": ["cross-gabled rooflines", "flat-headed window openings above first storey", "decorative wooden gable brackets", "pediments", "three-sided bay at first storey"],
        "statement_of_contribution": "Row retaining original Victorian features with cross-gabled rooflines.",
    },
    {
        "address": "23 Kensington Avenue",
        "hcd_reference_number": 187,
        "hcd_page": 111,
        "character_sub_area": "Market",
        "typology": "House-form, Row, Bay-and-Gable",
        "construction_date": "Pre-1889",
        "building_features": ["cross-gabled rooflines", "flat-headed window openings above first storey", "decorative wooden gable brackets", "pediments", "three-sided bay at first storey"],
        "statement_of_contribution": "Row retaining original Victorian features with cross-gabled rooflines.",
    },
    {
        "address": "25 Kensington Avenue",
        "hcd_reference_number": 189,
        "hcd_page": 111,
        "character_sub_area": "Market",
        "typology": "Converted House-form",
        "construction_date": "Pre-1889",
        "building_features": ["cross-gabled rooflines", "brick cladding", "flat-headed window openings above first storey", "one-storey commercial addition"],
        "statement_of_contribution": "Converted House-form with commercial addition, retaining original roofline and upper-storey features.",
    },
    {
        "address": "24 Kensington Avenue",
        "hcd_reference_number": 188,
        "hcd_page": 112,
        "character_sub_area": "Market",
        "typology": "Converted House-form, Semi-Detached, Bay-and-Gable",
        "construction_date": "Pre-1889, 1914-1930",
        "building_features": ["brick facade with parapet", "pressed metal cornice", "second storey window openings with brick and stone voussoirs", "pre-1889 front gable", "south gable-ended side wall"],
        "statement_of_contribution": "Two-storey commercial addition (1924-1930) over pre-1889 residential structure. Retains early-twentieth-century commercial features.",
    },
    {
        "address": "26 Kensington Avenue",
        "hcd_reference_number": 190,
        "hcd_page": 112,
        "character_sub_area": "Market",
        "typology": "House-form, Semi-Detached, Bay-and-Gable",
        "construction_date": "Pre-1889",
        "building_features": ["cross-gable roofline", "brick cladding", "double-height bay window", "decorative wooden gable brackets", "flat headed openings", "stained-glass transoms"],
        "statement_of_contribution": "Retains Victorian Bay-and-Gable features including stained-glass transoms.",
    },
    {
        "address": "27 Kensington Avenue",
        "hcd_reference_number": 191,
        "hcd_page": 113,
        "character_sub_area": "Market",
        "typology": "Converted House-form",
        "construction_date": "Pre-1889",
        "building_features": ["cross-gabled rooflines", "double-height bay windows", "brick cladding", "segmentally arched openings"],
        "statement_of_contribution": "Converted House-form retaining Victorian features including cross-gabled roofline.",
    },
    {
        "address": "29 Kensington Avenue",
        "hcd_reference_number": 193,
        "hcd_page": 113,
        "character_sub_area": "Market",
        "typology": "Converted House-form",
        "construction_date": "Pre-1889",
        "building_features": ["cross-gabled rooflines", "double-height bay windows", "brick cladding", "segmentally arched openings"],
        "statement_of_contribution": "Converted House-form retaining Victorian features.",
    },
    {
        "address": "31 Kensington Avenue",
        "hcd_reference_number": 195,
        "hcd_page": 113,
        "character_sub_area": "Market",
        "typology": "House-form, Row, Bay-and-Gable",
        "construction_date": "Pre-1889",
        "building_features": ["cross-gabled rooflines", "double-height bay windows", "brick cladding", "segmentally arched openings"],
        "statement_of_contribution": "Row house retaining Victorian features. Some openings at 31 have been modified.",
    },
    {
        "address": "33 Kensington Avenue",
        "hcd_reference_number": 197,
        "hcd_page": 113,
        "character_sub_area": "Market",
        "typology": "Converted House-form",
        "construction_date": "Pre-1889",
        "building_features": ["cross-gabled rooflines", "double-height bay windows", "brick cladding", "segmentally arched openings", "decorative wooden gable brackets", "one-storey commercial addition"],
        "statement_of_contribution": "Converted House-form with decorative gable brackets and commercial addition.",
    },
    {
        "address": "30 Kensington Avenue",
        "hcd_reference_number": 194,
        "hcd_page": 115,
        "character_sub_area": "Market",
        "typology": "House-Form, Row, Bay-and-Gable",
        "construction_date": "Pre-1889",
        "building_features": ["cross-gabled rooflines with dormers", "decorative wooden gable brackets and trim", "double-height bay windows"],
        "statement_of_contribution": "Row of four retaining Victorian features with cross-gabled rooflines and dormers.",
    },
    {
        "address": "32 Kensington Avenue",
        "hcd_reference_number": 196,
        "hcd_page": 115,
        "character_sub_area": "Market",
        "typology": "House-Form, Row, Bay-and-Gable",
        "construction_date": "Pre-1889",
        "building_features": ["cross-gabled rooflines", "decorative wooden gable brackets and trim"],
        "statement_of_contribution": "Row of four retaining Victorian Bay-and-Gable features.",
    },
    {
        "address": "34 Kensington Avenue",
        "hcd_reference_number": 198,
        "hcd_page": 115,
        "character_sub_area": "Market",
        "typology": "House-Form, Row, Bay-and-Gable",
        "construction_date": "Pre-1889",
        "building_features": ["cross-gabled rooflines", "decorative wooden gable brackets and trim"],
        "statement_of_contribution": "Row of four retaining Victorian Bay-and-Gable features.",
    },
    {
        "address": "36 Kensington Avenue",
        "hcd_reference_number": 200,
        "hcd_page": 115,
        "character_sub_area": "Market",
        "typology": "House-Form, Row, Bay-and-Gable",
        "construction_date": "Pre-1889",
        "building_features": ["cross-gabled rooflines", "double-height bay windows", "decorative wooden gable brackets and trim"],
        "statement_of_contribution": "Row of four retaining Victorian Bay-and-Gable features with double-height bays.",
    },
    # Lippincott Street (9-38)
    {
        "address": "9 Lippincott Street",
        "hcd_reference_number": 240,
        "hcd_page": 130,
        "character_sub_area": "n/a",
        "typology": "House-form, Detached, Ontario Cottage",
        "construction_date": "Pre-1889",
        "building_features": ["central gable", "entrance flanked by windows"],
        "statement_of_contribution": "Ontario Cottage House-form reflecting early workers' housing.",
    },
    {
        "address": "11 Lippincott Street",
        "hcd_reference_number": 241,
        "hcd_page": 131,
        "character_sub_area": "n/a",
        "typology": "House-form, Row, Bay-and-Gable",
        "construction_date": "Pre-1889",
        "building_features": ["cross-gabled rooflines", "double-height bays", "brick cladding", "decorative brickwork and stonework", "segmental round and flat arched openings"],
        "statement_of_contribution": "Row retaining Victorian Bay-and-Gable features with mixed arch types.",
    },
    {
        "address": "13 Lippincott Street",
        "hcd_reference_number": 243,
        "hcd_page": 131,
        "character_sub_area": "n/a",
        "typology": "House-form, Row, Bay-and-Gable",
        "construction_date": "Pre-1889",
        "building_features": ["cross-gabled rooflines", "double-height bays", "brick cladding", "decorative brickwork and stonework", "segmental round and flat arched openings"],
        "statement_of_contribution": "Row retaining Victorian Bay-and-Gable features with mixed arch types.",
    },
    {
        "address": "16 Lippincott Street",
        "hcd_reference_number": 244,
        "hcd_page": 132,
        "character_sub_area": "n/a",
        "typology": "House-form, Semi-detached",
        "construction_date": "Pre-1889",
        "building_features": ["shared roofline with central gable", "mirrored facades", "first floor bay windows", "segmental window openings", "brick cladding"],
        "statement_of_contribution": "Pair of semi-detached Victorian houses retaining original features. 16 Lippincott retains brick cladding.",
    },
    {
        "address": "18 Lippincott Street",
        "hcd_reference_number": 245,
        "hcd_page": 132,
        "character_sub_area": "n/a",
        "typology": "House-form, Semi-detached",
        "construction_date": "Pre-1889",
        "building_features": ["shared roofline with central gable", "mirrored facades", "first floor bay windows", "segmental window openings"],
        "statement_of_contribution": "Pair of semi-detached Victorian houses.",
    },
    {
        "address": "19 Lippincott Street",
        "hcd_reference_number": 246,
        "hcd_page": 133,
        "character_sub_area": "n/a",
        "typology": "House-form, Detached, Ontario Cottage",
        "construction_date": "Pre-1889",
        "building_features": ["central gable with pointed arch window", "entrance flanked by windows"],
        "statement_of_contribution": "Ontario Cottage with pointed arch gable window.",
    },
    {
        "address": "21 Lippincott Street",
        "hcd_reference_number": 247,
        "hcd_page": 134,
        "character_sub_area": "n/a",
        "typology": "House-form, Semi-detached",
        "construction_date": "Pre-1889",
        "building_features": ["shared mansard roofline", "dormer windows", "bracketed eaves", "brick cladding", "segmental and round arched openings"],
        "statement_of_contribution": "Second Empire style pair with mansard roofline, dormers, and bracketed eaves.",
    },
    {
        "address": "23 Lippincott Street",
        "hcd_reference_number": 249,
        "hcd_page": 134,
        "character_sub_area": "n/a",
        "typology": "House-form, Semi-detached",
        "construction_date": "Pre-1889",
        "building_features": ["shared mansard roofline", "dormer windows", "bracketed eaves", "brick cladding", "segmental and round arched openings"],
        "statement_of_contribution": "Second Empire style pair with mansard roofline, dormers, and bracketed eaves.",
    },
    {
        "address": "26 Lippincott Street",
        "hcd_reference_number": 250,
        "hcd_page": 136,
        "character_sub_area": "n/a",
        "typology": "House-form, Semi-detached",
        "construction_date": "1890-1903",
        "building_features": ["cross-gable roofline", "first storey bay window", "segmentally arched openings"],
        "statement_of_contribution": "Late Victorian semi-detached retaining cross-gable and bay window.",
    },
    {
        "address": "28 Lippincott Street",
        "hcd_reference_number": 251,
        "hcd_page": 137,
        "character_sub_area": "n/a",
        "typology": "House-form, Semi-detached",
        "construction_date": "Pre-1889",
        "building_features": ["shared roofline", "cross-gables", "brick cladding", "segmentally arched openings"],
        "statement_of_contribution": "Pre-1889 pair retaining original roofline and fenestration.",
    },
    {
        "address": "30 Lippincott Street",
        "hcd_reference_number": 253,
        "hcd_page": 137,
        "character_sub_area": "n/a",
        "typology": "House-form, Semi-detached",
        "construction_date": "Pre-1889",
        "building_features": ["shared roofline", "cross-gables", "brick cladding", "segmentally arched openings", "first storey bay window", "decorative brickwork", "round arched attic window"],
        "statement_of_contribution": "Pre-1889 pair with additional decorative features at #30.",
    },
    {
        "address": "29 Lippincott Street",
        "hcd_reference_number": 252,
        "hcd_page": 138,
        "character_sub_area": "n/a",
        "typology": "House-form, Detached",
        "construction_date": "Pre-1889",
        "building_features": ["side gable roof", "dormer", "round arch windows"],
        "statement_of_contribution": "Detached house retaining original side gable roof, dormer, and round arch windows.",
    },
    {
        "address": "32 Lippincott Street",
        "hcd_reference_number": 254,
        "hcd_page": 139,
        "character_sub_area": "n/a",
        "typology": "House-form, Semi-detached, Bay-and-Gable",
        "construction_date": "1890-1903",
        "building_features": ["mirrored facades", "cross-gabled roofline", "double-height bay windows", "flat headed openings"],
        "statement_of_contribution": "Late Victorian / early Edwardian pair with bay-and-gable form.",
    },
    {
        "address": "34 Lippincott Street",
        "hcd_reference_number": 255,
        "hcd_page": 139,
        "character_sub_area": "n/a",
        "typology": "House-form, Semi-detached, Bay-and-Gable",
        "construction_date": "1890-1903",
        "building_features": ["mirrored facades", "cross-gabled roofline", "double-height bay windows", "flat headed openings"],
        "statement_of_contribution": "Late Victorian / early Edwardian pair with bay-and-gable form.",
    },
    {
        "address": "36 Lippincott Street",
        "hcd_reference_number": 256,
        "hcd_page": 140,
        "character_sub_area": "n/a",
        "typology": "House-form, Row",
        "construction_date": "Pre-1889",
        "building_features": ["mansard roofline", "ground floor bay windows", "off-centre entrances"],
        "statement_of_contribution": "Second Empire style row houses with mansard roofline.",
    },
    {
        "address": "38 Lippincott Street",
        "hcd_reference_number": 257,
        "hcd_page": 140,
        "character_sub_area": "n/a",
        "typology": "House-form, Row",
        "construction_date": "Pre-1889",
        "building_features": ["mansard roofline", "ground floor bay windows", "off-centre entrances"],
        "statement_of_contribution": "Second Empire style row houses with mansard roofline.",
    },
    # Oxford Street (7-49)
    {
        "address": "7 Oxford Street",
        "hcd_reference_number": 305,
        "hcd_page": 164,
        "character_sub_area": "n/a",
        "typology": "House Form, Row, Bay-and-Gable",
        "construction_date": "Pre-1889",
        "building_features": ["shared roofline with gables", "brick cladding", "segmentally arched window and door openings", "ground level bay windows"],
        "statement_of_contribution": "Row of five (7-13) retaining Victorian features.",
    },
    {
        "address": "9 Oxford Street",
        "hcd_reference_number": 306,
        "hcd_page": 164,
        "character_sub_area": "n/a",
        "typology": "House Form, Row, Bay-and-Gable",
        "construction_date": "Pre-1889",
        "building_features": ["shared roofline with gables", "brick cladding", "segmentally arched window and door openings", "ground level bay windows"],
        "statement_of_contribution": "Row of five (7-13) retaining Victorian features.",
    },
    {
        "address": "11 Oxford Street",
        "hcd_reference_number": 307,
        "hcd_page": 164,
        "character_sub_area": "n/a",
        "typology": "House Form, Row, Bay-and-Gable",
        "construction_date": "Pre-1889",
        "building_features": ["shared roofline with gables", "brick cladding", "segmentally arched window and door openings", "ground level bay windows"],
        "statement_of_contribution": "Row of five (7-13) retaining Victorian features.",
    },
    {
        "address": "13 Oxford Street",
        "hcd_reference_number": 308,
        "hcd_page": 164,
        "character_sub_area": "n/a",
        "typology": "House Form, Row, Bay-and-Gable",
        "construction_date": "Pre-1889",
        "building_features": ["shared roofline with gables", "brick cladding", "segmentally arched window and door openings", "ground level bay windows"],
        "statement_of_contribution": "Row of five (7-13) retaining Victorian features.",
    },
    {
        "address": "15 Oxford Street",
        "hcd_reference_number": 309,
        "hcd_page": 164,
        "character_sub_area": "n/a",
        "typology": "House Form, Row, Bay-and-Gable",
        "construction_date": "Pre-1889",
        "building_features": ["brick cladding", "decorative brickwork", "mix of segmental and flat arch openings", "shallow projecting bay windows under gable", "decorative woodwork"],
        "statement_of_contribution": "End of row with additional decorative features.",
    },
    {
        "address": "18 Oxford Street",
        "hcd_reference_number": 310,
        "hcd_page": 165,
        "character_sub_area": "n/a",
        "typology": "House-form, Semi-detached, Bay-and-Gable",
        "construction_date": "Pre-1889",
        "building_features": ["shared roofline", "mirrored facades", "brick cladding", "decorative brickwork", "mix of rounded and flat arched openings", "projecting bay windows set under gables", "decorative woodwork"],
        "statement_of_contribution": "Pair with decorative brickwork and projecting gabled bays.",
    },
    {
        "address": "20 Oxford Street",
        "hcd_reference_number": 312,
        "hcd_page": 165,
        "character_sub_area": "n/a",
        "typology": "House-form, Semi-detached, Bay-and-Gable",
        "construction_date": "Pre-1889",
        "building_features": ["shared roofline", "mirrored facades", "brick cladding", "decorative brickwork", "mix of rounded and flat arched openings", "projecting bay windows set under gables", "decorative woodwork"],
        "statement_of_contribution": "Pair with decorative brickwork and projecting gabled bays.",
    },
    {
        "address": "19 Oxford Street",
        "hcd_reference_number": 311,
        "hcd_page": 166,
        "character_sub_area": "n/a",
        "typology": "House-form, Semi-detached",
        "construction_date": "1904-1913",
        "building_features": ["shared roofline", "mirrored facades", "brick cladding", "decorative brickwork and stonework", "mix of rounded and flat arch openings", "recessed front entrances", "gables with decorative woodwork", "recessed balconies"],
        "statement_of_contribution": "Edwardian pair with Queen Anne Revival and Victorian details, including recessed balconies.",
    },
    {
        "address": "21 Oxford Street",
        "hcd_reference_number": 313,
        "hcd_page": 166,
        "character_sub_area": "n/a",
        "typology": "House-form, Semi-detached",
        "construction_date": "1904-1913",
        "building_features": ["shared roofline", "mirrored facades", "brick cladding", "decorative brickwork and stonework", "mix of rounded and flat arch openings", "recessed front entrances", "gables with decorative woodwork", "recessed balconies"],
        "statement_of_contribution": "Edwardian pair with Queen Anne Revival and Victorian details.",
    },
    {
        "address": "23 Oxford Street",
        "hcd_reference_number": 314,
        "hcd_page": 167,
        "character_sub_area": "n/a",
        "typology": "House-form, Semi-detached, Bay-and-Gable",
        "construction_date": "Pre-1889",
        "building_features": ["shared roofline", "mirrored facades", "brick cladding", "decorative brickwork", "mix of segmental and flat arch openings", "shallow projecting bay windows set under gables", "decorative woodwork"],
        "statement_of_contribution": "Victorian pair with Bay-and-Gable form.",
    },
    {
        "address": "25 Oxford Street",
        "hcd_reference_number": 315,
        "hcd_page": 167,
        "character_sub_area": "n/a",
        "typology": "House-form, Semi-detached, Bay-and-Gable",
        "construction_date": "Pre-1889",
        "building_features": ["shared roofline", "mirrored facades", "brick cladding", "decorative brickwork", "mix of segmental and flat arch openings", "shallow projecting bay windows set under gables", "decorative woodwork"],
        "statement_of_contribution": "Victorian pair with Bay-and-Gable form.",
    },
    {
        "address": "27 Oxford Street",
        "hcd_reference_number": 316,
        "hcd_page": 168,
        "character_sub_area": "n/a",
        "typology": "House-form, Semi-detached, Bay-and-Gable",
        "construction_date": "Pre-1889",
        "building_features": ["shared roofline", "mirrored facades", "brick cladding", "decorative brickwork", "mix of segmental and flat arched openings", "shallow projecting bay windows set under gables", "decorative woodwork"],
        "statement_of_contribution": "Victorian pair with Bay-and-Gable form.",
    },
    {
        "address": "29 Oxford Street",
        "hcd_reference_number": 317,
        "hcd_page": 168,
        "character_sub_area": "n/a",
        "typology": "House-form, Semi-detached, Bay-and-Gable",
        "construction_date": "Pre-1889",
        "building_features": ["shared roofline", "mirrored facades", "brick cladding", "decorative brickwork", "mix of segmental and flat arched openings", "shallow projecting bay windows set under gables", "decorative woodwork"],
        "statement_of_contribution": "Victorian pair with Bay-and-Gable form.",
    },
    {
        "address": "33 Oxford Street",
        "hcd_reference_number": 318,
        "hcd_page": 169,
        "character_sub_area": "n/a",
        "typology": "House-form, Semi-detached, Bay-and-Gable",
        "construction_date": "Pre-1889",
        "building_features": ["shared roofline with gables", "first storey projecting bay windows", "brick cladding", "mix of flat and round arched openings", "decorative wooden bargeboards"],
        "statement_of_contribution": "Victorian pair with projecting bays and decorative bargeboards.",
    },
    {
        "address": "35 Oxford Street",
        "hcd_reference_number": 319,
        "hcd_page": 170,
        "character_sub_area": "n/a",
        "typology": "Multi-residential",
        "construction_date": "Pre-1889",
        "building_features": ["shared parapet", "segmentally arched window and door openings", "separate paired entrances", "two-storey verandah extending full width"],
        "statement_of_contribution": "Rare early residential duplex with two-storey verandah.",
    },
    {
        "address": "37 Oxford Street",
        "hcd_reference_number": 320,
        "hcd_page": 170,
        "character_sub_area": "n/a",
        "typology": "Multi-residential",
        "construction_date": "Pre-1889",
        "building_features": ["shared parapet", "segmentally arched window and door openings", "separate paired entrances", "two-storey verandah extending full width"],
        "statement_of_contribution": "Rare early residential duplex with two-storey verandah.",
    },
    {
        "address": "39 Oxford Street",
        "hcd_reference_number": 321,
        "hcd_page": 171,
        "character_sub_area": "n/a",
        "typology": "House-form, Semi-detached",
        "construction_date": "Pre-1889",
        "building_features": ["shared mansard roofline", "round-arched dormers", "wood scrollwork trim", "first-storey bay windows with round-arch window openings", "raised front entrances with segmentally arched transoms"],
        "statement_of_contribution": "Second Empire style pair with mansard roofline and ornamental details.",
    },
    {
        "address": "41 Oxford Street",
        "hcd_reference_number": 322,
        "hcd_page": 171,
        "character_sub_area": "n/a",
        "typology": "House-form, Semi-detached",
        "construction_date": "Pre-1889",
        "building_features": ["shared mansard roofline", "round-arched dormers", "wood scrollwork trim", "first-storey bay windows with round-arch window openings", "raised front entrances with segmentally arched transoms"],
        "statement_of_contribution": "Second Empire style pair with mansard roofline and ornamental details.",
    },
    {
        "address": "45 Oxford Street",
        "hcd_reference_number": 324,
        "hcd_page": 173,
        "character_sub_area": "n/a",
        "typology": "House-form, Semi-detached, Bay-and-Gable",
        "construction_date": "Pre-1889",
        "building_features": ["shared roofline", "mirrored facades", "brick cladding", "decorative brickwork and stonework", "mix of rounded and flat arch openings", "projecting gabled bays with three-sided bay windows"],
        "statement_of_contribution": "Victorian pair with projecting gabled three-sided bays.",
    },
    {
        "address": "47 Oxford Street",
        "hcd_reference_number": 325,
        "hcd_page": 173,
        "character_sub_area": "n/a",
        "typology": "House-form, Semi-detached, Bay-and-Gable",
        "construction_date": "Pre-1889",
        "building_features": ["shared roofline", "mirrored facades", "brick cladding", "decorative brickwork and stonework", "mix of rounded and flat arch openings", "projecting gabled bays with three-sided bay windows"],
        "statement_of_contribution": "Victorian pair with projecting gabled three-sided bays.",
    },
    {
        "address": "49 Oxford Street",
        "hcd_reference_number": 326,
        "hcd_page": 174,
        "character_sub_area": "n/a",
        "typology": "House-form, Semi-detached, Bay-and-Gable",
        "construction_date": "Pre-1889",
        "building_features": ["cross-gabled roofline", "double-height projecting bay", "decorative dichromatic brickwork at second storey", "segmental and round arch openings"],
        "statement_of_contribution": "Victorian Bay-and-Gable with dichromatic brickwork.",
    },
    # Nassau Street (8-36)
    {
        "address": "8 Nassau Street",
        "hcd_reference_number": 261,
        "hcd_page": 143,
        "character_sub_area": "n/a",
        "typology": "House-form, Semi-detached",
        "construction_date": "1890-1903",
        "building_features": ["shared roofline with projecting central gable", "mirrored facades", "brick cladding", "brick voussoirs", "second storey oriel windows"],
        "statement_of_contribution": "Late Victorian pair with central gable and oriel windows.",
    },
    {
        "address": "10 Nassau Street",
        "hcd_reference_number": 262,
        "hcd_page": 143,
        "character_sub_area": "n/a",
        "typology": "House-form, Semi-detached",
        "construction_date": "1890-1903",
        "building_features": ["shared roofline with projecting central gable", "mirrored facades", "brick cladding", "brick voussoirs", "second storey oriel windows"],
        "statement_of_contribution": "Late Victorian pair with central gable and oriel windows.",
    },
    {
        "address": "12 Nassau Street",
        "hcd_reference_number": 263,
        "hcd_page": 144,
        "character_sub_area": "n/a",
        "typology": "House-form, Semi-detached",
        "construction_date": "1890-1903",
        "building_features": ["shared roofline with projecting central gable", "mirrored facades", "brick cladding", "brick voussoirs", "second storey oriel windows"],
        "statement_of_contribution": "Late Victorian pair with central gable and oriel windows.",
    },
    {
        "address": "14 Nassau Street",
        "hcd_reference_number": 264,
        "hcd_page": 144,
        "character_sub_area": "n/a",
        "typology": "House-form, Semi-detached",
        "construction_date": "1890-1903",
        "building_features": ["shared roofline with projecting central gable", "mirrored facades", "brick cladding", "brick voussoirs", "second storey oriel windows"],
        "statement_of_contribution": "Late Victorian pair with central gable and oriel windows.",
    },
    {
        "address": "18 Nassau Street",
        "hcd_reference_number": 265,
        "hcd_page": 145,
        "character_sub_area": "n/a",
        "typology": "House-form, Row",
        "construction_date": "1890-1903",
        "building_features": ["shared roofline with central gable featuring wood shingles", "decorative brickwork", "stone sills and lintels on second storey", "round arched openings at first storey"],
        "statement_of_contribution": "Row with Queen Anne Revival details including wood shingles in gable.",
    },
    {
        "address": "20 Nassau Street",
        "hcd_reference_number": 267,
        "hcd_page": 146,
        "character_sub_area": "n/a",
        "typology": "House-form, Semi-detached, Bay-and-Gable",
        "construction_date": "Pre-1889",
        "building_features": ["cross-gabled rooflines", "mirrored facades", "brick cladding", "decorative brickwork", "double-height bay windows", "segmental and round arch openings"],
        "statement_of_contribution": "Victorian pair with Bay-and-Gable form and decorative brickwork.",
    },
    {
        "address": "22 Nassau Street",
        "hcd_reference_number": 268,
        "hcd_page": 146,
        "character_sub_area": "n/a",
        "typology": "House-form, Semi-detached, Bay-and-Gable",
        "construction_date": "Pre-1889",
        "building_features": ["cross-gabled rooflines", "mirrored facades", "brick cladding", "decorative brickwork", "double-height bay windows", "segmental and round arch openings"],
        "statement_of_contribution": "Victorian pair with Bay-and-Gable form and decorative brickwork.",
    },
    {
        "address": "26 Nassau Street",
        "hcd_reference_number": 269,
        "hcd_page": 147,
        "character_sub_area": "n/a",
        "typology": "House-form, Semi-detached",
        "construction_date": "Pre-1889",
        "building_features": ["shared gable-ended roofline", "mirrored facades", "brick cladding", "decorative brickwork", "segmentally arched openings"],
        "statement_of_contribution": "Victorian pair with gable-ended roofline.",
    },
    {
        "address": "28 Nassau Street",
        "hcd_reference_number": 270,
        "hcd_page": 147,
        "character_sub_area": "n/a",
        "typology": "House-form, Semi-detached",
        "construction_date": "Pre-1889",
        "building_features": ["shared gable-ended roofline", "mirrored facades", "brick cladding", "decorative brickwork", "segmentally arched openings"],
        "statement_of_contribution": "Victorian pair with gable-ended roofline.",
    },
    {
        "address": "29 Nassau Street",
        "hcd_reference_number": 271,
        "hcd_page": 148,
        "character_sub_area": "n/a",
        "typology": "House-form, Row, Bay-and-Gable",
        "construction_date": "1890-1903",
        "building_features": ["cross-gabled rooflines", "double-height bay windows", "brick cladding", "decorative wooden gable brackets and pediments", "flat headed openings featuring stone lintels and sills"],
        "statement_of_contribution": "Row of three (29-33) with Bay-and-Gable form and decorative details.",
    },
    {
        "address": "31 Nassau Street",
        "hcd_reference_number": 272,
        "hcd_page": 148,
        "character_sub_area": "n/a",
        "typology": "House-form, Row, Bay-and-Gable",
        "construction_date": "1890-1903",
        "building_features": ["cross-gabled rooflines", "double-height bay windows", "brick cladding", "decorative wooden gable brackets and pediments", "flat headed openings featuring stone lintels and sills"],
        "statement_of_contribution": "Row of three (29-33) with Bay-and-Gable form.",
    },
    {
        "address": "33 Nassau Street",
        "hcd_reference_number": 273,
        "hcd_page": 148,
        "character_sub_area": "n/a",
        "typology": "House-form, Row, Bay-and-Gable",
        "construction_date": "1890-1903",
        "building_features": ["cross-gabled rooflines", "double-height bay windows", "brick cladding", "decorative wooden gable brackets and pediments", "flat headed openings featuring stone lintels and sills"],
        "statement_of_contribution": "Row of three (29-33) with Bay-and-Gable form.",
    },
    {
        "address": "34 Nassau Street",
        "hcd_reference_number": 274,
        "hcd_page": 149,
        "character_sub_area": "n/a",
        "typology": "House-form, Semi-detached",
        "construction_date": "1914-1930",
        "building_features": ["shared roofline", "mirrored facades", "dormer windows above second storey bay windows", "brick cladding", "flat headed openings", "stone lintels"],
        "statement_of_contribution": "Early 20th century pair with dormers and bay windows.",
    },
    {
        "address": "36 Nassau Street",
        "hcd_reference_number": 275,
        "hcd_page": 149,
        "character_sub_area": "n/a",
        "typology": "House-form, Semi-detached",
        "construction_date": "1914-1930",
        "building_features": ["shared roofline", "mirrored facades", "dormer windows above second storey bay windows", "brick cladding", "flat headed openings", "stone lintels"],
        "statement_of_contribution": "Early 20th century pair with dormers and bay windows.",
    },
]


def main():
    PARAMS_DIR.mkdir(exist_ok=True)

    # Get existing files to skip
    existing = {f.stem for f in PARAMS_DIR.glob("*.json") if not f.name.startswith("_")}

    created = 0
    skipped = 0
    for bldg in HCD_BUILDINGS:
        filename, params = generate_param_file(bldg)
        stem = Path(filename).stem
        if stem in existing:
            print(f"  [SKIP] {filename} (already exists)")
            skipped += 1
            continue

        filepath = PARAMS_DIR / filename
        with open(filepath, "w") as fp:
            json.dump(params, fp, indent=2)
        print(f"  [NEW]  {filename} (HCD #{bldg['hcd_reference_number']})")
        created += 1

    # Update analysis summary
    summary_path = PARAMS_DIR / "_analysis_summary.json"
    if summary_path.exists():
        with open(summary_path) as fp:
            summary = json.load(fp)
    else:
        summary = {}

    all_files = sorted(PARAMS_DIR.glob("*.json"))
    all_files = [f for f in all_files if not f.name.startswith("_")]

    summary["total"] = len(all_files)
    summary["photo_analyzed"] = 10
    summary["hcd_skeleton"] = created + skipped
    summary["timestamp"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

    with open(summary_path, "w") as fp:
        json.dump(summary, fp, indent=2)

    print(f"\n=== Summary ===")
    print(f"Created: {created}")
    print(f"Skipped (existing): {skipped}")
    print(f"Total param files: {len(all_files)}")


if __name__ == "__main__":
    main()
