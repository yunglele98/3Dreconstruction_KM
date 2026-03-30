#!/usr/bin/env python3
"""
Analyze visual rhythm and heritage coherence metrics for each street.

Computes:
- frontage_widths: array of facade_width_m in street order
- height_profile: array of total_height_m in street order
- height_regularity: std dev of heights (lower = more uniform)
- width_regularity: std dev of widths
- material_runs: longest consecutive run of same facade_material
- era_coherence: % of adjacent pairs with same hcd_data.construction_date
- storefront_density: % of ground floors with has_storefront=true
- setback_uniformity: std dev of setbacks

Heritage quality score (0-100 scale):
  era_coherence * 30 + (1 - min(height_regularity/5, 1)) * 25 +
  (material_runs/building_count) * 20 + storefront_density * 15 +
  (1 - min(width_regularity/3, 1)) * 10

Output: outputs/streetscape_rhythm.json
Prints ranked table of streets by heritage quality score.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

import statistics


def extract_street_number(building_name: str) -> tuple[int | None, str]:
    """Extract street number and street name from building_name."""
    match = re.match(r'^(\d+)', building_name.strip())
    if not match:
        return None, ""

    number = int(match.group(1))
    street_name = building_name[match.end():].strip()
    return number, street_name


def safe_get(obj: dict, *keys: str, default: Any = None) -> Any:
    """Safely traverse nested dict."""
    current = obj
    for key in keys:
        if isinstance(current, dict):
            current = current.get(key, default)
        else:
            return default
    return current


def load_params(params_dir: Path) -> dict[str, Any]:
    """Load all non-skipped, non-metadata param files."""
    buildings = {}

    for json_file in params_dir.glob("*.json"):
        if json_file.name.startswith("_") or "backup" in json_file.name:
            continue
        if json_file.name.startswith("."):
            continue

        try:
            with open(json_file, encoding="utf-8") as f:
                data = json.load(f)

            if data.get("skipped"):
                continue

            address = data.get("building_name", json_file.stem)
            buildings[address] = data
        except (json.JSONDecodeError, IOError):
            continue

    return buildings


def group_by_street(buildings: dict[str, Any]) -> dict[str, list[tuple[int, str, Any]]]:
    """Group buildings by street, sorted by street_number."""
    streets = defaultdict(list)

    for building_name, params in buildings.items():
        street_number, street = extract_street_number(building_name)
        if street_number is None or not street:
            continue

        streets[street].append((street_number, building_name, params))

    for street in streets:
        streets[street].sort(key=lambda x: x[0])

    return streets


def compute_longest_material_run(buildings_data: list[Any]) -> int:
    """Find longest consecutive run of same facade_material."""
    if not buildings_data:
        return 0

    max_run = 1
    current_run = 1
    prev_material = safe_get(buildings_data[0], "facade_material", default="")

    for i in range(1, len(buildings_data)):
        material = safe_get(buildings_data[i], "facade_material", default="")
        if material and material == prev_material:
            current_run += 1
            max_run = max(max_run, current_run)
        else:
            current_run = 1
            prev_material = material

    return max_run


def compute_era_coherence(buildings_data: list[Any]) -> float:
    """Percentage of adjacent pairs with matching construction_date."""
    if len(buildings_data) < 2:
        return 1.0

    matching_pairs = 0
    total_pairs = 0

    for i in range(len(buildings_data) - 1):
        era1 = safe_get(buildings_data[i], "hcd_data", "construction_date", default="")
        era2 = safe_get(buildings_data[i + 1], "hcd_data", "construction_date", default="")

        # Only count pairs where both have valid eras
        if era1 and era2:
            total_pairs += 1
            if era1 == era2:
                matching_pairs += 1

    if total_pairs == 0:
        return 0.0

    return matching_pairs / total_pairs


def compute_storefront_density(buildings_data: list[Any]) -> float:
    """Percentage of buildings with has_storefront=true."""
    if not buildings_data:
        return 0.0

    storefronts = sum(1 for b in buildings_data if safe_get(b, "has_storefront", default=False))
    return storefronts / len(buildings_data)


def analyze_street(street_buildings: list[tuple[int, str, Any]]) -> dict[str, Any]:
    """Compute all metrics for a street."""
    if not street_buildings:
        return {
            "building_count": 0,
            "frontage_widths": [],
            "height_profile": [],
            "height_regularity": 0,
            "width_regularity": 0,
            "material_runs": 0,
            "era_coherence": 0,
            "storefront_density": 0,
            "setback_uniformity": 0,
            "heritage_quality_score": 0,
        }

    # Extract building data in order
    buildings_data = [params for _, _, params in street_buildings]
    street_name = safe_get(buildings_data[0], "site", "street", default="")
    building_count = len(buildings_data)

    # Compute arrays
    frontage_widths = [
        safe_get(b, "facade_width_m")
        for b in buildings_data
        if safe_get(b, "facade_width_m")
    ]
    height_profile = [
        safe_get(b, "total_height_m")
        for b in buildings_data
        if safe_get(b, "total_height_m")
    ]
    setbacks = [
        safe_get(b, "site", "setback_m") or 0
        for b in buildings_data
        if safe_get(b, "site", "setback_m") is not None
    ]

    # Compute regularity metrics
    height_regularity = statistics.stdev(height_profile) if len(height_profile) > 1 else 0
    width_regularity = statistics.stdev(frontage_widths) if len(frontage_widths) > 1 else 0
    setback_uniformity = statistics.stdev(setbacks) if len(setbacks) > 1 else 0

    # Compute coherence metrics
    material_runs = compute_longest_material_run(buildings_data)
    era_coherence = compute_era_coherence(buildings_data)
    storefront_density = compute_storefront_density(buildings_data)

    # Compute heritage quality score (0-100)
    score = (
        (era_coherence * 30)
        + ((1 - min(height_regularity / 5, 1)) * 25)
        + ((material_runs / max(building_count, 1)) * 20)
        + (storefront_density * 15)
        + ((1 - min(width_regularity / 3, 1)) * 10)
    )

    return {
        "street": street_name,
        "building_count": building_count,
        "frontage_widths": [round(w, 2) for w in frontage_widths],
        "height_profile": [round(h, 2) for h in height_profile],
        "height_regularity": round(height_regularity, 2),
        "width_regularity": round(width_regularity, 2),
        "material_runs": material_runs,
        "era_coherence": round(era_coherence, 3),
        "storefront_density": round(storefront_density, 3),
        "setback_uniformity": round(setback_uniformity, 2),
        "heritage_quality_score": round(score, 1),
    }


def main():
    """Main entry point."""
    params_dir = Path(__file__).parent.parent / "params"
    outputs_dir = Path(__file__).parent.parent / "outputs"
    outputs_dir.mkdir(exist_ok=True)

    print("Loading buildings...")
    buildings = load_params(params_dir)
    print(f"Loaded {len(buildings)} buildings")

    print("Grouping by street...")
    streets = group_by_street(buildings)
    print(f"Found {len(streets)} streets")

    print("Analyzing streetscape rhythm...")
    all_analyses = {}
    street_scores = []

    for street in sorted(streets.keys()):
        street_buildings = streets[street]
        analysis = analyze_street(street_buildings)
        all_analyses[street] = analysis
        street_scores.append((street, analysis["heritage_quality_score"]))

    # Write analysis
    analysis_file = outputs_dir / "streetscape_rhythm.json"
    with open(analysis_file, "w", encoding="utf-8") as f:
        json.dump(all_analyses, f, indent=2)
    print(f"\nWrote analysis for {len(all_analyses)} streets to {analysis_file}")

    # Print ranked table
    print("\n=== HERITAGE QUALITY RANKING ===")
    print("(Sorted by heritage_quality_score, descending)\n")

    street_scores.sort(key=lambda x: x[1], reverse=True)

    print(
        f"{'Rank':<6} {'Street':<30} {'Buildings':<12} {'Height Reg':<12} "
        f"{'Era Cohere':<12} {'Score':<8}"
    )
    print("-" * 90)

    for rank, (street, score) in enumerate(street_scores, 1):
        analysis = all_analyses[street]
        height_reg = analysis["height_regularity"]
        era_cohere = analysis["era_coherence"]
        building_count = analysis["building_count"]

        print(
            f"{rank:<6} {street:<30} {building_count:<12} {height_reg:<12.2f} "
            f"{era_cohere:<12.3f} {score:<8.1f}"
        )

    print("\n=== DETAILED METRICS ===\n")

    for rank, (street, score) in enumerate(street_scores, 1):
        analysis = all_analyses[street]
        print(f"{rank}. {street}")
        print(f"   Heritage Quality Score: {analysis['heritage_quality_score']:.1f}/100")
        print(f"   Buildings: {analysis['building_count']}")
        print(f"   Avg Height: {(statistics.mean(analysis['height_profile']) if analysis['height_profile'] else 0):.2f}m")
        print(f"   Height Regularity: {analysis['height_regularity']:.2f}m (std dev)")
        print(f"   Width Regularity: {analysis['width_regularity']:.2f}m (std dev)")
        print(f"   Longest Material Run: {analysis['material_runs']} building(s)")
        print(f"   Era Coherence: {analysis['era_coherence']*100:.1f}%")
        print(f"   Storefront Density: {analysis['storefront_density']*100:.1f}%")
        print(f"   Setback Uniformity: {analysis['setback_uniformity']:.2f}m (std dev)")
        print()


if __name__ == "__main__":
    main()
