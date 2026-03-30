#!/usr/bin/env python3
"""Tests for scripts/fix_handoff_findings.py"""
import json
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import fix_handoff_findings as fhf


# ── parse_expected_features ──

def test_parse_expected_features_basic():
    result = fhf.parse_expected_features("Entries for: voussoir, bracket, shingle")
    assert result == ["voussoir", "bracket", "shingle"]


def test_parse_expected_features_single():
    result = fhf.parse_expected_features("Entries for: cornice")
    assert result == ["cornice"]


def test_parse_expected_features_no_match():
    result = fhf.parse_expected_features("Some random string")
    assert result == []


def test_parse_expected_features_empty():
    result = fhf.parse_expected_features("")
    assert result == []


def test_parse_expected_features_case_insensitive():
    result = fhf.parse_expected_features("entries for: Voussoir, String Course")
    assert "voussoir" in result
    assert "string course" in result


# ── element_is_missing ──

def test_element_is_missing_not_present():
    decorative = {}
    assert fhf.element_is_missing(decorative, "cornice") is True


def test_element_is_missing_present_false():
    decorative = {"cornice": {"present": False}}
    assert fhf.element_is_missing(decorative, "cornice") is True


def test_element_is_missing_present_true():
    decorative = {"cornice": {"present": True, "projection_mm": 200}}
    assert fhf.element_is_missing(decorative, "cornice") is False


def test_element_is_missing_non_dict_value():
    decorative = {"cornice": "yes"}
    assert fhf.element_is_missing(decorative, "cornice") is False


# ── stamp_meta ──

def test_stamp_meta_new():
    data = {}
    fhf.stamp_meta(data, "test_fix")
    assert "_meta" in data
    fixes = data["_meta"]["handoff_fixes_applied"]
    assert len(fixes) == 1
    assert fixes[0]["fix"] == "test_fix"
    assert "timestamp" in fixes[0]


def test_stamp_meta_appends():
    data = {"_meta": {"handoff_fixes_applied": [{"fix": "old_fix"}]}}
    fhf.stamp_meta(data, "new_fix")
    fixes = data["_meta"]["handoff_fixes_applied"]
    assert len(fixes) == 2
    assert fixes[1]["fix"] == "new_fix"


def test_stamp_meta_idempotent_structure():
    data = {}
    fhf.stamp_meta(data, "fix1")
    fhf.stamp_meta(data, "fix2")
    assert len(data["_meta"]["handoff_fixes_applied"]) == 2


# ── address_to_filename ──

def test_address_to_filename():
    assert fhf.address_to_filename("123 Baldwin St") == "123_Baldwin_St.json"


def test_address_to_filename_complex():
    assert fhf.address_to_filename("2A Kensington Ave") == "2A_Kensington_Ave.json"


# ── fix_missing_features with temp files ──

def test_fix_missing_features_adds_voussoir(tmp_path):
    """Test adding voussoir to a building missing it."""
    # Setup: point module at temp dir
    old_params_dir = fhf.PARAMS_DIR
    fhf.PARAMS_DIR = tmp_path

    param_data = {
        "building_name": "Test Building",
        "decorative_elements": {},
        "_meta": {},
    }
    param_file = tmp_path / "123_Baldwin_St.json"
    param_file.write_text(json.dumps(param_data), encoding="utf-8")

    findings = [{
        "address": "123 Baldwin St",
        "status": "missing_features",
        "expected": "Entries for: voussoir",
    }]

    log = fhf.fix_missing_features(findings, apply=True)
    fhf.PARAMS_DIR = old_params_dir

    # Check the file was updated
    result = json.loads(param_file.read_text(encoding="utf-8"))
    assert "stone_voussoirs" in result["decorative_elements"]
    assert result["decorative_elements"]["stone_voussoirs"]["present"] is True


def test_fix_missing_features_noop_if_present(tmp_path):
    """Should not overwrite existing features."""
    old_params_dir = fhf.PARAMS_DIR
    fhf.PARAMS_DIR = tmp_path

    param_data = {
        "building_name": "Test",
        "decorative_elements": {
            "stone_voussoirs": {"present": True, "colour_hex": "#CUSTOM"},
        },
        "_meta": {},
    }
    param_file = tmp_path / "123_Baldwin_St.json"
    param_file.write_text(json.dumps(param_data), encoding="utf-8")

    findings = [{
        "address": "123 Baldwin St",
        "status": "missing_features",
        "expected": "Entries for: voussoir",
    }]

    log = fhf.fix_missing_features(findings, apply=True)
    fhf.PARAMS_DIR = old_params_dir

    result = json.loads(param_file.read_text(encoding="utf-8"))
    assert result["decorative_elements"]["stone_voussoirs"]["colour_hex"] == "#CUSTOM"


def test_fix_missing_features_file_not_found(tmp_path):
    old_params_dir = fhf.PARAMS_DIR
    fhf.PARAMS_DIR = tmp_path

    findings = [{
        "address": "999 Nonexistent St",
        "status": "missing_features",
        "expected": "Entries for: cornice",
    }]

    log = fhf.fix_missing_features(findings, apply=True)
    fhf.PARAMS_DIR = old_params_dir

    assert any("SKIP" in line for line in log)


# ── fix_window_counts ──

def test_fix_window_counts_applies(tmp_path):
    """Test that window count fixes are applied correctly."""
    old_params_dir = fhf.PARAMS_DIR
    fhf.PARAMS_DIR = tmp_path

    # Create a param file matching one of the WINDOW_FIXES entries
    for address, (floor_idx, correct_count) in list(fhf.WINDOW_FIXES.items())[:1]:
        param_data = {
            "building_name": address,
            "windows_detail": [
                {"floor": "Ground floor", "windows": [{"count": 1}]},
                {"floor": "Second floor", "windows": [{"count": 1}]},
            ],
            "_meta": {},
        }
        fname = fhf.address_to_filename(address)
        (tmp_path / fname).write_text(json.dumps(param_data), encoding="utf-8")

    log = fhf.fix_window_counts(apply=True)
    fhf.PARAMS_DIR = old_params_dir

    # At least one file should have been processed
    assert len(log) > 0
