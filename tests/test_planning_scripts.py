"""Tests for scripts/planning/ analysis scripts."""

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts" / "planning"))

from analyze_density import load_buildings, compute_metrics, compare_scenarios
from apply_scenario import apply_intervention, apply_scenario
from shadow_impact import shadow_length, analyze_shadow_impact
from heritage_impact import assess_heritage_impact


# ── analyze_density ───────────────────────────────────────────────────

def test_compute_metrics_basic(tmp_path):
    params_dir = tmp_path / "params"
    params_dir.mkdir()

    for i, floors in enumerate([2, 3]):
        p = {"building_name": f"Test {i}", "floors": floors,
             "total_height_m": floors * 3.0,
             "facade_width_m": 5.0, "facade_depth_m": 10.0,
             "site": {"street": "Test St"}}
        (params_dir / f"test_{i}.json").write_text(json.dumps(p), encoding="utf-8")

    buildings = load_buildings(params_dir)
    assert len(buildings) == 2

    metrics = compute_metrics(buildings)
    assert metrics["building_count"] == 2
    assert metrics["avg_floors"] == 2.5
    assert metrics["total_gfa_sqm"] == 5.0 * 10.0 * 2 + 5.0 * 10.0 * 3


def test_compare_scenarios():
    base = {"building_count": 100, "avg_floors": 2.0, "fsi": 1.5,
            "avg_height_m": 7.0, "total_gfa_sqm": 50000, "total_dwellings": 200,
            "storefront_count": 50, "total_floors": 200}
    scen = {"building_count": 102, "avg_floors": 2.2, "fsi": 1.65,
            "avg_height_m": 7.5, "total_gfa_sqm": 55000, "total_dwellings": 230,
            "storefront_count": 52, "total_floors": 224}

    deltas = compare_scenarios(base, scen)
    assert deltas["total_dwellings"]["delta"] == 30
    assert deltas["building_count"]["delta"] == 2


# ── shadow_impact ─────────────────────────────────────────────────────

def test_shadow_length_noon():
    # At 45 degrees, shadow = height
    assert abs(shadow_length(10.0, 45.0) - 10.0) < 0.01


def test_shadow_length_low_sun():
    # At 10 degrees, shadow is very long
    length = shadow_length(10.0, 10.0)
    assert length > 50


def test_shadow_length_zero():
    length = shadow_length(10.0, 0)
    assert length == float("inf")


def test_analyze_shadow_impact(tmp_path):
    baseline = tmp_path / "baseline"
    baseline.mkdir()
    scenario = tmp_path / "scenario"
    scenario.mkdir()

    # Baseline: 7m building
    p1 = {"building_name": "Test", "total_height_m": 7.0, "floors": 2,
          "_meta": {"address": "Test"}, "site": {"street": "Test St"}}
    (baseline / "Test.json").write_text(json.dumps(p1), encoding="utf-8")

    # Scenario: 10m building (added floor)
    p2 = dict(p1)
    p2["total_height_m"] = 10.0
    p2["floors"] = 3
    (scenario / "Test.json").write_text(json.dumps(p2), encoding="utf-8")

    result = analyze_shadow_impact(baseline, scenario, season="winter")
    assert result["buildings_with_height_change"] == 1
    assert result["changes"][0]["height_delta_m"] == 3.0
    assert result["changes"][0]["max_shadow_increase_m"] > 0


# ── heritage_impact ───────────────────────────────────────────────────

def test_heritage_safe_intervention(tmp_path):
    baseline = tmp_path / "params"
    baseline.mkdir()
    scenario = tmp_path / "scenario"
    scenario.mkdir()

    p = {"building_name": "Heritage", "_meta": {"address": "Heritage"},
         "hcd_data": {"contributing": "Yes", "construction_date": "Pre-1889"}}
    (baseline / "Heritage.json").write_text(json.dumps(p), encoding="utf-8")

    intvs = {"scenario_id": "test",
             "interventions": [{"address": "Heritage", "type": "heritage_restore",
                                "params_override": {"condition": "good"}}]}
    (scenario / "interventions.json").write_text(json.dumps(intvs), encoding="utf-8")

    result = assess_heritage_impact(baseline, scenario)
    assert result["scores"]["safe"] == 1
    assert result["heritage_preservation_score"] == 100.0


def test_heritage_incompatible(tmp_path):
    baseline = tmp_path / "params"
    baseline.mkdir()
    scenario = tmp_path / "scenario"
    scenario.mkdir()

    p = {"building_name": "Old", "_meta": {"address": "Old"},
         "hcd_data": {"contributing": "Yes", "construction_date": "Pre-1889"}}
    (baseline / "Old.json").write_text(json.dumps(p), encoding="utf-8")

    intvs = {"scenario_id": "test",
             "interventions": [{"address": "Old", "type": "demolish"}]}
    (scenario / "interventions.json").write_text(json.dumps(intvs), encoding="utf-8")

    result = assess_heritage_impact(baseline, scenario)
    assert result["scores"]["incompatible"] == 1
    assert result["heritage_preservation_score"] < 50


def test_heritage_new_build(tmp_path):
    baseline = tmp_path / "params"
    baseline.mkdir()
    scenario = tmp_path / "scenario"
    scenario.mkdir()

    intvs = {"scenario_id": "test",
             "interventions": [{"address": "NEW", "type": "new_build",
                                "params": {"building_name": "New"}}]}
    (scenario / "interventions.json").write_text(json.dumps(intvs), encoding="utf-8")

    result = assess_heritage_impact(baseline, scenario)
    assert result["scores"]["new_build"] == 1


# ── apply_scenario ───────────────────────────────────────────────────

def test_apply_add_floor():
    params = {"floors": 2, "total_height_m": 6.0, "floor_heights_m": [3.0, 3.0],
              "windows_per_floor": [3, 3]}
    intv = {"type": "add_floor", "params_override": {"floors": 3}}
    result = apply_intervention(params, intv)
    assert result["floors"] == 3
    assert len(result["floor_heights_m"]) == 3
    assert result["total_height_m"] == 9.0
    assert len(result["windows_per_floor"]) == 3


def test_apply_green_roof():
    params = {"roof_type": "flat"}
    intv = {"type": "green_roof", "params_override": {"green_roof_type": "extensive"}}
    result = apply_intervention(params, intv)
    assert result["roof_detail"]["green_roof"] is True
    assert result["roof_detail"]["green_roof_type"] == "extensive"


def test_apply_convert_ground():
    params = {"has_storefront": False}
    intv = {"type": "convert_ground", "params_override": {"has_storefront": True}}
    result = apply_intervention(params, intv)
    assert result["has_storefront"] is True
    assert result["context"]["general_use"] == "commercial"


def test_apply_demolish():
    params = {"building_name": "Doomed"}
    intv = {"type": "demolish"}
    result = apply_intervention(params, intv)
    assert result["skipped"] is True


def test_apply_scenario_preserves_originals(tmp_path):
    baseline = tmp_path / "params"
    baseline.mkdir()
    scenario_dir = tmp_path / "scenario"
    scenario_dir.mkdir()
    output = tmp_path / "output"

    original = {"building_name": "Test", "floors": 2, "total_height_m": 6.0,
                "floor_heights_m": [3.0, 3.0], "windows_per_floor": [3, 3],
                "_meta": {"address": "Test"}}
    (baseline / "Test.json").write_text(json.dumps(original), encoding="utf-8")

    intvs = {"scenario_id": "test",
             "interventions": [{"address": "Test", "type": "add_floor",
                                "params_override": {"floors": 3}}]}
    (scenario_dir / "interventions.json").write_text(json.dumps(intvs), encoding="utf-8")

    apply_scenario(baseline, scenario_dir, output)

    # Original unchanged
    orig_data = json.loads((baseline / "Test.json").read_text(encoding="utf-8"))
    assert orig_data["floors"] == 2

    # Scenario has new value
    scen_data = json.loads((output / "Test.json").read_text(encoding="utf-8"))
    assert scen_data["floors"] == 3


def test_apply_scenario_new_build(tmp_path):
    baseline = tmp_path / "params"
    baseline.mkdir()
    scenario_dir = tmp_path / "scenario"
    scenario_dir.mkdir()
    output = tmp_path / "output"

    intvs = {"scenario_id": "test",
             "interventions": [{"address": "LANEWAY_A", "type": "new_build",
                                "params": {"building_name": "Coach House",
                                           "floors": 2, "total_height_m": 6.5}}]}
    (scenario_dir / "interventions.json").write_text(json.dumps(intvs), encoding="utf-8")

    stats = apply_scenario(baseline, scenario_dir, output)
    assert stats["new_builds"] == 1
    assert (output / "LANEWAY_A.json").exists()


def test_intervention_tracks_provenance():
    params = {"floors": 2}
    intv = {"type": "add_floor", "params_override": {"floors": 3}, "scenario_id": "test"}
    result = apply_intervention(params, intv)
    assert "_meta" in result
    assert len(result["_meta"]["scenarios_applied"]) == 1
    assert result["_meta"]["scenarios_applied"][0]["scenario_id"] == "test"


# ── protected fields ─────────────────────────────────────────────────

def test_interventions_do_not_modify_protected_fields():
    """Verify that scenario overrides never touch site, city_data, or hcd_data."""
    scenarios_dir = REPO_ROOT / "scenarios"
    if not scenarios_dir.exists():
        pytest.skip("No scenarios directory")

    protected_keys = {"site", "city_data", "hcd_data"}

    for scenario in scenarios_dir.iterdir():
        intv_path = scenario / "interventions.json"
        if not intv_path.exists():
            continue
        data = json.loads(intv_path.read_text(encoding="utf-8"))
        for intv in data.get("interventions", []):
            override_keys = set(intv.get("params_override", {}).keys())
            param_keys = set(intv.get("params", {}).keys())
            all_keys = override_keys | param_keys
            violations = all_keys & protected_keys
            assert not violations, (
                f"{scenario.name}: intervention on {intv.get('address')} "
                f"modifies protected fields: {violations}"
            )
