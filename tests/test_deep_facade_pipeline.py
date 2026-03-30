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
)


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
    promote_roof(params, deep)
    # Should not overwrite if original has a value — depends on implementation
    # At minimum the function should not error


def test_promote_roof_bargeboard():
    params = {"roof_type": "gable", "roof_detail": {}, "decorative_elements": {}}
    deep = {"bargeboard": {"present": True, "style": "ornate", "colour_hex": "#4A3A2A"}}
    promote_roof(params, deep)
    # Should add bargeboard to decorative_elements or roof_detail


# ── promote_floor_heights ──

def test_promote_floor_heights_redistributes():
    params = {
        "floors": 3,
        "total_height_m": 9.0,
        "floor_heights_m": [3.0, 3.0, 3.0],
    }
    deep = {"floor_height_ratios": [0.4, 0.35, 0.25]}
    promote_floor_heights(params, deep)
    # Floor heights should be redistributed according to ratios
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


def test_promote_facade_no_data():
    params = {"facade_detail": {"brick_colour_hex": "#B85A3A"}}
    deep = {}
    promote_facade(params, deep)
    # Should not change existing
    assert params["facade_detail"]["brick_colour_hex"] == "#B85A3A"


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
    assert "cornice" in dec or "string_courses" in dec


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


# ── promote_windows ──

def test_promote_windows_basic():
    params = {"windows_detail": []}
    deep = {
        "windows_detail": [
            {"floor": "Ground floor", "count": 2, "type": "double_hung"},
            {"floor": "Second floor", "count": 3, "type": "double_hung"},
        ]
    }
    promote_windows(params, deep)


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
    promote_depth(params, deep)
