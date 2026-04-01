"""Tests for scripts/enrich_storefronts_advanced.py"""

import json
import pytest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from enrich_storefronts_advanced import (
    infer_awning,
    infer_signage,
    infer_security_grille,
    get_street_from_building_name,
)


def test_awning_market_street():
    params = {"building_name": "10 Kensington Ave", "has_storefront": True,
              "facade_width_m": 5.0, "storefront": {}}
    result = infer_awning(params)
    assert result["present"] is True


def test_awning_major_commercial():
    params = {"building_name": "400 Spadina Ave", "has_storefront": True,
              "facade_width_m": 6.0, "storefront": {}}
    result = infer_awning(params)
    assert result["present"] is True


def test_awning_residential_street():
    params = {"building_name": "10 Lippincott St", "has_storefront": True,
              "facade_width_m": 5.0, "storefront": {}}
    result = infer_awning(params)
    assert result.get("present") is False or result == {}


def test_signage_from_business_name():
    params = {"context": {"business_name": "Joe's Deli"}, "facade_width_m": 5.0}
    result = infer_signage(params)
    assert result is not None
    assert result["text"] == "Joe's Deli"


def test_signage_no_business_name():
    params = {"context": {}, "facade_width_m": 5.0}
    result = infer_signage(params)
    assert result is None or result == {}


def test_security_grille_market_street():
    params = {"building_name": "10 Kensington Ave"}
    result = infer_security_grille(params)
    assert result["present"] is True


def test_security_grille_non_market():
    params = {"building_name": "10 Lippincott St"}
    result = infer_security_grille(params)
    assert result is None or result.get("present") is False


def test_get_street_from_building_name():
    assert get_street_from_building_name("10 Kensington Ave") == "Kensington Ave"
    assert get_street_from_building_name("200A Baldwin St") == "Baldwin St"


def test_awning_width_proportional():
    params = {"building_name": "10 Augusta Ave", "has_storefront": True,
              "facade_width_m": 10.0, "storefront": {}}
    result = infer_awning(params)
    if result.get("present"):
        assert result["width_m"] <= 10.0


def test_signage_width_capped():
    params = {"context": {"business_name": "Test Shop"}, "facade_width_m": 20.0}
    result = infer_signage(params)
    if result and result.get("width_m"):
        assert result["width_m"] <= 20.0
