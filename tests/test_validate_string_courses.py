#!/usr/bin/env python3
"""Tests for scripts/validate_string_courses.py"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from validate_string_courses import (
    _to_float,
    _course_items,
    _extract_height_m,
    _set_height,
    MIN_HEIGHT_M,
    MAX_HEIGHT_M,
)


# ── _to_float ──

def test_to_float_int():
    assert _to_float(5) == 5.0


def test_to_float_str():
    assert _to_float("3.14") == 3.14


def test_to_float_none():
    assert _to_float(None) is None


def test_to_float_invalid():
    assert _to_float("abc") is None


def test_to_float_bool():
    # bool is subclass of int
    assert _to_float(True) == 1.0


# ── _course_items ──

def test_course_items_dict():
    data = {"decorative_elements": {"string_courses": {"present": True, "width_mm": 80}}}
    result = _course_items(data)
    assert len(result) == 1
    assert result[0]["width_mm"] == 80


def test_course_items_list():
    data = {"decorative_elements": {"string_courses": [
        {"width_mm": 80},
        {"width_mm": 120},
    ]}}
    result = _course_items(data)
    assert len(result) == 2


def test_course_items_none():
    data = {"decorative_elements": {"string_courses": None}}
    result = _course_items(data)
    assert result == []


def test_course_items_no_decorative():
    data = {}
    result = _course_items(data)
    assert result == []


def test_course_items_decorative_not_dict():
    data = {"decorative_elements": "something"}
    result = _course_items(data)
    assert result == []


# ── _extract_height_m ──

def test_extract_height_from_height_m():
    course = {"height_m": 0.12}
    val, key = _extract_height_m(course)
    assert val == 0.12
    assert key == "height_m"


def test_extract_height_from_string_course_height_m():
    course = {"string_course_height_m": 0.15}
    val, key = _extract_height_m(course)
    assert val == 0.15
    assert key == "string_course_height_m"


def test_extract_height_from_width_mm():
    course = {"width_mm": 80}
    val, key = _extract_height_m(course)
    assert abs(val - 0.08) < 0.001
    assert key == "width_mm"


def test_extract_height_priority():
    """string_course_height_m takes priority over height_m."""
    course = {"string_course_height_m": 0.10, "height_m": 0.20}
    val, key = _extract_height_m(course)
    assert val == 0.10
    assert key == "string_course_height_m"


def test_extract_height_none():
    course = {"present": True}
    val, key = _extract_height_m(course)
    assert val is None
    assert key is None


# ── _set_height ──

def test_set_height_mm():
    course = {"width_mm": 80}
    _set_height(course, "width_mm", 0.12)
    assert course["width_mm"] == 120


def test_set_height_m():
    course = {"height_m": 0.08}
    _set_height(course, "height_m", 0.15)
    assert course["height_m"] == 0.15


# ── Range constants ──

def test_range_constants():
    assert MIN_HEIGHT_M > 0
    assert MAX_HEIGHT_M > MIN_HEIGHT_M
    assert MAX_HEIGHT_M < 1.0  # should be reasonable


# ── Integration: full validation on temp files ──

def test_validation_valid_string_course(tmp_path):
    """A valid string course should not be flagged."""
    data = {
        "building_name": "Test",
        "floors": 2,
        "floor_heights_m": [3.5, 3.0],
        "decorative_elements": {
            "string_courses": {"present": True, "width_mm": 120}
        },
    }
    param_file = tmp_path / "test.json"
    param_file.write_text(json.dumps(data), encoding="utf-8")

    courses = _course_items(data)
    assert len(courses) == 1
    val, key = _extract_height_m(courses[0])
    assert MIN_HEIGHT_M <= val <= MAX_HEIGHT_M


def test_validation_out_of_range(tmp_path):
    """A too-tall string course should be detected."""
    data = {
        "building_name": "Test",
        "decorative_elements": {
            "string_courses": {"present": True, "height_m": 0.50}
        },
    }
    courses = _course_items(data)
    val, key = _extract_height_m(courses[0])
    assert val > MAX_HEIGHT_M  # out of range


def test_validation_too_small():
    data = {
        "decorative_elements": {
            "string_courses": {"present": True, "width_mm": 20}  # 0.02m, below min
        },
    }
    courses = _course_items(data)
    val, key = _extract_height_m(courses[0])
    assert val < MIN_HEIGHT_M
