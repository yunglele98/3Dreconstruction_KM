"""Unit tests for build_adjacency_graph.py"""

import json
from pathlib import Path
import pytest
from scripts.build_adjacency_graph import (
    extract_street_number,
    safe_get,
    group_by_street,
    find_neighbours,
    create_blocks,
)


class TestExtractStreetNumber:
    """Test extract_street_number function."""

    def test_simple_address(self):
        """Should extract number and street from simple address."""
        num, street = extract_street_number("10 Nassau St")
        assert num == 10
        assert street == "Nassau St"

    def test_address_with_suffix(self):
        """Should handle suffix like A."""
        num, street = extract_street_number("10A Nassau St")
        assert num == 10
        assert street == "A Nassau St"

    def test_address_with_dash(self):
        """Should extract first number from dash-separated."""
        num, street = extract_street_number("10-8 Nassau St")
        assert num == 10
        assert street == "-8 Nassau St"

    def test_address_with_fraction(self):
        """Should extract first number from fraction."""
        num, street = extract_street_number("10 1/2 Nassau St")
        assert num == 10
        assert street == "1/2 Nassau St"

    def test_no_number(self):
        """Should return None for address without number."""
        num, street = extract_street_number("Nassau St")
        assert num is None
        assert street == ""

    def test_large_number(self):
        """Should handle large street numbers."""
        num, street = extract_street_number("1234 Spadina Ave")
        assert num == 1234
        assert street == "Spadina Ave"

    def test_leading_zeros(self):
        """Should parse leading zeros correctly."""
        num, street = extract_street_number("007 Bond St")
        assert num == 7
        assert street == "Bond St"

    def test_empty_string(self):
        """Should handle empty string."""
        num, street = extract_street_number("")
        assert num is None
        assert street == ""

    def test_whitespace_handling(self):
        """Should handle extra whitespace."""
        num, street = extract_street_number("  100   Lippincott St  ")
        assert num == 100
        assert "Lippincott" in street


class TestSafeGet:
    """Test safe_get function."""

    def test_simple_key(self):
        """Should get simple key."""
        obj = {"name": "test"}
        assert safe_get(obj, "name") == "test"

    def test_nested_keys(self):
        """Should traverse nested dicts."""
        obj = {"site": {"street": "Lippincott"}}
        assert safe_get(obj, "site", "street") == "Lippincott"

    def test_missing_key_returns_default(self):
        """Should return default for missing key."""
        obj = {"name": "test"}
        assert safe_get(obj, "missing", default="unknown") == "unknown"

    def test_missing_nested_key_returns_default(self):
        """Should return default for missing nested key."""
        obj = {"site": {"street": "Lippincott"}}
        assert safe_get(obj, "site", "missing", default=None) is None

    def test_none_in_chain(self):
        """Should return default if any intermediate value is None."""
        obj = {"site": None}
        assert safe_get(obj, "site", "street", default="unknown") == "unknown"

    def test_non_dict_in_chain(self):
        """Should return default if chain hits non-dict."""
        obj = {"site": "not a dict"}
        assert safe_get(obj, "site", "street", default=None) is None

    def test_empty_dict(self):
        """Should handle empty dict."""
        obj = {}
        assert safe_get(obj, "any", default="default") == "default"

    def test_default_none(self):
        """Should return None as default if specified."""
        obj = {"a": 1}
        assert safe_get(obj, "missing", default=None) is None

    def test_single_level_traversal(self):
        """Should handle single-level traversal."""
        obj = {"value": 42}
        assert safe_get(obj, "value") == 42


class TestGroupByStreet:
    """Test group_by_street function."""

    def test_empty_buildings(self):
        """Should handle empty buildings dict."""
        result = group_by_street({})
        assert result == {}

    def test_single_building(self):
        """Should group single building."""
        buildings = {
            "10 Nassau St": {"building_name": "10 Nassau St"}
        }
        result = group_by_street(buildings)
        assert "Nassau St" in result
        assert len(result["Nassau St"]) == 1

    def test_multiple_buildings_same_street(self):
        """Should group multiple buildings on same street."""
        buildings = {
            "10 Nassau St": {"building_name": "10 Nassau St"},
            "20 Nassau St": {"building_name": "20 Nassau St"},
            "30 Nassau St": {"building_name": "30 Nassau St"},
        }
        result = group_by_street(buildings)
        assert len(result["Nassau St"]) == 3

    def test_buildings_sorted_by_number(self):
        """Should sort buildings by street number."""
        buildings = {
            "30 Nassau St": {"building_name": "30 Nassau St"},
            "10 Nassau St": {"building_name": "10 Nassau St"},
            "20 Nassau St": {"building_name": "20 Nassau St"},
        }
        result = group_by_street(buildings)
        numbers = [num for num, _, _ in result["Nassau St"]]
        assert numbers == [10, 20, 30]

    def test_multiple_streets(self):
        """Should group buildings across multiple streets."""
        buildings = {
            "10 Nassau St": {"building_name": "10 Nassau St"},
            "20 Lippincott Ave": {"building_name": "20 Lippincott Ave"},
            "30 Baldwin St": {"building_name": "30 Baldwin St"},
        }
        result = group_by_street(buildings)
        assert len(result) == 3
        assert "Nassau St" in result
        assert "Lippincott Ave" in result
        assert "Baldwin St" in result

    def test_buildings_without_number_skipped(self):
        """Should skip buildings without street number."""
        buildings = {
            "No Number Street": {"building_name": "No Number Street"},
            "10 Nassau St": {"building_name": "10 Nassau St"},
        }
        result = group_by_street(buildings)
        assert "No Number Street" not in result
        assert "Nassau St" in result

    def test_preserves_params(self):
        """Should preserve building params in grouping."""
        params = {
            "total_height_m": 12.5,
            "facade_material": "brick",
        }
        buildings = {"10 Nassau St": {"building_name": "10 Nassau St", **params}}
        result = group_by_street(buildings)
        _, _, stored_params = result["Nassau St"][0]
        assert stored_params["total_height_m"] == 12.5
        assert stored_params["facade_material"] == "brick"


class TestFindNeighbours:
    """Test find_neighbours function."""

    def test_single_building_no_neighbours(self):
        """Single building should have no neighbours."""
        street_buildings = [
            (10, "10 Nassau St", {"site": {"street": "Nassau St"}})
        ]
        result = find_neighbours(street_buildings)
        assert result["10 Nassau St"]["left_neighbour"] is None
        assert result["10 Nassau St"]["right_neighbour"] is None

    def test_two_buildings_neighbours(self):
        """Two adjacent buildings should be neighbours."""
        street_buildings = [
            (10, "10 Nassau St", {"site": {"street": "Nassau St"}, "total_height_m": 12}),
            (12, "12 Nassau St", {"site": {"street": "Nassau St"}, "total_height_m": 12}),
        ]
        result = find_neighbours(street_buildings)
        assert result["10 Nassau St"]["right_neighbour"] == "12 Nassau St"
        assert result["12 Nassau St"]["left_neighbour"] == "10 Nassau St"

    def test_gap_greater_than_2_no_neighbour(self):
        """Buildings with gap > 2 should not be neighbours."""
        street_buildings = [
            (10, "10 Nassau St", {"site": {"street": "Nassau St"}, "total_height_m": 12}),
            (15, "15 Nassau St", {"site": {"street": "Nassau St"}, "total_height_m": 12}),
        ]
        result = find_neighbours(street_buildings)
        assert result["10 Nassau St"]["right_neighbour"] is None
        assert result["15 Nassau St"]["left_neighbour"] is None

    def test_height_difference_calculated(self):
        """Should calculate height difference with neighbours."""
        street_buildings = [
            (10, "10 Nassau St", {"site": {"street": "Nassau St"}, "total_height_m": 12}),
            (12, "12 Nassau St", {"site": {"street": "Nassau St"}, "total_height_m": 15}),
        ]
        result = find_neighbours(street_buildings)
        # height_diff = current_height - neighbour_height
        assert result["10 Nassau St"]["height_diff_right_m"] == -3.0  # 12 - 15 = -3
        assert result["12 Nassau St"]["height_diff_left_m"] == 3.0  # 15 - 12 = 3

    def test_material_match_detected(self):
        """Should detect matching facade materials."""
        street_buildings = [
            (10, "10 Nassau St", {"site": {"street": "Nassau St"}, "facade_material": "brick"}),
            (12, "12 Nassau St", {"site": {"street": "Nassau St"}, "facade_material": "brick"}),
        ]
        result = find_neighbours(street_buildings)
        assert result["10 Nassau St"]["material_match_right"] is True
        assert result["12 Nassau St"]["material_match_left"] is True

    def test_material_mismatch_detected(self):
        """Should detect mismatched facade materials."""
        street_buildings = [
            (10, "10 Nassau St", {"site": {"street": "Nassau St"}, "facade_material": "brick"}),
            (12, "12 Nassau St", {"site": {"street": "Nassau St"}, "facade_material": "stone"}),
        ]
        result = find_neighbours(street_buildings)
        assert result["10 Nassau St"]["material_match_right"] is False

    def test_era_match_detected(self):
        """Should detect matching construction dates."""
        street_buildings = [
            (10, "10 Nassau St", {"site": {"street": "Nassau St"}, "hcd_data": {"construction_date": "1904-1913"}}),
            (12, "12 Nassau St", {"site": {"street": "Nassau St"}, "hcd_data": {"construction_date": "1904-1913"}}),
        ]
        result = find_neighbours(street_buildings)
        assert result["10 Nassau St"]["era_match_right"] is True

    def test_party_walls_recorded(self):
        """Should record party walls."""
        street_buildings = [
            (10, "10 Nassau St", {"site": {"street": "Nassau St"}, "party_wall_right": True}),
            (12, "12 Nassau St", {"site": {"street": "Nassau St"}, "party_wall_left": True}),
        ]
        result = find_neighbours(street_buildings)
        assert result["10 Nassau St"]["right_party_wall"] is True
        assert result["12 Nassau St"]["left_party_wall"] is True

    def test_three_buildings_in_sequence(self):
        """Should find correct neighbours for three consecutive buildings."""
        street_buildings = [
            (10, "10 Nassau St", {"site": {"street": "Nassau St"}, "total_height_m": 12}),
            (12, "12 Nassau St", {"site": {"street": "Nassau St"}, "total_height_m": 12}),
            (14, "14 Nassau St", {"site": {"street": "Nassau St"}, "total_height_m": 12}),
        ]
        result = find_neighbours(street_buildings)
        assert result["10 Nassau St"]["right_neighbour"] == "12 Nassau St"
        assert result["12 Nassau St"]["left_neighbour"] == "10 Nassau St"
        assert result["12 Nassau St"]["right_neighbour"] == "14 Nassau St"
        assert result["14 Nassau St"]["left_neighbour"] == "12 Nassau St"


class TestCreateBlocks:
    """Test create_blocks function."""

    def test_empty_list(self):
        """Should handle empty street."""
        result = create_blocks([])
        assert result == []

    def test_single_building_is_one_block(self):
        """Single building should form one block."""
        street_buildings = [
            (10, "10 Nassau St", {"facade_width_m": 5, "total_height_m": 12})
        ]
        result = create_blocks(street_buildings)
        assert len(result) == 1
        assert result[0]["building_count"] == 1
        assert result[0]["start_number"] == 10
        assert result[0]["end_number"] == 10

    def test_consecutive_addresses_single_block(self):
        """Consecutive addresses should form single block."""
        street_buildings = [
            (10, "10 Nassau St", {"facade_width_m": 5, "total_height_m": 12}),
            (12, "12 Nassau St", {"facade_width_m": 5, "total_height_m": 12}),
            (14, "14 Nassau St", {"facade_width_m": 5, "total_height_m": 12}),
        ]
        result = create_blocks(street_buildings)
        assert len(result) == 1
        assert result[0]["building_count"] == 3

    def test_gap_greater_than_4_creates_new_block(self):
        """Gap > 4 should create new block."""
        street_buildings = [
            (10, "10 Nassau St", {"facade_width_m": 5, "total_height_m": 12}),
            (12, "12 Nassau St", {"facade_width_m": 5, "total_height_m": 12}),
            (20, "20 Nassau St", {"facade_width_m": 5, "total_height_m": 12}),
        ]
        result = create_blocks(street_buildings)
        assert len(result) == 2
        assert result[0]["end_number"] == 12
        assert result[1]["start_number"] == 20

    def test_block_height_variance(self):
        """Should calculate height variance for block."""
        street_buildings = [
            (10, "10 Nassau St", {"facade_width_m": 5, "total_height_m": 12}),
            (12, "12 Nassau St", {"facade_width_m": 5, "total_height_m": 12}),
            (14, "14 Nassau St", {"facade_width_m": 5, "total_height_m": 12}),
        ]
        result = create_blocks(street_buildings)
        # All same height, variance should be 0
        assert result[0]["height_variance"] == 0.0

    def test_block_dominant_material(self):
        """Should identify dominant material in block."""
        street_buildings = [
            (10, "10 Nassau St", {"facade_material": "brick"}),
            (12, "12 Nassau St", {"facade_material": "brick"}),
            (14, "14 Nassau St", {"facade_material": "stone"}),
        ]
        result = create_blocks(street_buildings)
        assert result[0]["dominant_material"] == "brick"

    def test_block_party_wall_percentage(self):
        """Should calculate party wall percentage."""
        street_buildings = [
            (10, "10 Nassau St", {"party_wall_left": True}),
            (12, "12 Nassau St", {"party_wall_right": True}),
            (14, "14 Nassau St", {"party_wall_left": False}),
        ]
        result = create_blocks(street_buildings)
        # 2 out of 3 buildings have party walls = ~67%
        assert result[0]["party_wall_pct"] > 50.0

    def test_block_era_range(self):
        """Should show era range for block."""
        street_buildings = [
            (10, "10 Nassau St", {"hcd_data": {"construction_date": "1904-1913"}}),
            (12, "12 Nassau St", {"hcd_data": {"construction_date": "1890-1903"}}),
            (14, "14 Nassau St", {"hcd_data": {"construction_date": "1904-1913"}}),
        ]
        result = create_blocks(street_buildings)
        assert "1890-1903" in result[0]["era_range"]
        assert "1904-1913" in result[0]["era_range"]

    def test_block_total_frontage(self):
        """Should calculate total frontage."""
        street_buildings = [
            (10, "10 Nassau St", {"facade_width_m": 5}),
            (12, "12 Nassau St", {"facade_width_m": 6}),
            (14, "14 Nassau St", {"facade_width_m": 7}),
        ]
        result = create_blocks(street_buildings)
        assert result[0]["total_frontage_m"] == pytest.approx(18.0, rel=0.1)

    def test_multiple_blocks_correct_count(self):
        """Should create correct number of blocks with gaps."""
        street_buildings = [
            (10, "10 Nassau St", {"facade_width_m": 5}),
            (12, "12 Nassau St", {"facade_width_m": 5}),
            (25, "25 Nassau St", {"facade_width_m": 5}),
            (27, "27 Nassau St", {"facade_width_m": 5}),
            (50, "50 Nassau St", {"facade_width_m": 5}),
        ]
        result = create_blocks(street_buildings)
        assert len(result) == 3
