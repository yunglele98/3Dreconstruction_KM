#!/usr/bin/env python3
"""Generate per-building feature coverage matrix for active params files."""

from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
PARAMS_DIR = ROOT / "params"
DEFAULT_CSV = ROOT / "outputs" / "coverage_matrix.csv"
DEFAULT_SUMMARY_JSON = ROOT / "outputs" / "coverage_matrix_summary.json"
DEFAULT_SUMMARY_MD = ROOT / "docs" / "reports" / "coverage_matrix_2026-03-28.md"

FIELDS = [
    "floors",
    "total_height_m",
    "facade_width_m",
    "facade_depth_m",
    "facade_material",
    "roof_type",
    "roof_pitch_deg",
    "floor_heights_m",
    "windows_per_floor",
    "windows_detail",
    "doors_detail",
    "door_count",
    "has_storefront",
    "storefront",
    "porch",
    "colour_palette",
    "facade_detail",
    "decorative_elements",
    "deep_facade_analysis",
    "photo_observations",
    "hcd_data",
    "site.lon",
    "site.lat",
    "volumes",
    "condition",
]


def is_present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip() != ""
    if isinstance(value, (list, tuple, set, dict)):
        return len(value) > 0
    return True


def get_nested(params: dict[str, Any], key: str) -> Any:
    if "." not in key:
        return params.get(key)
    current: Any = params
    for part in key.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate params feature coverage matrix.")
    parser.add_argument("--params-dir", default=str(PARAMS_DIR))
    parser.add_argument("--output-csv", default=str(DEFAULT_CSV))
    parser.add_argument("--output-summary", default=str(DEFAULT_SUMMARY_JSON))
    parser.add_argument("--output-md", default=str(DEFAULT_SUMMARY_MD))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    params_dir = Path(args.params_dir).resolve()
    output_csv = Path(args.output_csv).resolve()
    output_summary = Path(args.output_summary).resolve()
    output_md = Path(args.output_md).resolve()

    output_csv.parent.mkdir(parents=True, exist_ok=True)
    output_summary.parent.mkdir(parents=True, exist_ok=True)
    output_md.parent.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, Any]] = []
    for path in sorted(params_dir.glob("*.json")):
        if path.name.startswith("_"):
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if data.get("skipped"):
            continue

        row: dict[str, Any] = {
            "file": path.name,
            "building_name": data.get("building_name") or path.stem,
        }
        present_count = 0
        for field in FIELDS:
            present = is_present(get_nested(data, field))
            row[field] = 1 if present else 0
            if present:
                present_count += 1
        row["present_count"] = present_count
        row["coverage_pct"] = round((present_count / len(FIELDS)) * 100, 2)
        rows.append(row)

    with output_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["file", "building_name", *FIELDS, "present_count", "coverage_pct"])
        writer.writeheader()
        writer.writerows(rows)

    field_totals = {field: 0 for field in FIELDS}
    for row in rows:
        for field in FIELDS:
            field_totals[field] += int(row[field])

    total_buildings = len(rows)
    field_coverage_pct = {
        field: round((field_totals[field] / total_buildings) * 100, 2) if total_buildings else 0.0
        for field in FIELDS
    }
    avg_coverage = round(sum(row["coverage_pct"] for row in rows) / total_buildings, 2) if total_buildings else 0.0

    summary = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "params_dir": str(params_dir),
        "total_buildings": total_buildings,
        "fields": FIELDS,
        "average_building_coverage_pct": avg_coverage,
        "field_presence_count": field_totals,
        "field_coverage_pct": field_coverage_pct,
        "outputs": {"csv": str(output_csv), "summary_json": str(output_summary), "summary_md": str(output_md)},
    }
    output_summary.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    lowest_buildings = sorted(rows, key=lambda row: row["coverage_pct"])[:20]
    lowest_fields = sorted(FIELDS, key=lambda field: field_coverage_pct[field])[:10]
    md_lines = [
        "# Coverage Matrix Report (2026-03-28)",
        "",
        f"- Generated: `{summary['generated_at']}`",
        f"- Total active buildings: `{total_buildings}`",
        f"- Average building coverage: `{avg_coverage}%`",
        "",
        "## Field Coverage",
        "",
        "| Field | Coverage % | Present Count |",
        "|---|---:|---:|",
    ]
    for field in FIELDS:
        md_lines.append(f"| `{field}` | {field_coverage_pct[field]} | {field_totals[field]} |")

    md_lines.extend(
        [
            "",
            "## Buildings With Lowest Coverage (Bottom 20)",
            "",
            "| Building | File | Coverage % | Present Fields |",
            "|---|---|---:|---:|",
        ]
    )
    for row in lowest_buildings:
        md_lines.append(
            f"| {row['building_name']} | `{row['file']}` | {row['coverage_pct']} | {row['present_count']}/{len(FIELDS)} |"
        )

    md_lines.extend(["", "## Fields With Lowest Coverage", ""])
    for field in lowest_fields:
        md_lines.append(f"- `{field}`: {field_coverage_pct[field]}% ({field_totals[field]}/{total_buildings})")

    output_md.write_text("\n".join(md_lines) + "\n", encoding="utf-8")

    print(f"[coverage] CSV: {output_csv}")
    print(f"[coverage] Summary JSON: {output_summary}")
    print(f"[coverage] Summary MD: {output_md}")
    print(f"[coverage] Buildings: {total_buildings}")
    print(f"[coverage] Avg coverage: {avg_coverage}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
