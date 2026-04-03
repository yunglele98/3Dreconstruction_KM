#!/usr/bin/env python3
"""Build web platform data files from params and scenarios.

Generates app_data.json (building list + stats) and scenario JSONs
for the web planning platform.

Usage:
    python scripts/export/build_web_data.py --params params/ --scenarios scenarios/ --output web/public/data/
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import Counter, defaultdict
from pathlib import Path

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def load_buildings(params_dir: Path) -> list[dict]:
    """Load all active building params and extract web-relevant fields."""
    buildings = []
    for f in sorted(params_dir.glob("*.json")):
        if f.name.startswith("_"):
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if data.get("skipped"):
            continue

        site = data.get("site", {})
        hcd = data.get("hcd_data", {})
        facade = data.get("facade_detail", {})
        palette = data.get("colour_palette", {})
        meta = data.get("_meta", {})

        buildings.append({
            "id": f.stem,
            "address": meta.get("address") or data.get("building_name", f.stem.replace("_", " ")),
            "street": site.get("street", ""),
            "lon": site.get("lon"),
            "lat": site.get("lat"),
            "floors": data.get("floors", 2),
            "total_height_m": data.get("total_height_m"),
            "height": data.get("total_height_m") or data.get("city_data", {}).get("height_max_m") or 7.0,
            "facade_width_m": data.get("facade_width_m"),
            "facade_depth_m": data.get("facade_depth_m"),
            "facade_material": data.get("facade_material", "brick"),
            "facade_hex": facade.get("brick_colour_hex") or palette.get("facade"),
            "trim_hex": facade.get("trim_colour_hex") or palette.get("trim"),
            "roof_hex": palette.get("roof"),
            "roof_type": data.get("roof_type", "flat"),
            "condition": data.get("condition", "fair"),
            "has_storefront": data.get("has_storefront", False),
            "party_wall_left": data.get("party_wall_left", False),
            "party_wall_right": data.get("party_wall_right", False),
            "contributing": hcd.get("contributing", "No"),
            "era": hcd.get("construction_date", ""),
            "typology": hcd.get("typology", ""),
            "architectural_style": hcd.get("architectural_style", ""),
            "has_render": False,  # Updated below
            "has_photo": bool(data.get("photo_observations", {}).get("photo")),
            "photo_path": data.get("photo_observations", {}).get("photo", ""),
            "gap_score": 0,
            "decorative": list(data.get("decorative_elements", {}).keys()),
        })

    return buildings


def compute_stats(buildings: list[dict]) -> dict:
    """Compute aggregate statistics for the dashboard."""
    streets = Counter(b["street"] for b in buildings if b["street"])
    eras = Counter(b["era"] for b in buildings if b["era"])
    materials = Counter(b["facade_material"] for b in buildings if b["facade_material"])
    conditions = Counter(b["condition"] for b in buildings if b["condition"])
    roof_types = Counter(b["roof_type"] for b in buildings if b["roof_type"])

    contributing = sum(1 for b in buildings if b["contributing"] == "Yes")
    with_photos = sum(1 for b in buildings if b["has_photo"])
    with_renders = sum(1 for b in buildings if b["has_render"])
    with_storefront = sum(1 for b in buildings if b["has_storefront"])

    return {
        "total_buildings": len(buildings),
        "contributing": contributing,
        "with_photos": with_photos,
        "with_renders": with_renders,
        "with_storefront": with_storefront,
        "streets": dict(streets),
        "eras": dict(eras),
        "materials": dict(materials),
        "conditions": dict(conditions),
        "roof_types": dict(roof_types),
    }


def check_renders(buildings: list[dict], renders_dir: Path):
    """Mark buildings that have render images."""
    for b in buildings:
        for ext in [".png", ".jpg"]:
            if (renders_dir / f"{b['id']}{ext}").exists():
                b["has_render"] = True
                break


def load_scenarios(scenarios_dir: Path) -> dict[str, dict]:
    """Load scenario intervention files."""
    scenarios = {}
    if not scenarios_dir.exists():
        return scenarios

    for scenario_dir in sorted(scenarios_dir.iterdir()):
        if not scenario_dir.is_dir():
            continue
        intv_path = scenario_dir / "interventions.json"
        if intv_path.exists():
            try:
                data = json.loads(intv_path.read_text(encoding="utf-8"))
                scenarios[scenario_dir.name] = data
            except (json.JSONDecodeError, OSError):
                pass

    return scenarios


def build_web_data(
    params_dir: Path,
    scenarios_dir: Path,
    output_dir: Path,
    renders_dir: Path | None = None,
) -> dict:
    """Build all web platform data files.

    Args:
        params_dir: Building params directory.
        scenarios_dir: Scenarios directory.
        output_dir: Output directory for web data.
        renders_dir: Optional renders directory to check for render images.

    Returns:
        Stats dict.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    buildings = load_buildings(params_dir)

    if renders_dir and renders_dir.exists():
        check_renders(buildings, renders_dir)

    stats = compute_stats(buildings)

    # Write app_data.json
    app_data = {
        "generated_at": __import__("datetime").datetime.utcnow().isoformat() + "Z",
        "buildings": buildings,
        "stats": stats,
    }
    app_data_path = output_dir / "app_data.json"
    app_data_path.write_text(
        json.dumps(app_data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    # Write scenario files
    scenarios = load_scenarios(scenarios_dir)
    scenario_dir = output_dir / "scenarios"
    scenario_dir.mkdir(exist_ok=True)
    for name, data in scenarios.items():
        out_path = scenario_dir / f"{name}.json"
        out_path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    return {
        "buildings": len(buildings),
        "scenarios": len(scenarios),
        "app_data_path": str(app_data_path),
    }


def main():
    parser = argparse.ArgumentParser(description="Build web platform data")
    parser.add_argument("--params", type=Path, default=REPO_ROOT / "params")
    parser.add_argument("--scenarios", type=Path, default=REPO_ROOT / "scenarios")
    parser.add_argument("--output", type=Path, default=REPO_ROOT / "web" / "public" / "data")
    parser.add_argument("--renders", type=Path,
                        default=REPO_ROOT / "outputs" / "buildings_renders_v1")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    stats = build_web_data(args.params, args.scenarios, args.output, args.renders)
    print(f"Web data built: {stats['buildings']} buildings, {stats['scenarios']} scenarios")
    print(f"  Output: {stats['app_data_path']}")


if __name__ == "__main__":
    main()
