"""Tests for scripts/analyze/ urban analysis scripts."""

import json
import math
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts" / "analyze"))

from shadow_analysis import shadow_length_m, compute_sun_hours


# ── shadow_analysis ──────────────────────────────────────────────────

def test_shadow_length_45_degrees():
    assert abs(shadow_length_m(10.0, 45.0) - 10.0) < 0.01


def test_shadow_length_zero_elevation():
    assert shadow_length_m(10.0, 0) == 999


def test_shadow_length_high_sun():
    # At 70 degrees, shadow is short
    length = shadow_length_m(10.0, 70.0)
    assert length < 5


def test_compute_sun_hours_isolated_building():
    """A building with no neighbours should get maximum sun hours."""
    buildings = [{"address": "Alone", "lon": -79.4, "lat": 43.65, "height": 7, "street": "Test"}]
    results = compute_sun_hours(buildings)
    assert len(results) == 1
    assert results[0]["avg_daily_sun_hours"] > 0
    assert results[0]["sun_hours_summer"] > results[0]["sun_hours_winter"]


def test_compute_sun_hours_shadowed():
    """A building directly north of a tall building should get less sun."""
    buildings = [
        {"address": "Tall", "lon": -79.4, "lat": 43.6500, "height": 30, "street": "Test"},
        {"address": "North", "lon": -79.4, "lat": 43.6502, "height": 7, "street": "Test"},
    ]
    results = compute_sun_hours(buildings)
    tall = next(r for r in results if r["address"] == "Tall")
    north = next(r for r in results if r["address"] == "North")
    # The northern building should have fewer sun hours (shadowed by tall building to south)
    assert north["annual_sun_hours"] <= tall["annual_sun_hours"]


# ── output files ─────────────────────────────────────────────────────

def test_shadow_output_exists():
    path = REPO_ROOT / "outputs" / "spatial" / "shadow_metrics.json"
    if not path.exists():
        pytest.skip("Shadow output not generated yet")
    data = json.loads(path.read_text(encoding="utf-8"))
    assert "overall" in data
    assert "buildings" in data
    assert data["overall"]["building_count"] > 0


def test_morphology_output_exists():
    path = REPO_ROOT / "outputs" / "spatial" / "morphology_metrics.json"
    if not path.exists():
        pytest.skip("Morphology output not generated yet")
    data = json.loads(path.read_text(encoding="utf-8"))
    assert "overall" in data
    assert data["overall"]["avg_area_sqm"] > 0
    assert data["overall"]["avg_compactness"] > 0


def test_network_output_exists():
    path = REPO_ROOT / "outputs" / "spatial" / "network_metrics.json"
    if not path.exists():
        pytest.skip("Network output not generated yet")
    data = json.loads(path.read_text(encoding="utf-8"))
    assert "network" in data
    assert data["network"]["node_count"] > 0
    assert data["network"]["edge_count"] > 0


def test_accessibility_output_exists():
    path = REPO_ROOT / "outputs" / "spatial" / "accessibility_metrics.json"
    if not path.exists():
        pytest.skip("Accessibility output not generated yet")
    data = json.loads(path.read_text(encoding="utf-8"))
    assert "overall" in data
    assert 0 <= data["overall"]["avg_walkability"] <= 100


def test_viewshed_output_exists():
    path = REPO_ROOT / "outputs" / "spatial" / "viewshed_metrics.json"
    if not path.exists():
        pytest.skip("Viewshed output not generated yet")
    data = json.loads(path.read_text(encoding="utf-8"))
    assert "overall" in data
    assert data["overall"]["viewpoint_count"] > 0
