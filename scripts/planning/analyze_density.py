#!/usr/bin/env python3
"""Analyze density impact of a planning scenario.

Reads interventions.json and baseline params, computes dwelling units added,
FSI change, lot coverage change, and height distribution. Writes
density_analysis.json to the scenario directory.

Usage:
    python scripts/planning/analyze_density.py --scenario scenarios/10yr_gentle_density/
"""

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
PARAMS = REPO / "params"

DEFAULT_FLOOR_HEIGHT_M = 3.0


def load_params(params_dir: Path) -> dict:
    """Load all param files into a dict keyed by building_name."""
    buildings = {}
    for f in sorted(params_dir.glob("*.json")):
        if f.name.startswith("_"):
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if data.get("skipped"):
            continue
        name = data.get("building_name") or data.get("_meta", {}).get("address", "")
        if name:
            buildings[name] = data
    return buildings


def load_interventions(scenario_dir: Path) -> dict:
    path = scenario_dir / "interventions.json"
    return json.loads(path.read_text(encoding="utf-8"))


def compute_metrics(buildings: dict) -> dict:
    """Compute aggregate density metrics from a buildings dict."""
    total_floors = 0
    total_height = 0.0
    total_gfa = 0.0
    total_footprint = 0.0
    total_dwellings = 0
    storefront_count = 0
    count = 0
    by_street = defaultdict(lambda: {"count": 0, "floors": 0, "height": 0.0, "dwellings": 0})

    for _addr, b in buildings.items():
        floors = b.get("floors") or 0
        height = b.get("total_height_m") or b.get("city_data", {}).get("height_avg_m") or (floors * DEFAULT_FLOOR_HEIGHT_M)
        footprint = b.get("city_data", {}).get("footprint_sqm") or (
            (b.get("facade_width_m") or 0) * (b.get("facade_depth_m") or 0)
        )
        gfa = b.get("city_data", {}).get("gfa_sqm") or (footprint * max(floors, 1))
        dwellings = b.get("city_data", {}).get("dwelling_units") or 0
        sf = b.get("has_storefront") or False

        total_floors += floors
        total_height += height
        total_gfa += gfa
        total_footprint += footprint
        total_dwellings += dwellings
        if sf:
            storefront_count += 1
        count += 1

        street = b.get("site", {}).get("street") or ""
        if street:
            s = by_street[street]
            s["count"] += 1
            s["floors"] += floors
            s["height"] += height
            s["dwellings"] += dwellings

    avg_floors = round(total_floors / count, 2) if count else 0
    avg_height = round(total_height / count, 2) if count else 0
    fsi = round(total_gfa / total_footprint, 3) if total_footprint else 0

    street_summary = {}
    for st, s in sorted(by_street.items()):
        street_summary[st] = {
            "count": s["count"],
            "avg_floors": round(s["floors"] / s["count"], 1) if s["count"] else 0,
            "avg_height_m": round(s["height"] / s["count"], 1) if s["count"] else 0,
            "dwellings": s["dwellings"],
        }

    return {
        "building_count": count,
        "total_floors": total_floors,
        "avg_floors": avg_floors,
        "avg_height_m": avg_height,
        "total_gfa_sqm": round(total_gfa, 1),
        "total_footprint_sqm": round(total_footprint, 1),
        "fsi": fsi,
        "total_dwellings": total_dwellings,
        "storefront_count": storefront_count,
        "by_street": street_summary,
    }


def apply_interventions(buildings: dict, interventions: list) -> dict:
    """Apply interventions to a deep copy of buildings, return modified set."""
    import copy
    modified = copy.deepcopy(buildings)

    for intervention in interventions:
        address = intervention.get("address", "")
        override = intervention.get("params_override", {})
        itype = intervention.get("type", "")

        if address in modified:
            for key, value in override.items():
                if isinstance(value, dict) and isinstance(modified[address].get(key), dict):
                    modified[address][key].update(value)
                else:
                    modified[address][key] = value

            # Estimate new dwelling units for add_floor
            if itype == "add_floor" and "floors" in override:
                old_floors = buildings[address].get("floors") or 0
                new_floors = override["floors"]
                added = max(0, new_floors - old_floors)
                old_units = modified[address].get("city_data", {}).get("dwelling_units") or 0
                modified[address].setdefault("city_data", {})["dwelling_units"] = old_units + added

            # Estimate new height for add_floor
            if itype == "add_floor" and "floors" in override:
                old_floors = buildings[address].get("floors") or 0
                new_floors = override["floors"]
                added = max(0, new_floors - old_floors)
                old_height = modified[address].get("total_height_m") or (old_floors * DEFAULT_FLOOR_HEIGHT_M)
                modified[address]["total_height_m"] = old_height + added * DEFAULT_FLOOR_HEIGHT_M

        elif itype == "new_build":
            new_data = {
                "building_name": address,
                "floors": override.get("floors", 2),
                "total_height_m": override.get("floors", 2) * DEFAULT_FLOOR_HEIGHT_M,
                "facade_width_m": override.get("facade_width_m", 6.0),
                "facade_depth_m": override.get("facade_depth_m", 8.0),
                "has_storefront": override.get("has_storefront", False),
                "city_data": {
                    "footprint_sqm": override.get("facade_width_m", 6.0) * override.get("facade_depth_m", 8.0),
                    "gfa_sqm": override.get("facade_width_m", 6.0) * override.get("facade_depth_m", 8.0) * override.get("floors", 2),
                    "dwelling_units": override.get("floors", 2),
                },
                "site": {},
            }
            new_data.update(override)
            modified[address] = new_data

    return modified


def compute_deltas(baseline: dict, scenario: dict) -> dict:
    """Compute deltas between baseline and scenario metrics."""
    deltas = {}
    for key in ["building_count", "total_floors", "avg_floors", "avg_height_m",
                 "total_gfa_sqm", "fsi", "total_dwellings", "storefront_count"]:
        b = baseline.get(key, 0)
        s = scenario.get(key, 0)
        delta = round(s - b, 3) if isinstance(s, float) else s - b
        pct = round((delta / b) * 100, 1) if b else 0.0
        deltas[key] = {
            "baseline": b,
            "scenario": s,
            "delta": delta,
            "pct_change": pct,
        }
    return deltas


def main():
    parser = argparse.ArgumentParser(description="Analyze density impact of a planning scenario")
    parser.add_argument("--scenario", required=True, help="Path to scenario directory")
    parser.add_argument("--baseline", default=None, help="Path to baseline params directory (default: params/)")
    args = parser.parse_args()

    scenario_dir = Path(args.scenario)
    if not scenario_dir.is_absolute():
        scenario_dir = REPO / scenario_dir

    baseline_dir = Path(args.baseline) if args.baseline else PARAMS
    if not baseline_dir.is_absolute():
        baseline_dir = REPO / baseline_dir

    print(f"Loading baseline params from {baseline_dir} ...")
    buildings = load_params(baseline_dir)
    print(f"  {len(buildings)} buildings loaded")

    scenario_data = load_interventions(scenario_dir)
    interventions = scenario_data.get("interventions", [])
    print(f"  {len(interventions)} interventions in {scenario_data.get('scenario_id', 'unknown')}")

    baseline_metrics = compute_metrics(buildings)
    modified = apply_interventions(buildings, interventions)
    scenario_metrics = compute_metrics(modified)
    deltas = compute_deltas(baseline_metrics, scenario_metrics)

    result = {
        "baseline": baseline_metrics,
        "scenario": scenario_metrics,
        "deltas": deltas,
    }

    out_path = scenario_dir / "density_analysis.json"
    out_path.write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"\nDensity analysis written to {out_path}")
    print(f"  Dwellings: {baseline_metrics['total_dwellings']} -> {scenario_metrics['total_dwellings']} "
          f"(+{deltas['total_dwellings']['delta']})")
    print(f"  FSI: {baseline_metrics['fsi']} -> {scenario_metrics['fsi']} "
          f"({deltas['fsi']['delta']:+.3f})")


if __name__ == "__main__":
    main()
