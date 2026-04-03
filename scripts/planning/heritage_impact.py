#!/usr/bin/env python3
"""Heritage impact assessment for planning scenarios.

Evaluates how scenario interventions affect heritage-contributing buildings.

Usage:
    python scripts/planning/heritage_impact.py --scenario scenarios/10yr_gentle_density/
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# Intervention types and their heritage compatibility
HERITAGE_COMPATIBILITY = {
    "heritage_restore": "safe",
    "signage_update": "safe",
    "facade_renovation": "caution",
    "green_roof": "caution",
    "add_patio": "caution",
    "convert_ground": "caution",
    "add_floor": "incompatible",
    "demolish": "incompatible",
    "new_build": "new_build",
    "bike_infra": "safe",
    "tree_planting": "safe",
    "pedestrianize": "safe",
}


def assess_heritage_impact(
    baseline_dir: Path,
    scenario_dir: Path,
) -> dict:
    """Assess heritage impact of a scenario.

    Args:
        baseline_dir: Directory with baseline param files.
        scenario_dir: Directory with interventions.json.

    Returns:
        Heritage impact report dict.
    """
    # Load interventions
    intv_path = scenario_dir / "interventions.json"
    intv_data = json.loads(intv_path.read_text(encoding="utf-8"))
    interventions = intv_data.get("interventions", [])

    # Load baseline heritage status
    heritage_status: dict[str, dict] = {}
    for f in sorted(baseline_dir.glob("*.json")):
        if f.name.startswith("_"):
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if data.get("skipped"):
            continue
        addr = data.get("_meta", {}).get("address") or data.get("building_name", f.stem)
        heritage_status[addr] = {
            "contributing": data.get("hcd_data", {}).get("contributing") == "Yes",
            "construction_date": data.get("hcd_data", {}).get("construction_date", ""),
        }

    scores = {"safe": 0, "caution": 0, "incompatible": 0, "new_build": 0}
    details = []

    for intv in interventions:
        addr = intv.get("address", "")
        intv_type = intv.get("type", "")
        compatibility = HERITAGE_COMPATIBILITY.get(intv_type, "caution")

        is_contributing = heritage_status.get(addr, {}).get("contributing", False)

        # New builds don't affect existing heritage
        if intv_type == "new_build":
            scores["new_build"] += 1
            details.append({
                "address": addr,
                "type": intv_type,
                "compatibility": "new_build",
                "contributing": False,
                "risk": "none",
            })
            continue

        # Heritage-contributing buildings get stricter assessment
        if is_contributing and compatibility == "incompatible":
            risk = "high"
        elif is_contributing and compatibility == "caution":
            risk = "medium"
        else:
            risk = "low"

        scores[compatibility] += 1
        details.append({
            "address": addr,
            "type": intv_type,
            "compatibility": compatibility,
            "contributing": is_contributing,
            "risk": risk,
        })

    total_interventions = sum(scores.values())
    safe_and_caution = scores["safe"] + scores["new_build"]
    heritage_score = (
        (safe_and_caution / total_interventions * 100)
        if total_interventions > 0 else 100.0
    )

    return {
        "scenario_id": intv_data.get("scenario_id", scenario_dir.name),
        "total_interventions": total_interventions,
        "scores": scores,
        "heritage_preservation_score": heritage_score,
        "details": details,
    }


def main():
    parser = argparse.ArgumentParser(description="Heritage impact assessment")
    parser.add_argument("--baseline", type=Path, default=REPO_ROOT / "params")
    parser.add_argument("--scenario", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    result = assess_heritage_impact(args.baseline, args.scenario)
    print(f"Heritage impact: score {result['heritage_preservation_score']:.0f}%")
    print(f"  Safe: {result['scores']['safe']}, Caution: {result['scores']['caution']}, "
          f"Incompatible: {result['scores']['incompatible']}, New builds: {result['scores']['new_build']}")

    if args.output:
        args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
