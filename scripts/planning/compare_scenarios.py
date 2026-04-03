#!/usr/bin/env python3
"""Compare baseline vs scenario outputs side-by-side.

Computes per-building and aggregate deltas for visual and metric comparison.

Usage:
    python scripts/planning/compare_scenarios.py --baseline params/ --scenario outputs/scenarios/gentle_density/
    python scripts/planning/compare_scenarios.py --baseline outputs/full/ --scenario outputs/scenarios/gentle_density/ --metric height
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def load_params(params_dir: Path) -> dict[str, dict]:
    """Load all non-skipped params keyed by filename stem."""
    result = {}
    for f in sorted(params_dir.glob("*.json")):
        if f.name.startswith("_"):
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if data.get("skipped"):
            continue
        result[f.stem] = data
    return result


def compare(baseline_dir: Path, scenario_dir: Path) -> dict:
    """Compare baseline vs scenario params.

    Returns:
        Comparison report with per-building changes and aggregate stats.
    """
    baseline = load_params(baseline_dir)
    scenario = load_params(scenario_dir)

    changes = []
    new_builds = []
    demolished = []

    compare_keys = ["floors", "total_height_m", "facade_width_m", "facade_depth_m",
                    "has_storefront", "roof_type", "condition"]

    for stem in sorted(set(baseline) | set(scenario)):
        base = baseline.get(stem)
        scen = scenario.get(stem)

        if base and not scen:
            demolished.append({"address": base.get("_meta", {}).get("address", stem), "stem": stem})
            continue
        if scen and not base:
            new_builds.append({
                "address": scen.get("_meta", {}).get("address", stem),
                "stem": stem,
                "floors": scen.get("floors"),
                "height": scen.get("total_height_m"),
            })
            continue

        diffs = {}
        for key in compare_keys:
            bv = base.get(key)
            sv = scen.get(key)
            if bv != sv:
                diffs[key] = {"baseline": bv, "scenario": sv}

        # Check roof_detail changes
        base_rd = base.get("roof_detail", {})
        scen_rd = scen.get("roof_detail", {})
        if scen_rd.get("green_roof") and not base_rd.get("green_roof"):
            diffs["green_roof"] = {"baseline": False, "scenario": True}

        if diffs:
            addr = base.get("_meta", {}).get("address", stem)
            changes.append({"address": addr, "stem": stem, "changes": diffs})

    # Aggregate stats
    base_heights = [b.get("total_height_m", 0) for b in baseline.values()]
    scen_heights = [s.get("total_height_m", 0) for s in scenario.values()]
    base_floors = [b.get("floors", 0) for b in baseline.values()]
    scen_floors = [s.get("floors", 0) for s in scenario.values()]

    report = {
        "summary": {
            "baseline_buildings": len(baseline),
            "scenario_buildings": len(scenario),
            "modified": len(changes),
            "new_builds": len(new_builds),
            "demolished": len(demolished),
        },
        "aggregates": {
            "baseline_avg_height": round(sum(base_heights) / max(len(base_heights), 1), 2),
            "scenario_avg_height": round(sum(scen_heights) / max(len(scen_heights), 1), 2),
            "baseline_avg_floors": round(sum(base_floors) / max(len(base_floors), 1), 2),
            "scenario_avg_floors": round(sum(scen_floors) / max(len(scen_floors), 1), 2),
            "baseline_storefronts": sum(1 for b in baseline.values() if b.get("has_storefront")),
            "scenario_storefronts": sum(1 for s in scenario.values() if s.get("has_storefront")),
        },
        "changes": changes,
        "new_builds": new_builds,
        "demolished": demolished,
    }

    return report


def main():
    parser = argparse.ArgumentParser(description="Compare baseline vs scenario")
    parser.add_argument("--baseline", type=Path, default=REPO_ROOT / "params")
    parser.add_argument("--scenario", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    report = compare(args.baseline, args.scenario)

    s = report["summary"]
    print(f"Comparison: {s['baseline_buildings']} baseline, {s['scenario_buildings']} scenario")
    print(f"  Modified: {s['modified']}, New builds: {s['new_builds']}, Demolished: {s['demolished']}")

    a = report["aggregates"]
    print(f"  Avg height: {a['baseline_avg_height']}m -> {a['scenario_avg_height']}m")
    print(f"  Avg floors: {a['baseline_avg_floors']} -> {a['scenario_avg_floors']}")
    print(f"  Storefronts: {a['baseline_storefronts']} -> {a['scenario_storefronts']}")

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"  Report: {args.output}")


if __name__ == "__main__":
    main()
