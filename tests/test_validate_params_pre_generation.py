"""Tests for validate_params_pre_generation.py."""

import json
import tempfile
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from validate_params_pre_generation import validate_param


def _write_param(tmp_dir, name, data):
    p = Path(tmp_dir) / name
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def test_valid_minimal():
    with tempfile.TemporaryDirectory() as d:
        p = _write_param(d, "test.json", {
            "floors": 2,
            "facade_width_m": 5.0,
            "facade_depth_m": 10.0,
            "total_height_m": 7.5,
        })
        errors, warnings = validate_param(p)
        assert errors == []


def test_missing_required():
    with tempfile.TemporaryDirectory() as d:
        p = _write_param(d, "test.json", {
            "floors": 2,
            # missing facade_width_m, facade_depth_m, total_height_m
        })
        errors, _ = validate_param(p)
        assert len(errors) == 3
        assert any("facade_width_m" in e for e in errors)


def test_negative_dimensions():
    with tempfile.TemporaryDirectory() as d:
        p = _write_param(d, "test.json", {
            "floors": 2,
            "facade_width_m": -1.0,
            "facade_depth_m": 10.0,
            "total_height_m": 7.5,
        })
        errors, _ = validate_param(p)
        assert any("positive" in e for e in errors)


def test_skipped_ignored():
    with tempfile.TemporaryDirectory() as d:
        p = _write_param(d, "test.json", {"skipped": True})
        errors, warnings = validate_param(p)
        assert errors == []
        assert warnings == []


def test_invalid_condition():
    with tempfile.TemporaryDirectory() as d:
        p = _write_param(d, "test.json", {
            "floors": 2,
            "facade_width_m": 5.0,
            "facade_depth_m": 10.0,
            "total_height_m": 7.5,
            "condition": "weathered",
        })
        _, warnings = validate_param(p)
        assert any("condition" in w for w in warnings)


def test_floor_heights_mismatch():
    with tempfile.TemporaryDirectory() as d:
        p = _write_param(d, "test.json", {
            "floors": 3,
            "facade_width_m": 5.0,
            "facade_depth_m": 10.0,
            "total_height_m": 9.0,
            "floor_heights_m": [3.5, 3.0],
        })
        _, warnings = validate_param(p)
        assert any("floor_heights_m length" in w for w in warnings)


def test_strict_mode():
    with tempfile.TemporaryDirectory() as d:
        p = _write_param(d, "test.json", {
            "floors": 2,
            "facade_width_m": 5.0,
            "facade_depth_m": 10.0,
            "total_height_m": 7.5,
            "condition": "weathered",
        })
        errors, warnings = validate_param(p, strict=True)
        assert len(errors) > 0
        assert warnings == []


def test_json_parse_error():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "bad.json"
        p.write_text("{bad json", encoding="utf-8")
        errors, _ = validate_param(p)
        assert any("JSON parse" in e for e in errors)


def test_extreme_dimensions_warn():
    with tempfile.TemporaryDirectory() as d:
        p = _write_param(d, "test.json", {
            "floors": 1,
            "facade_width_m": 100.0,
            "facade_depth_m": 10.0,
            "total_height_m": 7.5,
        })
        _, warnings = validate_param(p)
        assert any("facade_width_m" in w for w in warnings)
