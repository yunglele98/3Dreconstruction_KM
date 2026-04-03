#!/usr/bin/env python3
"""Apply a scenario overlay to baseline building params.

Reads a scenario's interventions.json and produces modified param files
in a scenario-specific output directory. The baseline params are never
modified -- scenario params are copies with interventions applied.

Usage:
    python scripts/planning/apply_scenario.py --baseline params/ --scenario scenarios/10yr_gentle_density/
    python scripts/planning/apply_scenario.py --scenario scenarios/10yr_heritage_first/ --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PARAMS_DIR = REPO_ROOT / "params"


def load_interventions(scenario_dir: Path) -> list:
    """Load interventions.json from a scenario directory."""
    ipath = scenario_dir / "interventions.json"
    if not ipath.exists():
        print(f"No interventions.json in {scenario_dir}")
        return []
    data = json.loads(ipath.read_text(encoding="utf-8"))
    return data.get("interventions", [])


def apply_intervention(params: dict, intervention: dict) -> dict:
    """Apply a single intervention to a param dict.

    Intervention types:
        add_floor     -- increase floors, adjust height
        new_build     -- create entirely new param from intervention.params
        convert_ground -- change ground floor use
        facade_renovation -- update facade material/colour
        demolish      -- mark as demolished
        green_roof    -- add green roof overlay
        heritage_restore -- revert to original heritage features
        signage_update -- update business name/signage
        tree_planting  -- add tree data (no param change, scene-level)
        pedestrianize  -- mark street as pedestrian (scene-level)
    """
    itype = intervention.get("type", "")
    overrides = intervention.get("params_override", {})

    if itype == "add_floor":
        current_floors = params.get("floors", 2)
        new_floors = overrides.get("floors", current_floors + 1)
        params["floors"] = new_floors
        # Adjust floor heights
        fh = params.get("floor_heights_m", [3.0] * current_floors)
        while len(fh) < new_floors:
            fh.append(fh[-1] if fh else 3.0)
        params["floor_heights_m"] = fh[:new_floors]
        params["total_height_m"] = sum(params["floor_heights_m"])
        # Update windows_per_floor
        wpf = params.get("windows_per_floor", [2] * current_floors)
        while len(wpf) < new_floors:
            wpf.append(wpf[-1] if wpf else 2)
        params["windows_per_floor"] = wpf[:new_floors]

    elif itype == "new_build":
        # Replace entirely with intervention params
        new_params = intervention.get("params", {})
        if new_params:
            params = new_params

    elif itype == "demolish":
        params["skipped"] = True
        params["skip_reason"] = f"demolished_by_scenario_{intervention.get('scenario_id', 'unknown')}"

    elif itype == "facade_renovation":
        for key, val in overrides.items():
            params[key] = val

    elif itype == "green_roof":
        rf = params.setdefault("roof_detail", {})
        rf["green_roof"] = True
        rf["green_roof_type"] = overrides.get("green_roof_type", "extensive")
        for key, val in overrides.items():
            params[key] = val

    elif itype == "convert_ground":
        params["has_storefront"] = overrides.get("has_storefront", True)
        ctx = params.setdefault("context", {})
        ctx["general_use"] = overrides.get("general_use", "commercial")
        for key, val in overrides.items():
            if key not in ("has_storefront", "general_use"):
                params[key] = val

    elif itype == "heritage_restore":
        # Apply heritage-guided overrides
        for key, val in overrides.items():
            params[key] = val
        params.setdefault("_meta", {})["heritage_restored"] = True

    elif itype == "signage_update":
        ctx = params.setdefault("context", {})
        if "business_name" in overrides:
            ctx["business_name"] = overrides["business_name"]
        for key, val in overrides.items():
            if key != "business_name":
                params[key] = val

    else:
        # Generic override
        for key, val in overrides.items():
            params[key] = val

    # Track scenario provenance
    meta = params.setdefault("_meta", {})
    scenarios = meta.setdefault("scenarios_applied", [])
    scenarios.append({
        "type": itype,
        "scenario_id": intervention.get("scenario_id", ""),
    })

    return params


def apply_scenario(
    baseline_dir: Path,
    scenario_dir: Path,
    output_dir: Path | None = None,
    dry_run: bool = False,
) -> dict:
    """Apply all interventions in a scenario."""
    interventions = load_interventions(scenario_dir)
    if not interventions:
        return {"applied": 0, "skipped": 0}

    if output_dir is None:
        output_dir = scenario_dir / "params"
    if not dry_run:
        output_dir.mkdir(parents=True, exist_ok=True)

    # Index interventions by address
    by_address = {}
    for intv in interventions:
        addr = intv.get("address", "")
        if addr not in by_address:
            by_address[addr] = []
        by_address[addr].append(intv)

    stats = {"applied": 0, "new_builds": 0, "skipped": 0, "copied": 0}

    # Process existing buildings
    for f in sorted(baseline_dir.glob("*.json")):
        if f.name.startswith("_"):
            if not dry_run:
                shutil.copy2(f, output_dir / f.name)
            continue

        try:
            params = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue

        address = params.get("_meta", {}).get("address", f.stem.replace("_", " "))
        addr_interventions = by_address.pop(address, [])

        if addr_interventions:
            for intv in addr_interventions:
                params = apply_intervention(params, intv)
                stats["applied"] += 1
        else:
            stats["copied"] += 1

        if not dry_run:
            content = json.dumps(params, indent=2, ensure_ascii=False) + "\n"
            (output_dir / f.name).write_text(content, encoding="utf-8")

    # Handle new_build interventions for addresses not in baseline
    for addr, intvs in by_address.items():
        for intv in intvs:
            if intv.get("type") == "new_build":
                new_params = apply_intervention({}, intv)
                stem = addr.replace(" ", "_").replace(",", "")
                if not dry_run:
                    content = json.dumps(new_params, indent=2, ensure_ascii=False) + "\n"
                    (output_dir / f"{stem}.json").write_text(content, encoding="utf-8")
                stats["new_builds"] += 1

    return stats


def main():
    parser = argparse.ArgumentParser(description="Apply scenario overlay to baseline params.")
    parser.add_argument("--baseline", type=Path, default=PARAMS_DIR)
    parser.add_argument("--scenario", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    scenario_name = args.scenario.name
    print(f"Applying scenario: {scenario_name}")
    print(f"Baseline: {args.baseline}")

    stats = apply_scenario(args.baseline, args.scenario, args.output, args.dry_run)

    mode = "DRY-RUN" if args.dry_run else "APPLIED"
    print(f"\n[{mode}] {stats['applied']} interventions, "
          f"{stats['new_builds']} new builds, "
          f"{stats['copied']} copied unchanged")


if __name__ == "__main__":
    main()
