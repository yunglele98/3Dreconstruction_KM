#!/usr/bin/env python3
"""Stage 11 — SCENARIOS: Assess heritage impact of scenario interventions.

Classifies each intervention as safe, cautious, or incompatible based on
the building's heritage status and intervention type. Computes a heritage
preservation score.

Usage:
    python scripts/planning/heritage_impact.py --scenario scenarios/10yr_gentle_density/
    python scripts/planning/heritage_impact.py --baseline params/ --scenario scenarios/10yr_gentle_density/
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# Intervention compatibility with contributing heritage buildings
HERITAGE_SAFE = {
    "heritage_restore", "signage_update", "facade_renovation",
}
HERITAGE_CAUTIOUS = {
    "green_roof", "convert_ground", "add_patio", "bike_infra",
    "tree_planting",
}
HERITAGE_INCOMPATIBLE = {
    "demolish", "add_floor", "new_build",
}


def classify_intervention(
    intervention: dict, building: dict | None
) -> str:
    """Classify an intervention's heritage compatibility.

    Returns 'safe', 'cautious', 'incompatible', or 'new_build'.
    """
    intv_type = intervention.get("type", "")

    if intv_type == "new_build":
        return "new_build"

    if building is None:
        return "new_build"

    contributing = (
        building.get("hcd_data", {}).get("contributing", "").lower() == "yes"
    )

    if not contributing:
        return "safe"

    if intv_type in HERITAGE_SAFE:
        return "safe"
    elif intv_type in HERITAGE_CAUTIOUS:
        return "cautious"
    elif intv_type in HERITAGE_INCOMPATIBLE:
        return "incompatible"
    return "cautious"


def assess_heritage_impact(
    baseline_dir: Path,
    scenario_dir: Path,
) -> dict:
    """Assess heritage impact of a scenario's interventions.

    Returns scores dict and heritage preservation score (0-100).
    """
    # Load baseline buildings
    buildings: dict[str, dict] = {}
    for f in sorted(baseline_dir.glob("*.json")):
        if f.name.startswith("_"):
            continue
        data = json.loads(f.read_text(encoding="utf-8"))
        addr = data.get("_meta", {}).get("address", f.stem.replace("_", " "))
        buildings[addr] = data

    # Load interventions
    intv_path = scenario_dir / "interventions.json"
    scenario_data = json.loads(intv_path.read_text(encoding="utf-8"))
    interventions = scenario_data.get("interventions", [])

    scores = {"safe": 0, "cautious": 0, "incompatible": 0, "new_build": 0}
    details = []

    for intv in interventions:
        addr = intv.get("address", "")
        building = buildings.get(addr)
        classification = classify_intervention(intv, building)
        scores[classification] += 1

        details.append({
            "address": addr,
            "type": intv.get("type", ""),
            "classification": classification,
            "contributing": (
                building.get("hcd_data", {}).get("contributing", "")
                if building else "N/A"
            ),
        })

    # Heritage preservation score: 100 = all safe, 0 = all incompatible
    total = scores["safe"] + scores["cautious"] + scores["incompatible"]
    if total > 0:
        preservation_score = round(
            (scores["safe"] * 100 + scores["cautious"] * 50) / total, 1
        )
    else:
        preservation_score = 100.0

    return {
        "scenario_id": scenario_data.get("scenario_id", "unknown"),
        "scores": scores,
        "heritage_preservation_score": preservation_score,
        "details": details,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Assess heritage impact")
    parser.add_argument("--baseline", type=Path, default=REPO_ROOT / "params")
    parser.add_argument("--scenario", required=True, type=Path)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    result = assess_heritage_impact(args.baseline, args.scenario)

    if args.output:
        args.output.write_text(
            json.dumps(result, indent=2), encoding="utf-8"
        )

    print(f"Heritage impact: score={result['heritage_preservation_score']}%")
    print(f"  Safe: {result['scores']['safe']}, "
          f"Cautious: {result['scores']['cautious']}, "
          f"Incompatible: {result['scores']['incompatible']}, "
          f"New builds: {result['scores']['new_build']}")


if __name__ == "__main__":
    main()
