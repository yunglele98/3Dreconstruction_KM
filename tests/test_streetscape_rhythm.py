"""Tests for scripts/analyze_streetscape_rhythm.py"""

import json
import pytest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.analyze_streetscape_rhythm import (
    compute_era_coherence,
    compute_longest_material_run,
    compute_storefront_density,
)


def test_era_coherence_all_same():
    buildings = [
        {"hcd_data": {"construction_date": "Pre-1889"}},
        {"hcd_data": {"construction_date": "Pre-1889"}},
        {"hcd_data": {"construction_date": "Pre-1889"}},
    ]
    score = compute_era_coherence(buildings)
    assert score == pytest.approx(1.0)


def test_era_coherence_all_different():
    buildings = [
        {"hcd_data": {"construction_date": "Pre-1889"}},
        {"hcd_data": {"construction_date": "1904-1913"}},
        {"hcd_data": {"construction_date": "1914-1930"}},
    ]
    score = compute_era_coherence(buildings)
    assert score < 1.0


def test_material_run_uniform():
    buildings = [{"facade_material": "brick"}] * 5
    run = compute_longest_material_run(buildings)
    assert run == 5


def test_material_run_mixed():
    buildings = [
        {"facade_material": "brick"},
        {"facade_material": "brick"},
        {"facade_material": "painted"},
        {"facade_material": "brick"},
    ]
    run = compute_longest_material_run(buildings)
    assert run == 2


def test_storefront_density():
    buildings = [
        {"has_storefront": True},
        {"has_storefront": True},
        {"has_storefront": False},
        {"has_storefront": False},
    ]
    density = compute_storefront_density(buildings)
    assert density == pytest.approx(0.5)
