#!/usr/bin/env python3
"""Scan params/*.json and report data-quality anomalies."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_PARAMS_DIR = ROOT_DIR / "params"

ALLOWED_CONDITIONS = {"good", "fair", "poor"}
KNOWN_FACADE_MATERIALS = {
    "brick",
    "stucco",
    "clapboard",
    "wood siding",
    "vinyl siding",
    "stone",
    "concrete",
    "mixed masonry",
    "painted",
    "glass",
    "metal",
}
MATERIAL_LIKE_WORDS = {
    "brick",
    "stucco",
    "clapboard",
    "wood",
    "vinyl",
    "siding",
    "stone",
    "concrete",
    "masonry",
    "glass",
    "paint",
    "metal",
    "other",
    "mixed",
}
GENERIC_MATERIAL_LABELS = {
    "brick",
    "stucco",
    "clapboard",
    "wood",
    "wood siding",
    "vinyl",
    "vinyl siding",
    "stone",
    "concrete",
    "masonry",
    "mixed",
    "mixed masonry",
    "glass",
    "painted",
    "metal",
    "other",
    "unknown",
}


def normalize_text(value: Any) -> str:
    return "" if value is None else str(value).strip().lower()


def is_number(value: Any) -> bool:
    try:
        return value is not None and not isinstance(value, bool) and float(value) == float(value)
    except (TypeError, ValueError):
        return False


def to_float(value: Any) -> float | None:
    if not is_number(value):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def to_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def canonical_material(raw: Any) -> str:
    text = normalize_text(raw).replace("_", " ")
    if not text:
        return ""
    if "brick" in text:
        return "brick"
    if "stucco" in text or "render" in text:
        return "stucco"
    if "clapboard" in text:
        return "clapboard"
    if "vinyl" in text:
        return "vinyl siding"
    if "wood" in text and "siding" in text:
        return "wood siding"
    if text == "wood":
        return "wood siding"
    if "stone" in text or "limestone" in text or "sandstone" in text:
        return "stone"
    if "concrete" in text or "cement" in text:
        return "concrete"
    if "mixed" in text:
        return "mixed masonry"
    if "glass" in text:
        return "glass"
    if "paint" in text:
        return "painted"
    if "metal" in text:
        return "metal"
    return text


def likely_material_label(text: str) -> bool:
    clean = text.replace("_", " ")
    return normalize_text(clean) in GENERIC_MATERIAL_LABELS


def load_json(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return None, str(exc)
    if not isinstance(data, dict):
        return None, "top-level JSON is not an object"
    return data, None


def add_issue(
    issues: list[dict[str, Any]],
    categories: Counter[str],
    path: Path,
    category: str,
    message: str,
    field: str | None = None,
    severity: str = "medium",
) -> None:
    issues.append(
        {
            "file": path.name,
            "category": category,
            "field": field,
            "severity": severity,
            "message": message,
        }
    )
    categories[category] += 1


def check_file(path: Path) -> dict[str, Any]:
    data, parse_error = load_json(path)
    issues: list[dict[str, Any]] = []
    categories: Counter[str] = Counter()

    result: dict[str, Any] = {
        "file": path.name,
        "path": str(path),
        "status": "ok",
        "issue_count": 0,
        "issues": issues,
    }

    if parse_error:
        add_issue(issues, categories, path, "parse_error", parse_error, severity="high")
        result["status"] = "parse_error"
        result["issue_count"] = len(issues)
        result["categories"] = dict(categories)
        return result

    assert data is not None
    if data.get("skipped") is True or data.get("skip") is True or normalize_text(data.get("reason")):
        result["status"] = "skipped"
        skip_reason = data.get("skip_reason", data.get("reason", ""))
        result["skip_reason"] = skip_reason
        if not normalize_text(skip_reason):
            add_issue(
                issues,
                categories,
                path,
                "skipped_missing_reason",
                "skipped file is missing skip_reason",
                field="skip_reason",
                severity="low",
            )
        result["issue_count"] = len(issues)
        result["categories"] = dict(categories)
        return result

    building_name = normalize_text(data.get("building_name"))
    floors = to_int(data.get("floors"))
    total_height = to_float(data.get("total_height_m"))
    facade_width = to_float(data.get("facade_width_m"))
    facade_depth = to_float(data.get("facade_depth_m"))
    roof_type = normalize_text(data.get("roof_type"))
    roof_pitch = to_float(data.get("roof_pitch_deg"))
    facade_material_raw = data.get("facade_material")
    facade_material = canonical_material(facade_material_raw)
    facade_colour = normalize_text(data.get("facade_colour"))
    windows_per_floor = data.get("windows_per_floor")
    window_type = normalize_text(data.get("window_type"))
    window_width = to_float(data.get("window_width_m"))
    window_height = to_float(data.get("window_height_m"))
    door_count = to_int(data.get("door_count"))
    condition = normalize_text(data.get("condition"))
    has_storefront = data.get("has_storefront")
    storefront = data.get("storefront") if isinstance(data.get("storefront"), dict) else None
    site = data.get("site") if isinstance(data.get("site"), dict) else {}
    context = data.get("context") if isinstance(data.get("context"), dict) else {}
    city = data.get("city_data") if isinstance(data.get("city_data"), dict) else {}
    floor_heights = data.get("floor_heights_m")

    if not building_name:
        add_issue(issues, categories, path, "core_missing", "missing building_name", "building_name", "high")
    if floors is None or floors <= 0:
        add_issue(issues, categories, path, "core_missing", "missing or invalid floors", "floors", "high")
    if total_height is None or total_height <= 0:
        add_issue(issues, categories, path, "core_missing", "missing or invalid total_height_m", "total_height_m", "high")
    if facade_width is None or facade_width <= 0:
        add_issue(issues, categories, path, "core_missing", "missing or invalid facade_width_m", "facade_width_m", "high")
    if facade_depth is None or facade_depth <= 0:
        add_issue(issues, categories, path, "core_missing", "missing or invalid facade_depth_m", "facade_depth_m", "high")
    if not roof_type:
        add_issue(issues, categories, path, "core_missing", "missing roof_type", "roof_type", "medium")
    if roof_pitch is None or roof_pitch < 0 or roof_pitch > 90:
        add_issue(issues, categories, path, "core_invalid", "roof_pitch_deg outside 0-90", "roof_pitch_deg", "medium")
    if not facade_material:
        add_issue(issues, categories, path, "core_missing", "missing facade_material", "facade_material", "high")
    elif facade_material not in KNOWN_FACADE_MATERIALS:
        add_issue(
            issues,
            categories,
            path,
            "unknown_facade_material",
            f"unrecognized facade_material '{facade_material_raw}'",
            "facade_material",
            "medium",
        )
    if not facade_colour:
        add_issue(issues, categories, path, "core_missing", "missing facade_colour", "facade_colour", "medium")
    elif likely_material_label(facade_colour):
        add_issue(
            issues,
            categories,
            path,
            "core_invalid",
            f"facade_colour looks like a material label ('{data.get('facade_colour')}')",
            "facade_colour",
            "medium",
        )
    if not isinstance(windows_per_floor, list) or not windows_per_floor:
        add_issue(issues, categories, path, "core_missing", "missing or invalid windows_per_floor", "windows_per_floor", "high")
    else:
        bad_windows = [v for v in windows_per_floor if to_int(v) is None or to_int(v) < 0 or to_int(v) > 20]
        if bad_windows:
            add_issue(
                issues,
                categories,
                path,
                "core_invalid",
                f"windows_per_floor contains suspicious values: {bad_windows[:3]}",
                "windows_per_floor",
                "medium",
            )
        if floors and len(windows_per_floor) != floors:
            add_issue(
                issues,
                categories,
                path,
                "suspicious_dimensions",
                f"windows_per_floor length ({len(windows_per_floor)}) != floors ({floors})",
                "windows_per_floor",
                "low",
            )
    if not window_type:
        add_issue(issues, categories, path, "core_missing", "missing window_type", "window_type", "medium")
    if window_width is None or window_width <= 0:
        add_issue(issues, categories, path, "core_missing", "missing or invalid window_width_m", "window_width_m", "medium")
    if window_height is None or window_height <= 0:
        add_issue(issues, categories, path, "core_missing", "missing or invalid window_height_m", "window_height_m", "medium")
    if door_count is None or door_count < 0:
        add_issue(issues, categories, path, "core_missing", "missing or invalid door_count", "door_count", "medium")
    if condition and condition not in ALLOWED_CONDITIONS:
        add_issue(issues, categories, path, "core_invalid", f"unexpected condition '{data.get('condition')}'", "condition", "low")
    elif not condition:
        add_issue(issues, categories, path, "core_missing", "missing condition", "condition", "medium")
    if not isinstance(has_storefront, bool):
        add_issue(issues, categories, path, "core_invalid", "has_storefront is not boolean", "has_storefront", "low")
    if not is_number(site.get("lon")) or not is_number(site.get("lat")):
        add_issue(issues, categories, path, "core_missing", "missing site lon/lat", "site.lon/site.lat", "high")
    else:
        lon = float(site["lon"])
        lat = float(site["lat"])
        if not (-80.5 <= lon <= -78.5 and 42.5 <= lat <= 44.5):
            add_issue(issues, categories, path, "core_invalid", f"site lon/lat out of range ({lon}, {lat})", "site.lon/site.lat", "medium")

    if isinstance(floor_heights, list) and floor_heights and floors:
        values = [to_float(v) for v in floor_heights]
        if any(v is None or v <= 0 for v in values):
            add_issue(
                issues,
                categories,
                path,
                "suspicious_dimensions",
                f"floor_heights_m contains non-positive values: {floor_heights}",
                "floor_heights_m",
                "high",
            )
        if len(values) == floors:
            heights = [v for v in values if v is not None]
            if heights:
                height_min = min(heights)
                height_max = max(heights)
                if height_max > 8.0 or (height_min > 0 and height_max / height_min > 2.5 and height_max > 5.5):
                    add_issue(
                        issues,
                        categories,
                        path,
                        "suspicious_dimensions",
                        f"floor_heights_m spread looks unusual: {floor_heights}",
                        "floor_heights_m",
                        "high",
                    )
                height_sum = sum(heights)
                if total_height is not None and height_sum > 0:
                    delta = abs(total_height - height_sum)
                    if delta > max(1.5, height_sum * 0.35):
                        add_issue(
                            issues,
                            categories,
                            path,
                            "suspicious_dimensions",
                            f"total_height_m ({total_height}) differs from sum(floor_heights_m) ({round(height_sum, 2)})",
                            "total_height_m",
                            "high",
                        )
                    if total_height < max(heights):
                        add_issue(
                            issues,
                            categories,
                            path,
                            "suspicious_dimensions",
                            f"total_height_m ({total_height}) is below a floor height ({max(heights)})",
                            "total_height_m",
                            "high",
                        )
        elif len(values) != floors:
            add_issue(
                issues,
                categories,
                path,
                "suspicious_dimensions",
                f"floor_heights_m length ({len(values)}) != floors ({floors})",
                "floor_heights_m",
                "medium",
            )

    if total_height is not None and total_height > 60:
        add_issue(issues, categories, path, "suspicious_dimensions", f"total_height_m unusually high ({total_height})", "total_height_m", "low")
    avg_height = to_float(city.get("height_avg_m"))
    if total_height is not None and avg_height and total_height > avg_height * 1.8:
        add_issue(
            issues,
            categories,
            path,
            "suspicious_dimensions",
            f"total_height_m ({total_height}) is far above city_data.height_avg_m ({avg_height})",
            "total_height_m",
            "medium",
        )

    lot_width_ft = to_float(city.get("lot_width_ft"))
    lot_depth_ft = to_float(city.get("lot_depth_ft"))
    if lot_width_ft and facade_width is not None:
        lot_width_m = lot_width_ft * 0.3048
        if facade_width > lot_width_m * 1.35:
            add_issue(
                issues,
                categories,
                path,
                "suspicious_dimensions",
                f"facade_width_m ({facade_width}) exceeds lot width by a lot ({round(lot_width_m, 2)} m)",
                "facade_width_m",
                "medium",
            )
    if lot_depth_ft and facade_depth is not None:
        lot_depth_m = lot_depth_ft * 0.3048
        if facade_depth > lot_depth_m * 1.35:
            add_issue(
                issues,
                categories,
                path,
                "suspicious_dimensions",
                f"facade_depth_m ({facade_depth}) exceeds lot depth by a lot ({round(lot_depth_m, 2)} m)",
                "facade_depth_m",
                "medium",
            )

    storefront_reason = None
    if storefront and not normalize_text(storefront.get("status")):
        storefront_reason = "storefront.status is empty"
        add_issue(issues, categories, path, "storefront_inconsistency", storefront_reason, "storefront.status", "low")
    if bool(has_storefront) and storefront is None:
        add_issue(
            issues,
            categories,
            path,
            "storefront_inconsistency",
            "has_storefront is true but storefront object is missing",
            "has_storefront",
            "medium",
        )
    if not bool(has_storefront) and storefront is not None:
        add_issue(
            issues,
            categories,
            path,
            "storefront_inconsistency",
            "storefront object exists but has_storefront is false",
            "storefront",
            "medium",
        )

    general_use = normalize_text(context.get("general_use"))
    commercial_use = normalize_text(context.get("commercial_use"))
    if not bool(has_storefront) and (general_use in {"commercial", "mixed use"} or commercial_use):
        add_issue(
            issues,
            categories,
            path,
            "storefront_inconsistency",
            f"commercial-use signals present but has_storefront is false (general_use={context.get('general_use')!r}, commercial_use={context.get('commercial_use')!r})",
            "has_storefront",
            "medium",
        )

    result["status"] = "issues" if issues else "ok"
    result["issue_count"] = len(issues)
    result["categories"] = dict(categories)
    result["building_name"] = data.get("building_name", "")
    result["skipped"] = False
    return result


def render_report(report: dict[str, Any], limit_examples: int = 10) -> str:
    lines = []
    lines.append(f"Scanned {report['scanned_files']} files from {report['params_dir']}")
    lines.append(
        f"Building files: {report['building_files']} | skipped: {report['skipped_files']} | parse errors: {report['parse_errors']}"
    )
    lines.append(f"Files with issues: {report['files_with_issues']} | total anomalies: {report['total_issues']}")
    lines.append("Issue counts:")
    for category, count in sorted(report["issue_counts"].items(), key=lambda item: (-item[1], item[0])):
        lines.append(f"  {category}: {count}")

    examples = report["examples"][:limit_examples]
    if examples:
        lines.append("Top files:")
        for item in examples:
            category_summary = ", ".join(
                f"{key}={value}" for key, value in sorted(item["categories"].items(), key=lambda kv: (-kv[1], kv[0]))
            )
            first_issue = item["issues"][0]["message"] if item["issues"] else ""
            tail = f" - {first_issue}" if first_issue else ""
            lines.append(f"  {item['file']}: {item['issue_count']} issue(s) [{category_summary}]{tail}")
    return "\n".join(lines)


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

    parser = argparse.ArgumentParser(description="Scan params/*.json for quality anomalies")
    parser.add_argument("--params-dir", default=str(DEFAULT_PARAMS_DIR), help="Directory containing param JSON files")
    parser.add_argument("--limit", type=int, default=None, help="Limit the number of files scanned")
    parser.add_argument("--json-output", default=None, help="Optional path to write the full report JSON")
    args = parser.parse_args()

    params_dir = Path(args.params_dir).expanduser().resolve()
    if not params_dir.exists():
        raise SystemExit(f"params dir not found: {params_dir}")

    files = sorted(
        path
        for path in params_dir.glob("*.json")
        if path.is_file() and not path.name.startswith(("_", "."))
    )
    if isinstance(args.limit, int) and args.limit > 0:
        files = files[: args.limit]

    results = [check_file(path) for path in files]
    issue_results = [item for item in results if item["status"] == "issues"]
    skipped_results = [item for item in results if item["status"] == "skipped"]
    parse_errors = [item for item in results if item["status"] == "parse_error"]

    issue_counts = Counter()
    for item in results:
        issue_counts.update(item.get("categories", {}))

    report = {
        "params_dir": str(params_dir),
        "scanned_files": len(files),
        "building_files": len(results) - len(skipped_results) - len(parse_errors),
        "skipped_files": len(skipped_results),
        "parse_errors": len(parse_errors),
        "files_with_issues": len(issue_results) + len(parse_errors),
        "total_issues": sum(item["issue_count"] for item in results),
        "issue_counts": dict(issue_counts),
        "examples": sorted(
            [item for item in results if item["issue_count"] > 0],
            key=lambda item: (-item["issue_count"], item["file"]),
        ),
        "files": results,
    }

    print(render_report(report))

    if args.json_output:
        json_output = Path(args.json_output).expanduser().resolve()
        json_output.parent.mkdir(parents=True, exist_ok=True)
        json_output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"Wrote JSON report: {json_output}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
