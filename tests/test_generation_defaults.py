#!/usr/bin/env python3
"""Tests for scripts/generation_defaults.py — verify all exported constants."""
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import generation_defaults as gd


# ── Existence and type checks ──

def test_wall_geometry_constants():
    assert isinstance(gd.WALL_THICKNESS_M, (int, float))
    assert gd.WALL_THICKNESS_M > 0
    assert isinstance(gd.DEFAULT_DEPTH_M, (int, float))
    assert gd.DEFAULT_DEPTH_M > 0


def test_window_constants():
    assert isinstance(gd.DEFAULT_WINDOW_WIDTH_M, (int, float))
    assert 0.3 < gd.DEFAULT_WINDOW_WIDTH_M < 3.0
    assert isinstance(gd.DEFAULT_WINDOW_HEIGHT_M, (int, float))
    assert 0.5 < gd.DEFAULT_WINDOW_HEIGHT_M < 4.0
    assert isinstance(gd.WINDOW_SILL_HEIGHT_M, (int, float))
    assert isinstance(gd.WINDOW_FRAME_DEPTH_M, (int, float))


def test_door_constants():
    assert isinstance(gd.DEFAULT_DOOR_WIDTH_M, (int, float))
    assert 0.5 < gd.DEFAULT_DOOR_WIDTH_M < 3.0
    assert isinstance(gd.DEFAULT_DOOR_HEIGHT_M, (int, float))
    assert 1.5 < gd.DEFAULT_DOOR_HEIGHT_M < 4.0


def test_string_course_constants():
    assert isinstance(gd.STRING_COURSE_HEIGHT_MM, (int, float))
    assert gd.STRING_COURSE_HEIGHT_MM > 0
    assert isinstance(gd.STRING_COURSE_PROJECTION_MM, (int, float))


def test_roof_constants():
    assert isinstance(gd.DEFAULT_ROOF_PITCH_DEG, (int, float))
    assert 0 <= gd.DEFAULT_ROOF_PITCH_DEG <= 90
    assert isinstance(gd.PARAPET_HEIGHT_M, (int, float))
    assert isinstance(gd.EAVE_OVERHANG_MM, (int, float))


def test_chimney_constants():
    assert isinstance(gd.DEFAULT_CHIMNEY_WIDTH_M, (int, float))
    assert isinstance(gd.DEFAULT_CHIMNEY_DEPTH_M, (int, float))
    assert isinstance(gd.DEFAULT_CHIMNEY_HEIGHT_ABOVE_RIDGE_M, (int, float))


def test_bay_window_constants():
    assert isinstance(gd.DEFAULT_BAY_WINDOW_PROJECTION_M, (int, float))
    assert isinstance(gd.DEFAULT_BAY_WINDOW_WIDTH_RATIO, (int, float))
    assert 0 < gd.DEFAULT_BAY_WINDOW_WIDTH_RATIO < 1
    assert gd.MIN_BAY_WINDOW_WIDTH_M < gd.MAX_BAY_WINDOW_WIDTH_M


def test_foundation_constants():
    assert isinstance(gd.FOUNDATION_HEIGHT_M, (int, float))
    assert gd.FOUNDATION_HEIGHT_M > 0


def test_material_roughness_values():
    for name in [
        "BRICK_MATERIAL_ROUGHNESS",
        "WOOD_MATERIAL_ROUGHNESS",
        "PAINTED_MATERIAL_ROUGHNESS",
        "ROOF_MATERIAL_ROUGHNESS",
        "STONE_MATERIAL_ROUGHNESS",
    ]:
        val = getattr(gd, name)
        assert isinstance(val, (int, float))
        assert 0 <= val <= 1, f"{name} = {val} out of range"


# ── Colour hex validation ──

HEX_PATTERN = re.compile(r"^#[0-9A-Fa-f]{6}$")

def _check_hex(name, val):
    assert isinstance(val, str), f"{name} should be str, got {type(val)}"
    assert HEX_PATTERN.match(val), f"{name} = {val!r} is not a valid hex colour"


def test_brick_colour_hex_constants():
    # Check all _HEX constants
    hex_attrs = [
        "STRING_COURSE_COLOUR_HEX",
        "QUOIN_COLOUR_HEX",
        "CORNICE_COLOUR_HEX",
        "MORTAR_COLOUR_DEFAULT_HEX",
        "MORTAR_COLOUR_GREY_HEX",
        "MORTAR_COLOUR_LIGHT_HEX",
        "TRIM_COLOUR_DARK_HEX",
        "TRIM_COLOUR_BLACK_HEX",
        "TRIM_COLOUR_CREAM_HEX",
        "POST_COLOUR_DARK_HEX",
        "ROOF_COLOUR_DARK_HEX",
        "ROOF_COLOUR_GREY_HEX",
        "ROOF_COLOUR_RED_HEX",
        "CONCRETE_COLOUR_HEX",
        "WOOD_COLOUR_HEX",
        "DEFAULT_PARAM_ROOF_COLOUR",
        "GABLE_SHINGLE_COLOUR_HEX",
    ]
    for name in hex_attrs:
        val = getattr(gd, name)
        _check_hex(name, val)


def test_glass_colour_rgb():
    assert isinstance(gd.GLASS_COLOUR_RGB, tuple)
    assert len(gd.GLASS_COLOUR_RGB) == 3
    for c in gd.GLASS_COLOUR_RGB:
        assert 0 <= c <= 1


def test_brick_colour_rgb_values():
    for name in ["BRICK_COLOUR_DEFAULT_RGB", "BRICK_COLOUR_PRE1889_RGB"]:
        val = getattr(gd, name)
        assert isinstance(val, tuple)
        assert len(val) == 3
        for c in val:
            assert 0 <= c <= 1


# ── Default param values ──

def test_default_param_values():
    assert isinstance(gd.DEFAULT_PARAM_FACADE_WIDTH_M, (int, float))
    assert gd.DEFAULT_PARAM_FACADE_WIDTH_M > 0
    assert isinstance(gd.DEFAULT_PARAM_FLOORS, int)
    assert gd.DEFAULT_PARAM_FLOORS >= 1
    assert isinstance(gd.DEFAULT_PARAM_WINDOW_TYPE, str)
    assert isinstance(gd.DEFAULT_PARAM_CONDITION, str)


# ── Site coordinate constants ──

def test_site_coordinates():
    assert isinstance(gd.SITE_COORDINATE_ORIGIN_X, (int, float))
    assert isinstance(gd.SITE_COORDINATE_ORIGIN_Y, (int, float))
    # Should be in NAD83 / Ontario MTM Zone 10 range
    assert 300000 < gd.SITE_COORDINATE_ORIGIN_X < 400000
    assert 4800000 < gd.SITE_COORDINATE_ORIGIN_Y < 4900000
