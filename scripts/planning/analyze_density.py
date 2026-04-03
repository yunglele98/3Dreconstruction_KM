#!/usr/bin/env python3
"""Stage 11 — SCENARIOS: Analyze density metrics for baseline or scenario params.

Computes building count, average floors, FSI, GFA, dwelling estimates,
and storefront counts from a params directory.

Usage:
    python scripts/planning/analyze_density.py --scenario scenarios/10yr_gentle_density/
    python scripts/planning/analyze_density.py --baseline params/ --scenario-params outputs/scenarios/gentle_density/
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def load_buildings(params_dir: Path) -> list[dict]:
    """Load all non-skipped building params from a directory."""
    buildings = []
    for f in sorted(params_dir.glob("*.json")):
        if f.name.startswith("_"):
            continue
        data = json.loads(f.read_text(encoding="utf-8"))
        if data.get("skipped"):
            continue
        buildings.append(data)
    return buildings


def compute_metrics(buildings: list[dict]) -> dict:
    """Compute aggregate density metrics from a list of building params."""
    if not buildings:
        return {
            "building_count": 0, "total_floors": 0, "avg_floors": 0,
            "avg_height_m": 0, "total_gfa_sqm": 0, "fsi": 0,
            "total_dwellings": 0, "storefront_count": 0,
        }

    total_floors = 0
    total_height = 0.0
    total_gfa = 0.0
    total_footprint = 0.0
    total_dwellings = 0
    storefront_count = 0

    for b in buildings:
        floors = b.get("floors", 2)
        height = b.get("total_height_m", floors * 3.0)
        width = b.get("facade_width_m", 5.0)
        depth = b.get("facade_depth_m", 10.0)
        footprint = width * depth
        gfa = footprint * floors

        total_floors += floors
        total_height += height
        total_gfa += gfa
        total_footprint += footprint

        # Estimate dwellings: residential floors * 1 unit per floor (simple)
        dwellings = b.get("city_data", {}).get("dwelling_units", 0)
        if not dwellings:
            residential_floors = max(0, floors - (1 if b.get("has_storefront") else 0))
            dwellings = residential_floors
        total_dwellings += dwellings

        if b.get("has_storefront"):
            storefront_count += 1

    n = len(buildings)
    return {
        "building_count": n,
        "total_floors": total_floors,
        "avg_floors": round(total_floors / n, 2) if n else 0,
        "avg_height_m": round(total_height / n, 2) if n else 0,
        "total_gfa_sqm": round(total_gfa, 1),
        "total_footprint_sqm": round(total_footprint, 1),
        "fsi": round(total_gfa / total_footprint, 3) if total_footprint else 0,
        "total_dwellings": total_dwellings,
        "storefront_count": storefront_count,
    }


def compare_scenarios(baseline_metrics: dict, scenario_metrics: dict) -> dict:
    """Compute deltas between baseline and scenario metrics."""
    deltas = {}
    for key in baseline_metrics:
        if isinstance(baseline_metrics[key], (int, float)):
            base_val = baseline_metrics[key]
            scen_val = scenario_metrics.get(key, base_val)
            deltas[key] = {
                "baseline": base_val,
                "scenario": scen_val,
                "delta": round(scen_val - base_val, 3) if isinstance(scen_val, float) else scen_val - base_val,
            }
    return deltas


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze density metrics")
    parser.add_argument("--baseline", type=Path, default=REPO_ROOT / "params")
    parser.add_argument("--scenario-params", type=Path, default=None)
    parser.add_argument("--scenario", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    baseline_buildings = load_buildings(args.baseline)
    baseline_metrics = compute_metrics(baseline_buildings)

    print(f"Baseline: {baseline_metrics['building_count']} buildings, "
          f"avg {baseline_metrics['avg_floors']} floors, "
          f"FSI {baseline_metrics['fsi']}")

    if args.scenario_params:
        scen_buildings = load_buildings(args.scenario_params)
        scen_metrics = compute_metrics(scen_buildings)
        deltas = compare_scenarios(baseline_metrics, scen_metrics)

        result = {
            "baseline": baseline_metrics,
            "scenario": scen_metrics,
            "deltas": deltas,
        }

        if args.output:
            args.output.write_text(
                json.dumps(result, indent=2), encoding="utf-8"
            )
        else:
            print(json.dumps(deltas, indent=2))


if __name__ == "__main__":
    main()
