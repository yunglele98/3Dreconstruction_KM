"""Tests for scripts/infer_setbacks.py"""

import pytest
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.infer_setbacks import (
    infer_setback,
    infer_step_count,
    is_market_street,
    is_major_street,
    is_residential_street,
    get_typology_type,
)


def test_residential_detached_setback():
    sb = infer_setback("10 Lippincott St",
                       {"street": "Lippincott St"},
                       {"typology": "House-form, Detached"},
                       False, {})
    assert sb >= 2.0


def test_market_commercial_setback():
    sb = infer_setback("10 Kensington Ave",
                       {"street": "Kensington Ave"},
                       {"typology": "Commercial"},
                       True, {})
    assert sb == 0.0


def test_major_street_commercial():
    sb = infer_setback("400 Spadina Ave",
                       {"street": "Spadina Ave"},
                       {"typology": "Commercial"},
                       True, {})
    assert sb == 0.0


def test_major_street_default():
    sb = infer_setback("400 Spadina Ave",
                       {"street": "Spadina Ave"},
                       {"typology": "House-form"},
                       False, {})
    assert sb <= 1.0


def test_is_market_street():
    assert is_market_street("Kensington Ave")
    assert is_market_street("Augusta Ave")
    assert not is_market_street("Lippincott St")


def test_is_major_street():
    assert is_major_street("Spadina Ave")
    assert is_major_street("College St")
    assert not is_major_street("Nassau St")


def test_is_residential_street():
    assert is_residential_street("Lippincott St")
    assert is_residential_street("Wales Ave")


def test_step_count_from_foundation():
    steps = infer_step_count(0.36, 2.0)
    assert steps >= 1


def test_step_count_none_foundation():
    steps = infer_step_count(None, 0.0)
    assert steps >= 1


def test_typology_type():
    result = get_typology_type("House-form, Semi-detached")
    assert isinstance(result, str)
    assert len(result) > 0
