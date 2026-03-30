#!/usr/bin/env python3
"""
Build adjacency graph for Kensington Market buildings.

For each street, sort buildings by street_number and find immediate neighbours.
Record party walls, height differences, and material/era matches.

Also group consecutive addresses into "blocks" and compute block-level metrics.

Output: outputs/adjacency_graph.json, outputs/block_profiles.json
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

import statistics


def extract_street_number(building_name: str) -> tuple[int | None, str]:
    """
    Extract street number and street name from building_name.

    Examples:
        "10 Nassau St" → (10, "Nassau St")
        "10A Nassau St" → (10, "Nassau St")
        "10-8 Nassau St" → (10, "Nassau St")  # take first number
        "10 1/2 Nassau St" → (10, "Nassau St")
    """
    # Match leading number(s), possibly with A, -, /, but take the first numeric part
    match = re.match(r'^(\d+)', building_name.strip())
    if not match:
        return None, ""

    number = int(match.group(1))
    # Everything after the number is the street name
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

    # Find all JSON files in params/, exclude backups and metadata files
    for json_file in params_dir.glob("*.json"):
        if json_file.name.startswith("_") or "backup" in json_file.name:
            continue
        if json_file.name.startswith("."):
            continue

        try:
            with open(json_file, encoding="utf-8") as f:
                data = json.load(f)

            # Skip if marked as skipped
            if data.get("skipped"):
                continue

            address = data.get("building_name", json_file.stem)
            buildings[address] = data
        except (json.JSONDecodeError, IOError):
            continue

    return buildings


def group_by_street(buildings: dict[str, Any]) -> dict[str, list[tuple[int, str, Any]]]:
    """
    Group buildings by street.

    Returns: dict[street] -> list of (street_number, building_name, params)
    """
    streets = defaultdict(list)

    for building_name, params in buildings.items():
        street_number, street = extract_street_number(building_name)
        if street_number is None or not street:
            continue

        streets[street].append((street_number, building_name, params))

    # Sort each street by street_number
    for street in streets:
        streets[street].sort(key=lambda x: x[0])

    return streets


def find_neighbours(street_buildings: list[tuple[int, str, Any]]) -> dict[str, Any]:
    """
    For each building on a street, find left and right neighbours.

    Neighbours are determined by nearest street_number (±2 range for even/odd skip).
    """
    adjacency = {}

    for idx, (num, building_name, params) in enumerate(street_buildings):
        street = safe_get(params, "site", "street", default="")
        total_height = safe_get(params, "total_height_m", default=0)
        facade_material = safe_get(params, "facade_material", default="")
        construction_date = safe_get(params, "hcd_data", "construction_date", default="")
        party_wall_left = safe_get(params, "party_wall_left", default=False)
        party_wall_right = safe_get(params, "party_wall_right", default=False)

        left_neighbour = None
        left_number = None
        left_party_wall = False
        left_height_diff = None
        left_material_match = False
        left_era_match = False

        right_neighbour = None
        right_number = None
        right_party_wall = False
        right_height_diff = None
        right_material_match = False
        right_era_match = False

        # Find left neighbour (lower street number)
        if idx > 0:
            left_num, left_name, left_params = street_buildings[idx - 1]
            # Check if within ±2 range (account for even/odd skip)
            if num - left_num <= 2:
                left_neighbour = left_name
                left_number = left_num
                left_party_wall = party_wall_left
                left_height = safe_get(left_params, "total_height_m", default=0)
                if total_height and left_height:
                    left_height_diff = total_height - left_height
                left_facade = safe_get(left_params, "facade_material", default="")
                left_material_match = facade_material and facade_material == left_facade
                left_construction = safe_get(left_params, "hcd_data", "construction_date", default="")
                left_era_match = (
                    construction_date
                    and construction_date == left_construction
                    and construction_date != ""
                )

        # Find right neighbour (higher street number)
        if idx < len(street_buildings) - 1:
            right_num, right_name, right_params = street_buildings[idx + 1]
            # Check if within ±2 range
            if right_num - num <= 2:
                right_neighbour = right_name
                right_number = right_num
                right_party_wall = party_wall_right
                right_height = safe_get(right_params, "total_height_m", default=0)
                if total_height and right_height:
                    right_height_diff = total_height - right_height
                right_facade = safe_get(right_params, "facade_material", default="")
                right_material_match = facade_material and facade_material == right_facade
                right_construction = safe_get(right_params, "hcd_data", "construction_date", default="")
                right_era_match = (
                    construction_date
                    and construction_date == right_construction
                    and construction_date != ""
                )

        adjacency[building_name] = {
            "address": building_name,
            "street": street,
            "street_number": num,
            "left_neighbour": left_neighbour,
            "right_neighbour": right_neighbour,
            "left_party_wall": left_party_wall,
            "right_party_wall": right_party_wall,
            "height_diff_left_m": left_height_diff,
            "height_diff_right_m": right_height_diff,
            "material_match_left": left_material_match,
            "material_match_right": right_material_match,
            "era_match_left": left_era_match,
            "era_match_right": right_era_match,
        }

    return adjacency


def create_blocks(street_buildings: list[tuple[int, str, Any]]) -> list[dict[str, Any]]:
    """
    Group consecutive addresses into blocks.

    Break blocks at cross streets or gaps > 4 in numbering.
    """
    if not street_buildings:
        return []

    blocks = []
    current_block = [street_buildings[0]]

    for i in range(1, len(street_buildings)):
        num, building_name, params = street_buildings[i]
        prev_num = current_block[-1][0]

        # Break if gap > 4
        if num - prev_num > 4:
            # Finalize current block
            blocks.append(_finalize_block(current_block, street_buildings[0][2]))
            current_block = [street_buildings[i]]
        else:
            current_block.append(street_buildings[i])

    # Finalize last block
    if current_block:
        blocks.append(_finalize_block(current_block, street_buildings[0][2]))

    return blocks


def _finalize_block(
    block: list[tuple[int, str, Any]],
    first_params: Any,
) -> dict[str, Any]:
    """Compute block-level metrics."""
    street = safe_get(first_params, "site", "street", default="")
    start_number = block[0][0]
    end_number = block[-1][0]
    building_count = len(block)

    heights = []
    widths = []
    materials = []
    party_walls = 0
    construction_dates = []

    for num, building_name, params in block:
        h = safe_get(params, "total_height_m")
        if h:
            heights.append(h)

        w = safe_get(params, "facade_width_m")
        if w:
            widths.append(w)

        mat = safe_get(params, "facade_material")
        if mat:
            materials.append(mat)

        if safe_get(params, "party_wall_left") or safe_get(params, "party_wall_right"):
            party_walls += 1

        cd = safe_get(params, "hcd_data", "construction_date")
        if cd:
            construction_dates.append(cd)

    height_variance = 0
    if len(heights) > 1:
        height_variance = statistics.stdev(heights)

    height_regularity = height_variance if heights else 0
    width_variance = statistics.stdev(widths) if len(widths) > 1 else 0
    avg_height = statistics.mean(heights) if heights else 0

    # Dominant material
    dominant_material = ""
    if materials:
        material_counts = defaultdict(int)
        for m in materials:
            material_counts[m] += 1
        dominant_material = max(material_counts, key=material_counts.get)

    # Party wall percentage
    party_wall_pct = (party_walls / building_count * 100) if building_count > 0 else 0

    # Era range
    era_range = ""
    if construction_dates:
        unique_eras = sorted(set(construction_dates))
        if unique_eras:
            era_range = f"{unique_eras[0]} to {unique_eras[-1]}"

    # Total frontage
    total_frontage = sum(widths) if widths else 0

    return {
        "street": street,
        "start_number": start_number,
        "end_number": end_number,
        "building_count": building_count,
        "avg_height_m": round(avg_height, 2),
        "height_variance": round(height_regularity, 2),
        "dominant_material": dominant_material,
        "party_wall_pct": round(party_wall_pct, 1),
        "era_range": era_range,
        "total_frontage_m": round(total_frontage, 1),
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

    print("Building adjacency graph...")
    all_adjacency = {}
    all_blocks = {}

    for street in sorted(streets.keys()):
        street_buildings = streets[street]
        adjacency = find_neighbours(street_buildings)
        blocks = create_blocks(street_buildings)

        all_adjacency.update(adjacency)
        all_blocks[street] = blocks

        print(f"  {street}: {len(street_buildings)} buildings, {len(blocks)} block(s)")

    # Write adjacency graph
    adjacency_file = outputs_dir / "adjacency_graph.json"
    with open(adjacency_file, "w", encoding="utf-8") as f:
        json.dump(all_adjacency, f, indent=2)
    print(f"\nWrote {len(all_adjacency)} adjacency records to {adjacency_file}")

    # Write block profiles
    block_file = outputs_dir / "block_profiles.json"
    with open(block_file, "w", encoding="utf-8") as f:
        json.dump(all_blocks, f, indent=2)
    print(f"Wrote {sum(len(b) for b in all_blocks.values())} block profiles to {block_file}")

    # Print summary
    print("\n=== SUMMARY ===")
    print(f"Streets analyzed: {len(streets)}")
    print(f"Buildings in adjacency graph: {len(all_adjacency)}")
    print(f"Total blocks: {sum(len(b) for b in all_blocks.values())}")

    # Show street-by-street breakdown
    print("\nStreet breakdown:")
    for street in sorted(streets.keys()):
        building_count = len(streets[street])
        block_count = len(all_blocks[street])
        print(f"  {street}: {building_count} buildings, {block_count} block(s)")


if __name__ == "__main__":
    main()
