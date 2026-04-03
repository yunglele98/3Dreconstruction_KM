#!/usr/bin/env python3
"""Stage 8 — EXPORT: Build web platform data bundle.

Aggregates params, scenario data, and spatial data into a JSON bundle
for the web planning platform (CesiumJS + Potree).

Usage:
    python scripts/export/build_web_data.py --params params/ --scenarios scenarios/ --output web/public/data/
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_PARAMS = REPO_ROOT / "params"
DEFAULT_SCENARIOS = REPO_ROOT / "scenarios"
DEFAULT_OUTPUT = REPO_ROOT / "web" / "public" / "data"


def build_building_index(params_dir: Path) -> list[dict]:
    """Build a lightweight building index for the web inspector."""
    buildings = []
    for f in sorted(params_dir.glob("*.json")):
        if f.name.startswith("_"):
            continue
        data = json.loads(f.read_text(encoding="utf-8"))
        if data.get("skipped"):
            continue

        site = data.get("site", {})
        hcd = data.get("hcd_data", {})

        buildings.append({
            "name": data.get("building_name", f.stem.replace("_", " ")),
            "address": data.get("_meta", {}).get("address", ""),
            "street": site.get("street", ""),
            "lat": site.get("lat"),
            "lon": site.get("lon"),
            "floors": data.get("floors", 0),
            "height_m": data.get("total_height_m", 0),
            "facade_material": data.get("facade_material", ""),
            "roof_type": data.get("roof_type", ""),
            "has_storefront": data.get("has_storefront", False),
            "contributing": hcd.get("contributing", ""),
            "construction_date": hcd.get("construction_date", ""),
            "typology": hcd.get("typology", ""),
            "condition": data.get("condition", ""),
        })

    return buildings


def build_scenario_index(scenarios_dir: Path) -> list[dict]:
    """Build a scenario summary index for the web scenario selector."""
    scenarios = []
    if not scenarios_dir.exists():
        return scenarios

    for d in sorted(scenarios_dir.iterdir()):
        if not d.is_dir():
            continue
        intv_path = d / "interventions.json"
        if not intv_path.exists():
            continue

        data = json.loads(intv_path.read_text(encoding="utf-8"))
        scenarios.append({
            "id": data.get("scenario_id", d.name),
            "name": data.get("name", d.name),
            "description": data.get("description", ""),
            "intervention_count": len(data.get("interventions", [])),
        })

    return scenarios


def build_web_data(
    params_dir: Path,
    scenarios_dir: Path,
    output_dir: Path,
    *,
    dry_run: bool = False,
) -> dict:
    """Build the complete web data bundle."""
    buildings = build_building_index(params_dir)
    scenarios = build_scenario_index(scenarios_dir)

    result = {
        "building_count": len(buildings),
        "scenario_count": len(scenarios),
        "output": str(output_dir),
    }

    if dry_run:
        result["status"] = "would_build"
        return result

    output_dir.mkdir(parents=True, exist_ok=True)

    (output_dir / "buildings.json").write_text(
        json.dumps(buildings, indent=2), encoding="utf-8"
    )
    (output_dir / "scenarios.json").write_text(
        json.dumps(scenarios, indent=2), encoding="utf-8"
    )

    # Copy scenario interventions for the web platform
    scen_dir = output_dir / "scenarios"
    scen_dir.mkdir(exist_ok=True)
    for s in scenarios:
        src = scenarios_dir / s["id"] if (scenarios_dir / s["id"]).exists() else None
        if not src:
            # Try matching directory name
            for d in scenarios_dir.iterdir():
                if d.is_dir() and s["id"] in d.name:
                    src = d
                    break
        if src:
            intv = src / "interventions.json"
            if intv.exists():
                dest = scen_dir / f"{s['id']}.json"
                dest.write_text(intv.read_text(encoding="utf-8"), encoding="utf-8")

    result["status"] = "built"
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Build web platform data")
    parser.add_argument("--params", type=Path, default=DEFAULT_PARAMS)
    parser.add_argument("--scenarios", type=Path, default=DEFAULT_SCENARIOS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    result = build_web_data(
        args.params, args.scenarios, args.output, dry_run=args.dry_run
    )

    prefix = "[DRY RUN] " if args.dry_run else ""
    print(f"{prefix}Web data: {result['building_count']} buildings, "
          f"{result['scenario_count']} scenarios → {result['output']}")


if __name__ == "__main__":
    main()
