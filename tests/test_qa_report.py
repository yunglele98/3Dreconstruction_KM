#!/usr/bin/env python3
"""Tests for scripts/generate_qa_report.py (HTML dashboard version)."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from generate_qa_report import _check_building, _extract_street_from_name, _scan_params


def _base_params():
    return {
        "building_name": "99 Test St",
        "facade_width_m": 6.0,
        "total_height_m": 6.5,
        "floors": 2,
        "floor_heights_m": [3.0, 3.5],
        "facade_material": "brick",
        "facade_detail": {"brick_colour_hex": "#B85A3A"},
        "roof_type": "flat",
        "has_storefront": False,
        "doors_detail": [{"position": "left", "type": "single"}],
        "windows_detail": [{"floor": "Ground floor", "windows": [{"count": 2}]}],
        "decorative_elements": {"cornice": {"present": True}},
        "deep_facade_analysis": {"storeys_observed": 2},
        "photo_observations": {"facade_colour_observed": "red"},
        "city_data": {"height_avg_m": 6.5},
    }


DUMMY_PATH = Path("params/99_Test_St.json")


def test_clean_building_no_issues():
    issues, score = _check_building(_base_params(), DUMMY_PATH)
    assert len(issues) == 0
    assert score == 100


def test_missing_windows_detail():
    p = _base_params()
    p["windows_detail"] = []
    issues, score = _check_building(p, DUMMY_PATH)
    cats = [i.category for i in issues]
    assert "missing_windows_detail" in cats


def test_missing_doors_detail():
    p = _base_params()
    p.pop("doors_detail")
    issues, score = _check_building(p, DUMMY_PATH)
    cats = [i.category for i in issues]
    assert "missing_doors_detail" in cats


def test_missing_roof_type():
    p = _base_params()
    p["roof_type"] = None
    issues, score = _check_building(p, DUMMY_PATH)
    cats = [i.category for i in issues]
    assert "missing_roof_type" in cats


def test_height_mismatch():
    p = _base_params()
    p["total_height_m"] = 15.0
    p["city_data"] = {"height_avg_m": 6.5}
    issues, score = _check_building(p, DUMMY_PATH)
    cats = [i.category for i in issues]
    assert "height_mismatch" in cats


def test_missing_brick_colour():
    p = _base_params()
    p["facade_material"] = "brick"
    p["facade_detail"] = {}
    issues, score = _check_building(p, DUMMY_PATH)
    cats = [i.category for i in issues]
    assert "missing_brick_colour" in cats


def test_storefront_conflict():
    p = _base_params()
    p["storefront"] = {"type": "full"}
    p["has_storefront"] = False
    issues, score = _check_building(p, DUMMY_PATH)
    cats = [i.category for i in issues]
    assert "storefront_conflict" in cats


def test_missing_decorative_elements():
    p = _base_params()
    p.pop("decorative_elements")
    issues, score = _check_building(p, DUMMY_PATH)
    cats = [i.category for i in issues]
    assert "missing_decorative_elements" in cats


def test_floor_heights_mismatch():
    p = _base_params()
    p["floors"] = 3
    p["floor_heights_m"] = [3.0, 3.5]
    issues, score = _check_building(p, DUMMY_PATH)
    cats = [i.category for i in issues]
    assert "floor_heights_mismatch" in cats


def test_extract_street_from_name():
    assert "Test St" in _extract_street_from_name("99 Test St")
    assert "Augusta Ave" in _extract_street_from_name("22 Augusta Ave")


def test_scan_params_skips_skipped(tmp_path):
    params_dir = tmp_path / "params"
    params_dir.mkdir()
    output_dir = tmp_path / "outputs"
    output_dir.mkdir()
    active = _base_params()
    skipped = {"building_name": "Skip", "skipped": True}
    (params_dir / "a.json").write_text(json.dumps(active), encoding="utf-8")
    (params_dir / "b.json").write_text(json.dumps(skipped), encoding="utf-8")
    report = _scan_params(params_dir, output_dir, {})
    assert report["total_buildings_scanned"] == 1
    assert report["skipped_files"] >= 1


def test_score_decreases_with_issues():
    """More issues should produce lower score."""
    clean = _base_params()
    _, score_clean = _check_building(clean, DUMMY_PATH)

    broken = _base_params()
    broken["windows_detail"] = []
    broken.pop("doors_detail")
    broken["roof_type"] = None
    _, score_broken = _check_building(broken, DUMMY_PATH)

    assert score_clean > score_broken
