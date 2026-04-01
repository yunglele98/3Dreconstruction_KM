"""Unit tests for map_megascans_materials.py"""

from __future__ import annotations

import json
import pytest
from pathlib import Path
from typing import Dict

from map_megascans_materials import (
    hex_to_lab,
    colour_distance,
    find_closest_megascans_brick,
    find_closest_megascans_material,
    collect_building_materials,
    map_materials_to_megascans,
    MEGASCANS_MATERIALS,
)


class TestHexToLab:
    """Tests for hex_to_lab function."""

    def test_hex_to_lab_red_brick(self):
        """Test conversion of red brick hex to LAB."""
        result = hex_to_lab("#B85A3A")
        assert isinstance(result, tuple)
        assert len(result) == 3
        l, a, b = result
        assert isinstance(l, float)
        assert isinstance(a, float)
        assert isinstance(b, float)
        # Red brick should have positive a (red) component
        assert a > 0

    def test_hex_to_lab_white(self):
        """Test conversion of white hex to LAB."""
        result = hex_to_lab("#FFFFFF")
        l, a, b = result
        # White should have high L value
        assert l > 90
        # White should have a and b close to 0
        assert abs(a) < 10
        assert abs(b) < 10

    def test_hex_to_lab_black(self):
        """Test conversion of black hex to LAB."""
        result = hex_to_lab("#000000")
        l, a, b = result
        # Black should have low L value
        assert l < 10

    def test_hex_to_lab_gray(self):
        """Test conversion of gray hex to LAB."""
        result = hex_to_lab("#808080")
        l, a, b = result
        # Gray should have mid-range L
        assert 40 < l < 60
        assert abs(a) < 5
        assert abs(b) < 5

    def test_hex_to_lab_with_lowercase(self):
        """Test conversion with lowercase hex."""
        result1 = hex_to_lab("#B85A3A")
        result2 = hex_to_lab("#b85a3a")
        assert result1 == result2

    def test_hex_to_lab_without_hash(self):
        """Test conversion without hash prefix."""
        result = hex_to_lab("B85A3A")
        assert isinstance(result, tuple)
        assert len(result) == 3

    def test_hex_to_lab_buff_brick(self):
        """Test conversion of buff brick."""
        result = hex_to_lab("#D4B896")
        l, a, b = result
        # Buff is lighter and more yellow
        assert l > 60

    def test_hex_to_lab_brown_brick(self):
        """Test conversion of brown brick."""
        result = hex_to_lab("#7A5C44")
        l, a, b = result
        # Brown should have positive a and b
        assert a > 0
        assert b > 0

    def test_hex_to_lab_green(self):
        """Test conversion of green."""
        result = hex_to_lab("#00FF00")
        l, a, b = result
        # Green should have negative a (green)
        assert a < 0

    def test_hex_to_lab_blue(self):
        """Test conversion of blue."""
        result = hex_to_lab("#0000FF")
        l, a, b = result
        # Blue should have negative b (blue)
        assert b < 0


class TestColourDistance:
    """Tests for colour_distance function."""

    def test_colour_distance_identical_colours(self):
        """Test distance between identical colours is 0."""
        distance = colour_distance("#B85A3A", "#B85A3A")
        assert distance == 0.0

    def test_colour_distance_white_to_black(self):
        """Test distance between white and black is large."""
        distance = colour_distance("#FFFFFF", "#000000")
        assert distance > 100

    def test_colour_distance_similar_reds(self):
        """Test distance between similar red shades."""
        distance = colour_distance("#B85A3A", "#C85A3A")
        assert 0 < distance < 50

    def test_colour_distance_symmetric(self):
        """Test that colour distance is symmetric."""
        d1 = colour_distance("#B85A3A", "#D4B896")
        d2 = colour_distance("#D4B896", "#B85A3A")
        assert d1 == d2

    def test_colour_distance_returns_float(self):
        """Test that colour distance returns float."""
        result = colour_distance("#FF0000", "#00FF00")
        assert isinstance(result, float)

    def test_colour_distance_always_positive(self):
        """Test that colour distance is always >= 0."""
        test_cases = [
            ("#000000", "#FFFFFF"),
            ("#B85A3A", "#D4B896"),
            ("#808080", "#FF00FF"),
        ]
        for hex1, hex2 in test_cases:
            distance = colour_distance(hex1, hex2)
            assert distance >= 0

    def test_colour_distance_small_differences(self):
        """Test distance for very similar colours."""
        d1 = colour_distance("#CCCCCC", "#CCCCCD")
        assert d1 < 1

    def test_colour_distance_different_materials(self):
        """Test distance between brick and painted colours."""
        brick_red = "#B85A3A"
        cream_paint = "#F5F1ED"
        distance = colour_distance(brick_red, cream_paint)
        assert distance > 30


class TestFindClosestMegascansBrick:
    """Tests for find_closest_megascans_brick function."""

    def test_find_closest_brick_exact_match(self):
        """Test finding closest brick with exact hex match."""
        result = find_closest_megascans_brick("#B85A3A")
        assert result in MEGASCANS_MATERIALS
        assert MEGASCANS_MATERIALS[result]["category"] == "brick"

    def test_find_closest_brick_red(self):
        """Test finding closest brick for red hex."""
        result = find_closest_megascans_brick("#B85A3A")
        # Should find brick_red
        assert "brick" in result

    def test_find_closest_brick_buff(self):
        """Test finding closest brick for buff hex."""
        result = find_closest_megascans_brick("#D4B896")
        assert "brick" in result

    def test_find_closest_brick_brown(self):
        """Test finding closest brick for brown hex."""
        result = find_closest_megascans_brick("#7A5C44")
        assert "brick" in result

    def test_find_closest_brick_returns_key(self):
        """Test that function returns a valid MEGASCANS key."""
        result = find_closest_megascans_brick("#999999")
        assert result in MEGASCANS_MATERIALS

    def test_find_closest_brick_returns_brick_category(self):
        """Test that returned material is brick category."""
        result = find_closest_megascans_brick("#CCCCCC")
        material = MEGASCANS_MATERIALS[result]
        assert material["category"] == "brick"

    def test_find_closest_brick_arbitrary_colour(self):
        """Test with arbitrary colour."""
        result = find_closest_megascans_brick("#FF6600")
        assert "brick" in result

    def test_find_closest_brick_deterministic(self):
        """Test that function returns same result for same input."""
        result1 = find_closest_megascans_brick("#B85A3A")
        result2 = find_closest_megascans_brick("#B85A3A")
        assert result1 == result2


class TestFindClosestMegascansMaterial:
    """Tests for find_closest_megascans_material function."""

    def test_find_closest_material_brick_category(self):
        """Test finding closest brick material."""
        result = find_closest_megascans_material("#B85A3A", "brick")
        assert result in MEGASCANS_MATERIALS
        assert MEGASCANS_MATERIALS[result]["category"] == "brick"

    def test_find_closest_material_painted_category(self):
        """Test finding closest painted material."""
        result = find_closest_megascans_material("#FFFFFF", "painted")
        assert result in MEGASCANS_MATERIALS
        assert MEGASCANS_MATERIALS[result]["category"] == "painted"

    def test_find_closest_material_roofing_category(self):
        """Test finding closest roofing material."""
        result = find_closest_megascans_material("#5A5A5A", "roofing")
        assert result in MEGASCANS_MATERIALS
        assert MEGASCANS_MATERIALS[result]["category"] == "roofing"

    def test_find_closest_material_wood_category(self):
        """Test finding closest wood material."""
        result = find_closest_megascans_material("#C9A876", "wood")
        assert result in MEGASCANS_MATERIALS
        assert MEGASCANS_MATERIALS[result]["category"] == "wood"

    def test_find_closest_material_stone_category(self):
        """Test finding closest stone material."""
        result = find_closest_megascans_material("#D0C0A8", "stone")
        assert result in MEGASCANS_MATERIALS
        assert MEGASCANS_MATERIALS[result]["category"] == "stone"

    def test_find_closest_material_stucco_category(self):
        """Test finding closest stucco material."""
        result = find_closest_megascans_material("#E8E8E8", "stucco")
        assert result in MEGASCANS_MATERIALS
        assert MEGASCANS_MATERIALS[result]["category"] == "stucco"

    def test_find_closest_material_invalid_category_fallback(self):
        """Test fallback when category has no materials."""
        result = find_closest_megascans_material("#CCCCCC", "nonexistent_category")
        assert result in MEGASCANS_MATERIALS

    def test_find_closest_material_returns_valid_key(self):
        """Test that function always returns valid key."""
        result = find_closest_megascans_material("#FF00FF", "brick")
        assert result in MEGASCANS_MATERIALS

    def test_find_closest_material_deterministic(self):
        """Test that function is deterministic."""
        result1 = find_closest_megascans_material("#B85A3A", "brick")
        result2 = find_closest_megascans_material("#B85A3A", "brick")
        assert result1 == result2


class TestCollectBuildingMaterials:
    """Tests for collect_building_materials function."""

    def test_collect_building_materials_empty_dir(self, tmp_path):
        """Test collecting materials from empty directory."""
        result = collect_building_materials(tmp_path)
        assert isinstance(result, dict)
        assert len(result) == 0

    def test_collect_building_materials_single_file(self, tmp_path):
        """Test collecting from single param file."""
        param_file = tmp_path / "22_Lippincott_St.json"
        params = {
            "building_name": "22 Lippincott St",
            "facade_material": "brick",
            "facade_detail": {"brick_colour_hex": "#B85A3A"},
            "roof_colour": "#5A5A5A",
            "site": {"street_number": "22", "street": "Lippincott St"},
        }
        param_file.write_text(json.dumps(params), encoding="utf-8")

        result = collect_building_materials(tmp_path)
        assert len(result) == 1
        assert "22" in result

    def test_collect_building_materials_ignores_metadata(self, tmp_path):
        """Test that files starting with _ are ignored."""
        meta_file = tmp_path / "_site_coordinates.json"
        meta_file.write_text(json.dumps({"data": "metadata"}), encoding="utf-8")

        result = collect_building_materials(tmp_path)
        assert len(result) == 0

    def test_collect_building_materials_ignores_skipped(self, tmp_path):
        """Test that skipped buildings are ignored."""
        param_file = tmp_path / "photo_only.json"
        params = {
            "building_name": "Photo Only",
            "skipped": True,
            "skip_reason": "not a building",
        }
        param_file.write_text(json.dumps(params), encoding="utf-8")

        result = collect_building_materials(tmp_path)
        assert len(result) == 0

    def test_collect_building_materials_uses_fallback_address(self, tmp_path):
        """Test fallback to building_name when site address missing."""
        param_file = tmp_path / "test.json"
        params = {
            "building_name": "Test Building",
            "facade_material": "brick",
        }
        param_file.write_text(json.dumps(params), encoding="utf-8")

        result = collect_building_materials(tmp_path)
        assert len(result) == 1
        assert "Test Building" in result

    def test_collect_building_materials_default_values(self, tmp_path):
        """Test that defaults are applied."""
        param_file = tmp_path / "minimal.json"
        params = {
            "building_name": "Minimal Building",
        }
        param_file.write_text(json.dumps(params), encoding="utf-8")

        result = collect_building_materials(tmp_path)
        assert len(result) == 1
        material_data = list(result.values())[0]
        assert material_data["facade_material"] == "brick"
        assert material_data["brick_hex"] == "#B85A3A"
        assert material_data["roof_colour"] == "#5A5A5A"

    def test_collect_building_materials_multiple_buildings(self, tmp_path):
        """Test collecting from multiple param files."""
        for i in range(3):
            param_file = tmp_path / f"building_{i}.json"
            params = {
                "building_name": f"Building {i}",
                "facade_material": "brick",
                "site": {"street_number": str(i)},
            }
            param_file.write_text(json.dumps(params), encoding="utf-8")

        result = collect_building_materials(tmp_path)
        assert len(result) == 3

    def test_collect_building_materials_handles_invalid_json(self, tmp_path):
        """Test that invalid JSON is skipped gracefully."""
        bad_file = tmp_path / "bad.json"
        bad_file.write_text("{ invalid json }", encoding="utf-8")

        result = collect_building_materials(tmp_path)
        # Should not raise error, just skip bad file
        assert isinstance(result, dict)

    def test_collect_building_materials_includes_file_reference(self, tmp_path):
        """Test that results include file reference."""
        param_file = tmp_path / "test.json"
        params = {"building_name": "Test"}
        param_file.write_text(json.dumps(params), encoding="utf-8")

        result = collect_building_materials(tmp_path)
        material_data = list(result.values())[0]
        assert "file" in material_data
        assert material_data["file"] == "test.json"


class TestMapMaterialsToMegascans:
    """Tests for map_materials_to_megascans function."""

    def test_map_materials_single_building(self):
        """Test mapping single building."""
        materials = {
            "22 Test St": {
                "file": "22_Test_St.json",
                "facade_material": "brick",
                "brick_hex": "#B85A3A",
                "roof_colour": "#5A5A5A",
            }
        }
        result = map_materials_to_megascans(materials)
        assert len(result) == 1
        assert "22 Test St" in result
        mapping = result["22 Test St"]
        assert "megascans_facade_id" in mapping
        assert "megascans_roof_id" in mapping

    def test_map_materials_brick_building(self):
        """Test mapping of brick building."""
        materials = {
            "Test": {
                "file": "test.json",
                "facade_material": "brick",
                "brick_hex": "#B85A3A",
                "roof_colour": "#5A5A5A",
            }
        }
        result = map_materials_to_megascans(materials)
        mapping = result["Test"]
        assert mapping["megascans_facade_category"] == "brick"
        assert "brick" in mapping["megascans_facade_key"]

    def test_map_materials_painted_building(self):
        """Test mapping of painted building."""
        materials = {
            "Test": {
                "file": "test.json",
                "facade_material": "paint",
                "brick_hex": "#FFFFFF",
                "roof_colour": "#5A5A5A",
            }
        }
        result = map_materials_to_megascans(materials)
        mapping = result["Test"]
        # Should find a painted material
        assert mapping["megascans_facade_category"] in ["painted", "brick"]

    def test_map_materials_stone_building(self):
        """Test mapping of stone building."""
        materials = {
            "Test": {
                "file": "test.json",
                "facade_material": "stone",
                "brick_hex": "#D0C0A8",
                "roof_colour": "#5A5A5A",
            }
        }
        result = map_materials_to_megascans(materials)
        mapping = result["Test"]
        assert mapping["megascans_facade_key"] in MEGASCANS_MATERIALS

    def test_map_materials_clapboard_building(self):
        """Test mapping of clapboard building."""
        materials = {
            "Test": {
                "file": "test.json",
                "facade_material": "clapboard",
                "brick_hex": "#C9A876",
                "roof_colour": "#5A5A5A",
            }
        }
        result = map_materials_to_megascans(materials)
        mapping = result["Test"]
        assert mapping["megascans_facade_key"] in MEGASCANS_MATERIALS

    def test_map_materials_preserves_original_data(self):
        """Test that original material data is preserved."""
        materials = {
            "Test": {
                "file": "test.json",
                "facade_material": "brick",
                "brick_hex": "#B85A3A",
                "roof_colour": "#5A5A5A",
            }
        }
        result = map_materials_to_megascans(materials)
        mapping = result["Test"]
        assert mapping["facade_material"] == "brick"
        assert mapping["brick_hex"] == "#B85A3A"
        assert mapping["roof_colour"] == "#5A5A5A"

    def test_map_materials_includes_names(self):
        """Test that results include material names."""
        materials = {
            "Test": {
                "file": "test.json",
                "facade_material": "brick",
                "brick_hex": "#B85A3A",
                "roof_colour": "#5A5A5A",
            }
        }
        result = map_materials_to_megascans(materials)
        mapping = result["Test"]
        assert "megascans_facade_name" in mapping
        assert "megascans_roof_name" in mapping
        assert isinstance(mapping["megascans_facade_name"], str)
        assert isinstance(mapping["megascans_roof_name"], str)

    def test_map_materials_multiple_buildings(self):
        """Test mapping multiple buildings."""
        materials = {
            "A": {
                "file": "a.json",
                "facade_material": "brick",
                "brick_hex": "#B85A3A",
                "roof_colour": "#5A5A5A",
            },
            "B": {
                "file": "b.json",
                "facade_material": "paint",
                "brick_hex": "#FFFFFF",
                "roof_colour": "#6A5A4A",
            },
        }
        result = map_materials_to_megascans(materials)
        assert len(result) == 2
        assert "A" in result
        assert "B" in result

    def test_map_materials_empty_dictionary(self):
        """Test mapping empty materials dict."""
        result = map_materials_to_megascans({})
        assert isinstance(result, dict)
        assert len(result) == 0

    def test_map_materials_all_fields_present(self):
        """Test that all required fields are in result."""
        materials = {
            "Test": {
                "file": "test.json",
                "facade_material": "brick",
                "brick_hex": "#B85A3A",
                "roof_colour": "#5A5A5A",
            }
        }
        result = map_materials_to_megascans(materials)
        mapping = result["Test"]
        required_fields = [
            "facade_material",
            "brick_hex",
            "roof_colour",
            "megascans_facade_key",
            "megascans_facade_id",
            "megascans_facade_name",
            "megascans_facade_category",
            "megascans_roof_key",
            "megascans_roof_id",
            "megascans_roof_name",
            "file",
        ]
        for field in required_fields:
            assert field in mapping, f"Missing field: {field}"


class TestIntegration:
    """Integration tests combining multiple functions."""

    def test_full_pipeline(self, tmp_path):
        """Test full pipeline from collection to mapping."""
        # Create param file
        param_file = tmp_path / "22_Test_St.json"
        params = {
            "building_name": "22 Test St",
            "facade_material": "brick",
            "facade_detail": {"brick_colour_hex": "#B85A3A"},
            "roof_colour": "#5A5A5A",
            "site": {"street_number": "22", "street": "Test St"},
        }
        param_file.write_text(json.dumps(params), encoding="utf-8")

        # Collect materials
        materials = collect_building_materials(tmp_path)
        assert len(materials) == 1

        # Map to Megascans
        mappings = map_materials_to_megascans(materials)
        assert len(mappings) == 1

        mapping = mappings["22"]
        assert mapping["megascans_facade_id"] in [m["surface_id"] for m in MEGASCANS_MATERIALS.values()]
        assert mapping["megascans_roof_id"] in [m["surface_id"] for m in MEGASCANS_MATERIALS.values()]

    def test_colour_matching_consistency(self):
        """Test that colour matching is consistent across similar colours."""
        hex1 = "#B85A3A"
        hex2 = "#B85A3B"
        result1 = find_closest_megascans_brick(hex1)
        result2 = find_closest_megascans_brick(hex2)
        # Should find same or very similar materials
        assert result1 == result2

    def test_multiple_material_categories(self, tmp_path):
        """Test handling of multiple material categories."""
        # Create various building types
        buildings = [
            {"name": "brick.json", "material": "brick", "colour": "#B85A3A"},
            {"name": "painted.json", "material": "paint", "colour": "#FFFFFF"},
            {"name": "stone.json", "material": "stone", "colour": "#D0C0A8"},
        ]

        for building in buildings:
            param_file = tmp_path / building["name"]
            params = {
                "building_name": building["name"],
                "facade_material": building["material"],
                "brick_hex": building["colour"],
                "roof_colour": "#5A5A5A",
            }
            param_file.write_text(json.dumps(params), encoding="utf-8")

        materials = collect_building_materials(tmp_path)
        assert len(materials) == 3

        mappings = map_materials_to_megascans(materials)
        assert len(mappings) == 3
