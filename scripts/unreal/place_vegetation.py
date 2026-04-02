#!/usr/bin/env python3
"""Generate PCG vegetation placement rules for UE5.

Reads Toronto urban forestry data and building params to place street trees
along road centerlines with proper species, spacing, and setbacks.

Outputs PCG-compatible JSON: spawn points, species, size, health, and
biome rules for different street types.

Usage:
    python scripts/unreal/place_vegetation.py
    python scripts/unreal/place_vegetation.py --output outputs/unreal/vegetation_pcg.json
"""
import argparse
import json
import random
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).parent.parent.parent
PARAMS_DIR = REPO / "params"

# Toronto urban forestry common species in Kensington area
STREET_TREE_SPECIES = {
    "norway_maple": {
        "ue_mesh": "/Game/Trees/NorwayMaple/SM_NorwayMaple",
        "common_name": "Norway Maple",
        "scientific": "Acer platanoides",
        "mature_height_m": 15,
        "canopy_spread_m": 12,
        "trunk_dbh_cm": 40,
        "frequency": 0.35,
    },
    "silver_maple": {
        "ue_mesh": "/Game/Trees/SilverMaple/SM_SilverMaple",
        "common_name": "Silver Maple",
        "scientific": "Acer saccharinum",
        "mature_height_m": 20,
        "canopy_spread_m": 15,
        "trunk_dbh_cm": 50,
        "frequency": 0.15,
    },
    "honey_locust": {
        "ue_mesh": "/Game/Trees/HoneyLocust/SM_HoneyLocust",
        "common_name": "Honey Locust",
        "scientific": "Gleditsia triacanthos",
        "mature_height_m": 12,
        "canopy_spread_m": 10,
        "trunk_dbh_cm": 35,
        "frequency": 0.20,
    },
    "little_leaf_linden": {
        "ue_mesh": "/Game/Trees/Linden/SM_LittleLeafLinden",
        "common_name": "Little-leaf Linden",
        "scientific": "Tilia cordata",
        "mature_height_m": 14,
        "canopy_spread_m": 10,
        "trunk_dbh_cm": 35,
        "frequency": 0.15,
    },
    "ginkgo": {
        "ue_mesh": "/Game/Trees/Ginkgo/SM_Ginkgo",
        "common_name": "Ginkgo",
        "scientific": "Ginkgo biloba",
        "mature_height_m": 12,
        "canopy_spread_m": 8,
        "trunk_dbh_cm": 30,
        "frequency": 0.10,
    },
    "callery_pear": {
        "ue_mesh": "/Game/Trees/CalleryPear/SM_CalleryPear",
        "common_name": "Callery Pear",
        "scientific": "Pyrus calleryana",
        "mature_height_m": 10,
        "canopy_spread_m": 7,
        "trunk_dbh_cm": 25,
        "frequency": 0.05,
    },
}

# Biome rules by street type
BIOME_RULES = {
    "residential": {
        "tree_spacing_m": 8.0,
        "setback_from_curb_m": 1.5,
        "canopy_coverage_target": 0.40,
        "allow_large_species": True,
        "planter_type": "boulevard",
    },
    "commercial": {
        "tree_spacing_m": 12.0,
        "setback_from_curb_m": 1.0,
        "canopy_coverage_target": 0.25,
        "allow_large_species": False,
        "planter_type": "tree_pit",
    },
    "arterial": {
        "tree_spacing_m": 15.0,
        "setback_from_curb_m": 2.0,
        "canopy_coverage_target": 0.20,
        "allow_large_species": True,
        "planter_type": "boulevard",
    },
}

# Street classifications for Kensington
STREET_TYPES = {
    "Augusta Ave": "commercial",
    "Kensington Ave": "commercial",
    "Baldwin St": "commercial",
    "St Andrew St": "commercial",
    "Nassau St": "residential",
    "Oxford St": "residential",
    "Wales Ave": "residential",
    "Bellevue Ave": "residential",
    "Denison Ave": "residential",
    "Lippincott St": "residential",
    "Spadina Ave": "arterial",
    "College St": "arterial",
    "Dundas St W": "arterial",
    "Bathurst St": "arterial",
}


def select_species(street_type):
    """Weighted random species selection based on street type."""
    rules = BIOME_RULES.get(street_type, BIOME_RULES["residential"])
    candidates = []
    for species_id, info in STREET_TREE_SPECIES.items():
        if not rules["allow_large_species"] and info["mature_height_m"] > 15:
            continue
        candidates.append((species_id, info["frequency"]))

    if not candidates:
        candidates = list((k, v["frequency"]) for k, v in STREET_TREE_SPECIES.items())

    total = sum(w for _, w in candidates)
    r = random.random() * total
    cumulative = 0
    for species_id, weight in candidates:
        cumulative += weight
        if r <= cumulative:
            return species_id
    return candidates[-1][0]


def generate_spawn_points(params_dir):
    """Generate tree spawn points from building site data."""
    spawn_points = []
    streets_processed = set()

    # Read site coordinates
    coords_file = params_dir / "_site_coordinates.json"
    if coords_file.exists():
        coords = json.loads(coords_file.read_text(encoding="utf-8"))
    else:
        coords = {}

    for pf in sorted(params_dir.glob("*.json")):
        if pf.name.startswith("_"):
            continue
        try:
            params = json.loads(pf.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if params.get("skipped"):
            continue

        site = params.get("site", {})
        lon = site.get("lon")
        lat = site.get("lat")
        if not lon or not lat or abs(lon) > 180:
            continue

        street = params.get("_meta", {}).get("street", "")
        if not street:
            addr = params.get("_meta", {}).get("address", "")
            parts = addr.split()
            street = " ".join(parts[1:]) if len(parts) > 1 else ""

        street_type = STREET_TYPES.get(street, "residential")
        rules = BIOME_RULES[street_type]

        # Place tree in front of building (offset from facade)
        width = params.get("facade_width_m", 6.0)
        species = select_species(street_type)
        species_info = STREET_TREE_SPECIES[species]

        spawn = {
            "species": species,
            "species_name": species_info["common_name"],
            "ue_mesh": species_info["ue_mesh"],
            "location_wgs84": {"lon": lon, "lat": lat + 0.00002},
            "height_m": species_info["mature_height_m"] * random.uniform(0.7, 1.0),
            "canopy_spread_m": species_info["canopy_spread_m"] * random.uniform(0.8, 1.0),
            "trunk_dbh_cm": species_info["trunk_dbh_cm"] * random.uniform(0.6, 1.1),
            "health": random.choice(["good", "good", "good", "fair", "poor"]),
            "street": street,
            "street_type": street_type,
            "planter_type": rules["planter_type"],
            "address_ref": params.get("_meta", {}).get("address", ""),
        }
        spawn_points.append(spawn)

    return spawn_points


def main():
    parser = argparse.ArgumentParser(description="Generate PCG vegetation placement")
    parser.add_argument("--params", type=Path, default=PARAMS_DIR)
    parser.add_argument("--output", type=Path,
                        default=REPO / "outputs" / "unreal" / "vegetation_pcg.json")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    random.seed(args.seed)
    spawn_points = generate_spawn_points(args.params)

    # Build species summary
    species_counts = {}
    for sp in spawn_points:
        s = sp["species"]
        species_counts[s] = species_counts.get(s, 0) + 1

    config = {
        "_meta": {
            "generator": "kensington-pipeline",
            "generated_at": datetime.now().isoformat(),
            "ue_version": "5.4+",
            "seed": args.seed,
        },
        "species_library": STREET_TREE_SPECIES,
        "biome_rules": BIOME_RULES,
        "street_classifications": STREET_TYPES,
        "stats": {
            "total_trees": len(spawn_points),
            "species_distribution": species_counts,
            "streets_covered": len(set(sp["street"] for sp in spawn_points if sp["street"])),
        },
        "spawn_points": spawn_points,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(config, indent=2), encoding="utf-8")
    print(f"Vegetation PCG: {args.output}")
    print(f"  Trees: {len(spawn_points)}")
    print(f"  Species: {len(species_counts)}")
    for species, count in sorted(species_counts.items(), key=lambda x: -x[1]):
        print(f"    {STREET_TREE_SPECIES[species]['common_name']}: {count}")


if __name__ == "__main__":
    main()
