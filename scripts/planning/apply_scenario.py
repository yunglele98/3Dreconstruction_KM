#!/usr/bin/env python3
"""Stage 11 — SCENARIOS: Apply a scenario overlay to baseline params.

Reads interventions.json from a scenario directory, applies each
intervention to the corresponding building params, and writes modified
params to an output directory (originals are never modified).

Usage:
    python scripts/planning/apply_scenario.py --baseline params/ --scenario scenarios/10yr_gentle_density/
    python scripts/planning/apply_scenario.py --baseline params/ --scenario scenarios/10yr_gentle_density/ --output outputs/scenarios/gentle_density/
"""

import argparse
import copy
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# Fields that interventions must never override
PROTECTED_FIELDS = {"site", "city_data", "hcd_data"}

# Intervention types that are compatible with heritage buildings
HERITAGE_SAFE_TYPES = {
    "heritage_restore", "facade_renovation", "signage_update",
}

# Intervention types that are incompatible with contributing heritage buildings
HERITAGE_INCOMPATIBLE_TYPES = {"demolish", "add_floor"}


def apply_intervention(params: dict, intervention: dict) -> dict:
    """Apply a single intervention to a building's params (returns a copy)."""
    result = copy.deepcopy(params)
    intv_type = intervention.get("type", "")
    override = intervention.get("params_override", {})
    scenario_id = intervention.get("scenario_id", "")

    # Track provenance
    meta = result.setdefault("_meta", {})
    applied = meta.setdefault("scenarios_applied", [])
    applied.append({
        "scenario_id": scenario_id,
        "type": intv_type,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })

    if intv_type == "demolish":
        result["skipped"] = True
        result["skip_reason"] = "demolished_in_scenario"
        return result

    if intv_type == "add_floor":
        new_floors = override.get("floors", result.get("floors", 2) + 1)
        old_floors = result.get("floors", 2)
        floor_heights = list(result.get("floor_heights_m", [3.0] * old_floors))
        windows = list(result.get("windows_per_floor", [3] * old_floors))

        # Extend arrays if adding floors
        while len(floor_heights) < new_floors:
            floor_heights.append(floor_heights[-1] if floor_heights else 3.0)
        while len(windows) < new_floors:
            windows.append(windows[-1] if windows else 3)

        result["floors"] = new_floors
        result["floor_heights_m"] = floor_heights[:new_floors]
        result["windows_per_floor"] = windows[:new_floors]
        result["total_height_m"] = sum(result["floor_heights_m"])

    elif intv_type == "green_roof":
        roof_detail = result.setdefault("roof_detail", {})
        roof_detail["green_roof"] = True
        for k, v in override.items():
            roof_detail[k] = v

    elif intv_type == "convert_ground":
        for k, v in override.items():
            if k not in PROTECTED_FIELDS:
                result[k] = v
        ctx = result.setdefault("context", {})
        ctx["general_use"] = "commercial"

    else:
        # Generic override (facade_renovation, signage_update, etc.)
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

    Returns stats dict with counts.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    interventions_path = scenario_dir / "interventions.json"
    scenario_data = json.loads(interventions_path.read_text(encoding="utf-8"))
    scenario_id = scenario_data.get("scenario_id", "unknown")
    interventions = scenario_data.get("interventions", [])

    # Index interventions by address (copy dicts to avoid mutating originals)
    intv_by_addr: dict[str, list[dict]] = {}
    for intv in interventions:
        addr = intv.get("address", "")
        tagged = {**intv, "scenario_id": scenario_id}
        intv_by_addr.setdefault(addr, []).append(tagged)

    stats = {"modified": 0, "new_builds": 0, "unchanged": 0, "total": 0}
    matched_addresses: set[str] = set()

    # Copy and modify existing buildings
    for param_file in sorted(baseline_dir.glob("*.json")):
        if param_file.name.startswith("_"):
            continue

        data = json.loads(param_file.read_text(encoding="utf-8"))
        address = data.get("_meta", {}).get("address", param_file.stem.replace("_", " "))

        if address in intv_by_addr:
            matched_addresses.add(address)
            for intv in intv_by_addr[address]:
                data = apply_intervention(data, intv)
            stats["modified"] += 1
        else:
            stats["unchanged"] += 1

        (output_dir / param_file.name).write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        stats["total"] += 1

    # Handle new builds (only addresses NOT already in baseline)
    for addr, intvs in intv_by_addr.items():
        if addr in matched_addresses:
            continue
        for intv in intvs:
            if intv.get("type") == "new_build":
                new_params = copy.deepcopy(intv.get("params", {}))
                new_params["_meta"] = {
                    "address": addr,
                    "source": "scenario_new_build",
                    "scenarios_applied": [{
                        "scenario_id": scenario_id,
                        "type": "new_build",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }],
                }
                safe_name = addr.replace(" ", "_")
                (output_dir / f"{safe_name}.json").write_text(
                    json.dumps(new_params, indent=2, ensure_ascii=False), encoding="utf-8"
                )
                stats["new_builds"] += 1
                stats["total"] += 1

    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply scenario overlay to baseline params")
    parser.add_argument("--baseline", type=Path, default=REPO_ROOT / "params")
    parser.add_argument("--scenario", required=True, type=Path)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    if args.output is None:
        scenario_name = args.scenario.name
        args.output = REPO_ROOT / "outputs" / "scenarios" / scenario_name

    stats = apply_scenario(args.baseline, args.scenario, args.output)
    print(f"Applied scenario: {stats['modified']} modified, "
          f"{stats['new_builds']} new builds, {stats['unchanged']} unchanged")


if __name__ == "__main__":
    main()
