#!/usr/bin/env python3
"""Apply scenario interventions to baseline params.

Reads baseline params and interventions.json, deep-copies matching param files,
applies params_override, and writes modified params to the scenario directory.
Does NOT mutate originals.

Usage:
    python scripts/planning/apply_scenario.py --baseline params/ --scenario scenarios/10yr_gentle_density/
"""

import argparse
import copy
import json
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent


def load_params(params_dir: Path) -> dict:
    """Load all param files into a dict keyed by building_name (address)."""
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
            buildings[name] = (f, data)
    return buildings


def load_interventions(scenario_dir: Path) -> dict:
    """Load interventions.json from scenario directory."""
    path = scenario_dir / "interventions.json"
    return json.loads(path.read_text(encoding="utf-8"))


def apply_override(params: dict, override: dict) -> dict:
    """Deep-copy params and apply override dict on top."""
    result = copy.deepcopy(params)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key].update(value)
        else:
            result[key] = value
    return result


def main():
    parser = argparse.ArgumentParser(description="Apply scenario interventions to baseline params")
    parser.add_argument("--baseline", required=True, help="Path to baseline params directory")
    parser.add_argument("--scenario", required=True, help="Path to scenario directory")
    args = parser.parse_args()

    baseline_dir = Path(args.baseline)
    if not baseline_dir.is_absolute():
        baseline_dir = REPO / baseline_dir
    scenario_dir = Path(args.scenario)
    if not scenario_dir.is_absolute():
        scenario_dir = REPO / scenario_dir

    print(f"Loading baseline params from {baseline_dir} ...")
    buildings = load_params(baseline_dir)
    print(f"  {len(buildings)} buildings loaded")

    scenario = load_interventions(scenario_dir)
    interventions = scenario.get("interventions", [])
    print(f"  {len(interventions)} interventions in {scenario.get('scenario_id', 'unknown')}")

    output_dir = scenario_dir / "modified_params"
    output_dir.mkdir(parents=True, exist_ok=True)

    applied = 0
    not_found = []
    new_builds = 0

    for intervention in interventions:
        address = intervention.get("address", "")
        override = intervention.get("params_override", {})
        itype = intervention.get("type", "")

        if address in buildings:
            _orig_path, orig_data = buildings[address]
            modified = apply_override(orig_data, override)
            modified.setdefault("_meta", {})["scenario_intervention"] = {
                "type": itype,
                "scenario_id": scenario.get("scenario_id", ""),
            }
            filename = address.replace(" ", "_") + ".json"
            out_path = output_dir / filename
            out_path.write_text(
                json.dumps(modified, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            applied += 1
        elif itype == "new_build":
            # New builds have no baseline -- create from override
            new_params = copy.deepcopy(override)
            new_params["building_name"] = address
            new_params.setdefault("_meta", {})["scenario_intervention"] = {
                "type": itype,
                "scenario_id": scenario.get("scenario_id", ""),
            }
            filename = address.replace(" ", "_") + ".json"
            out_path = output_dir / filename
            out_path.write_text(
                json.dumps(new_params, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            new_builds += 1
        else:
            not_found.append(address)

    print(f"\nApplied {applied} interventions, {new_builds} new builds")
    if not_found:
        print(f"{len(not_found)} addresses not found:")
        for addr in not_found:
            print(f"  - {addr}")
    print(f"Modified params written to {output_dir}")


if __name__ == "__main__":
    main()
