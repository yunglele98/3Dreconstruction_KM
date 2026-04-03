#!/usr/bin/env python3
"""Compute density metrics for baseline and scenario params.

Usage:
    python scripts/planning/analyze_density.py --baseline params/
    python scripts/planning/analyze_density.py --scenario outputs/scenarios/gentle_density/
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def load_buildings(params_dir: Path) -> list[dict]:
    """Load all non-skipped, non-metadata building params."""
    buildings = []
    for f in sorted(params_dir.glob("*.json")):
        if f.name.startswith("_"):
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if data.get("skipped"):
            continue
        buildings.append(data)
    return buildings


def compute_metrics(buildings: list[dict]) -> dict:
    """Compute aggregate density metrics from building list."""
    if not buildings:
        return {
            "building_count": 0, "avg_floors": 0, "total_floors": 0,
            "avg_height_m": 0, "total_gfa_sqm": 0, "fsi": 0,
            "total_dwellings": 0, "storefront_count": 0,
        }

    total_floors = sum(b.get("floors", 1) for b in buildings)
    total_height = sum(b.get("total_height_m", 0) for b in buildings)
    total_gfa = sum(
        b.get("facade_width_m", 0) * b.get("facade_depth_m", 0) * b.get("floors", 1)
        for b in buildings
    )
    total_footprint = sum(
        b.get("facade_width_m", 0) * b.get("facade_depth_m", 0)
        for b in buildings
    )
    total_dwellings = sum(
        b.get("city_data", {}).get("dwelling_units", 0) for b in buildings
    )
    storefront_count = sum(1 for b in buildings if b.get("has_storefront"))

    n = len(buildings)
    return {
        "building_count": n,
        "avg_floors": total_floors / n,
        "total_floors": total_floors,
        "avg_height_m": total_height / n,
        "total_gfa_sqm": total_gfa,
        "fsi": total_gfa / total_footprint if total_footprint else 0,
        "total_dwellings": total_dwellings,
        "storefront_count": storefront_count,
    }


def compare_scenarios(baseline_metrics: dict, scenario_metrics: dict) -> dict:
    """Compare two metric sets and return deltas."""
    deltas = {}
    for key in baseline_metrics:
        base_val = baseline_metrics[key]
        scen_val = scenario_metrics.get(key, base_val)
        deltas[key] = {
            "baseline": base_val,
            "scenario": scen_val,
            "delta": scen_val - base_val if isinstance(base_val, (int, float)) else None,
            "pct_change": (
                ((scen_val - base_val) / base_val * 100) if base_val and isinstance(base_val, (int, float)) else None
            ),
        }
    return deltas


def main():
    parser = argparse.ArgumentParser(description="Compute density metrics")
    parser.add_argument("--baseline", type=Path, default=REPO_ROOT / "params")
    parser.add_argument("--scenario", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    base_buildings = load_buildings(args.baseline)
    base_metrics = compute_metrics(base_buildings)
    print(f"Baseline: {base_metrics['building_count']} buildings, "
          f"avg {base_metrics['avg_floors']:.1f} floors, "
          f"FSI {base_metrics['fsi']:.2f}")

    if args.scenario:
        scen_buildings = load_buildings(args.scenario)
        scen_metrics = compute_metrics(scen_buildings)
        deltas = compare_scenarios(base_metrics, scen_metrics)
        print(f"\nScenario: {scen_metrics['building_count']} buildings")
        for key, d in deltas.items():
            if d["delta"] is not None:
                print(f"  {key}: {d['baseline']} -> {d['scenario']} ({d['delta']:+.1f})")

        if args.output:
            args.output.write_text(
                json.dumps({"baseline": base_metrics, "scenario": scen_metrics, "deltas": deltas},
                           indent=2),
                encoding="utf-8",
            )


if __name__ == "__main__":
    main()
