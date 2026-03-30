#!/usr/bin/env python3
"""Tests for scripts/enrich_roof_and_heritage.py"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from enrich_roof_and_heritage import (
    enrich_gable_window,
    enrich_heritage_expression,
    has_gable_keyword,
    build_feature_list,
)


# ── Gable window from HCD keywords ──

def test_gable_window_from_hcd_keyword():
    params = {
        "roof_type": "gable",
        "floors": 2,
        "hcd_data": {"statement_of_contribution": "Features include a gable window and cornice"},
        "roof_detail": {},
    }
    changes = enrich_gable_window(params)
    assert len(changes) > 0
    assert params["roof_detail"]["gable_window"]["present"] is True


def test_gable_window_from_half_storey():
    params = {
        "roof_type": "gable",
        "floors": 2,
        "hcd_data": {"statement_of_contribution": "A fine projecting gable defines the roofline"},
        "roof_detail": {},
    }
    changes = enrich_gable_window(params)
    assert params["roof_detail"]["gable_window"]["present"] is True


def test_gable_window_no_keyword():
    params = {
        "roof_type": "gable",
        "floors": 2,
        "hcd_data": {"statement_of_contribution": "Simple brick building"},
        "roof_detail": {},
    }
    changes = enrich_gable_window(params)
    assert params["roof_detail"]["gable_window"]["present"] is False


def test_gable_window_skip_flat_roof():
    params = {"roof_type": "flat", "floors": 2, "roof_detail": {}}
    changes = enrich_gable_window(params)
    assert len(changes) == 0


def test_gable_window_skip_1_floor():
    params = {"roof_type": "gable", "floors": 1, "roof_detail": {}}
    changes = enrich_gable_window(params)
    assert len(changes) == 0


def test_gable_window_skip_already_set():
    params = {
        "roof_type": "gable",
        "floors": 2,
        "roof_detail": {"gable_window": {"present": True, "width_m": 1.0}},
    }
    changes = enrich_gable_window(params)
    assert len(changes) == 0
    assert params["roof_detail"]["gable_window"]["width_m"] == 1.0


# ── Heritage expression ──

def test_heritage_expression_with_features():
    params = {
        "facade_detail": {},
        "decorative_elements": {
            "cornice": {"present": True},
            "stone_voussoirs": {"present": True},
        },
        "bay_window": {"present": False},
        "has_storefront": False,
    }
    changes = enrich_heritage_expression(params)
    expr = params["facade_detail"]["heritage_expression"]
    assert "projecting cornice" in expr
    assert "stone voussoirs" in expr


def test_heritage_expression_no_features():
    params = {
        "facade_detail": {},
        "decorative_elements": {},
        "bay_window": {},
        "has_storefront": False,
    }
    changes = enrich_heritage_expression(params)
    expr = params["facade_detail"]["heritage_expression"]
    assert "original massing" in expr


def test_heritage_expression_with_bay_and_storefront():
    params = {
        "facade_detail": {},
        "decorative_elements": {},
        "bay_window": {"present": True},
        "has_storefront": True,
    }
    enrich_heritage_expression(params)
    expr = params["facade_detail"]["heritage_expression"]
    assert "bay window" in expr
    assert "storefront" in expr


def test_heritage_expression_skip_if_set():
    params = {"facade_detail": {"heritage_expression": "Custom text"}}
    changes = enrich_heritage_expression(params)
    assert len(changes) == 0
    assert params["facade_detail"]["heritage_expression"] == "Custom text"


def test_heritage_summary_filled():
    params = {
        "facade_detail": {},
        "decorative_elements": {"cornice": {"present": True}},
        "hcd_data": {"construction_date": "1889-1903", "typology": "House-form, Semi-detached"},
    }
    enrich_heritage_expression(params)
    summary = params["facade_detail"]["heritage_summary"]
    assert "1889-1903" in summary


# ── Idempotency ──

def test_idempotency():
    params = {
        "roof_type": "gable", "floors": 2,
        "hcd_data": {"statement_of_contribution": "gable window"},
        "roof_detail": {},
        "facade_detail": {},
        "decorative_elements": {"cornice": {"present": True}},
    }
    enrich_gable_window(params)
    enrich_heritage_expression(params)
    first = json.dumps(params)
    enrich_gable_window(params)
    enrich_heritage_expression(params)
    second = json.dumps(params)
    assert first == second
