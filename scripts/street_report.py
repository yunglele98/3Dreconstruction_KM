#!/usr/bin/env python3
"""Generate per-street summary reports with pipeline status.

Aggregates building params, coverage, and quality metrics per street
for progress tracking and intervention planning.

Usage:
    python scripts/street_report.py
    python scripts/street_report.py --street "Augusta Ave"
    python scripts/street_report.py --output outputs/street_reports/ --format json
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent


def load_all_buildings(params_dir: Path) -> list[dict]:
    """Load all active building params."""
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
        data["_stem"] = f.stem
        buildings.append(data)
    return buildings


def compute_street_report(buildings: list[dict]) -> dict:
    """Compute per-street metrics."""
    by_street = defaultdict(list)
    for b in buildings:
        street = b.get("site", {}).get("street", "Unknown")
        by_street[street].append(b)

    reports = {}
    for street, street_buildings in sorted(by_street.items()):
        n = len(street_buildings)
        contributing = sum(1 for b in street_buildings if b.get("hcd_data", {}).get("contributing") == "Yes")
        enriched = sum(1 for b in street_buildings if b.get("_meta", {}).get("enriched"))
        promoted = sum(1 for b in street_buildings if b.get("_meta", {}).get("geometry_revised"))
        has_photo = sum(1 for b in street_buildings if b.get("photo_observations", {}).get("photo") or
                        b.get("deep_facade_analysis", {}).get("source_photo"))
        has_storefront = sum(1 for b in street_buildings if b.get("has_storefront"))

        heights = [b.get("total_height_m", 0) for b in street_buildings if b.get("total_height_m")]
        floors_list = [b.get("floors", 0) for b in street_buildings if b.get("floors")]
        widths = [b.get("facade_width_m", 0) for b in street_buildings if b.get("facade_width_m")]

        eras = Counter(b.get("hcd_data", {}).get("construction_date", "Unknown") for b in street_buildings)
        materials = Counter(b.get("facade_material", "unknown") for b in street_buildings)
        roof_types = Counter(b.get("roof_type", "unknown") for b in street_buildings)
        conditions = Counter(b.get("condition", "unknown") for b in street_buildings)

        # Decorative richness
        dec_counts = []
        for b in street_buildings:
            dec = b.get("decorative_elements", {})
            dec_counts.append(len(dec) if isinstance(dec, dict) else 0)

        reports[street] = {
            "building_count": n,
            "contributing": contributing,
            "contributing_pct": round(contributing / n * 100, 1) if n else 0,
            "enriched": enriched,
            "promoted": promoted,
            "has_photo": has_photo,
            "has_storefront": has_storefront,
            "avg_height_m": round(float(np.mean(heights)), 1) if heights else 0,
            "avg_floors": round(float(np.mean(floors_list)), 1) if floors_list else 0,
            "avg_width_m": round(float(np.mean(widths)), 1) if widths else 0,
            "avg_decorative_elements": round(float(np.mean(dec_counts)), 1),
            "eras": dict(eras.most_common(5)),
            "materials": dict(materials.most_common(5)),
            "roof_types": dict(roof_types.most_common(5)),
            "conditions": dict(conditions),
            "pipeline_completeness": round((enriched + promoted + has_photo) / (n * 3) * 100, 1) if n else 0,
        }

    return reports


def main():
    parser = argparse.ArgumentParser(description="Generate per-street summary reports")
    parser.add_argument("--params", type=Path, default=REPO_ROOT / "params")
    parser.add_argument("--street", type=str, default=None)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--format", choices=["text", "json"], default="text")
    args = parser.parse_args()

    buildings = load_all_buildings(args.params)
    reports = compute_street_report(buildings)

    if args.street:
        reports = {k: v for k, v in reports.items() if args.street.lower() in k.lower()}

    if args.format == "json":
        output = json.dumps(reports, indent=2, ensure_ascii=False)
        if args.output:
            args.output.mkdir(parents=True, exist_ok=True)
            (args.output / "street_reports.json").write_text(output, encoding="utf-8")
        else:
            print(output)
    else:
        print(f"{'Street':<25} {'Bldgs':>5} {'HCD%':>5} {'Photo':>5} {'Enrich':>6} {'Promo':>5} "
              f"{'Avg H':>5} {'Avg Fl':>6} {'Dec':>4} {'Pipe%':>5}")
        print("-" * 100)
        for street, r in sorted(reports.items(), key=lambda x: -x[1]["building_count"]):
            print(f"{street:<25} {r['building_count']:>5} {r['contributing_pct']:>5.0f} "
                  f"{r['has_photo']:>5} {r['enriched']:>6} {r['promoted']:>5} "
                  f"{r['avg_height_m']:>5.1f} {r['avg_floors']:>6.1f} "
                  f"{r['avg_decorative_elements']:>4.1f} {r['pipeline_completeness']:>5.1f}")
        print("-" * 100)
        total = len(buildings)
        print(f"{'TOTAL':<25} {total:>5}")

        if args.output:
            args.output.mkdir(parents=True, exist_ok=True)
            out = args.output / "street_reports.json"
            out.write_text(json.dumps(reports, indent=2, ensure_ascii=False), encoding="utf-8")
            print(f"\nSaved: {out}")


if __name__ == "__main__":
    main()
