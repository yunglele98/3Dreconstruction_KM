#!/usr/bin/env python3
"""
Export all active buildings to a summary CSV.

Output: outputs/deliverables/building_summary.csv
"""
import csv
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PARAMS_DIR = ROOT / "params"
OUTPUT_DIR = ROOT / "outputs" / "deliverables"


def get_street_number(params: dict, filename: str) -> tuple:
    site = params.get("site", {})
    street = (site.get("street") or "").strip()
    number = site.get("street_number", "")
    if not street:
        name = params.get("building_name", filename.replace("_", " "))
        m = re.match(r"(\d+[A-Za-z]?)\s+(.*)", name)
        if m:
            number = m.group(1)
            street = m.group(2)
        else:
            street = name
    return street, str(number)


def sort_key(item):
    street, number = item
    # Extract numeric part for sorting
    m = re.match(r"(\d+)", number)
    num = int(m.group(1)) if m else 0
    return (street.lower(), num)


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUT_DIR / "building_summary.csv"

    rows = []
    for param_file in sorted(PARAMS_DIR.glob("*.json")):
        if param_file.name.startswith("_") or "backup" in param_file.name:
            continue
        with open(param_file, encoding="utf-8") as f:
            params = json.load(f)
        if params.get("skipped"):
            continue

        street, number = get_street_number(params, param_file.stem)
        hcd = params.get("hcd_data", {})
        dec = params.get("decorative_elements", {})
        dec_count = sum(
            1 for v in dec.values()
            if isinstance(v, dict) and v.get("present")
        )
        facade_detail = params.get("facade_detail", {})
        palette = params.get("colour_palette", {})
        bay = params.get("bay_window", {})

        rows.append({
            "address": params.get("building_name", param_file.stem.replace("_", " ")),
            "street": street,
            "street_number": number,
            "floors": params.get("floors", ""),
            "total_height_m": params.get("total_height_m", ""),
            "facade_width_m": params.get("facade_width_m", ""),
            "facade_material": params.get("facade_material", ""),
            "roof_type": params.get("roof_type", ""),
            "construction_date": hcd.get("construction_date", ""),
            "typology": hcd.get("typology", ""),
            "contributing": hcd.get("contributing", ""),
            "condition": params.get("condition", ""),
            "has_storefront": params.get("has_storefront", False),
            "has_bay_window": bool(bay.get("present")) if isinstance(bay, dict) else False,
            "decorative_element_count": dec_count,
            "deep_facade_coverage": bool(params.get("deep_facade_analysis")),
            "facade_hex": facade_detail.get("brick_colour_hex") or palette.get("facade", ""),
            "trim_hex": facade_detail.get("trim_colour_hex") or palette.get("trim", ""),
            "generation_ready": bool(
                params.get("floors") and params.get("total_height_m") and params.get("facade_width_m")
            ),
        })

    # Sort by street then number
    rows.sort(key=lambda r: sort_key((r["street"], r["street_number"])))

    fieldnames = [
        "address", "street", "floors", "total_height_m", "facade_width_m",
        "facade_material", "roof_type", "construction_date", "typology",
        "contributing", "condition", "has_storefront", "has_bay_window",
        "decorative_element_count", "deep_facade_coverage", "facade_hex",
        "trim_hex", "generation_ready",
    ]

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    print(f"Exported {len(rows)} buildings to {output_path}")


if __name__ == "__main__":
    main()
