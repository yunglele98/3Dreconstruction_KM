#!/usr/bin/env python3
"""Analyze density metrics for a scenario vs baseline.

Compares building params between baseline and scenario directories,
computing FSI, dwelling units, height changes, and per-street summaries.

Usage:
    python scripts/planning/analyze_density.py --baseline params/ --scenario scenarios/10yr_gentle_density/params/
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PARAMS_DIR = REPO_ROOT / "params"


def load_buildings(params_dir: Path) -> dict:
    """Load all active building params, keyed by filename stem."""
    buildings = {}
    for f in sorted(params_dir.glob("*.json")):
        if f.name.startswith("_"):
            continue
        try:
            params = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if params.get("skipped"):
            continue
        buildings[f.stem] = params
    return buildings


def compute_metrics(buildings: dict) -> dict:
    """Compute aggregate density metrics from a set of buildings."""
    total_height = 0
    total_floors = 0
    total_gfa = 0
    total_footprint = 0
    total_dwellings = 0
    storefronts = 0
    building_count = 0

    by_street = defaultdict(lambda: {"count": 0, "floors": 0, "height": 0, "dwellings": 0})

    for stem, p in buildings.items():
        building_count += 1
        floors = p.get("floors", 0) or 0
        height = p.get("total_height_m", 0) or 0
        width = p.get("facade_width_m", 0) or 0
        depth = p.get("facade_depth_m", 0) or 0

        footprint = width * depth
        gfa = footprint * floors

        total_height += height
        total_floors += floors
        total_gfa += gfa
        total_footprint += footprint

        city = p.get("city_data", {})
        dwellings = city.get("dwelling_units", 0) or 0
        total_dwellings += dwellings

        if p.get("has_storefront"):
            storefronts += 1

        street = p.get("site", {}).get("street", "unknown")
        by_street[street]["count"] += 1
        by_street[street]["floors"] += floors
        by_street[street]["height"] += height
        by_street[street]["dwellings"] += dwellings

    avg_height = total_height / max(building_count, 1)
    avg_floors = total_floors / max(building_count, 1)
    fsi = total_gfa / max(total_footprint, 1)

    # Per-street averages
    street_summary = {}
    for street, data in sorted(by_street.items()):
        n = max(data["count"], 1)
        street_summary[street] = {
            "count": data["count"],
            "avg_floors": round(data["floors"] / n, 1),
            "avg_height_m": round(data["height"] / n, 1),
            "dwellings": data["dwellings"],
        }

    return {
        "building_count": building_count,
        "total_floors": total_floors,
        "avg_floors": round(avg_floors, 2),
        "avg_height_m": round(avg_height, 2),
        "total_gfa_sqm": round(total_gfa, 1),
        "total_footprint_sqm": round(total_footprint, 1),
        "fsi": round(fsi, 3),
        "total_dwellings": total_dwellings,
        "storefront_count": storefronts,
        "by_street": street_summary,
    }


def compare_scenarios(baseline_metrics: dict, scenario_metrics: dict) -> dict:
    """Compute deltas between baseline and scenario."""
    deltas = {}
    for key in ["building_count", "total_floors", "avg_floors", "avg_height_m",
                 "total_gfa_sqm", "fsi", "total_dwellings", "storefront_count"]:
        base_val = baseline_metrics.get(key, 0)
        scen_val = scenario_metrics.get(key, 0)
        delta = scen_val - base_val
        pct = (delta / base_val * 100) if base_val else 0
        deltas[key] = {
            "baseline": base_val,
            "scenario": scen_val,
            "delta": round(delta, 2),
            "pct_change": round(pct, 1),
        }
    return deltas


def main():
    parser = argparse.ArgumentParser(description="Analyze density metrics for scenario vs baseline.")
    parser.add_argument("--baseline", type=Path, default=PARAMS_DIR)
    parser.add_argument("--scenario", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    print(f"Loading baseline: {args.baseline}")
    baseline = load_buildings(args.baseline)
    baseline_metrics = compute_metrics(baseline)

    print(f"Loading scenario: {args.scenario}")
    scenario = load_buildings(args.scenario)
    scenario_metrics = compute_metrics(scenario)

    deltas = compare_scenarios(baseline_metrics, scenario_metrics)

    result = {
        "baseline": baseline_metrics,
        "scenario": scenario_metrics,
        "deltas": deltas,
    }

    output = args.output or (args.scenario.parent / "density_analysis.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    print(f"\n{'Metric':<25} {'Baseline':>10} {'Scenario':>10} {'Delta':>10} {'%':>8}")
    print("-" * 65)
    for key, d in deltas.items():
        label = key.replace("_", " ").title()
        print(f"{label:<25} {d['baseline']:>10} {d['scenario']:>10} {d['delta']:>+10} {d['pct_change']:>+7.1f}%")

    print(f"\nOutput: {output}")


if __name__ == "__main__":
    main()
