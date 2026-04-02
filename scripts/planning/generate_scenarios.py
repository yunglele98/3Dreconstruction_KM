#!/usr/bin/env python3
"""Generate realistic scenario interventions from building data.

Reads params-slim.json and produces interventions.json for each of the
5 scenario directories. Uses actual building data (condition, contributing
status, roof type, floors) to select appropriate candidates.

Usage:
    python scripts/planning/generate_scenarios.py
"""

import json
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
SLIM = REPO / "web" / "public" / "data" / "params-slim.json"
SCENARIOS = REPO / "scenarios"


def load_data():
    return json.loads(SLIM.read_text(encoding="utf-8"))


def write_scenario(name, scenario):
    out = SCENARIOS / name / "interventions.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(scenario, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"  {name}: {len(scenario['interventions'])} interventions -> {out}")


def generate_heritage_first(data):
    interventions = []

    # Heritage restore: contributing + poor condition
    hrc = [b for b in data if b.get("contributing") == "Yes"
           and (b.get("condition") or "").lower() == "poor"]
    for b in hrc[:25]:
        interventions.append({
            "address": b["address"],
            "type": "heritage_restore",
            "params_override": {"condition": "good"},
        })

    # Facade renovation: contributing + fair on main streets
    fair_contrib = [b for b in data if b.get("contributing") == "Yes"
                    and (b.get("condition") or "").lower() == "fair"
                    and b.get("street") in ["Augusta Ave", "Kensington Ave", "Baldwin St", "Nassau St"]]
    for b in fair_contrib[:15]:
        interventions.append({
            "address": b["address"],
            "type": "facade_renovation",
            "params_override": {"condition": "good"},
        })

    return {
        "scenario_id": "heritage_first",
        "name": "Heritage First (2036)",
        "description": "Maximum heritage preservation: restore 25 contributing buildings in poor condition, renovate 15 fair-condition facades on key commercial streets.",
        "principles": [
            "Prioritize contributing buildings in poor condition",
            "Restore original brick, trim, and decorative elements",
            "No height additions to heritage buildings",
            "Focus investment on market-facing streets",
            "Use HCD guidelines for all material choices",
        ],
        "interventions": interventions,
        "impact": {
            "heritage_restorations": sum(1 for i in interventions if i["type"] == "heritage_restore"),
            "facade_renovations": sum(1 for i in interventions if i["type"] == "facade_renovation"),
            "dwelling_units_added": 0,
            "fsi_change": "0",
            "height_changes": 0,
        },
    }


def generate_mixed_use(data):
    interventions = []

    # Convert ground floors on side streets
    side_streets = ["Nassau St", "Oxford St", "Wales Ave", "Lippincott St"]
    no_sf = [b for b in data if b.get("street") in side_streets
             and not b.get("has_storefront") and b.get("contributing") != "Yes"]
    for b in no_sf[:12]:
        interventions.append({
            "address": b["address"],
            "type": "convert_ground",
            "params_override": {"has_storefront": True},
        })

    # Add floors on perimeter arterials
    perim = ["College St", "Spadina Ave", "Dundas St W", "Bathurst St"]
    add_fl = [b for b in data if b.get("street") in perim
              and (b.get("floors") or 0) <= 2 and b.get("contributing") != "Yes"]
    for b in add_fl[:10]:
        interventions.append({
            "address": b["address"],
            "type": "add_floor",
            "params_override": {"floors": 3},
        })

    # Signage updates on market streets
    market_sf = [b for b in data if b.get("street") in ["Augusta Ave", "Kensington Ave"]
                 and b.get("has_storefront")]
    for b in market_sf[:8]:
        interventions.append({
            "address": b["address"],
            "type": "signage_update",
            "params_override": {},
        })

    return {
        "scenario_id": "mixed_use",
        "name": "Mixed Use Intensification (2036)",
        "description": "Ground-floor commercial conversion on residential side streets, modest density on perimeter arterials, market signage refresh.",
        "principles": [
            "Extend commercial frontage to side streets near market core",
            "Add density only on perimeter arterials, not heritage core",
            "Preserve market character while improving economic activity",
            "Support small-scale retail and maker spaces",
            "Maintain residential upper floors",
        ],
        "interventions": interventions,
        "impact": {
            "commercial_conversions": sum(1 for i in interventions if i["type"] == "convert_ground"),
            "height_changes": sum(1 for i in interventions if i["type"] == "add_floor"),
            "dwelling_units_added": sum(2 for i in interventions if i["type"] == "add_floor"),
            "fsi_change": "+0.08",
        },
    }


def generate_green_infra(data):
    interventions = []

    # Green roofs on flat-roof buildings in good/fair condition
    flat_good = [b for b in data if (b.get("roof_type") or "").lower() == "flat"
                 and (b.get("condition") or "").lower() in ("good", "fair")
                 and b.get("lon") and b.get("lat")]
    for b in flat_good[:30]:
        green_type = "extensive" if (b.get("floors") or 0) <= 2 else "intensive"
        interventions.append({
            "address": b["address"],
            "type": "green_roof",
            "params_override": {"green_roof_type": green_type},
        })

    # Tree planting corridors
    tree_streets = [
        {"street": "Kensington Ave", "segment": "Dundas to Baldwin", "count": 12, "lon": -79.4005, "lat": 43.6540},
        {"street": "Augusta Ave", "segment": "Dundas to College", "count": 18, "lon": -79.4025, "lat": 43.6550},
        {"street": "Nassau St", "segment": "Augusta to Bellevue", "count": 8, "lon": -79.4010, "lat": 43.6558},
        {"street": "Oxford St", "segment": "Augusta to Bellevue", "count": 10, "lon": -79.4015, "lat": 43.6535},
        {"street": "Baldwin St", "segment": "Kensington to Augusta", "count": 6, "lon": -79.4015, "lat": 43.6545},
        {"street": "Wales Ave", "segment": "full length", "count": 8, "lon": -79.3995, "lat": 43.6548},
    ]
    for ts in tree_streets:
        interventions.append({
            "address": "STREET_" + ts["street"].replace(" ", "_"),
            "type": "tree_planting",
            "lon": ts["lon"],
            "lat": ts["lat"],
            "params_override": {
                "street": ts["street"],
                "segment": ts["segment"],
                "trees_added": ts["count"],
                "species": "mixed native",
            },
        })

    total_trees = sum(ts["count"] for ts in tree_streets)

    return {
        "scenario_id": "green_infra",
        "name": "Green Infrastructure (2036)",
        "description": f"Extensive green roofs on 30 flat-roof buildings, {total_trees} new street trees across 6 corridors. Focus on stormwater management and urban heat reduction.",
        "principles": [
            "Extensive green roofs on flat-roof buildings (lower weight load)",
            "Intensive green roofs only on structurally-suitable 3+ floor buildings",
            "Native species for street trees (climate-resilient)",
            "Prioritize streets with lowest existing canopy",
            "Integrate rain gardens at key intersections",
        ],
        "interventions": interventions,
        "impact": {
            "green_roofs": sum(1 for i in interventions if i["type"] == "green_roof"),
            "trees_planted": total_trees,
            "dwelling_units_added": 0,
            "fsi_change": "0",
            "height_changes": 0,
        },
    }


def generate_mobility(data):
    interventions = []

    # Pedestrianize Augusta Ave market section
    interventions.append({
        "address": "STREET_Augusta_Ave_Market",
        "type": "pedestrianize",
        "lon": -79.4025,
        "lat": 43.6548,
        "params_override": {
            "street": "Augusta Ave",
            "segment": "Nassau St to Baldwin St",
            "treatment": "full pedestrianization",
            "description": "Close to vehicles, widen sidewalks, add market stalls and seating",
        },
    })

    # Pedestrianize Kensington Ave core (shared street)
    interventions.append({
        "address": "STREET_Kensington_Ave_Core",
        "type": "pedestrianize",
        "lon": -79.4005,
        "lat": 43.6542,
        "params_override": {
            "street": "Kensington Ave",
            "segment": "Dundas St W to St Andrew St",
            "treatment": "shared street (woonerf)",
            "description": "Reduce speed to walking pace, remove curbs, add bollards",
        },
    })

    # Bike infrastructure on collector streets
    bike_streets = [
        {"street": "Baldwin St", "segment": "Spadina to Augusta", "treatment": "protected bike lane", "lon": -79.4015, "lat": 43.6545},
        {"street": "Nassau St", "segment": "Spadina to Bathurst", "treatment": "contraflow bike lane", "lon": -79.4010, "lat": 43.6558},
        {"street": "Oxford St", "segment": "Augusta to Spadina", "treatment": "bike boulevard (sharrow)", "lon": -79.4015, "lat": 43.6535},
        {"street": "Bellevue Ave", "segment": "Dundas to College", "treatment": "protected bike lane", "lon": -79.4035, "lat": 43.6545},
    ]
    for bs in bike_streets:
        interventions.append({
            "address": "STREET_" + bs["street"].replace(" ", "_"),
            "type": "bike_infra",
            "lon": bs["lon"],
            "lat": bs["lat"],
            "params_override": {
                "street": bs["street"],
                "segment": bs["segment"],
                "treatment": bs["treatment"],
            },
        })

    # Bike parking at key intersections
    interventions.append({
        "address": "BIKE_PARKING_Augusta_Baldwin",
        "type": "bike_infra",
        "lon": -79.4025,
        "lat": 43.6545,
        "params_override": {"type": "bike_parking", "location": "Augusta Ave & Baldwin St", "capacity": 24},
    })
    interventions.append({
        "address": "BIKE_PARKING_Kensington_StAndrew",
        "type": "bike_infra",
        "lon": -79.4005,
        "lat": 43.6537,
        "params_override": {"type": "bike_parking", "location": "Kensington Ave & St Andrew St", "capacity": 16},
    })

    # Patios on pedestrianized Augusta Ave
    patio_bldgs = [b for b in data if b.get("street") == "Augusta Ave" and b.get("has_storefront")]
    for b in patio_bldgs[:6]:
        interventions.append({
            "address": b["address"],
            "type": "add_patio",
            "params_override": {"patio_depth_m": 2.5, "patio_type": "seasonal"},
        })

    return {
        "scenario_id": "mobility",
        "name": "Sustainable Mobility (2036)",
        "description": "Pedestrianize Augusta Ave market section and Kensington Ave core, add protected bike lanes on 4 streets, install bike parking, and seasonal patios.",
        "principles": [
            "Prioritize pedestrians in market core",
            "Connected bike network through neighbourhood",
            "Maintain vehicle access for deliveries (time-restricted)",
            "Add seating and gathering spaces on pedestrianized streets",
            "Support seasonal patios for market businesses",
        ],
        "interventions": interventions,
        "impact": {
            "pedestrianized_streets": 2,
            "bike_lanes_km": 3.2,
            "bike_parking_spaces": 40,
            "patios_added": 6,
            "dwelling_units_added": 0,
            "fsi_change": "0",
            "height_changes": 0,
        },
    }


def generate_metadata(scenario_id, scenario):
    """Write metadata.json for a scenario."""
    meta = {
        "scenario_id": scenario_id,
        "name": scenario["name"],
        "description": scenario["description"],
        "created": "2026-04-02",
        "author": "planning-agent",
        "total_interventions": len(scenario["interventions"]),
        "intervention_types": {},
        "principles": scenario.get("principles", []),
    }
    from collections import Counter
    types = Counter(i["type"] for i in scenario["interventions"])
    meta["intervention_types"] = dict(types)
    return meta


def main():
    print("Loading building data...")
    data = load_data()
    print(f"  {len(data)} buildings loaded")

    print("\nGenerating scenarios:")

    scenarios = {
        "10yr_heritage_first": generate_heritage_first(data),
        "10yr_mixed_use": generate_mixed_use(data),
        "10yr_green_infra": generate_green_infra(data),
        "10yr_mobility": generate_mobility(data),
    }

    for name, scenario in scenarios.items():
        write_scenario(name, scenario)
        # Write metadata
        meta = generate_metadata(scenario["scenario_id"], scenario)
        meta_path = SCENARIOS / name / "metadata.json"
        meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # Also update web scenario files
    web_scenarios = REPO / "web" / "public" / "data" / "scenarios"
    web_scenarios.mkdir(parents=True, exist_ok=True)
    for name, scenario in scenarios.items():
        short_name = name.replace("10yr_", "")
        out = web_scenarios / f"{short_name}.json"
        out.write_text(json.dumps(scenario, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"  web: {out.name}")

    print("\nDone.")


if __name__ == "__main__":
    main()
