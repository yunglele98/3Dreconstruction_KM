#!/usr/bin/env python3
"""Stage 3: Enrich building params with rear facade observations from panoramic photos.

Rooftop panoramas capture the backs of Kensington buildings -- rear additions,
party wall materials, backyard structures, laneway access, and roof details
not visible from street level. This script stores observations that inform:
- Party wall generation (material, window presence)
- Rear addition volumes (for multi-volume buildings)
- Roof type/colour validation from above
- Backyard depth estimation
- Laneway building candidates for gentle density scenarios

Sources:
- PHOTOS KENSINGTON sorted/Panoramic rooftop view/*.jpg
- PHOTOS KENSINGTON sorted/Panoramic rooftop view, Kensington backyards/*.jpg
- PHOTOS KENSINGTON sorted/The planet traveler hostel Panorama/*.jpg

Usage:
    python scripts/enrich/enrich_rear_facades.py --observations rear_observations.json
    python scripts/enrich/enrich_rear_facades.py --observations rear_observations.json --apply
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PARAMS_DIR = REPO_ROOT / "params"
PANORAMA_DIRS = [
    REPO_ROOT / "PHOTOS KENSINGTON sorted" / "Panoramic rooftop view",
    REPO_ROOT / "PHOTOS KENSINGTON sorted" / "Panoramic rooftop view, Kensington backyards",
    REPO_ROOT / "PHOTOS KENSINGTON sorted" / "The planet traveler hostel Panorama",
]

# Known panorama metadata (manually catalogued from visual inspection)
PANORAMA_CATALOG = [
    {
        "file": "IMG_20260315_152359743.jpg",
        "location": "rooftop_kensington",
        "lat": 43.6545,
        "lon": -79.4020,
        "direction": "south-east",
        "time": "daytime",
        "coverage": "Kensington Ave to Spadina Ave roofscape",
        "visible_features": [
            "flat_roofs", "gable_roofs", "chimneys", "skylights",
            "roof_materials", "cn_tower", "downtown_skyline",
            "party_walls", "rear_additions",
        ],
        "pipeline_uses": [
            "roof_type_validation",
            "height_massing_comparison",
            "environment_hdr_daytime",
        ],
    },
    {
        "file": "IMG_20260315_152444905.jpg",
        "location": "rooftop_backyards",
        "lat": 43.6545,
        "lon": -79.4020,
        "direction": "north-west",
        "time": "daytime",
        "coverage": "Rear of rowhouses, laneways, backyards between Kensington and Augusta",
        "visible_features": [
            "rear_facades", "party_walls", "rear_additions",
            "fences", "vegetation", "laneway_access",
            "brick_party_walls", "stucco_rear_walls",
            "backyard_structures", "parking_pads",
        ],
        "pipeline_uses": [
            "rear_facade_material",
            "party_wall_validation",
            "laneway_housing_feasibility",
            "backyard_depth_estimation",
        ],
    },
    {
        "file": "IMG_20260320_202641739.jpg",
        "location": "planet_traveler_hostel",
        "lat": 43.6554,
        "lon": -79.4003,
        "direction": "south",
        "time": "night",
        "coverage": "College St / Spadina Ave intersection, south Kensington perimeter",
        "visible_features": [
            "commercial_signage_lit", "building_heights_silhouette",
            "street_lighting", "traffic_patterns",
        ],
        "pipeline_uses": [
            "scenario_baseline_night",
            "commercial_activity_indicator",
            "signage_detection_night",
        ],
    },
    {
        "file": "IMG_20260320_202738428.jpg",
        "location": "planet_traveler_hostel",
        "lat": 43.6554,
        "lon": -79.4003,
        "direction": "south-east",
        "time": "night",
        "coverage": "College St looking east, commercial strip, high-rise context",
        "visible_features": [
            "commercial_frontages", "building_scale_contrast",
            "perimeter_street_character", "transit_corridor",
        ],
        "pipeline_uses": [
            "scenario_baseline_night",
            "height_context_perimeter",
        ],
    },
]


def atomic_write_json(filepath: Path, data: dict):
    content = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    fd, tmp = tempfile.mkstemp(dir=filepath.parent, suffix=".tmp")
    os.write(fd, content.encode("utf-8"))
    os.close(fd)
    os.replace(tmp, str(filepath))


def find_param_file(address: str, params_dir: Path) -> Path | None:
    stem = address.replace(" ", "_")
    candidate = params_dir / f"{stem}.json"
    if candidate.exists():
        return candidate
    for f in params_dir.glob("*.json"):
        if f.name.startswith("_"):
            continue
        try:
            p = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if p.get("_meta", {}).get("address") == address:
            return f
    return None


def enrich_from_observations(
    observations_path: Path,
    params_dir: Path,
    apply: bool = False,
) -> dict:
    """Apply rear facade observations to params.

    Observations JSON format:
    [
        {
            "address": "22 Lippincott St",
            "source_panorama": "IMG_20260315_152444905.jpg",
            "rear_material": "brick",
            "rear_colour_hex": "#B85A3A",
            "rear_additions": true,
            "rear_addition_depth_m": 3.0,
            "party_wall_left_material": "brick",
            "party_wall_right_material": "exposed_brick",
            "roof_type_from_above": "gable",
            "roof_material_from_above": "asphalt_shingle",
            "chimney_visible_from_above": true,
            "backyard_depth_m": 8.0,
            "laneway_access": true,
            "laneway_width_m": 3.5
        }
    ]
    """
    if not observations_path.exists():
        print(f"No observations file at {observations_path}")
        return {"applied": 0}

    observations = json.loads(observations_path.read_text(encoding="utf-8"))
    if not isinstance(observations, list):
        observations = observations.get("observations", [])

    stats = {"applied": 0, "not_found": 0, "skipped": 0}

    for obs in observations:
        address = obs.get("address", "")
        if not address:
            stats["skipped"] += 1
            continue

        pf = find_param_file(address, params_dir)
        if not pf:
            stats["not_found"] += 1
            continue

        params = json.loads(pf.read_text(encoding="utf-8"))

        # Store rear facade data
        rear = params.setdefault("rear_facade", {})
        for key in ["rear_material", "rear_colour_hex", "rear_additions",
                     "rear_addition_depth_m", "rear_condition"]:
            if key in obs:
                rear[key] = obs[key]

        # Party wall updates
        if "party_wall_left_material" in obs:
            params["party_wall_left_material"] = obs["party_wall_left_material"]
        if "party_wall_right_material" in obs:
            params["party_wall_right_material"] = obs["party_wall_right_material"]

        # Roof validation from above
        roof_detail = params.setdefault("roof_detail", {})
        if "roof_type_from_above" in obs:
            roof_detail["roof_type_observed_above"] = obs["roof_type_from_above"]
        if "roof_material_from_above" in obs:
            roof_detail["roof_material_observed_above"] = obs["roof_material_from_above"]
        if "chimney_visible_from_above" in obs:
            roof_detail["chimney_confirmed_above"] = obs["chimney_visible_from_above"]

        # Laneway/backyard data (feeds scenario framework)
        site = params.setdefault("site", {})
        if "backyard_depth_m" in obs:
            site["backyard_depth_m"] = obs["backyard_depth_m"]
        if "laneway_access" in obs:
            site["laneway_access"] = obs["laneway_access"]
        if "laneway_width_m" in obs:
            site["laneway_width_m"] = obs["laneway_width_m"]

        # Provenance
        meta = params.setdefault("_meta", {})
        fusion = meta.setdefault("fusion_applied", [])
        if "panorama_rear" not in fusion:
            fusion.append("panorama_rear")
        meta["panorama_source"] = obs.get("source_panorama", "")

        if apply:
            atomic_write_json(pf, params)

        stats["applied"] += 1

    return stats


def generate_panorama_index(output_path: Path):
    """Write the panorama catalog to a JSON index for other scripts."""
    index = {
        "panoramas": PANORAMA_CATALOG,
        "total": len(PANORAMA_CATALOG),
        "directories": [str(d) for d in PANORAMA_DIRS],
        "pipeline_uses": {
            "roof_validation": [p["file"] for p in PANORAMA_CATALOG
                                if "roof_type_validation" in p.get("pipeline_uses", [])],
            "rear_facade": [p["file"] for p in PANORAMA_CATALOG
                            if "rear_facade_material" in p.get("pipeline_uses", [])],
            "scenario_baseline": [p["file"] for p in PANORAMA_CATALOG
                                   if "scenario_baseline_night" in p.get("pipeline_uses", [])],
            "environment_hdr": [p["file"] for p in PANORAMA_CATALOG
                                if "environment_hdr_daytime" in p.get("pipeline_uses", [])],
        },
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(index, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Panorama index: {len(PANORAMA_CATALOG)} photos -> {output_path}")
    return index


def main():
    parser = argparse.ArgumentParser(
        description="Enrich params with rear facade observations from panoramic photos."
    )
    parser.add_argument("--observations", type=Path, default=None,
                        help="JSON file with per-building rear facade observations")
    parser.add_argument("--params", type=Path, default=PARAMS_DIR)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--index-only", action="store_true",
                        help="Only generate panorama catalog index")
    args = parser.parse_args()

    # Always generate the panorama index
    index_path = REPO_ROOT / "outputs" / "panorama_index.json"
    generate_panorama_index(index_path)

    if args.index_only:
        return

    if args.observations:
        mode = "APPLY" if args.apply else "DRY-RUN"
        stats = enrich_from_observations(args.observations, args.params, apply=args.apply)
        print(f"\n[{mode}] Applied: {stats['applied']}, "
              f"Not found: {stats['not_found']}, Skipped: {stats['skipped']}")
    else:
        print("\nNo --observations file provided.")
        print("To use this script:")
        print("  1. Run AI analysis on panorama photos to generate observations JSON")
        print("  2. python scripts/enrich/enrich_rear_facades.py --observations rear_obs.json --apply")
        print("\nObservation JSON format: see script docstring for schema.")


if __name__ == "__main__":
    main()
