#!/usr/bin/env python3
"""Tests for scripts/enrich_doors_and_foundations.py"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from enrich_doors_and_foundations import (
    enrich_doors,
    enrich_foundations,
    get_era,
    get_foundation_height,
    is_commercial,
)


# ── Door colour by material + era ──

def test_door_wood_pre_1889():
    params = {
        "hcd_data": {"construction_date": "Pre-1889"},
        "doors_detail": [{"id": "d1", "material": "wood"}],
    }
    enrich_doors(params)
    assert params["doors_detail"][0]["colour_hex"] == "#3A2A20"
    assert params["doors_detail"][0]["colour"] == "dark brown"


def test_door_wood_1889_1903():
    params = {
        "hcd_data": {"construction_date": "1889-1903"},
        "doors_detail": [{"id": "d1", "material": "wood"}],
    }
    enrich_doors(params)
    assert params["doors_detail"][0]["colour_hex"] == "#2A3A2A"


def test_door_glass():
    params = {
        "hcd_data": {},
        "doors_detail": [{"id": "d1", "material": "glass"}],
    }
    enrich_doors(params)
    assert params["doors_detail"][0]["colour_hex"] == "#1A1A2A"


def test_door_metal():
    params = {
        "hcd_data": {},
        "doors_detail": [{"id": "d1", "material": "steel"}],
    }
    enrich_doors(params)
    assert params["doors_detail"][0]["colour_hex"] == "#3A3A3A"


def test_door_skip_if_set():
    params = {
        "hcd_data": {},
        "doors_detail": [{"id": "d1", "material": "wood", "colour_hex": "#FF0000"}],
    }
    enrich_doors(params)
    assert params["doors_detail"][0]["colour_hex"] == "#FF0000"


def test_door_material_infer_commercial():
    params = {
        "hcd_data": {},
        "has_storefront": True,
        "doors_detail": [{"id": "d1"}],
    }
    enrich_doors(params)
    assert params["doors_detail"][0]["material"] == "glass_and_aluminum"


def test_door_material_infer_residential():
    params = {
        "hcd_data": {},
        "has_storefront": False,
        "doors_detail": [{"id": "d1"}],
    }
    enrich_doors(params)
    assert params["doors_detail"][0]["material"] == "wood"


# ── Foundation heights ──

def test_foundation_house():
    params = {"hcd_data": {"typology": "House-form, Semi-detached"}}
    assert get_foundation_height(params) == 0.3


def test_foundation_commercial():
    params = {"hcd_data": {"typology": "Commercial, Row"}}
    assert get_foundation_height(params) == 0.15


def test_foundation_institutional():
    params = {"hcd_data": {"typology": "Institutional"}}
    assert get_foundation_height(params) == 0.45


def test_foundation_default():
    params = {"hcd_data": {}}
    assert get_foundation_height(params) == 0.3


def test_foundation_skip_if_set():
    params = {"hcd_data": {}, "foundation_height_m": 0.5}
    changes = enrich_foundations(params)
    assert len(changes) == 0
    assert params["foundation_height_m"] == 0.5


def test_foundation_updates_dfa():
    params = {
        "hcd_data": {"typology": "House-form"},
        "deep_facade_analysis": {"depth_notes": {"foundation_height_m_est": 0.3}},
    }
    enrich_foundations(params)
    assert params["deep_facade_analysis"]["depth_notes"]["foundation_height_m_est"] == 0.3


# ── Idempotency ──

def test_idempotency():
    params = {
        "hcd_data": {"construction_date": "Pre-1889"},
        "doors_detail": [{"id": "d1"}],
    }
    enrich_doors(params)
    enrich_foundations(params)
    first = json.dumps(params)
    enrich_doors(params)
    enrich_foundations(params)
    second = json.dumps(params)
    assert first == second
