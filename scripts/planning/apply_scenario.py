#!/usr/bin/env python3
"""Apply scenario JSON overlays onto baseline params.

Reads interventions.json from a scenario directory and applies each
intervention to the corresponding building params, outputting modified
params to a separate directory (never modifying originals).

Usage:
    python scripts/planning/apply_scenario.py --baseline params/ --scenario scenarios/10yr_gentle_density/ --output outputs/scenarios/gentle_density/
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# Fields that interventions must never modify
PROTECTED_FIELDS = {"site", "city_data", "hcd_data"}


def apply_intervention(params: dict, intervention: dict) -> dict:
    """Apply a single intervention to a copy of building params.

    Args:
        params: Original building params dict.
        intervention: Intervention dict with type and params_override.

    Returns:
        Modified params dict (deep copy, original untouched).
    """
    result = copy.deepcopy(params)
    intv_type = intervention.get("type", "")
    override = intervention.get("params_override", {})
    scenario_id = intervention.get("scenario_id", "")

    # Track provenance
    if "_meta" not in result:
        result["_meta"] = {}
    if "scenarios_applied" not in result.get("_meta", {}):
        result["_meta"]["scenarios_applied"] = []
    result["_meta"]["scenarios_applied"].append({
        "scenario_id": scenario_id,
        "type": intv_type,
        "applied_at": datetime.utcnow().isoformat() + "Z",
    })

    if intv_type == "demolish":
        result["skipped"] = True
        result["skip_reason"] = f"Demolished in scenario {scenario_id}"
        return result

    if intv_type == "add_floor":
        new_floors = override.get("floors", result.get("floors", 1) + 1)
        old_floors = result.get("floors", 1)
        floor_heights = list(result.get("floor_heights_m", [3.0] * old_floors))
        windows = list(result.get("windows_per_floor", [3] * old_floors))

        # Add floors as needed
        while len(floor_heights) < new_floors:
            floor_heights.append(floor_heights[-1] if floor_heights else 3.0)
        while len(windows) < new_floors:
            windows.append(windows[-1] if windows else 3)

        result["floors"] = new_floors
        result["floor_heights_m"] = floor_heights[:new_floors]
        result["windows_per_floor"] = windows[:new_floors]
        result["total_height_m"] = sum(result["floor_heights_m"])

    elif intv_type == "green_roof":
        if "roof_detail" not in result:
            result["roof_detail"] = {}
        result["roof_detail"]["green_roof"] = True
        for k, v in override.items():
            result["roof_detail"][k] = v

    elif intv_type == "convert_ground":
        for k, v in override.items():
            if k not in PROTECTED_FIELDS:
                result[k] = v
        if "context" not in result:
            result["context"] = {}
        result["context"]["general_use"] = "commercial"

    elif intv_type == "facade_renovation":
        for k, v in override.items():
            if k not in PROTECTED_FIELDS:
                result[k] = v

    elif intv_type == "heritage_restore":
        for k, v in override.items():
            if k not in PROTECTED_FIELDS:
                result[k] = v

    elif intv_type == "new_build":
        # new_build is handled at scenario level, not here
        pass

    else:
        # Generic override
        for k, v in override.items():
            if k not in PROTECTED_FIELDS:
                result[k] = v

    return result


def apply_scenario(
    baseline_dir: Path,
    scenario_dir: Path,
    output_dir: Path,
) -> dict:
    """Apply all interventions in a scenario to baseline params.

    Args:
        baseline_dir: Directory with baseline param JSON files.
        scenario_dir: Directory with interventions.json.
        output_dir: Directory for modified param files.

    Returns:
        Stats dict with counts of modifications, new_builds, etc.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    intv_path = scenario_dir / "interventions.json"
    intv_data = json.loads(intv_path.read_text(encoding="utf-8"))
    scenario_id = intv_data.get("scenario_id", scenario_dir.name)
    interventions = intv_data.get("interventions", [])

    # Index interventions by address
    intv_by_address: dict[str, dict] = {}
    new_builds: list[dict] = []
    for intv in interventions:
        intv["scenario_id"] = scenario_id
        if intv.get("type") == "new_build":
            new_builds.append(intv)
        else:
            addr = intv.get("address", "")
            intv_by_address[addr] = intv

    stats = {"modified": 0, "new_builds": 0, "copied": 0, "demolished": 0}

    # Process existing buildings
    for param_file in sorted(baseline_dir.glob("*.json")):
        if param_file.name.startswith("_"):
            continue

        data = json.loads(param_file.read_text(encoding="utf-8"))
        address = data.get("_meta", {}).get("address") or data.get("building_name", "")

        if address in intv_by_address:
            result = apply_intervention(data, intv_by_address[address])
            if result.get("skipped") and "Demolished" in result.get("skip_reason", ""):
                stats["demolished"] += 1
            else:
                stats["modified"] += 1
        else:
            result = copy.deepcopy(data)
            stats["copied"] += 1

        out_path = output_dir / param_file.name
        out_path.write_text(
            json.dumps(result, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    # Handle new builds
    for intv in new_builds:
        addr = intv.get("address", "")
        new_params = intv.get("params", {})
        new_params["_meta"] = new_params.get("_meta", {})
        new_params["_meta"]["address"] = addr
        new_params["_meta"]["scenarios_applied"] = [{
            "scenario_id": scenario_id,
            "type": "new_build",
            "applied_at": datetime.utcnow().isoformat() + "Z",
        }]

        stem = addr.replace(" ", "_").replace(",", "")
        out_path = output_dir / f"{stem}.json"
        out_path.write_text(
            json.dumps(new_params, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        stats["new_builds"] += 1

    return stats


def main():
    parser = argparse.ArgumentParser(description="Apply scenario overlay to baseline params")
    parser.add_argument("--baseline", type=Path, default=REPO_ROOT / "params")
    parser.add_argument("--scenario", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    if args.output is None:
        args.output = REPO_ROOT / "outputs" / "scenarios" / args.scenario.name

    stats = apply_scenario(args.baseline, args.scenario, args.output)
    print(f"Scenario applied: {stats}")


if __name__ == "__main__":
    main()
