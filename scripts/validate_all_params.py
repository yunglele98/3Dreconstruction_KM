#!/usr/bin/env python3
"""
Validate all active param files against the expected schema.

Reports valid/invalid counts, top schema violations, and optionally
auto-fixes safe issues (wrong types, missing required fields with defaults).

Usage:
    python scripts/validate_all_params.py              # report-only
    python scripts/validate_all_params.py --fix        # auto-fix safe issues
"""
import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PARAMS_DIR = ROOT / "params"
OUTPUT_FILE = ROOT / "outputs" / "param_validation_report.json"

HEX_PATTERN = re.compile(r"^#[0-9A-Fa-f]{6}$")

REQUIRED_FIELDS = {
    "building_name": str,
    "floors": int,
    "total_height_m": (int, float),
    "facade_width_m": (int, float),
    "facade_material": str,
    "roof_type": str,
}

RANGE_CHECKS = {
    "floors": (1, 10),
    "total_height_m": (2.0, 40.0),
    "facade_width_m": (2.0, 50.0),
    "roof_pitch_deg": (0, 55),
}


def validate_hex(value: str) -> bool:
    return bool(HEX_PATTERN.match(value))


def fix_hex_case(value: str) -> str:
    if isinstance(value, str) and value.startswith("#") and len(value) == 7:
        return "#" + value[1:].upper()
    return value


def try_coerce(value, target_type):
    """Try to coerce a value to the target type."""
    if isinstance(target_type, tuple):
        for t in target_type:
            try:
                return t(value)
            except (ValueError, TypeError):
                continue
    else:
        try:
            return target_type(value)
        except (ValueError, TypeError):
            pass
    return None


def validate_building(params: dict, do_fix: bool = False) -> list:
    """Validate a single building's params. Returns list of issues."""
    issues = []
    fixed = []

    # Required fields
    for field, expected_type in REQUIRED_FIELDS.items():
        val = params.get(field)
        if val is None:
            issues.append(f"missing required field: {field}")
            continue
        if not isinstance(val, expected_type if isinstance(expected_type, tuple) else (expected_type,)):
            coerced = try_coerce(val, expected_type)
            if coerced is not None and do_fix:
                params[field] = coerced
                fixed.append(f"coerced {field}: {val!r} -> {coerced}")
            else:
                issues.append(f"wrong type for {field}: expected {expected_type}, got {type(val).__name__}")

    # Range checks
    for field, (lo, hi) in RANGE_CHECKS.items():
        val = params.get(field)
        if val is None:
            continue
        try:
            val = float(val)
        except (TypeError, ValueError):
            continue
        if val < lo or val > hi:
            if do_fix:
                clamped = max(lo, min(hi, val))
                params[field] = clamped
                fixed.append(f"clamped {field}: {val} -> {clamped}")
            else:
                issues.append(f"{field}={val} outside range [{lo}, {hi}]")

    # Array length consistency
    floors = params.get("floors", 0)
    if isinstance(floors, (int, float)):
        floors = int(floors)

        fh = params.get("floor_heights_m", [])
        if isinstance(fh, list) and len(fh) != floors and floors > 0:
            if do_fix:
                if len(fh) > floors:
                    params["floor_heights_m"] = fh[:floors]
                    fixed.append(f"truncated floor_heights_m: {len(fh)} -> {floors}")
                elif len(fh) < floors:
                    avg = sum(fh) / len(fh) if fh else 3.0
                    while len(params["floor_heights_m"]) < floors:
                        params["floor_heights_m"].append(round(avg, 2))
                    fixed.append(f"extended floor_heights_m: {len(fh)} -> {floors}")
            else:
                issues.append(f"floor_heights_m length ({len(fh)}) != floors ({floors})")

        wpf = params.get("windows_per_floor", [])
        if isinstance(wpf, list) and len(wpf) != floors and floors > 0:
            if do_fix:
                if len(wpf) > floors:
                    params["windows_per_floor"] = wpf[:floors]
                    fixed.append(f"truncated windows_per_floor: {len(wpf)} -> {floors}")
                elif len(wpf) < floors:
                    params.setdefault("windows_per_floor", list(wpf))
                    while len(params["windows_per_floor"]) < floors:
                        params["windows_per_floor"].append(1)
                    fixed.append(f"extended windows_per_floor: {len(wpf)} -> {floors}")
            else:
                issues.append(f"windows_per_floor length ({len(wpf)}) != floors ({floors})")

    # Height consistency
    fh = params.get("floor_heights_m", [])
    total_h = params.get("total_height_m")
    if isinstance(fh, list) and fh and isinstance(total_h, (int, float)):
        diff = abs(sum(fh) - total_h)
        if diff > 0.5:
            issues.append(f"floor_heights_m sum ({sum(fh):.2f}) differs from total_height_m ({total_h}) by {diff:.2f}")

    if fixed:
        issues.extend([f"[FIXED] {f}" for f in fixed])

    return issues


def process(do_fix: bool = False) -> None:
    all_issues = {}
    violation_counts = {}
    total_valid = 0
    total_invalid = 0
    total_active = 0

    for param_file in sorted(PARAMS_DIR.glob("*.json")):
        if param_file.name.startswith("_") or "backup" in param_file.name:
            continue
        with open(param_file, encoding="utf-8") as f:
            params = json.load(f)
        if params.get("skipped"):
            continue

        total_active += 1
        issues = validate_building(params, do_fix=do_fix)

        if issues:
            total_invalid += 1
            all_issues[param_file.name] = issues
            for issue in issues:
                # Extract issue type
                key = issue.split(":")[0].strip() if ":" in issue else issue[:40]
                violation_counts[key] = violation_counts.get(key, 0) + 1

            if do_fix and any("[FIXED]" in i for i in issues):
                meta = params.setdefault("_meta", {})
                fixes = meta.setdefault("handoff_fixes_applied", [])
                fixes.append({
                    "fix": "validate_all_params",
                    "fixes": [i.replace("[FIXED] ", "") for i in issues if "[FIXED]" in i],
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })
                with open(param_file, "w", encoding="utf-8") as f:
                    json.dump(params, f, indent=2, ensure_ascii=False)
                    f.write("\n")
        else:
            total_valid += 1

    # Top violations
    top_violations = sorted(violation_counts.items(), key=lambda x: -x[1])[:10]

    report = {
        "total_active": total_active,
        "valid": total_valid,
        "invalid": total_invalid,
        "top_violations": top_violations,
        "per_building": {k: v for k, v in list(all_issues.items())[:100]},
    }

    print(f"Param Validation Report")
    print(f"{'='*50}")
    print(f"Active: {total_active}, Valid: {total_valid}, Invalid: {total_invalid}")
    print(f"\nTop 10 violations:")
    for vtype, count in top_violations:
        print(f"  {vtype}: {count}")

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(f"\nReport: {OUTPUT_FILE}")


def main():
    parser = argparse.ArgumentParser(description="Validate all param files")
    parser.add_argument("--fix", action="store_true", help="Auto-fix safe issues")
    args = parser.parse_args()
    process(do_fix=args.fix)


if __name__ == "__main__":
    main()
