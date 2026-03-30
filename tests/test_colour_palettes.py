#!/usr/bin/env python3
"""
Tests for scripts/rebuild_colour_palettes.py

Tests the colour palette resolution functions and priority chains for facade,
trim, roof, and accent colours.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

# Import the functions to test
from scripts.rebuild_colour_palettes import (
    BRICK_COLOURS,
    ROOF_COLOURS,
    TRIM_COLOURS_BY_ERA,
    infer_facade_hex_from_text,
    infer_roof_hex_from_text,
    is_complete_palette,
    is_valid_hex,
    parse_construction_date,
    resolve_accent_hex,
    resolve_facade_hex,
    resolve_roof_hex,
    resolve_trim_hex,
)


class TestHexValidation:
    """Tests for is_valid_hex()"""

    def test_valid_hex_uppercase(self):
        assert is_valid_hex("#B85A3A") is True

    def test_valid_hex_lowercase(self):
        assert is_valid_hex("#b85a3a") is True

    def test_valid_hex_mixed_case(self):
        assert is_valid_hex("#B8aA3a") is True

    def test_invalid_hex_missing_hash(self):
        assert is_valid_hex("B85A3A") is False

    def test_invalid_hex_too_short(self):
        assert is_valid_hex("#B85A3") is False

    def test_invalid_hex_too_long(self):
        assert is_valid_hex("#B85A3AA") is False

    def test_invalid_hex_non_string(self):
        assert is_valid_hex(None) is False
        assert is_valid_hex(123) is False
        assert is_valid_hex({}) is False


class TestConstructionDateParsing:
    """Tests for parse_construction_date()"""

    def test_pre_1889(self):
        assert parse_construction_date("pre-1889") == "pre-1889"
        assert parse_construction_date("1850") == "pre-1889"

    def test_1889_1903(self):
        assert parse_construction_date("1889-1903") == "1889-1903"
        assert parse_construction_date("1895") == "1889-1903"

    def test_1904_1913(self):
        assert parse_construction_date("1904-1913") == "1904-1913"
        assert parse_construction_date("1907") == "1904-1913"

    def test_1914_1930(self):
        assert parse_construction_date("1914-1930") == "1914-1930"
        assert parse_construction_date("1925") == "1914-1930"

    def test_1931_plus(self):
        assert parse_construction_date("1931+") == "1931+"
        assert parse_construction_date("1950") == "1931+"
        assert parse_construction_date("2000") == "1931+"

    def test_none_defaults_to_1889_1903(self):
        assert parse_construction_date(None) == "1889-1903"
        assert parse_construction_date("") == "1889-1903"

    def test_case_insensitive(self):
        assert parse_construction_date("PRE-1889") == "pre-1889"
        assert parse_construction_date("1889-1903") == "1889-1903"


class TestFacadeHexInference:
    """Tests for infer_facade_hex_from_text()"""

    def test_direct_match_red(self):
        assert infer_facade_hex_from_text("red") == "#B85A3A"

    def test_direct_match_buff(self):
        assert infer_facade_hex_from_text("buff") == "#D4B896"

    def test_direct_match_brown(self):
        assert infer_facade_hex_from_text("brown") == "#7A5C44"

    def test_direct_match_cream(self):
        assert infer_facade_hex_from_text("cream") == "#E8D8B0"

    def test_fuzzy_match_in_text(self):
        # "red brick" should match "red"
        assert infer_facade_hex_from_text("red brick") == "#B85A3A"

    def test_case_insensitive(self):
        assert infer_facade_hex_from_text("RED") == "#B85A3A"
        assert infer_facade_hex_from_text("Buff") == "#D4B896"

    def test_none_returns_none(self):
        assert infer_facade_hex_from_text(None) is None
        assert infer_facade_hex_from_text("") is None

    def test_unknown_colour_returns_none(self):
        assert infer_facade_hex_from_text("neon green") is None
        assert infer_facade_hex_from_text("mauve") is None


class TestRoofHexInference:
    """Tests for infer_roof_hex_from_text()"""

    def test_direct_match_grey(self):
        assert infer_roof_hex_from_text("grey") == "#5A5A5A"

    def test_direct_match_slate(self):
        assert infer_roof_hex_from_text("slate") == "#4A5A5A"

    def test_direct_match_brown(self):
        assert infer_roof_hex_from_text("brown") == "#6A5040"

    def test_direct_match_red(self):
        assert infer_roof_hex_from_text("red") == "#8A3A2A"

    def test_fuzzy_match_in_text(self):
        assert infer_roof_hex_from_text("slate tiles") == "#4A5A5A"

    def test_case_insensitive(self):
        assert infer_roof_hex_from_text("GREY") == "#5A5A5A"
        assert infer_roof_hex_from_text("Slate") == "#4A5A5A"

    def test_none_returns_none(self):
        assert infer_roof_hex_from_text(None) is None
        assert infer_roof_hex_from_text("") is None

    def test_unknown_colour_returns_none(self):
        assert infer_roof_hex_from_text("polka dot") is None


class TestResolveFacadeHex:
    """Tests for resolve_facade_hex() - priority chain"""

    def test_priority_1_facade_detail_brick_hex(self):
        """Priority 1: facade_detail.brick_colour_hex (if brick material)"""
        params = {
            "facade_material": "brick",
            "facade_detail": {"brick_colour_hex": "#C87040"},
        }
        stats = {
            "facade_from_detail_brick": 0,
            "facade_from_deep_brick": 0,
            "facade_from_deep_palette": 0,
            "facade_from_text_inference": 0,
            "facade_from_era_default_red": 0,
            "facade_from_era_default_orange": 0,
            "facade_from_era_default_buff": 0,
        }
        result = resolve_facade_hex(params, stats)
        assert result == "#C87040"
        assert stats["facade_from_detail_brick"] == 1

    def test_priority_2_deep_brick_hex(self):
        """Priority 2: deep_facade_analysis.brick_colour_hex"""
        params = {
            "facade_material": "stucco",
            "deep_facade_analysis": {"brick_colour_hex": "#D4B896"},
        }
        stats = {
            "facade_from_detail_brick": 0,
            "facade_from_deep_brick": 0,
            "facade_from_deep_palette": 0,
            "facade_from_text_inference": 0,
            "facade_from_era_default_red": 0,
            "facade_from_era_default_orange": 0,
            "facade_from_era_default_buff": 0,
        }
        result = resolve_facade_hex(params, stats)
        assert result == "#D4B896"
        assert stats["facade_from_deep_brick"] == 1

    def test_priority_3_deep_palette_facade(self):
        """Priority 3: deep_facade_analysis.colour_palette_observed.facade"""
        params = {
            "facade_material": "stucco",
            "deep_facade_analysis": {
                "colour_palette_observed": {"facade": "#B85A3A"}
            },
        }
        stats = {
            "facade_from_detail_brick": 0,
            "facade_from_deep_brick": 0,
            "facade_from_deep_palette": 0,
            "facade_from_text_inference": 0,
            "facade_from_era_default_red": 0,
            "facade_from_era_default_orange": 0,
            "facade_from_era_default_buff": 0,
        }
        result = resolve_facade_hex(params, stats)
        assert result == "#B85A3A"
        assert stats["facade_from_deep_palette"] == 1

    def test_priority_4_text_inference(self):
        """Priority 4: Text inference from facade_colour"""
        params = {
            "facade_material": "stucco",
            "facade_colour": "buff",
        }
        stats = {
            "facade_from_detail_brick": 0,
            "facade_from_deep_brick": 0,
            "facade_from_deep_palette": 0,
            "facade_from_text_inference": 0,
            "facade_from_era_default_red": 0,
            "facade_from_era_default_orange": 0,
            "facade_from_era_default_buff": 0,
        }
        result = resolve_facade_hex(params, stats)
        assert result == "#D4B896"
        assert stats["facade_from_text_inference"] == 1

    def test_priority_5_era_default_pre_1889(self):
        """Priority 5: Era default for pre-1889"""
        params = {
            "facade_material": "stucco",
            "hcd_data": {"construction_date": "pre-1889"},
        }
        stats = {
            "facade_from_detail_brick": 0,
            "facade_from_deep_brick": 0,
            "facade_from_deep_palette": 0,
            "facade_from_text_inference": 0,
            "facade_from_era_default_red": 0,
            "facade_from_era_default_orange": 0,
            "facade_from_era_default_buff": 0,
        }
        result = resolve_facade_hex(params, stats)
        assert result == "#B85A3A"
        assert stats["facade_from_era_default_red"] == 1

    def test_priority_5_era_default_1914_plus(self):
        """Priority 5: Era default for 1914+"""
        params = {
            "facade_material": "stucco",
            "hcd_data": {"construction_date": "1914-1930"},
        }
        stats = {
            "facade_from_detail_brick": 0,
            "facade_from_deep_brick": 0,
            "facade_from_deep_palette": 0,
            "facade_from_text_inference": 0,
            "facade_from_era_default_red": 0,
            "facade_from_era_default_orange": 0,
            "facade_from_era_default_buff": 0,
        }
        result = resolve_facade_hex(params, stats)
        assert result == "#D4B896"
        assert stats["facade_from_era_default_buff"] == 1


class TestResolveTrimHex:
    """Tests for resolve_trim_hex() - priority chain"""

    def test_priority_1_trim_colour_hex(self):
        """Priority 1: facade_detail.trim_colour_hex"""
        params = {
            "facade_detail": {"trim_colour_hex": "#2A2A2A"},
        }
        stats = {
            "trim_from_detail": 0,
            "trim_from_deep": 0,
            "trim_from_era_default": 0,
        }
        result = resolve_trim_hex(params, stats)
        assert result == "#2A2A2A"
        assert stats["trim_from_detail"] == 1

    def test_priority_2_deep_palette_trim(self):
        """Priority 2: deep_facade_analysis.colour_palette_observed.trim"""
        params = {
            "facade_detail": {},
            "deep_facade_analysis": {
                "colour_palette_observed": {"trim": "#3A2A20"}
            },
        }
        stats = {
            "trim_from_detail": 0,
            "trim_from_deep": 0,
            "trim_from_era_default": 0,
        }
        result = resolve_trim_hex(params, stats)
        assert result == "#3A2A20"
        assert stats["trim_from_deep"] == 1

    def test_priority_3_era_default_pre_1889(self):
        """Priority 3: Era default for pre-1889"""
        params = {
            "hcd_data": {"construction_date": "pre-1889"},
        }
        stats = {
            "trim_from_detail": 0,
            "trim_from_deep": 0,
            "trim_from_era_default": 0,
        }
        result = resolve_trim_hex(params, stats)
        assert result == "#3A2A20"
        assert stats["trim_from_era_default"] == 1

    def test_priority_3_era_default_1914_plus(self):
        """Priority 3: Era default for 1914+"""
        params = {
            "hcd_data": {"construction_date": "1914-1930"},
        }
        stats = {
            "trim_from_detail": 0,
            "trim_from_deep": 0,
            "trim_from_era_default": 0,
        }
        result = resolve_trim_hex(params, stats)
        assert result == "#F0EDE8"
        assert stats["trim_from_era_default"] == 1


class TestResolveRoofHex:
    """Tests for resolve_roof_hex() - priority chain"""

    def test_priority_1_deep_palette_roof(self):
        """Priority 1: deep_facade_analysis.colour_palette_observed.roof"""
        params = {
            "deep_facade_analysis": {
                "colour_palette_observed": {"roof": "#4A5A5A"}
            },
        }
        stats = {
            "roof_from_deep": 0,
            "roof_from_text_inference": 0,
            "roof_from_default": 0,
        }
        result = resolve_roof_hex(params, stats)
        assert result == "#4A5A5A"
        assert stats["roof_from_deep"] == 1

    def test_priority_2_text_inference(self):
        """Priority 2: Text inference from roof_colour"""
        params = {
            "roof_colour": "slate",
        }
        stats = {
            "roof_from_deep": 0,
            "roof_from_text_inference": 0,
            "roof_from_default": 0,
        }
        result = resolve_roof_hex(params, stats)
        assert result == "#4A5A5A"
        assert stats["roof_from_text_inference"] == 1

    def test_priority_3_default_grey(self):
        """Priority 3: Default grey"""
        params = {}
        stats = {
            "roof_from_deep": 0,
            "roof_from_text_inference": 0,
            "roof_from_default": 0,
        }
        result = resolve_roof_hex(params, stats)
        assert result == "#5A5A5A"
        assert stats["roof_from_default"] == 1


class TestResolveAccentHex:
    """Tests for resolve_accent_hex() - priority chain"""

    def test_priority_1_deep_palette_accent(self):
        """Priority 1: deep_facade_analysis.colour_palette_observed.accent"""
        params = {
            "deep_facade_analysis": {
                "colour_palette_observed": {"accent": "#C87040"}
            },
            "hcd_data": {"construction_date": "1904-1913"},
        }
        stats = {
            "accent_from_deep": 0,
            "accent_from_doors": 0,
            "accent_from_trim_default": 0,
        }
        result = resolve_accent_hex(params, stats)
        assert result == "#C87040"
        assert stats["accent_from_deep"] == 1

    def test_priority_2_doors_detail_colour_hex(self):
        """Priority 2: doors_detail[0].colour_hex"""
        params = {
            "doors_detail": [
                {"colour_hex": "#8A3A2A"},
                {"colour_hex": "#3A2A20"},
            ],
            "hcd_data": {"construction_date": "1904-1913"},
        }
        stats = {
            "accent_from_deep": 0,
            "accent_from_doors": 0,
            "accent_from_trim_default": 0,
        }
        result = resolve_accent_hex(params, stats)
        assert result == "#8A3A2A"
        assert stats["accent_from_doors"] == 1

    def test_accent_prefers_doors_over_trim_default(self):
        """Test that doors take priority when deep analysis is absent"""
        params = {
            "doors_detail": [
                {"colour_hex": "#8A3A2A"},
            ],
            "facade_detail": {"trim_colour_hex": "#2A2A2A"},
        }
        stats = {
            "accent_from_deep": 0,
            "accent_from_doors": 0,
            "accent_from_trim_default": 0,
        }
        result = resolve_accent_hex(params, stats)
        assert result == "#8A3A2A"
        assert stats["accent_from_doors"] == 1


class TestIsCompletePalette:
    """Tests for is_complete_palette()"""

    def test_complete_palette(self):
        palette = {
            "facade": "#B85A3A",
            "trim": "#3A2A20",
            "roof": "#5A5A5A",
            "accent": "#C87040",
        }
        assert is_complete_palette(palette) is True

    def test_incomplete_palette_missing_accent(self):
        palette = {
            "facade": "#B85A3A",
            "trim": "#3A2A20",
            "roof": "#5A5A5A",
        }
        assert is_complete_palette(palette) is False

    def test_incomplete_palette_invalid_hex(self):
        palette = {
            "facade": "#B85A3A",
            "trim": "#3A2A20",
            "roof": "#5A5A5A",
            "accent": "not_a_hex",
        }
        assert is_complete_palette(palette) is False

    def test_none_palette(self):
        assert is_complete_palette(None) is False

    def test_empty_palette(self):
        assert is_complete_palette({}) is False

    def test_non_dict_palette(self):
        assert is_complete_palette("invalid") is False


class TestIntegrationScenarios:
    """Integration tests with realistic param structures"""

    def test_historic_pre_1889_building(self):
        """Test a pre-1889 historic building with minimal data"""
        params = {
            "building_name": "10 Oxford St",
            "facade_material": "brick",
            "facade_detail": {"trim_colour_hex": "#3A2A20"},
            "doors_detail": [{"colour_hex": "#8A3A2A"}],
            "hcd_data": {
                "construction_date": "pre-1889",
            },
        }
        stats = {
            "facade_from_detail_brick": 0,
            "facade_from_deep_brick": 0,
            "facade_from_deep_palette": 0,
            "facade_from_text_inference": 0,
            "facade_from_era_default_red": 0,
            "facade_from_era_default_orange": 0,
            "facade_from_era_default_buff": 0,
            "trim_from_detail": 0,
            "trim_from_deep": 0,
            "trim_from_era_default": 0,
            "roof_from_deep": 0,
            "roof_from_text_inference": 0,
            "roof_from_default": 0,
            "accent_from_deep": 0,
            "accent_from_doors": 0,
            "accent_from_trim_default": 0,
        }

        facade = resolve_facade_hex(params, stats)
        trim = resolve_trim_hex(params, stats)
        roof = resolve_roof_hex(params, stats)
        accent = resolve_accent_hex(params, stats)

        assert facade == "#B85A3A"  # era default red
        assert trim == "#3A2A20"  # from facade_detail
        assert roof == "#5A5A5A"  # default grey
        assert accent == "#8A3A2A"  # from doors_detail

    def test_well_analyzed_building_with_deep_facade_data(self):
        """Test a building with rich deep_facade_analysis data"""
        params = {
            "building_name": "22 Lippincott St",
            "facade_material": "brick",
            "deep_facade_analysis": {
                "brick_colour_hex": "#C87040",
                "colour_palette_observed": {
                    "facade": "#C87040",
                    "trim": "#2A2A2A",
                    "roof": "#4A5A5A",
                    "accent": "#8A3A2A",
                },
            },
            "hcd_data": {
                "construction_date": "1904-1913",
            },
        }
        stats = {
            "facade_from_detail_brick": 0,
            "facade_from_deep_brick": 0,
            "facade_from_deep_palette": 0,
            "facade_from_text_inference": 0,
            "facade_from_era_default_red": 0,
            "facade_from_era_default_orange": 0,
            "facade_from_era_default_buff": 0,
            "trim_from_detail": 0,
            "trim_from_deep": 0,
            "trim_from_era_default": 0,
            "roof_from_deep": 0,
            "roof_from_text_inference": 0,
            "roof_from_default": 0,
            "accent_from_deep": 0,
            "accent_from_doors": 0,
            "accent_from_trim_default": 0,
        }

        facade = resolve_facade_hex(params, stats)
        trim = resolve_trim_hex(params, stats)
        roof = resolve_roof_hex(params, stats)
        accent = resolve_accent_hex(params, stats)

        # All should come from deep_facade_analysis
        assert facade == "#C87040"
        assert trim == "#2A2A2A"
        assert roof == "#4A5A5A"
        assert accent == "#8A3A2A"

    def test_facade_detail_brick_hex_wins_over_palette(self):
        """Test that facade_detail.brick_colour_hex wins over palette"""
        params = {
            "building_name": "Test",
            "facade_material": "brick",
            "facade_detail": {
                "brick_colour_hex": "#B85A3A",
            },
            "colour_palette": {
                "facade": "#D4B896",  # This should be overwritten
                "trim": "#3A2A20",
                "roof": "#5A5A5A",
                "accent": "#C87040",
            },
            "hcd_data": {
                "construction_date": "1904-1913",
            },
        }
        stats = {
            "facade_from_detail_brick": 0,
            "facade_from_deep_brick": 0,
            "facade_from_deep_palette": 0,
            "facade_from_text_inference": 0,
            "facade_from_era_default_red": 0,
            "facade_from_era_default_orange": 0,
            "facade_from_era_default_buff": 0,
        }

        facade = resolve_facade_hex(params, stats)
        assert facade == "#B85A3A"
        assert stats["facade_from_detail_brick"] == 1
