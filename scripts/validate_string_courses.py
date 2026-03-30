#!/usr/bin/env python3
"""Validate string-course dimensions and optional floor-boundary placement."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
PARAMS_DIR = ROOT / "params"

MIN_HEIGHT_M = 0.05
MAX_HEIGHT_M = 0.30


def _to_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _course_items(data: dict[str, Any]) -> list[dict[str, Any]]:
    de = data.get("decorative_elements")
    if not isinstance(de, dict):
        return []
    sc = de.get("string_courses")
    if isinstance(sc, dict):
        return [sc]
    if isinstance(sc, list):
        return [item for item in sc if isinstance(item, dict)]
    return []


def _extract_height_m(course: dict[str, Any]) -> tuple[float | None, str | None]:
    if "string_course_height_m" in course:
        value = _to_float(course.get("string_course_height_m"))
        return value, "string_course_height_m"
    if "height_m" in course:
        value = _to_float(course.get("height_m"))
        return value, "height_m"
    if "width_mm" in course:
        value = _to_float(course.get("width_mm"))
        return (value / 1000.0 if value is not None else None), "width_mm"
    return None, None


def _set_height(course: dict[str, Any], key: str, value_m: float) -> None:
    if key == "width_mm":
        course["width_mm"] = int(round(value_m * 1000))
    else:
        course[key] = round(value_m, 3)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate/fix string-course ranges and placement checks.")
    parser.add_argument("--params-dir", default=str(PARAMS_DIR))
    parser.add_argument("--fix", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    params_dir = Path(args.params_dir)

    flagged_buildings = 0
    range_issues = 0
    boundary_issues = 0
    fixes_applied = 0

    for path in sorted(params_dir.glob("*.json")):
        if path.name.startswith("_"):
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if data.get("skipped"):
            continue

        courses = _course_items(data)
        if not courses:
            continue

        building_issues = 0
        floor_heights = data.get("floor_heights_m") or []
        cumulative = []
        total = 0.0
        for h in floor_heights:
            fh = _to_float(h)
            if fh:
                total += fh
                cumulative.append(total)

        for idx, course in enumerate(courses, start=1):
            value_m, key = _extract_height_m(course)
            if value_m is not None and key is not None:
                if value_m < MIN_HEIGHT_M or value_m > MAX_HEIGHT_M:
                    building_issues += 1
                    range_issues += 1
                    clamped = min(MAX_HEIGHT_M, max(MIN_HEIGHT_M, value_m))
                    print(f"[string] {path.name} course#{idx}: out-of-range height {value_m:.3f}m")
                    if args.fix:
                        _set_height(course, key, clamped)
                        fixes_applied += 1
                        print(f"  -> clamped to {clamped:.3f}m")

            # Optional boundary validation if explicit elevation data exists
            z = None
            for zkey in ("z_m", "height_at_m", "elevation_m"):
                z = _to_float(course.get(zkey))
                if z is not None:
                    break
            if z is not None and cumulative:
                # Allow tolerance around floor boundaries.
                near_boundary = any(abs(z - b) <= 0.6 for b in cumulative)
                if not near_boundary:
                    building_issues += 1
                    boundary_issues += 1
                    print(f"[string] {path.name} course#{idx}: elevation {z:.2f}m outside floor boundaries")

        if building_issues:
            flagged_buildings += 1
            if args.fix:
                meta = data.get("_meta") if isinstance(data.get("_meta"), dict) else {}
                meta["string_course_validated"] = True
                data["_meta"] = meta
                path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"[string] Buildings flagged: {flagged_buildings}")
    print(f"[string] Range issues: {range_issues}")
    print(f"[string] Boundary issues: {boundary_issues}")
    print(f"[string] Fixes applied: {fixes_applied if args.fix else 0}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
