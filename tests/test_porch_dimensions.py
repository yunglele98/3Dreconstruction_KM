"""Tests for scripts/enrich_porch_dimensions.py"""

import pytest
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from enrich_porch_dimensions import (
    get_porch_width_m,
    get_porch_columns,
    infer_step_count,
    parse_era,
)


def test_porch_width_narrow_facade():
    assert get_porch_width_m(4.0) == pytest.approx(4.0 * 0.6, rel=0.1)


def test_porch_width_medium_facade():
    assert get_porch_width_m(6.0) == pytest.approx(6.0 * 0.5, rel=0.1)


def test_porch_width_wide_facade():
    assert get_porch_width_m(12.0) == pytest.approx(4.0, rel=0.1)


def test_porch_columns_pre_1889():
    cols = get_porch_columns("Pre-1889")
    assert cols["type"] == "square" or cols["material"] == "wood"


def test_porch_columns_edwardian():
    cols = get_porch_columns("1904-1913")
    assert cols["type"] == "tapered_square"


def test_porch_columns_modern():
    cols = get_porch_columns("1914-1930")
    assert cols["type"] == "square"


def test_step_count_from_params():
    # infer_step_count takes a full params dict
    params = {"foundation_height_m": 0.54, "deep_facade_analysis": {"depth_notes": {}}}
    steps = infer_step_count(params)
    assert steps >= 2


def test_step_count_no_foundation():
    params = {"deep_facade_analysis": {"depth_notes": {}}}
    steps = infer_step_count(params)
    assert steps >= 1


def test_parse_era_standard():
    era = parse_era("1889-1903")
    assert era is not None
