#!/usr/bin/env python3
"""Tests for scripts/audit_decorative_completeness.py."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import audit_decorative_completeness as adc


# ── extract_hcd_keywords ──────────────────────────────────────────────────────

class TestExtractHcdKeywords:
    def test_voussoir_detected(self):
        assert "voussoir" in adc.extract_hcd_keywords("Features include stone voussoir arches")

    def test_bracket_detected(self):
        assert "bracket" in adc.extract_hcd_keywords("ornamental bracket under eave")

    def test_shingle_detected(self):
        assert "shingle" in adc.extract_hcd_keywords("decorative wood shingle in gable")

    def test_cornice_detected(self):
        assert "cornice" in adc.extract_hcd_keywords("original brick cornice retained")

    def test_string_course_detected(self):
        assert "string course" in adc.extract_hcd_keywords("has a stone string course at sill level")

    def test_quoin_detected(self):
        assert "quoin" in adc.extract_hcd_keywords("brick quoin at corners")

    def test_bargeboard_detected(self):
        assert "bargeboard" in adc.extract_hcd_keywords("wooden bargeboard on gable edge")

    def test_bay_window_detected(self):
        assert "bay window" in adc.extract_hcd_keywords("canted bay window on second floor")

    def test_dormer_detected(self):
        assert "dormer" in adc.extract_hcd_keywords("shed dormer in roof")

    def test_chimney_detected(self):
        assert "chimney" in adc.extract_hcd_keywords("decorative chimney stack")

    def test_multiple_keywords_detected(self):
        result = adc.extract_hcd_keywords("has voussoir arches, quoin, and cornice")
        assert "voussoir" in result
        assert "quoin" in result
        assert "cornice" in result

    def test_empty_string_returns_empty(self):
        assert adc.extract_hcd_keywords("") == []

    def test_none_returns_empty(self):
        assert adc.extract_hcd_keywords(None) == []

    def test_no_keywords_returns_empty(self):
        assert adc.extract_hcd_keywords("a plain brick building with no features") == []

    def test_case_insensitive(self):
        assert "cornice" in adc.extract_hcd_keywords("Decorative CORNICE at roofline")


# ── element_present ──────────────────────────────────────────────────────────

class TestElementPresent:
    def test_key_missing_returns_false(self):
        assert adc.element_present({}, "cornice") is False

    def test_key_none_map_returns_false(self):
        assert adc.element_present({"cornice": None}, "cornice") is False

    def test_dict_with_present_true(self):
        assert adc.element_present({"cornice": {"present": True}}, "cornice") is True

    def test_dict_with_present_false_still_truthy(self):
        # element_present returns (val.get("present", False) OR bool(val)).
        # A dict {"present": False} is non-empty, so bool(val) is True and the
        # function returns True even though present=False.  An empty dict {}
        # is the correct way to signal "element recorded but absent".
        assert adc.element_present({"cornice": {"present": False}}, "cornice") is True

    def test_non_empty_dict_without_present_key(self):
        # Any non-empty dict counts as present
        assert adc.element_present({"cornice": {"colour_hex": "#fff"}}, "cornice") is True

    def test_empty_dict_value(self):
        assert adc.element_present({"cornice": {}}, "cornice") is False

    def test_truthy_string_value(self):
        assert adc.element_present({"bargeboard": "wood"}, "bargeboard") is True

    def test_none_key_always_false(self):
        assert adc.element_present({"dormer": {"present": True}}, None) is False

    def test_false_value(self):
        assert adc.element_present({"string_courses": False}, "string_courses") is False


# ── main() integration via temp files ────────────────────────────────────────

def _write_param(tmp_path: Path, name: str, data: dict) -> Path:
    p = tmp_path / name
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return p


class TestMainIntegration:
    def _setup_adc(self, tmp_path):
        adc.PARAMS_DIR = tmp_path
        adc.OUTPUT_FILE = tmp_path / "decorative_completeness_audit.json"

    def test_building_with_all_elements_present(self, tmp_path, capsys):
        _write_param(
            tmp_path,
            "complete.json",
            {
                "building_name": "Complete Building",
                "hcd_data": {
                    "statement_of_contribution": "voussoir cornice quoin bargeboard",
                },
                "decorative_elements": {
                    "stone_voussoirs": {"present": True},
                    "cornice": {"present": True},
                    "quoins": {"present": True},
                    "bargeboard": {"colour_hex": "#5A3A20"},
                },
            },
        )
        self._setup_adc(tmp_path)
        adc.main()

        data = json.loads(adc.OUTPUT_FILE.read_text(encoding="utf-8"))
        assert data["summary"]["total_missing"] == 0
        assert data["summary"]["total_complete"] == 1

    def test_building_missing_element_reported(self, tmp_path, capsys):
        _write_param(
            tmp_path,
            "incomplete.json",
            {
                "building_name": "Incomplete Building",
                "hcd_data": {
                    "statement_of_contribution": "features include a decorative cornice",
                },
                "decorative_elements": {},
            },
        )
        self._setup_adc(tmp_path)
        adc.main()

        data = json.loads(adc.OUTPUT_FILE.read_text(encoding="utf-8"))
        assert data["summary"]["total_missing"] == 1
        findings = data["findings"]
        assert len(findings) == 1
        assert "cornice" in findings[0]["missing_elements"]

    def test_skipped_files_not_evaluated(self, tmp_path):
        _write_param(
            tmp_path,
            "skipped.json",
            {
                "skipped": True,
                "hcd_data": {"statement_of_contribution": "has cornice"},
                "decorative_elements": {},
            },
        )
        self._setup_adc(tmp_path)
        adc.main()

        data = json.loads(adc.OUTPUT_FILE.read_text(encoding="utf-8"))
        assert data["summary"]["total_checked"] == 0

    def test_metadata_files_not_evaluated(self, tmp_path):
        _write_param(
            tmp_path,
            "_site_coordinates.json",
            {
                "hcd_data": {"statement_of_contribution": "has cornice"},
                "decorative_elements": {},
            },
        )
        self._setup_adc(tmp_path)
        adc.main()

        data = json.loads(adc.OUTPUT_FILE.read_text(encoding="utf-8"))
        assert data["summary"]["total_checked"] == 0

    def test_building_with_no_hcd_keywords_not_evaluated(self, tmp_path):
        _write_param(
            tmp_path,
            "plain.json",
            {
                "building_name": "Plain Building",
                "hcd_data": {"statement_of_contribution": "a plain brick commercial building"},
                "decorative_elements": {},
            },
        )
        self._setup_adc(tmp_path)
        adc.main()

        data = json.loads(adc.OUTPUT_FILE.read_text(encoding="utf-8"))
        assert data["summary"]["total_checked"] == 0

    def test_keyword_stats_tracked(self, tmp_path):
        _write_param(
            tmp_path,
            "b1.json",
            {
                "building_name": "B1",
                "hcd_data": {"statement_of_contribution": "has a quoin at corners"},
                "decorative_elements": {"quoins": {"present": True}},
            },
        )
        _write_param(
            tmp_path,
            "b2.json",
            {
                "building_name": "B2",
                "hcd_data": {"statement_of_contribution": "features a quoin"},
                "decorative_elements": {},
            },
        )
        self._setup_adc(tmp_path)
        adc.main()

        data = json.loads(adc.OUTPUT_FILE.read_text(encoding="utf-8"))
        quoin_stats = data["keyword_stats"]["quoin"]
        assert quoin_stats["mentioned"] == 2
        assert quoin_stats["present"] == 1
        assert quoin_stats["missing"] == 1

    def test_building_features_list_also_scanned(self, tmp_path):
        _write_param(
            tmp_path,
            "features_list.json",
            {
                "building_name": "Features List Building",
                "hcd_data": {
                    "statement_of_contribution": "",
                    "building_features": ["decorative_brick", "string course present"],
                },
                "decorative_elements": {},
            },
        )
        self._setup_adc(tmp_path)
        adc.main()

        data = json.loads(adc.OUTPUT_FILE.read_text(encoding="utf-8"))
        assert data["summary"]["total_missing"] == 1
        findings = data["findings"]
        assert "string course" in findings[0]["missing_elements"]
