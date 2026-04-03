"""Tests for realism analysis scripts in scripts/analyze/."""

import json
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts" / "analyze"))
sys.path.insert(0, str(ROOT / "scripts"))

from facade_colour_realism import hex_to_hsv, colour_distance, check_era_match, analyze_street
from streetscape_continuity import analyze_adjacent_pairs
from weathering_consistency import analyze_building_weathering
from window_pattern_realism import analyze_window_realism
from decorative_completeness import get_present_elements, analyze_building


# ── facade_colour_realism ──

def test_hex_to_hsv_basic():
    h, s, v = hex_to_hsv("#FF0000")
    assert abs(h) < 1 or abs(h - 360) < 1  # red = 0 degrees
    assert s == 1.0
    assert v == 1.0


def test_hex_to_hsv_invalid():
    assert hex_to_hsv("") is None
    assert hex_to_hsv(None) is None
    assert hex_to_hsv("#GGG") is None


def test_colour_distance_identical():
    assert colour_distance("#B85A3A", "#B85A3A") == 0.0


def test_colour_distance_different():
    d = colour_distance("#FF0000", "#0000FF")
    assert d > 0.5


def test_era_match_victorian_red_brick():
    ok, _ = check_era_match("#B85A3A", "Pre-1889")
    assert ok


def test_era_match_bright_blue_fails():
    ok, reason = check_era_match("#0000FF", "Pre-1889")
    assert not ok
    assert "hue" in reason


def test_analyze_street_basic():
    buildings = [
        {"building_name": "A", "facade_detail": {"brick_colour_hex": "#B85A3A"},
         "facade_material": "brick", "hcd_data": {"construction_date": "Pre-1889"}},
        {"building_name": "B", "facade_detail": {"brick_colour_hex": "#C87040"},
         "facade_material": "brick", "hcd_data": {"construction_date": "1904-1913"}},
    ]
    result = analyze_street(buildings, "Test St")
    assert result is not None
    assert result["building_count"] == 2
    assert result["unique_colours"] == 2


# ── streetscape_continuity ──

def test_height_step_detected():
    buildings = [
        {"building_name": "1 Test", "party_wall_right": True, "total_height_m": 9.0,
         "facade_material": "brick", "hcd_data": {}, "site": {}},
        {"building_name": "3 Test", "party_wall_left": True, "total_height_m": 4.0,
         "facade_material": "brick", "hcd_data": {}, "site": {}},
    ]
    issues = analyze_adjacent_pairs(buildings)
    assert any(i["type"] == "HEIGHT_STEP" for i in issues)


def test_no_issues_on_matching_pair():
    buildings = [
        {"building_name": "1 Test", "party_wall_right": True, "total_height_m": 8.0,
         "facade_material": "brick", "roof_type": "gable", "hcd_data": {}, "site": {}},
        {"building_name": "3 Test", "party_wall_left": True, "total_height_m": 8.5,
         "facade_material": "brick", "roof_type": "gable", "hcd_data": {}, "site": {}},
    ]
    issues = analyze_adjacent_pairs(buildings)
    height_issues = [i for i in issues if i["type"] == "HEIGHT_STEP"]
    assert len(height_issues) == 0


def test_missing_party_wall_flagged():
    buildings = [
        {"building_name": "1 Test", "party_wall_right": False, "total_height_m": 8.0,
         "facade_material": "brick", "hcd_data": {"typology": "Row"}, "site": {}},
        {"building_name": "3 Test", "party_wall_left": True, "total_height_m": 8.0,
         "facade_material": "brick", "hcd_data": {}, "site": {}},
    ]
    issues = analyze_adjacent_pairs(buildings)
    assert any(i["type"] == "MISSING_PARTY_WALL" for i in issues)


# ── weathering_consistency ──

def test_era_condition_unlikely():
    params = {
        "building_name": "Old Building",
        "condition": "good",
        "facade_material": "brick",
        "hcd_data": {"construction_date": "Pre-1889"},
        "facade_detail": {"mortar_joint_width_mm": 10, "bond_pattern": "running bond"},
    }
    result = analyze_building_weathering(params)
    assert any(i["type"] == "ERA_CONDITION_UNLIKELY" for i in result["issues"])


def test_missing_mortar_detail():
    params = {
        "building_name": "Brick House",
        "condition": "fair",
        "facade_material": "brick",
        "hcd_data": {"construction_date": "1904-1913"},
        "facade_detail": {},
    }
    result = analyze_building_weathering(params)
    assert any(i["type"] == "MISSING_MORTAR_DETAIL" for i in result["issues"])


def test_weathering_params_returned():
    params = {
        "building_name": "Test",
        "condition": "poor",
        "facade_material": "stucco",
        "hcd_data": {},
    }
    result = analyze_building_weathering(params)
    assert result["weathering_params"]["roughness_bias"] > 0.1


# ── window_pattern_realism ──

def test_bay_gable_needs_bay_window():
    params = {
        "building_name": "Bay House",
        "floors": 2,
        "facade_width_m": 5.0,
        "windows_per_floor": [2, 2],
        "has_storefront": False,
        "hcd_data": {"typology": "House-form, Semi-detached, Bay-and-Gable",
                     "construction_date": "1889-1903"},
        "bay_window": {},
        "roof_detail": {},
    }
    result = analyze_window_realism(params)
    assert any(i["type"] == "BAY_GABLE_MISSING_BAY" for i in result["issues"])


def test_normal_windows_no_issues():
    params = {
        "building_name": "Normal",
        "floors": 2,
        "facade_width_m": 6.0,
        "windows_per_floor": [2, 3],
        "has_storefront": False,
        "hcd_data": {"typology": "House-form", "construction_date": "1904-1913"},
    }
    result = analyze_window_realism(params)
    assert result["score"] >= 80


# ── decorative_completeness ──

def test_get_present_elements():
    params = {
        "decorative_elements": {
            "cornice": {"present": True},
            "string_courses": {"present": False},
            "quoins": {"present": True},
        },
        "bay_window": {"present": True},
    }
    present = get_present_elements(params)
    assert "cornice" in present
    assert "quoins" in present
    assert "bay_window" in present
    assert "string_courses" not in present


def test_contributing_low_completeness_flagged():
    params = {
        "building_name": "Heritage House",
        "hcd_data": {
            "construction_date": "Pre-1889",
            "typology": "House-form",
            "contributing": "Yes",
        },
        "roof_type": "gable",
        "decorative_elements": {},
    }
    result = analyze_building(params)
    assert "flag" in result
    assert result["completeness"] < 0.3
