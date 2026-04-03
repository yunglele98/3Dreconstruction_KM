#!/usr/bin/env python3
"""Build web platform data from params and scenarios.

Produces a lightweight JSON dataset for the CesiumJS web viewer.
Each building gets a compact record with position, dimensions, heritage info,
and scenario overlay data.

Usage:
    python scripts/build_web_data.py
    python scripts/build_web_data.py --params params/ --scenarios scenarios/ --output web/public/data/
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PARAMS_DIR = REPO_ROOT / "params"
SCENARIOS_DIR = REPO_ROOT / "scenarios"
OUTPUT_DIR = REPO_ROOT / "web" / "public" / "data"

ORIGIN_X = 312672.94
ORIGIN_Y = 4834994.86


def build_building_record(params: dict) -> dict | None:
    meta = params.get("_meta", {})
    site = params.get("site", {})
    hcd = params.get("hcd_data", {})
    ctx = params.get("context", {})

    address = meta.get("address", "")
    if not address:
        return None

    record = {
        "address": address,
        "lat": site.get("lat"),
        "lon": site.get("lon"),
        "street": site.get("street", ""),
        "street_number": site.get("street_number", ""),
        "floors": params.get("floors", 0),
        "height_m": params.get("total_height_m", 0),
        "width_m": params.get("facade_width_m", 0),
        "depth_m": params.get("facade_depth_m", 0),
        "material": params.get("facade_material", ""),
        "roof_type": params.get("roof_type", ""),
        "condition": params.get("condition", ""),
        "has_storefront": params.get("has_storefront", False),
        "typology": hcd.get("typology", ""),
        "era": hcd.get("construction_date", ""),
        "contributing": (hcd.get("contributing") or "").lower() == "yes",
        "business_name": ctx.get("business_name", ""),
        "facade_hex": params.get("facade_detail", {}).get("brick_colour_hex", ""),
        "trim_hex": params.get("facade_detail", {}).get("trim_colour_hex", ""),
        "photo": (params.get("photo_observations", {}) or {}).get("photo", ""),
    }

    return {k: v for k, v in record.items() if v is not None and v != ""}


def build_scenario_overlay(scenario_dir: Path) -> dict | None:
    intvs_path = scenario_dir / "interventions.json"
    if not intvs_path.exists():
        return None

    data = json.loads(intvs_path.read_text(encoding="utf-8"))
    interventions = data.get("interventions", [])
    if not interventions:
        return None

    return {
        "id": data.get("scenario_id", scenario_dir.name),
        "name": data.get("name", scenario_dir.name),
        "description": data.get("description", ""),
        "interventions": [
            {"address": i.get("address", ""), "type": i.get("type", ""),
             "overrides": i.get("params_override", {})}
            for i in interventions
        ],
        "impact": data.get("impact", {}),
    }


def main():
    parser = argparse.ArgumentParser(description="Build web platform data.")
    parser.add_argument("--params", type=Path, default=PARAMS_DIR)
    parser.add_argument("--scenarios", type=Path, default=SCENARIOS_DIR)
    parser.add_argument("--output", type=Path, default=OUTPUT_DIR)
    args = parser.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)

    buildings = []
    for f in sorted(args.params.glob("*.json")):
        if f.name.startswith("_"):
            continue
        try:
            params = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if params.get("skipped"):
            continue
        record = build_building_record(params)
        if record:
            buildings.append(record)

    (args.output / "buildings.json").write_text(
        json.dumps(buildings, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Buildings: {len(buildings)}")

    scenarios = []
    if args.scenarios.exists():
        for sd in sorted(args.scenarios.iterdir()):
            if not sd.is_dir():
                continue
            overlay = build_scenario_overlay(sd)
            if overlay:
                scenarios.append(overlay)

    (args.output / "scenarios.json").write_text(
        json.dumps(scenarios, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Scenarios: {len(scenarios)}")

    meta = {
        "origin": {"x": ORIGIN_X, "y": ORIGIN_Y, "srid": 2952},
        "building_count": len(buildings),
        "scenario_count": len(scenarios),
        "streets": sorted(set(b.get("street", "") for b in buildings if b.get("street"))),
        "eras": sorted(set(b.get("era", "") for b in buildings if b.get("era"))),
    }
    (args.output / "meta.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    total_kb = sum(p.stat().st_size for p in args.output.glob("*.json")) / 1024
    print(f"Total: {total_kb:.1f} KB -> {args.output}")


if __name__ == "__main__":
    main()
