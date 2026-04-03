#!/usr/bin/env python3
"""Assess heritage impact of scenario interventions.

Reads interventions.json and baseline params, scores each intervention:
  - high: intervention on a contributing building
  - medium: intervention adjacent to a contributing building
  - low: intervention on a non-contributing building with no adjacent contributing
  - safe: heritage-compatible intervention (restore, facade_renovation)

Writes heritage_impact.json to the scenario directory.

Usage:
    python scripts/planning/heritage_impact.py --scenario scenarios/10yr_gentle_density/
"""

import argparse
import json
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
PARAMS = REPO / "params"

# Intervention types that are heritage-compatible by nature
SAFE_TYPES = {"heritage_restore", "facade_renovation", "signage_update"}

# Intervention types that are potentially incompatible with heritage
RISKY_TYPES = {"add_floor", "new_build", "demolish", "convert_ground"}


def load_params(params_dir: Path) -> dict:
    """Load all param files keyed by building_name."""
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


def is_contributing(params: dict) -> bool:
    return (params.get("hcd_data") or {}).get("contributing") == "Yes"


def get_street_neighbours(address: str, buildings: dict) -> list:
    """Get buildings on the same street with adjacent street numbers."""
    params = buildings.get(address)
    if not params:
        return []
    street = (params.get("site") or {}).get("street", "")
    number = (params.get("site") or {}).get("street_number")
    if not street or not number:
        return []

    try:
        num = int(number)
    except (ValueError, TypeError):
        return []

    neighbours = []
    for addr, b in buildings.items():
        if addr == address:
            continue
        b_street = (b.get("site") or {}).get("street", "")
        b_number = (b.get("site") or {}).get("street_number")
        if b_street != street or not b_number:
            continue
        try:
            b_num = int(b_number)
        except (ValueError, TypeError):
            continue
        # Adjacent = within 4 street numbers (typical lot spacing)
        if abs(b_num - num) <= 4:
            neighbours.append(addr)

    return neighbours


def assess_impact(intervention: dict, buildings: dict) -> dict:
    """Assess heritage impact of a single intervention."""
    address = intervention.get("address", "")
    itype = intervention.get("type", "")

    params = buildings.get(address, {})
    contributing = is_contributing(params)
    era = (params.get("hcd_data") or {}).get("construction_date", "")
    typology = (params.get("hcd_data") or {}).get("typology", "")
    heritage_status = "contributing" if contributing else "non-contributing"

    # Heritage-compatible interventions are always safe
    if itype in SAFE_TYPES:
        if contributing:
            note = f"Heritage-compatible intervention on {era} {typology}"
        else:
            note = f"Heritage-compatible intervention on non-contributing building"
        return {
            "address": address,
            "type": itype,
            "heritage_status": heritage_status,
            "era": era,
            "typology": typology,
            "impact": "safe",
            "severity": "ok",
            "note": note,
        }

    # Risky interventions on contributing buildings
    if contributing:
        note = f"Intervention on contributing {era} {typology} -- requires HCD review"
        return {
            "address": address,
            "type": itype,
            "heritage_status": heritage_status,
            "era": era,
            "typology": typology,
            "impact": "incompatible",
            "severity": "high",
            "note": note,
        }

    # Check adjacency to contributing buildings
    neighbours = get_street_neighbours(address, buildings)
    adjacent_contributing = [n for n in neighbours if is_contributing(buildings.get(n, {}))]

    if adjacent_contributing:
        note = (f"Adjacent to {len(adjacent_contributing)} contributing building(s): "
                f"{', '.join(adjacent_contributing[:3])}")
        return {
            "address": address,
            "type": itype,
            "heritage_status": heritage_status,
            "era": era,
            "typology": typology,
            "impact": "review",
            "severity": "medium",
            "note": note,
        }

    # Non-contributing, no adjacent heritage
    note = "Non-contributing building, no adjacent heritage properties"
    return {
        "address": address,
        "type": itype,
        "heritage_status": heritage_status,
        "era": era,
        "typology": typology,
        "impact": "safe",
        "severity": "ok",
        "note": note,
    }


def main():
    parser = argparse.ArgumentParser(description="Assess heritage impact of scenario interventions")
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

    findings = []
    for intervention in interventions:
        finding = assess_impact(intervention, buildings)
        findings.append(finding)

    scores = Counter(f["impact"] for f in findings)
    heritage_count = scores.get("safe", 0) + scores.get("review", 0)
    total = len(findings) or 1
    preservation_score = round((heritage_count / total) * 100, 1)

    result = {
        "scenario_id": scenario_data.get("scenario_id", ""),
        "total_interventions": len(findings),
        "scores": {
            "safe": scores.get("safe", 0),
            "review": scores.get("review", 0),
            "incompatible": scores.get("incompatible", 0),
            "non_contributing": sum(1 for f in findings if f["heritage_status"] == "non-contributing"),
            "new_build": sum(1 for f in findings if f["type"] == "new_build"),
        },
        "heritage_preservation_score": preservation_score,
        "findings": findings,
    }

    out_path = scenario_dir / "heritage_impact.json"
    out_path.write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"\nHeritage impact written to {out_path}")
    print(f"  Safe: {scores.get('safe', 0)}, Review: {scores.get('review', 0)}, "
          f"Incompatible: {scores.get('incompatible', 0)}")
    print(f"  Heritage preservation score: {preservation_score}%")


if __name__ == "__main__":
    main()
