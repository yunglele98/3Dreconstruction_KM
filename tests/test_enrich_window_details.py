#!/usr/bin/env python3
"""Tests for scripts/enrich_window_details.py"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from enrich_window_details import (
    get_era,
    has_voussoirs,
    enrich_windows,
    validate_windows,
    WINDOW_TYPE_NORMALIZE,
)


# ── get_era ──

def test_get_era_pre_1889():
    params = {"hcd_data": {"construction_date": "Pre-1889"}}
    assert get_era(params) == "pre-1889"


def test_get_era_1889_1903():
    params = {"hcd_data": {"construction_date": "1889-1903"}}
    assert get_era(params) == "1889-1903"


def test_get_era_1904_1913():
    params = {"hcd_data": {"construction_date": "1904-1913"}}
    assert get_era(params) == "1904-1913"


def test_get_era_1914_1930():
    params = {"hcd_data": {"construction_date": "1914-1930"}}
    assert get_era(params) == "1914-1930"


def test_get_era_unknown():
    params = {"hcd_data": {}}
    assert get_era(params) == "unknown"


# ── arch_type by era ──

def test_arch_type_pre_1889_segmental():
    params = {
        "hcd_data": {"construction_date": "Pre-1889"},
        "windows_detail": [
            {"floor": "Ground floor", "windows": [{"count": 2}]},
            {"floor": "Second floor", "windows": [{"count": 2}]},
        ],
        "decorative_elements": {},
    }
    enrich_windows(params)
    assert params["windows_detail"][0]["windows"][0]["arch_type"] == "segmental"
    assert params["windows_detail"][1]["windows"][0]["arch_type"] == "segmental"


def test_arch_type_1889_mixed():
    params = {
        "hcd_data": {"construction_date": "1889-1903"},
        "windows_detail": [
            {"floor": "Ground floor", "windows": [{"count": 2}]},
            {"floor": "Second floor", "windows": [{"count": 2}]},
        ],
        "decorative_elements": {},
    }
    enrich_windows(params)
    assert params["windows_detail"][0]["windows"][0]["arch_type"] == "segmental"
    assert params["windows_detail"][1]["windows"][0]["arch_type"] == "flat"


def test_arch_type_voussoir_override():
    params = {
        "hcd_data": {"construction_date": "1914-1930"},
        "windows_detail": [
            {"floor": "Ground floor", "windows": [{"count": 2}]},
        ],
        "decorative_elements": {"stone_voussoirs": {"present": True}},
    }
    enrich_windows(params)
    assert params["windows_detail"][0]["windows"][0]["arch_type"] == "segmental"


# ── glazing defaults ──

def test_glazing_pre_1889():
    params = {
        "hcd_data": {"construction_date": "Pre-1889"},
        "windows_detail": [{"floor": "Ground floor", "windows": [{"count": 1}]}],
    }
    enrich_windows(params)
    assert params["windows_detail"][0]["windows"][0]["glazing"] == "2-over-2"


def test_glazing_casement_single_pane():
    params = {
        "hcd_data": {"construction_date": "Pre-1889"},
        "windows_detail": [{"floor": "Ground floor", "windows": [{"count": 1, "type": "casement"}]}],
    }
    enrich_windows(params)
    assert params["windows_detail"][0]["windows"][0]["glazing"] == "single-pane"


def test_glazing_fixed_single_pane():
    params = {
        "hcd_data": {},
        "windows_detail": [{"floor": "Ground floor", "windows": [{"count": 1, "type": "fixed"}]}],
    }
    enrich_windows(params)
    assert params["windows_detail"][0]["windows"][0]["glazing"] == "single-pane"


# ── frame_colour ──

def test_frame_colour_pre_1889_dark():
    params = {
        "hcd_data": {"construction_date": "Pre-1889"},
        "windows_detail": [{"floor": "Ground floor", "windows": [{"count": 1}]}],
    }
    enrich_windows(params)
    assert params["windows_detail"][0]["windows"][0]["frame_colour"] == "dark"


def test_frame_colour_1914_white():
    params = {
        "hcd_data": {"construction_date": "1914-1930"},
        "windows_detail": [{"floor": "Ground floor", "windows": [{"count": 1}]}],
    }
    enrich_windows(params)
    assert params["windows_detail"][0]["windows"][0]["frame_colour"] == "white"


# ── window_type normalization ──

def test_window_type_normalize():
    params = {
        "window_type": "Double-hung sash",
        "hcd_data": {},
        "windows_detail": [],
    }
    enrich_windows(params)
    assert params["window_type"] == "double_hung"


def test_window_type_empty_infers():
    params = {
        "window_type": "",
        "hcd_data": {"construction_date": "1914-1930"},
        "windows_detail": [],
    }
    enrich_windows(params)
    assert params["window_type"] == "casement"


# ── existing values never overwritten ──

def test_no_overwrite_existing_arch_type():
    params = {
        "hcd_data": {"construction_date": "Pre-1889"},
        "windows_detail": [
            {"floor": "Ground floor", "windows": [{"count": 2, "arch_type": "pointed"}]},
        ],
    }
    enrich_windows(params)
    assert params["windows_detail"][0]["windows"][0]["arch_type"] == "pointed"


def test_no_overwrite_existing_glazing():
    params = {
        "hcd_data": {},
        "windows_detail": [
            {"floor": "Ground floor", "windows": [{"count": 1, "glazing": "4-over-4"}]},
        ],
    }
    enrich_windows(params)
    assert params["windows_detail"][0]["windows"][0]["glazing"] == "4-over-4"


# ── idempotency ──

def test_idempotency():
    params = {
        "hcd_data": {"construction_date": "1889-1903"},
        "windows_detail": [
            {"floor": "Ground floor", "windows": [{"count": 2}]},
        ],
    }
    enrich_windows(params)
    first = json.dumps(params)
    enrich_windows(params)
    second = json.dumps(params)
    assert first == second


# ── edge: no windows_detail ──

def test_no_windows_detail():
    params = {"hcd_data": {}}
    changes = enrich_windows(params)
    # Should not crash


# ── edge: empty windows array ──

def test_empty_windows_array():
    params = {
        "hcd_data": {},
        "windows_detail": [{"floor": "Ground floor", "windows": []}],
    }
    changes = enrich_windows(params)
    # Should not crash


# ── validation ──

def test_validate_complete():
    params = {
        "windows_detail": [{
            "floor": "Ground floor",
            "windows": [{
                "count": 2, "type": "double_hung", "arch_type": "flat",
                "glazing": "1-over-1", "frame_colour": "white",
                "width_m": 0.85, "height_m": 1.3,
            }],
        }],
    }
    assert validate_windows(params) == []


def test_validate_missing():
    params = {
        "windows_detail": [{
            "floor": "Ground floor",
            "windows": [{"count": 2}],
        }],
    }
    missing = validate_windows(params)
    assert len(missing) > 0
