#!/usr/bin/env python3
"""Compare metrics across multiple planning scenarios.

Reads analysis outputs from scenario directories and produces a comparison
table. Can compare two specific scenarios or all scenarios found under
the scenarios/ directory.

Usage:
    python scripts/planning/compare_scenarios.py --baseline outputs/full/ --scenario outputs/scenarios/gentle_density/
    python scripts/planning/compare_scenarios.py --all
"""

import argparse
import json
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
SCENARIOS = REPO / "scenarios"


def load_scenario_summary(scenario_dir: Path) -> dict:
    """Load summary data from a scenario directory."""
    summary = {
        "path": str(scenario_dir),
        "name": scenario_dir.name,
    }

    # Load interventions metadata
    interventions_path = scenario_dir / "interventions.json"
    if interventions_path.exists():
        data = json.loads(interventions_path.read_text(encoding="utf-8"))
        summary["scenario_id"] = data.get("scenario_id", "")
        summary["scenario_name"] = data.get("name", "")
        summary["description"] = data.get("description", "")
        summary["total_interventions"] = len(data.get("interventions", []))

        from collections import Counter
        types = Counter(i["type"] for i in data.get("interventions", []))
        summary["intervention_types"] = dict(types)

    # Load density analysis if available
    density_path = scenario_dir / "density_analysis.json"
    if density_path.exists():
        density = json.loads(density_path.read_text(encoding="utf-8"))
        deltas = density.get("deltas", {})
        summary["density"] = {
            "dwelling_units_added": deltas.get("total_dwellings", {}).get("delta", 0),
            "fsi_change": deltas.get("fsi", {}).get("delta", 0),
            "avg_floors_change": deltas.get("avg_floors", {}).get("delta", 0),
            "avg_height_change_m": deltas.get("avg_height_m", {}).get("delta", 0),
            "gfa_change_sqm": deltas.get("total_gfa_sqm", {}).get("delta", 0),
            "storefront_change": deltas.get("storefront_count", {}).get("delta", 0),
        }

    # Load heritage impact if available
    heritage_path = scenario_dir / "heritage_impact.json"
    if heritage_path.exists():
        heritage = json.loads(heritage_path.read_text(encoding="utf-8"))
        summary["heritage"] = {
            "preservation_score": heritage.get("heritage_preservation_score", 0),
            "safe": heritage.get("scores", {}).get("safe", 0),
            "review": heritage.get("scores", {}).get("review", 0),
            "incompatible": heritage.get("scores", {}).get("incompatible", 0),
        }

    # Load shadow analysis if available
    shadow_path = scenario_dir / "shadow_analysis.json"
    if shadow_path.exists():
        shadow = json.loads(shadow_path.read_text(encoding="utf-8"))
        summary["shadow"] = {
            "buildings_with_height_change": shadow.get("buildings_with_height_change", 0),
            "max_shadow_increase_m": shadow.get("max_shadow_increase_m", 0),
        }

    return summary


def compare_two(baseline_dir: Path, scenario_dir: Path) -> dict:
    """Compare two specific scenario/output directories."""
    baseline = load_scenario_summary(baseline_dir)
    scenario = load_scenario_summary(scenario_dir)
    return {
        "comparison_type": "pairwise",
        "baseline": baseline,
        "scenario": scenario,
    }


def compare_all() -> dict:
    """Compare all scenarios found in the scenarios/ directory."""
    scenarios = []
    for d in sorted(SCENARIOS.iterdir()):
        if d.is_dir() and (d / "interventions.json").exists():
            summary = load_scenario_summary(d)
            scenarios.append(summary)

    # Build comparison table
    table = []
    for s in scenarios:
        row = {
            "scenario": s.get("scenario_name", s["name"]),
            "interventions": s.get("total_interventions", 0),
            "intervention_types": s.get("intervention_types", {}),
        }
        if "density" in s:
            row["dwelling_units_added"] = s["density"]["dwelling_units_added"]
            row["fsi_change"] = s["density"]["fsi_change"]
            row["gfa_change_sqm"] = s["density"]["gfa_change_sqm"]
        if "heritage" in s:
            row["heritage_preservation_score"] = s["heritage"]["preservation_score"]
            row["heritage_incompatible"] = s["heritage"]["incompatible"]
            row["heritage_review"] = s["heritage"]["review"]
        if "shadow" in s:
            row["max_shadow_increase_m"] = s["shadow"]["max_shadow_increase_m"]
            row["buildings_with_height_change"] = s["shadow"]["buildings_with_height_change"]
        table.append(row)

    return {
        "comparison_type": "all_scenarios",
        "scenario_count": len(scenarios),
        "scenarios": scenarios,
        "comparison_table": table,
    }


def main():
    parser = argparse.ArgumentParser(description="Compare metrics across planning scenarios")
    parser.add_argument("--baseline", default=None, help="Path to baseline output directory")
    parser.add_argument("--scenario", default=None, help="Path to scenario output directory")
    parser.add_argument("--all", action="store_true", help="Compare all scenarios in scenarios/")
    parser.add_argument("--output", default=None, help="Output path (default: scenarios/comparison.json)")
    args = parser.parse_args()

    if args.all or (not args.baseline and not args.scenario):
        print("Comparing all scenarios ...")
        if not SCENARIOS.is_dir():
            print(f"  ERROR: Scenarios directory not found: {SCENARIOS}")
            print("  Run 'python scripts/planning/generate_scenarios.py' first.")
            return
        try:
            result = compare_all()
        except (json.JSONDecodeError, KeyError) as exc:
            print(f"  ERROR reading scenario files: {exc}")
            return
        out_path = Path(args.output) if args.output else SCENARIOS / "comparison.json"
    elif args.baseline and args.scenario:
        baseline_dir = Path(args.baseline)
        if not baseline_dir.is_absolute():
            baseline_dir = REPO / baseline_dir
        scenario_dir = Path(args.scenario)
        if not scenario_dir.is_absolute():
            scenario_dir = REPO / scenario_dir
        print(f"Comparing {baseline_dir.name} vs {scenario_dir.name} ...")
        result = compare_two(baseline_dir, scenario_dir)
        out_path = Path(args.output) if args.output else scenario_dir / "comparison.json"
    else:
        parser.error("Provide both --baseline and --scenario, or use --all")
        return

    if not out_path.is_absolute():
        out_path = REPO / out_path

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    print(f"\nComparison written to {out_path}")

    # Print summary table
    if result.get("comparison_type") == "all_scenarios":
        table = result.get("comparison_table", [])
        print(f"\n{'Scenario':<35} {'Intv':>5} {'Units+':>7} {'FSI+':>7} {'Heritage%':>10} {'Shadow':>8}")
        print("-" * 75)
        for row in table:
            print(f"{row.get('scenario', '?'):<35} "
                  f"{row.get('interventions', 0):>5} "
                  f"{row.get('dwelling_units_added', 0):>7} "
                  f"{row.get('fsi_change', 0):>7.3f} "
                  f"{row.get('heritage_preservation_score', 0):>9.1f}% "
                  f"{row.get('max_shadow_increase_m', 0):>7.1f}m")


if __name__ == "__main__":
    main()
