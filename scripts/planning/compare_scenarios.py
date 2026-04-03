#!/usr/bin/env python3
"""Compare two scenario outputs side by side.

Produces a summary table of key metrics for each scenario plus deltas.

Usage:
    python scripts/planning/compare_scenarios.py --scenarios scenarios/10yr_gentle_density/ scenarios/10yr_heritage_first/
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PARAMS_DIR = REPO_ROOT / "params"


def load_scenario_metrics(scenario_dir: Path) -> dict:
    """Load pre-computed density analysis or compute on the fly."""
    analysis = scenario_dir / "density_analysis.json"
    if analysis.exists():
        data = json.loads(analysis.read_text(encoding="utf-8"))
        return data.get("scenario", data)

    # Fallback: compute from params
    params_dir = scenario_dir / "params"
    if not params_dir.exists():
        return {}

    from analyze_density import load_buildings, compute_metrics
    buildings = load_buildings(params_dir)
    return compute_metrics(buildings)


def main():
    parser = argparse.ArgumentParser(description="Compare scenario outputs.")
    parser.add_argument("--baseline", type=Path, default=PARAMS_DIR)
    parser.add_argument("--scenarios", type=Path, nargs="+", required=True)
    parser.add_argument("--output", type=Path, default=REPO_ROOT / "outputs" / "scenario_comparison.json")
    args = parser.parse_args()

    # Load baseline
    from analyze_density import load_buildings, compute_metrics
    baseline = compute_metrics(load_buildings(args.baseline))

    results = {"baseline": baseline, "scenarios": {}}

    print(f"{'Metric':<25} {'Baseline':>10}", end="")
    for s in args.scenarios:
        name = s.name
        metrics = load_scenario_metrics(s)
        results["scenarios"][name] = metrics
        print(f" {name:>15}", end="")
    print()
    print("-" * (40 + 16 * len(args.scenarios)))

    keys = ["building_count", "avg_floors", "avg_height_m", "fsi",
            "total_dwellings", "storefront_count"]
    for key in keys:
        label = key.replace("_", " ").title()
        print(f"{label:<25} {baseline.get(key, 0):>10}", end="")
        for s in args.scenarios:
            name = s.name
            val = results["scenarios"][name].get(key, 0)
            print(f" {val:>15}", end="")
        print()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(results, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"\nOutput: {args.output}")


if __name__ == "__main__":
    main()
