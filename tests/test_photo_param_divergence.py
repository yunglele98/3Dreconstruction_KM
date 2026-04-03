"""Tests for photo_param_divergence.py."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts" / "analyze"))

from photo_param_divergence import compare_building, apply_fixes, _colour_similar


def _building(**overrides):
    base = {
        "building_name": "Test Building",
        "facade_material": "brick",
        "facade_detail": {"brick_colour_hex": "#B85A3A"},
        "floors": 2,
        "roof_type": "gable",
        "roof_pitch_deg": 35,
        "condition": "fair",
        "has_storefront": False,
        "bay_window": {"present": False},
        "door_count": 1,
        "windows_per_floor": [2, 3],
        "colour_palette": {"facade": "#B85A3A", "trim": "#3A2A20", "roof": "#5A5A5A"},
        "photo_observations": {"photo": "test.jpg"},
        "deep_facade_analysis": {
            "source_photo": "test.jpg",
            "facade_material_observed": "brick",
            "brick_colour_hex": "#B85A3A",
            "storeys_observed": 2,
            "roof_type_observed": "gable",
            "roof_pitch_deg": 35,
            "condition_observed": "fair",
            "storefront_observed": {},
            "bay_window_observed": {"present": False},
            "doors_observed": [{"position": "center"}],
            "windows_detail": [
                {"floor": "ground", "count": 2},
                {"floor": "second", "count": 3},
            ],
            "colour_palette_observed": {
                "facade": "#B85A3A", "trim": "#3A2A20",
                "roof": "#5A5A5A", "accent": "#D06030",
            },
        },
    }
    base.update(overrides)
    return base


def test_perfect_match():
    result = compare_building(_building())
    assert result["fidelity_score"] == 100
    assert result["divergence_count"] == 0


def test_no_photo():
    b = _building()
    b["photo_observations"] = {}
    b["deep_facade_analysis"]["source_photo"] = None
    result = compare_building(b)
    assert result is None


def test_material_divergence():
    b = _building()
    b["facade_material"] = "stucco"
    result = compare_building(b)
    assert any(d["field"] == "facade_material" for d in result["divergences"])


def test_floor_count_divergence():
    b = _building(floors=3)
    result = compare_building(b)
    assert any(d["field"] == "floors" for d in result["divergences"])


def test_colour_divergence():
    b = _building()
    b["facade_detail"]["brick_colour_hex"] = "#0000FF"
    result = compare_building(b)
    assert any("brick_colour" in d["field"] for d in result["divergences"])


def test_storefront_divergence():
    b = _building(has_storefront=True)
    result = compare_building(b)
    assert any(d["field"] == "has_storefront" for d in result["divergences"])


def test_condition_divergence():
    b = _building(condition="poor")
    result = compare_building(b)
    assert any(d["field"] == "condition" for d in result["divergences"])


def test_apply_fixes():
    b = _building(condition="poor")
    result = compare_building(b)
    fixable = [d for d in result["divergences"] if d.get("fix_field")]
    applied = apply_fixes(b, fixable)
    assert len(applied) > 0
    assert b["condition"] == "fair"


def test_colour_similar_same():
    assert _colour_similar("#B85A3A", "#B85A3A")


def test_colour_similar_different():
    assert not _colour_similar("#FF0000", "#0000FF")


def test_colour_similar_close():
    assert _colour_similar("#B85A3A", "#BA5C3C")


def test_roof_pitch_divergence():
    b = _building()
    b["roof_pitch_deg"] = 10
    b["deep_facade_analysis"]["roof_pitch_deg"] = 40
    result = compare_building(b)
    assert any(d["field"] == "roof_pitch_deg" for d in result["divergences"])


def test_bay_window_divergence():
    b = _building()
    b["bay_window"] = {"present": True}
    result = compare_building(b)
    assert any("bay_window" in d["field"] for d in result["divergences"])
