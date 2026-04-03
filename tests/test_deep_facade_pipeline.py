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
    promote_roof,
    promote_floor_heights,
    promote_facade,
    promote_decorative,
    promote_windows,
    promote_storefront,
    promote_depth,
    promote_doors,
    promote_party_walls,
    promote_bay_window,
    promote_chimney,
    promote_porch,
    _is_valid_hex,
    _normalize_roof_type,
)


# ── _is_valid_hex ──

def test_valid_hex():
    assert _is_valid_hex("#B85A3A") is True
    assert _is_valid_hex("#000000") is True
    assert _is_valid_hex("#ffffff") is True


def test_invalid_hex():
    assert _is_valid_hex("B85A3A") is False
    assert _is_valid_hex("#GGG000") is False
    assert _is_valid_hex("#12345") is False
    assert _is_valid_hex("") is False
    assert _is_valid_hex(None) is False
    assert _is_valid_hex(123) is False


# ── _normalize_roof_type ──

def test_normalize_roof_type_gable():
    assert _normalize_roof_type("gable") == "Gable"
    assert _normalize_roof_type("Gable roof") == "Gable"


def test_normalize_roof_type_cross_gable():
    assert _normalize_roof_type("cross-gable") == "Cross-Gable"
    assert _normalize_roof_type("Cross Gable") == "Cross-Gable"


def test_normalize_roof_type_hip():
    assert _normalize_roof_type("hip") == "Hip"
    assert _normalize_roof_type("Hip roof") == "Hip"


def test_normalize_roof_type_mansard():
    assert _normalize_roof_type("mansard") == "Mansard"


def test_normalize_roof_type_flat():
    assert _normalize_roof_type("flat") == "Flat"


def test_normalize_roof_type_unknown():
    assert _normalize_roof_type("bizarre") is None
    assert _normalize_roof_type("") is None
    assert _normalize_roof_type(None) is None


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
    result, is_new = merge_deep_into_param(param, deep)
    assert "deep_facade_analysis" in result
    assert is_new is True
    dfa = result["deep_facade_analysis"]
    assert dfa["storeys_observed"] == 3
    assert dfa["facade_material_observed"] == "brick"


def test_merge_deep_idempotent():
    """Running merge twice should not duplicate data."""
    param = {"building_name": "Test", "floors": 2}
    deep = {"storeys": 2, "facade_material": "brick", "condition": "fair"}
    result1, is_new1 = merge_deep_into_param(param, deep)
    assert is_new1 is True
    result2, is_new2 = merge_deep_into_param(result1, deep)
    assert is_new2 is False
    assert "deep_facade_analysis" in result2


def test_merge_tracks_meta():
    """Merge should add fusion_applied and timestamp to _meta."""
    param = {"building_name": "Test", "_meta": {"source": "postgis_export"}}
    deep = {"storeys": 2, "facade_material": "brick"}
    result, _ = merge_deep_into_param(param, deep)
    meta = result["_meta"]
    assert "deep_facade" in meta["fusion_applied"]
    assert "deep_facade_merge_ts" in meta


def test_merge_validates_hex():
    """Invalid hex should be stored as None."""
    param = {"building_name": "Test"}
    deep = {"brick_colour_hex": "not-a-hex", "roof_colour_hex": "#ZZZZZZ"}
    result, _ = merge_deep_into_param(param, deep)
    assert result["deep_facade_analysis"]["brick_colour_hex"] is None
    assert result["deep_facade_analysis"]["roof_colour_hex"] is None


def test_merge_stores_chimney_and_porch():
    """New fields chimney_observed and porch_observed should be stored."""
    param = {}
    deep = {
        "chimney": {"present": True, "count": 2},
        "porch": {"present": True, "type": "open"},
    }
    result, _ = merge_deep_into_param(param, deep)
    assert result["deep_facade_analysis"]["chimney_observed"] == {"present": True, "count": 2}
    assert result["deep_facade_analysis"]["porch_observed"] == {"present": True, "type": "open"}


# ── promote_roof ──

def test_promote_roof_gable():
    params = {"roof_type": "flat", "roof_pitch_deg": 0, "roof_detail": {}}
    deep = {"roof_type_observed": "gable", "roof_pitch_deg": 38}
    changes = promote_roof(params, deep)
    assert params["roof_type"] == "Gable"
    assert params["roof_pitch_deg"] == 38
    assert len(changes) >= 1


def test_promote_roof_hip():
    params = {"roof_type": "gable", "roof_detail": {}}
    deep = {"roof_type_observed": "hip roof"}
    changes = promote_roof(params, deep)
    assert params["roof_type"] == "Hip"


def test_promote_roof_cross_gable():
    params = {"roof_type": "", "roof_detail": {}}
    deep = {"roof_type_observed": "cross-gable"}
    changes = promote_roof(params, deep)
    assert params["roof_type"] == "Cross-Gable"


def test_promote_roof_mansard():
    params = {"roof_type": "flat", "roof_detail": {}}
    deep = {"roof_type_observed": "mansard"}
    changes = promote_roof(params, deep)
    assert params["roof_type"] == "Mansard"


def test_promote_roof_material_and_colour():
    params = {"roof_detail": {}}
    deep = {"roof_material": "asphalt shingles", "roof_colour_hex": "#5A5A5A"}
    changes = promote_roof(params, deep)
    assert params["roof_material"] == "asphalt shingles"
    assert params["roof_colour"] == "#5A5A5A"


def test_promote_roof_bargeboard():
    params = {"roof_type": "gable", "roof_detail": {}, "decorative_elements": {}}
    deep = {"bargeboard": {"present": True, "style": "ornate", "colour_hex": "#4A3A2A"}}
    changes = promote_roof(params, deep)
    assert params["roof_detail"]["bargeboard_style"] == "ornate"
    assert params["roof_detail"]["bargeboard_colour_hex"] == "#4A3A2A"


def test_promote_roof_pitch_clamped():
    """Pitch outside 5-75 range should be ignored."""
    params = {"roof_pitch_deg": 35, "roof_detail": {}}
    deep = {"roof_pitch_deg": 90}
    changes = promote_roof(params, deep)
    assert params["roof_pitch_deg"] == 35


def test_promote_roof_eave_clamped():
    """Eave overhang outside 50-1200 range should be ignored."""
    params = {"roof_detail": {}}
    deep = {"depth_notes": {"eave_overhang_mm_est": 5000}}
    changes = promote_roof(params, deep)
    assert "eave_overhang_mm" not in params


# ── promote_floor_heights ──

def test_promote_floor_heights_redistributes():
    params = {
        "floors": 3,
        "total_height_m": 9.0,
        "floor_heights_m": [3.0, 3.0, 3.0],
    }
    deep = {"floor_height_ratios": [0.4, 0.35, 0.25]}
    promote_floor_heights(params, deep)
    fh = params["floor_heights_m"]
    assert len(fh) == 3
    assert abs(sum(fh) - 9.0) < 0.1


def test_promote_floor_heights_no_ratios():
    """No ratios in deep -> should not change."""
    params = {"floors": 2, "total_height_m": 6.0, "floor_heights_m": [3.0, 3.0]}
    deep = {}
    promote_floor_heights(params, deep)
    assert params["floor_heights_m"] == [3.0, 3.0]


# ── promote_facade ──

def test_promote_facade_brick_hex():
    params = {"facade_detail": {}}
    deep = {"brick_colour_hex": "#C87040"}
    promote_facade(params, deep)
    assert params["facade_detail"].get("brick_colour_hex") == "#C87040"


def test_promote_facade_invalid_hex_ignored():
    params = {"facade_detail": {}}
    deep = {"brick_colour_hex": "not-valid"}
    promote_facade(params, deep)
    assert "brick_colour_hex" not in params["facade_detail"]


def test_promote_facade_no_data():
    params = {"facade_detail": {"brick_colour_hex": "#B85A3A"}}
    deep = {}
    promote_facade(params, deep)
    assert params["facade_detail"]["brick_colour_hex"] == "#B85A3A"


def test_promote_facade_colour_palette_validates_hex():
    params = {}
    deep = {
        "colour_palette_observed": {
            "facade": "#AA0000",
            "trim": "bad-hex",
            "roof": "#555555",
        }
    }
    promote_facade(params, deep)
    cp = params.get("colour_palette", {})
    assert cp.get("facade") == "#AA0000"
    assert "trim" not in cp
    assert cp.get("roof") == "#555555"


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


def test_promote_decorative_string_courses_list():
    """String courses as list (old format) should also work."""
    params = {"decorative_elements": {}}
    deep = {
        "decorative_elements_observed": {
            "string_courses": [{"height_m": 3.0}, {"height_m": 6.0}],
        }
    }
    promote_decorative(params, deep)
    sc = params["decorative_elements"]["string_courses"]
    assert sc["present"] is True
    assert sc["count"] == 2


def test_promote_decorative_string_courses_dict():
    """String courses as dict (schema format) should work."""
    params = {"decorative_elements": {}}
    deep = {
        "decorative_elements_observed": {
            "string_courses": {"present": True, "width_mm": 100, "colour_hex": "#888888"},
        }
    }
    promote_decorative(params, deep)
    sc = params["decorative_elements"]["string_courses"]
    assert sc["present"] is True
    assert sc["width_mm"] == 100
    assert sc["colour_hex"] == "#888888"


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
    assert params["decorative_elements"]["cornice"]["projection_mm"] == 150


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
    assert len(changes) >= 1


# ── promote_storefront ──

def test_promote_storefront():
    params = {}
    deep = {
        "storefront_observed": {
            "width_pct": 80,
            "awning": True,
        }
    }
    promote_storefront(params, deep)


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
    assert len(changes) >= 1


# ── promote_party_walls ──

def test_promote_party_walls():
    params = {}
    deep = {"party_wall_left": True, "party_wall_right": False}
    changes = promote_party_walls(params, deep)
    assert params["party_wall_left"] is True
    assert params["party_wall_right"] is False
    assert len(changes) == 2


def test_promote_party_walls_no_overwrite():
    params = {"party_wall_left": False}
    deep = {"party_wall_left": True}
    changes = promote_party_walls(params, deep)
    assert params["party_wall_left"] is False
    assert len(changes) == 0


# ── promote_bay_window ──

def test_promote_bay_window():
    params = {}
    deep = {
        "bay_window_observed": {
            "present": True,
            "type": "canted",
            "width_m_est": 2.0,
            "projection_m_est": 0.5,
            "floors_spanned": 2,
        }
    }
    changes = promote_bay_window(params, deep)
    assert params["bay_window"]["present"] is True
    assert params["bay_window"]["type"] == "canted"
    assert params["bay_window"]["width_m"] == 2.0
    assert params["bay_window"]["floors_spanned"] == 2
    assert len(changes) == 1


def test_promote_bay_window_no_overwrite():
    params = {"bay_window": {"present": True, "type": "box"}}
    deep = {"bay_window_observed": {"present": True, "type": "canted"}}
    changes = promote_bay_window(params, deep)
    assert params["bay_window"]["type"] == "box"
    assert len(changes) == 0


# ── promote_chimney ──

def test_promote_chimney_bool():
    params = {}
    deep = {"chimney_observed": True}
    changes = promote_chimney(params, deep)
    assert params["chimneys"]["count"] == 1
    assert "chimney" in params["roof_features"]
    assert len(changes) == 1


def test_promote_chimney_dict():
    params = {"roof_features": []}
    deep = {"chimney_observed": {"present": True, "count": 2, "position": "center"}}
    changes = promote_chimney(params, deep)
    assert params["chimneys"]["count"] == 2
    assert params["chimneys"]["position"] == "center"


def test_promote_chimney_no_overwrite():
    params = {"chimneys": {"count": 1, "position": "side"}}
    deep = {"chimney_observed": {"present": True, "count": 3}}
    changes = promote_chimney(params, deep)
    assert params["chimneys"]["count"] == 1
    assert len(changes) == 0


# ── promote_porch ──

def test_promote_porch():
    params = {}
    deep = {
        "porch_observed": {
            "present": True,
            "type": "covered",
            "width_m_est": 3.0,
            "depth_m_est": 1.5,
        }
    }
    changes = promote_porch(params, deep)
    assert params["porch"]["present"] is True
    assert params["porch"]["type"] == "covered"
    assert params["porch_present"] is True
    assert len(changes) == 1


def test_promote_porch_no_overwrite():
    params = {"porch": {"present": True, "type": "open"}}
    deep = {"porch_observed": {"present": True, "type": "enclosed"}}
    changes = promote_porch(params, deep)
    assert params["porch"]["type"] == "open"
    assert len(changes) == 0
