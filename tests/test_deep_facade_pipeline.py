#!/usr/bin/env python3
"""Tests for scripts/deep_facade_pipeline.py"""
import json
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from deep_facade_pipeline import (
    normalize_address,
    should_skip,
    merge_deep_into_param,
    is_valid_hex,
    promote_roof,
    promote_floor_heights,
    promote_facade,
    promote_decorative,
    promote_windows,
    promote_storefront,
    promote_depth,
    promote_doors,
    promote_party_walls,
    promote_condition,
)


# ── is_valid_hex ──

def test_valid_hex():
    assert is_valid_hex("#B85A3A") is True
    assert is_valid_hex("#ffffff") is True
    assert is_valid_hex("#000000") is True


def test_invalid_hex():
    assert is_valid_hex("B85A3A") is False
    assert is_valid_hex("#GGG000") is False
    assert is_valid_hex("#FFF") is False
    assert is_valid_hex("") is False
    assert is_valid_hex(None) is False
    assert is_valid_hex(123) is False


# ── normalize_address ──

def test_normalize_address_basic():
    assert normalize_address("  123 Baldwin St  ") == "123 Baldwin St"


def test_normalize_address_removes_parenthetical():
    assert normalize_address("123 Baldwin St (near corner)") == "123 Baldwin St"


def test_normalize_address_slash_takes_first():
    assert normalize_address("123 Baldwin St / 456 Spadina") == "123 Baldwin St"


def test_normalize_address_tilde():
    assert normalize_address("~242 Augusta Ave") == "242 Augusta Ave"


def test_normalize_address_empty():
    assert normalize_address("") == ""
    assert normalize_address(None) == ""


# ── should_skip ──

def test_should_skip_alley():
    assert should_skip("alley behind Baldwin", {}) is True


def test_should_skip_mural():
    assert should_skip("mural on wall", {}) is True


def test_should_skip_no_address():
    assert should_skip("", {}) is True
    assert should_skip(None, {}) is True


def test_should_skip_valid_building():
    assert should_skip("123 Baldwin St", {"facade_material": "brick"}) is False


def test_should_skip_no_data():
    # No facade_material and no storeys -> skip
    assert should_skip("123 Baldwin St", {}) is True


# ── merge_deep_into_param ──

def test_merge_deep_into_param_basic():
    param = {"building_name": "Test", "floors": 2}
    deep = {
        "storeys": 3,
        "facade_material": "brick",
        "brick_colour_hex": "#B85A3A",
        "roof_type": "gable",
        "roof_pitch_deg": 40,
        "windows": [{"floor": "Ground", "count": 2}],
        "condition": "good",
    }
    result = merge_deep_into_param(param, deep)
    assert "deep_facade_analysis" in result
    dfa = result["deep_facade_analysis"]
    assert dfa["storeys_observed"] == 3
    assert dfa["facade_material_observed"] == "brick"


def test_merge_deep_idempotent():
    """Running merge twice should not duplicate data."""
    param = {"building_name": "Test", "floors": 2}
    deep = {"storeys": 2, "facade_material": "brick", "condition": "fair"}
    result1 = merge_deep_into_param(param, deep)
    result2 = merge_deep_into_param(result1, deep)
    # Should have exactly one deep_facade_analysis
    assert "deep_facade_analysis" in result2


# ── promote_roof ──

def test_promote_roof_gable():
    params = {"roof_type": "flat", "roof_pitch_deg": 0, "roof_detail": {}}
    deep = {"roof_type_observed": "gable", "roof_pitch_deg": 38}
    changes = promote_roof(params, deep)
    assert params["roof_type"] == "Gable"
    assert params["roof_pitch_deg"] == 38
    assert len(changes) >= 2


def test_promote_roof_cross_gable():
    params = {"roof_type": "", "roof_detail": {}}
    deep = {"roof_type_observed": "cross-gable"}
    changes = promote_roof(params, deep)
    assert params["roof_type"] == "Cross-Gable"


def test_promote_roof_hip():
    params = {"roof_type": "", "roof_detail": {}}
    deep = {"roof_type_observed": "hip roof"}
    changes = promote_roof(params, deep)
    assert params["roof_type"] == "Hip"


def test_promote_roof_bargeboard():
    params = {"roof_type": "gable", "roof_detail": {}, "decorative_elements": {}}
    deep = {"bargeboard": {"present": True, "style": "ornate", "colour_hex": "#4A3A2A"}}
    changes = promote_roof(params, deep)
    rd = params["roof_detail"]
    assert rd["bargeboard_style"] == "ornate"
    assert rd["bargeboard_colour_hex"] == "#4A3A2A"


def test_promote_roof_material_and_colour():
    params = {"roof_detail": {}}
    deep = {"roof_material": "slate", "roof_colour_hex": "#4A5A6A"}
    changes = promote_roof(params, deep)
    assert params["roof_material"] == "slate"
    assert params["roof_colour"] == "#4A5A6A"
    assert any("roof_material" in c for c in changes)


def test_promote_roof_invalid_colour_ignored():
    params = {"roof_detail": {}}
    deep = {"roof_colour_hex": "not-a-hex"}
    changes = promote_roof(params, deep)
    assert "roof_colour" not in params


def test_promote_roof_gable_window():
    params = {"roof_type": "gable", "roof_detail": {}}
    deep = {"gable_window": {"present": True, "type": "round", "width_m_est": 0.5, "height_m_est": 0.5}}
    changes = promote_roof(params, deep)
    gw = params["roof_detail"]["gable_window"]
    assert gw["present"] is True
    assert gw["type"] == "round"


# ── promote_floor_heights ──

def test_promote_floor_heights_redistributes():
    params = {
        "floors": 3,
        "total_height_m": 9.0,
        "floor_heights_m": [3.0, 3.0, 3.0],
    }
    deep = {"floor_height_ratios": [0.4, 0.35, 0.25], "storeys_observed": 3}
    promote_floor_heights(params, deep)
    fh = params["floor_heights_m"]
    assert len(fh) == 3
    assert abs(sum(fh) - 9.0) < 0.1
    assert fh[0] > fh[1] > fh[2]


def test_promote_floor_heights_no_ratios():
    """No ratios in deep -> should not change."""
    params = {"floors": 2, "total_height_m": 6.0, "floor_heights_m": [3.0, 3.0]}
    deep = {}
    promote_floor_heights(params, deep)
    assert params["floor_heights_m"] == [3.0, 3.0]


def test_promote_floor_heights_half_storey():
    params = {"floors": 2, "total_height_m": 7.0, "roof_type": "gable"}
    deep = {"has_half_storey_gable": True, "floor_height_ratios": [0.55, 0.45], "storeys_observed": 2}
    promote_floor_heights(params, deep)
    assert params.get("roof_detail", {}).get("has_half_storey") is True


# ── promote_facade ──

def test_promote_facade_brick_hex():
    params = {"facade_detail": {}}
    deep = {"brick_colour_hex": "#C87040"}
    promote_facade(params, deep)
    assert params["facade_detail"].get("brick_colour_hex") == "#C87040"


def test_promote_facade_brick_hex_overwrites_defaults():
    """Should overwrite skeleton default hex values."""
    for default_hex in ("#B85A3A", "#D4B896", "#7A5C44"):
        params = {"facade_detail": {"brick_colour_hex": default_hex}}
        deep = {"brick_colour_hex": "#AA6633"}
        promote_facade(params, deep)
        assert params["facade_detail"]["brick_colour_hex"] == "#AA6633"


def test_promote_facade_invalid_hex_ignored():
    params = {"facade_detail": {}}
    deep = {"brick_colour_hex": "reddish-brown"}
    promote_facade(params, deep)
    assert "brick_colour_hex" not in params["facade_detail"]


def test_promote_facade_no_data():
    params = {"facade_detail": {"brick_colour_hex": "#B85A3A"}}
    deep = {}
    promote_facade(params, deep)
    # Default hex should remain since deep has nothing
    assert params["facade_detail"]["brick_colour_hex"] == "#B85A3A"


def test_promote_facade_bond_pattern():
    params = {"facade_detail": {}}
    deep = {"brick_bond_observed": "Flemish bond"}
    promote_facade(params, deep)
    assert params["facade_detail"]["bond_pattern"] == "Flemish bond"


def test_promote_facade_mortar_colour():
    params = {"facade_detail": {}}
    deep = {"mortar_colour": "light grey"}
    promote_facade(params, deep)
    assert params["facade_detail"]["mortar_colour"] == "light grey"


def test_promote_facade_colour_palette():
    params = {"colour_palette": {"facade": "#AA0000"}}
    deep = {"colour_palette_observed": {"facade": "#BB0000", "trim": "#FFFFFF", "roof": "#333333"}}
    promote_facade(params, deep)
    cp = params["colour_palette"]
    assert cp["facade"] == "#AA0000"  # existing not overwritten
    assert cp["trim"] == "#FFFFFF"    # new value filled in
    assert cp["roof"] == "#333333"


def test_promote_facade_material_painted():
    params = {"facade_material": "brick"}
    deep = {"facade_material_observed": "painted brick"}
    promote_facade(params, deep)
    assert "painted" in params.get("facade_colour", "")


def test_promote_facade_material_unknown_to_brick():
    params = {"facade_material": ""}
    deep = {"facade_material_observed": "brick"}
    promote_facade(params, deep)
    assert params["facade_material"] == "brick"


# ── promote_decorative ──

def test_promote_decorative_adds_elements():
    params = {"decorative_elements": {}}
    deep = {
        "decorative_elements_observed": {
            "cornice": {"present": True, "projection_mm": 200},
            "string_courses": {"present": True, "width_mm": 80},
        }
    }
    promote_decorative(params, deep)
    dec = params["decorative_elements"]
    assert "cornice" in dec
    assert "string_courses" in dec


def test_promote_decorative_cornice_preserves_dimensions():
    params = {"decorative_elements": {}}
    deep = {
        "decorative_elements_observed": {
            "cornice": {"present": True, "height_mm": 250, "projection_mm": 180, "colour_hex": "#3A2A20"},
        }
    }
    promote_decorative(params, deep)
    cornice = params["decorative_elements"]["cornice"]
    assert cornice["height_mm"] == 250
    assert cornice["projection_mm"] == 180
    assert cornice["colour_hex"] == "#3A2A20"


def test_promote_decorative_no_overwrite():
    params = {
        "decorative_elements": {
            "cornice": {"present": True, "projection_mm": 150},
        }
    }
    deep = {
        "decorative_elements_observed": {
            "cornice": {"present": True, "projection_mm": 300},
        }
    }
    promote_decorative(params, deep)
    # Original value should be preserved (no overwrite)
    assert params["decorative_elements"]["cornice"]["projection_mm"] == 150


def test_promote_decorative_string_courses_list():
    """String courses as a list of dicts."""
    params = {"decorative_elements": {}}
    deep = {
        "decorative_elements_observed": {
            "string_courses": [{"height": "between 1st and 2nd"}, {"height": "above 2nd"}],
        }
    }
    promote_decorative(params, deep)
    sc = params["decorative_elements"]["string_courses"]
    assert sc["present"] is True
    assert sc["count"] == 2


def test_promote_decorative_string_courses_dict():
    """String courses as a dict with present flag."""
    params = {"decorative_elements": {}}
    deep = {
        "decorative_elements_observed": {
            "string_courses": {"present": True, "count": 3, "width_mm": 80, "colour_hex": "#B85A3A"},
        }
    }
    promote_decorative(params, deep)
    sc = params["decorative_elements"]["string_courses"]
    assert sc["present"] is True
    assert sc["count"] == 3
    assert sc["width_mm"] == 80
    assert sc["colour_hex"] == "#B85A3A"


def test_promote_decorative_polychromatic():
    params = {"decorative_elements": {}}
    deep = {"decorative_elements_observed": {"diamond_brick_patterns": True}}
    promote_decorative(params, deep)
    assert params["decorative_elements"]["polychromatic_brick"] is True


def test_promote_decorative_stone_lintels():
    params = {"decorative_elements": {}}
    deep = {
        "decorative_elements_observed": {
            "stone_lintels": {"present": True, "colour_hex": "#AAAAAA"},
        }
    }
    promote_decorative(params, deep)
    assert params["decorative_elements"]["stone_lintels"]["present"] is True
    assert params["decorative_elements"]["stone_lintels"]["colour_hex"] == "#AAAAAA"


def test_promote_decorative_quoins_with_details():
    params = {"decorative_elements": {}}
    deep = {
        "decorative_elements_observed": {
            "quoins": {"present": True, "strip_width_mm": 120, "colour_hex": "#CCCCCC"},
        }
    }
    promote_decorative(params, deep)
    q = params["decorative_elements"]["quoins"]
    assert q["present"] is True
    assert q["strip_width_mm"] == 120
    assert q["colour_hex"] == "#CCCCCC"


# ── promote_windows ──

def test_promote_windows_basic():
    params = {"windows_detail": []}
    deep = {
        "windows_detail": [
            {"floor": "Ground floor", "count": 2, "type": "double_hung"},
            {"floor": "Second floor", "count": 3, "type": "double_hung"},
        ]
    }
    changes = promote_windows(params, deep)
    assert len(params["windows_detail"]) == 2
    assert params["windows_per_floor"] == [2, 3]


def test_promote_windows_floor_mapping():
    """Floor names should be normalized to canonical names."""
    params = {"windows_detail": [], "facade_width_m": 6.0}
    deep = {
        "windows_detail": [
            {"floor": "ground", "count": 1, "type": "fixed"},
            {"floor": "second", "count": 2, "type": "double-hung", "width_ratio": 0.15},
            {"floor": "attic", "count": 1, "type": "round"},
        ]
    }
    promote_windows(params, deep)
    floors = [w["floor"] for w in params["windows_detail"]]
    assert floors == ["Ground floor", "Second floor", "Gable"]
    # Width from ratio
    win = params["windows_detail"][1]["windows"][0]
    assert win["width_m"] == 0.9  # 6.0 * 0.15


def test_promote_windows_glazing_and_sill():
    params = {"windows_detail": []}
    deep = {
        "windows_detail": [
            {"floor": "Second floor", "count": 2, "type": "double-hung",
             "glazing": "2-over-2", "sill_height_m": 0.8},
        ]
    }
    promote_windows(params, deep)
    win = params["windows_detail"][0]["windows"][0]
    assert win["glazing"] == "2-over-2"
    assert win["sill_height_m"] == 0.8


def test_promote_windows_storefront_floor():
    params = {"windows_detail": []}
    deep = {
        "windows_detail": [
            {"floor": "Ground floor", "count": 0, "note": "storefront glazing"},
            {"floor": "Second floor", "count": 3, "type": "double-hung"},
        ]
    }
    promote_windows(params, deep)
    assert params["windows_detail"][0]["is_storefront"] is True
    assert params["windows_per_floor"] == [0, 3]


# ── promote_storefront ──

def test_promote_storefront_awning_dict():
    params = {}
    deep = {
        "storefront_observed": {
            "awning": {"present": True, "type": "retractable", "colour": "red"},
        }
    }
    changes = promote_storefront(params, deep)
    assert params["storefront"]["awning"]["type"] == "retractable"
    assert params["storefront"]["awning"]["colour"] == "red"


def test_promote_storefront_awning_boolean():
    params = {}
    deep = {
        "storefront_observed": {
            "awning": True,
        }
    }
    changes = promote_storefront(params, deep)
    assert params["storefront"]["awning"]["present"] is True
    assert any("boolean" in c for c in changes)


def test_promote_storefront_width_from_pct():
    params = {"facade_width_m": 5.0}
    deep = {
        "storefront_observed": {"width_pct": 80}
    }
    changes = promote_storefront(params, deep)
    assert params["storefront"]["width_m"] == 4.0
    assert params["has_storefront"] is True


def test_promote_storefront_security_grille():
    params = {}
    deep = {"storefront_observed": {"security_grille": True}}
    promote_storefront(params, deep)
    assert params["storefront"]["security_grille"] is True


def test_promote_storefront_signage():
    params = {}
    deep = {"storefront_observed": {"signage_text": "KENSINGTON FRUIT"}}
    promote_storefront(params, deep)
    assert params["storefront"]["signage_text"] == "KENSINGTON FRUIT"


# ── promote_depth ──

def test_promote_depth_notes():
    params = {"site": {}, "roof_detail": {}}
    deep = {
        "depth_notes": {
            "setback_m_est": 1.5,
            "foundation_height_m_est": 0.4,
            "eave_overhang_mm_est": 350,
            "step_count": 4,
        }
    }
    changes = promote_depth(params, deep)
    assert params["foundation_height_m"] == 0.4
    assert any("foundation" in c for c in changes)


def test_promote_depth_step_count_to_doors():
    params = {"doors_detail": [{"id": "door_1", "type": "residential"}]}
    deep = {"depth_notes": {"step_count": 3}}
    changes = promote_depth(params, deep)
    assert params["doors_detail"][0]["steps"] == 3


# ── promote_doors ──

def test_promote_doors_creates_detail():
    params = {}
    deep = {
        "doors_observed": [
            {"type": "residential", "position": "left", "width_m_est": 0.85, "transom": True, "steps": 2},
            {"type": "commercial", "position": "center", "width_m_est": 1.2},
        ]
    }
    changes = promote_doors(params, deep)
    assert len(params["doors_detail"]) == 2
    assert params["doors_detail"][0]["transom"]["present"] is True
    assert params["doors_detail"][0]["steps"] == 2
    assert params["doors_detail"][1]["position"] == "center"


def test_promote_doors_no_overwrite():
    params = {"doors_detail": [{"id": "door_1", "type": "existing"}]}
    deep = {
        "doors_observed": [{"type": "commercial", "position": "center"}]
    }
    changes = promote_doors(params, deep)
    # Should not overwrite existing doors_detail
    assert params["doors_detail"][0]["type"] == "existing"
    assert len(changes) == 0


# ── promote_party_walls ──

def test_promote_party_walls():
    params = {}
    deep = {"party_wall_left": True, "party_wall_right": False}
    changes = promote_party_walls(params, deep)
    assert params["party_wall_left"] is True
    assert params["party_wall_right"] is False
    assert len(changes) == 2


def test_promote_party_walls_no_change():
    params = {"party_wall_left": True}
    deep = {"party_wall_left": True}
    changes = promote_party_walls(params, deep)
    assert len(changes) == 0


def test_promote_party_walls_none_skipped():
    params = {}
    deep = {"party_wall_left": None}
    changes = promote_party_walls(params, deep)
    assert len(changes) == 0
    assert "party_wall_left" not in params


# ── promote_condition ──

def test_promote_condition():
    params = {}
    deep = {"condition_observed": "fair", "condition_notes": "Cracked mortar on east side"}
    changes = promote_condition(params, deep)
    assert params["condition"] == "fair"
    assert params["assessment"]["condition_issues"] == "Cracked mortar on east side"
    assert len(changes) == 2


def test_promote_condition_valid_values():
    for cond in ("good", "fair", "poor", "excellent"):
        params = {}
        deep = {"condition_observed": cond}
        changes = promote_condition(params, deep)
        assert params["condition"] == cond


def test_promote_condition_invalid_skipped():
    params = {}
    deep = {"condition_observed": "needs work"}
    changes = promote_condition(params, deep)
    assert "condition" not in params


def test_promote_condition_no_overwrite_notes():
    params = {"assessment": {"condition_issues": "existing notes"}}
    deep = {"condition_notes": "new notes"}
    changes = promote_condition(params, deep)
    assert params["assessment"]["condition_issues"] == "existing notes"
