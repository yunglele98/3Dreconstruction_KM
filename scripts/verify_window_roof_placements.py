#!/usr/bin/env python3
"""
Audit parameter-level consistency for window and roof placements.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


GABLE_ROOFS = {"gable", "cross-gable"}


def _load_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _is_skipped(data: dict) -> bool:
    return bool(data.get("skipped"))


def audit_file(path: Path, data: dict) -> list[str]:
    issues: list[str] = []
    floors = int(data.get("floors") or 0)
    roof_type = (data.get("roof_type") or "").strip().lower()
    windows_per_floor = data.get("windows_per_floor") or []
    windows_detail = data.get("windows_detail") or []
    roof_detail = data.get("roof_detail") or {}
    gable_window = roof_detail.get("gable_window") if isinstance(roof_detail, dict) else None

    if isinstance(windows_per_floor, list) and floors > 0:
        if len(windows_per_floor) not in (floors, floors + 1):
            issues.append(
                f"windows_per_floor length {len(windows_per_floor)} does not align with floors={floors}"
            )

    if isinstance(gable_window, dict) and gable_window.get("present"):
        if roof_type not in GABLE_ROOFS:
            issues.append(f"gable_window present but roof_type={roof_type!r}")

    if isinstance(windows_detail, list) and floors > 0:
        upper_entries = 0
        for entry in windows_detail:
            if not isinstance(entry, dict):
                continue
            floor_name = str(entry.get("floor") or "").lower()
            if "ground" in floor_name or "storefront" in floor_name:
                continue
            upper_entries += 1
        if upper_entries > floors + 1:
            issues.append(
                f"windows_detail has {upper_entries} non-ground entries for floors={floors}"
            )

    return issues


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit window/roof placement consistency")
    parser.add_argument("--params-dir", default="params")
    parser.add_argument("--output", default="outputs/window_roof_placement_audit.json")
    args = parser.parse_args()

    params_dir = Path(args.params_dir)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    results: dict[str, list[str]] = {}
    scanned = 0
    parse_errors = 0

    for path in sorted(params_dir.glob("*.json")):
        if path.name.startswith("_"):
            continue
        data = _load_json(path)
        if data is None:
            parse_errors += 1
            results[path.name] = ["parse_error"]
            continue
        if _is_skipped(data):
            continue
        scanned += 1
        issues = audit_file(path, data)
        if issues:
            results[path.name] = issues

    report = {
        "scanned": scanned,
        "parse_errors": parse_errors,
        "files_with_issues": len(results),
        "results": results,
    }
    output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"Scanned: {scanned}")
    print(f"Parse errors: {parse_errors}")
    print(f"Files with placement issues: {len(results)}")
    print(f"Report: {output_path.resolve()}")


if __name__ == "__main__":
    main()
