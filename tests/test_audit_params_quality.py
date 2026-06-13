#!/usr/bin/env python3
"""Tests for scripts/audit_params_quality.py – data quality helpers and check_file."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import audit_params_quality as apq


# ── normalize_text ────────────────────────────────────────────────────────────

class TestNormalizeText:
    def test_none_becomes_empty_string(self):
        assert apq.normalize_text(None) == ""

    def test_strips_whitespace(self):
        assert apq.normalize_text("  brick  ") == "brick"

    def test_lowercased(self):
        assert apq.normalize_text("Brick") == "brick"

    def test_integer_to_string(self):
        assert apq.normalize_text(42) == "42"


# ── is_number ─────────────────────────────────────────────────────────────────

class TestIsNumber:
    def test_int_is_number(self):
        assert apq.is_number(5) is True

    def test_float_is_number(self):
        assert apq.is_number(3.14) is True

    def test_none_is_not_number(self):
        assert apq.is_number(None) is False

    def test_bool_is_not_number(self):
        assert apq.is_number(True) is False

    def test_string_not_number(self):
        assert apq.is_number("abc") is False

    def test_numeric_string_is_number(self):
        # The function explicitly uses float(value), but strings are not rejected by float()
        # However the function checks isinstance(bool) first and then tries float()
        # "5" can be float()-converted, so it is a number
        assert apq.is_number("5") is True


# ── to_float ──────────────────────────────────────────────────────────────────

class TestToFloat:
    def test_int_converted(self):
        assert apq.to_float(3) == pytest.approx(3.0)

    def test_float_returned(self):
        assert apq.to_float(2.5) == pytest.approx(2.5)

    def test_none_returns_none(self):
        assert apq.to_float(None) is None

    def test_bool_returns_none(self):
        assert apq.to_float(True) is None

    def test_bad_string_returns_none(self):
        assert apq.to_float("abc") is None


# ── to_int ────────────────────────────────────────────────────────────────────

class TestToInt:
    def test_int_returned(self):
        assert apq.to_int(3) == 3

    def test_float_truncated(self):
        assert apq.to_int(2.9) == 2

    def test_none_returns_none(self):
        assert apq.to_int(None) is None

    def test_bool_returns_none(self):
        assert apq.to_int(True) is None

    def test_numeric_string_parsed(self):
        # to_int("3") returns 3 – string numeric values ARE parsed
        assert apq.to_int("3") == 3

    def test_non_numeric_string_returns_none(self):
        assert apq.to_int("abc") is None


# ── canonical_material ────────────────────────────────────────────────────────

class TestCanonicalMaterial:
    def test_brick(self):
        assert apq.canonical_material("brick") == "brick"

    def test_old_brick_phrase(self):
        assert apq.canonical_material("red brick") == "brick"

    def test_stucco(self):
        assert apq.canonical_material("stucco") == "stucco"

    def test_render_maps_to_stucco(self):
        assert apq.canonical_material("render") == "stucco"

    def test_clapboard(self):
        assert apq.canonical_material("clapboard") == "clapboard"

    def test_vinyl_siding(self):
        assert apq.canonical_material("vinyl siding") == "vinyl siding"

    def test_wood_string_maps_to_wood_siding(self):
        assert apq.canonical_material("wood") == "wood siding"

    def test_stone(self):
        assert apq.canonical_material("limestone") == "stone"

    def test_concrete(self):
        assert apq.canonical_material("concrete") == "concrete"

    def test_mixed(self):
        assert apq.canonical_material("mixed masonry") == "mixed masonry"

    def test_glass(self):
        assert apq.canonical_material("glass") == "glass"

    def test_empty_returns_empty(self):
        assert apq.canonical_material("") == ""

    def test_none_returns_empty(self):
        assert apq.canonical_material(None) == ""


# ── likely_material_label ─────────────────────────────────────────────────────

class TestLikelyMaterialLabel:
    def test_brick_is_material_label(self):
        assert apq.likely_material_label("brick") is True

    def test_stucco_is_material_label(self):
        assert apq.likely_material_label("stucco") is True

    def test_hex_colour_is_not_material_label(self):
        assert apq.likely_material_label("#B85A3A") is False

    def test_descriptive_colour_is_not_material_label(self):
        assert apq.likely_material_label("red") is False

    def test_unknown_is_material_label(self):
        assert apq.likely_material_label("unknown") is True

    def test_underscore_variant_normalised(self):
        # "wood_siding" → replace _ with space → "wood siding" which IS in GENERIC_MATERIAL_LABELS
        assert apq.likely_material_label("wood_siding") is True


# ── check_file ────────────────────────────────────────────────────────────────

def _make_valid_params() -> dict:
    return {
        "building_name": "22 Lippincott St",
        "floors": 2,
        "total_height_m": 7.0,
        "facade_width_m": 6.5,
        "facade_depth_m": 12.0,
        "roof_type": "gable",
        "roof_pitch_deg": 30,
        "facade_material": "brick",
        "facade_colour": "#B85A3A",
        "windows_per_floor": [2, 2],
        "window_type": "double-hung",
        "window_width_m": 0.9,
        "window_height_m": 1.3,
        "door_count": 1,
        "condition": "good",
        "floor_heights_m": [3.5, 3.5],
        "has_storefront": False,
        "site": {"lon": -79.4, "lat": 43.66},
    }


def _check(data: dict, tmp_path: Path) -> dict:
    p = tmp_path / "test.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return apq.check_file(p)


class TestCheckFile:
    def test_valid_building_ok(self, tmp_path):
        result = _check(_make_valid_params(), tmp_path)
        assert result["status"] == "ok"
        assert result["issue_count"] == 0

    def test_skipped_file_status(self, tmp_path):
        result = _check({"skipped": True, "skip_reason": "not a building"}, tmp_path)
        assert result["status"] == "skipped"

    def test_skipped_missing_reason_flagged(self, tmp_path):
        result = _check({"skipped": True}, tmp_path)
        assert result["status"] == "skipped"
        categories = result.get("categories", {})
        assert "skipped_missing_reason" in categories

    def test_missing_building_name(self, tmp_path):
        data = _make_valid_params()
        del data["building_name"]
        result = _check(data, tmp_path)
        assert result["status"] == "issues"
        assert any(i["field"] == "building_name" for i in result["issues"])

    def test_missing_total_height(self, tmp_path):
        data = _make_valid_params()
        del data["total_height_m"]
        result = _check(data, tmp_path)
        assert any(i["field"] == "total_height_m" for i in result["issues"])

    def test_invalid_roof_pitch(self, tmp_path):
        data = _make_valid_params()
        data["roof_pitch_deg"] = 100  # > 90
        result = _check(data, tmp_path)
        assert any(i["field"] == "roof_pitch_deg" for i in result["issues"])

    def test_unknown_facade_material(self, tmp_path):
        data = _make_valid_params()
        data["facade_material"] = "super_special_material"
        result = _check(data, tmp_path)
        assert any(i["category"] == "unknown_facade_material" for i in result["issues"])

    def test_facade_colour_looks_like_material(self, tmp_path):
        data = _make_valid_params()
        data["facade_colour"] = "brick"  # looks like a material label
        result = _check(data, tmp_path)
        assert any(i["field"] == "facade_colour" for i in result["issues"])

    def test_invalid_condition(self, tmp_path):
        data = _make_valid_params()
        data["condition"] = "excellent"  # not in ALLOWED_CONDITIONS
        result = _check(data, tmp_path)
        assert any(i["field"] == "condition" for i in result["issues"])

    def test_floor_heights_length_mismatch(self, tmp_path):
        data = _make_valid_params()
        data["floor_heights_m"] = [3.5]  # only 1, floors=2
        result = _check(data, tmp_path)
        assert any(i["field"] == "floor_heights_m" for i in result["issues"])

    def test_parse_error_status(self, tmp_path):
        p = tmp_path / "bad.json"
        p.write_text("{ invalid json }", encoding="utf-8")
        result = apq.check_file(p)
        assert result["status"] == "parse_error"

    def test_windows_per_floor_count_mismatch(self, tmp_path):
        data = _make_valid_params()
        data["windows_per_floor"] = [2]  # only 1 entry, floors=2
        result = _check(data, tmp_path)
        assert any(i["field"] == "windows_per_floor" for i in result["issues"])

    def test_zero_facade_width_invalid(self, tmp_path):
        data = _make_valid_params()
        data["facade_width_m"] = 0
        result = _check(data, tmp_path)
        assert any(i["field"] == "facade_width_m" for i in result["issues"])


# ── render_report ─────────────────────────────────────────────────────────────

class TestRenderReport:
    def test_render_report_returns_string(self, tmp_path):
        data = _make_valid_params()
        p = tmp_path / "building.json"
        p.write_text(json.dumps(data), encoding="utf-8")
        result = apq.check_file(p)
        report = {
            "params_dir": str(tmp_path),
            "scanned_files": 1,
            "building_files": 1,
            "skipped_files": 0,
            "parse_errors": 0,
            "files_with_issues": 0,
            "total_issues": 0,
            "issue_counts": {},
            "examples": [],
            "files": [result],
        }
        rendered = apq.render_report(report)
        assert isinstance(rendered, str)
        assert "Scanned 1 files" in rendered

    def test_render_report_shows_issue_counts(self, tmp_path):
        data = _make_valid_params()
        del data["building_name"]
        p = tmp_path / "broken.json"
        p.write_text(json.dumps(data), encoding="utf-8")
        result = apq.check_file(p)
        report = {
            "params_dir": str(tmp_path),
            "scanned_files": 1,
            "building_files": 1,
            "skipped_files": 0,
            "parse_errors": 0,
            "files_with_issues": 1,
            "total_issues": result["issue_count"],
            "issue_counts": result["categories"],
            "examples": [result],
            "files": [result],
        }
        rendered = apq.render_report(report)
        assert "core_missing" in rendered
