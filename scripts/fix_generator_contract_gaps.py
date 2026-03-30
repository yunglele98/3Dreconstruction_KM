"""
Fix script: read the contract audit output and fill missing required fields in param files
with safe defaults.

Usage:
    python scripts/fix_generator_contract_gaps.py              # dry-run (default)
    python scripts/fix_generator_contract_gaps.py --apply      # apply fixes

Output: modifies params/*.json files in place, stamps _meta.contract_gaps_fixed
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


# Configuration
AUDIT_FILE = Path(__file__).parent.parent / "outputs" / "generator_contract_audit.json"
PARAMS_DIR = Path(__file__).parent.parent / "params"


# Safe defaults for missing fields
DEFAULTS = {
    "bay_window.floors_spanned": [1],
    "bay_window.width_m": 2.0,
    "bay_window.projection_m": 0.6,
    "bay_window.height_m": 2.0,
    "bay_window.sill_height_m": 0.5,
    "bay_window.type": "box",
    "bay_window.position": "center",
    "storefront.height_m": 3.5,
    "storefront.width_m": None,  # computed from facade_width_m below
    "storefront.type": "modern",
    "decorative_elements.cornice.type": "simple",
    "decorative_elements.cornice.present": True,
    "decorative_elements.cornice.height_mm": 150,
    "decorative_elements.cornice.projection_mm": 80,
    "decorative_elements.bargeboard.width_mm": 200,
    "decorative_elements.bargeboard.projection_mm": 100,
    "decorative_elements.bargeboard.present": True,
    "decorative_elements.string_courses.width_mm": 50,
    "decorative_elements.string_courses.height_mm": 20,
    "decorative_elements.string_courses.projection_mm": 10,
    "decorative_elements.string_courses.present": True,
    "decorative_elements.quoins.strip_width_mm": 100,
    "decorative_elements.quoins.projection_mm": 80,
    "decorative_elements.quoins.present": True,
    "roof_pitch_deg": 30,
    "window_width_m": 0.9,
    "window_height_m": 1.5,
    "porch.height_m": 2.5,
    "porch.width_m": 2.0,
    "porch.depth_m": 1.5,
    "porch.present": True,
    "floor_heights_m": [3.0, 3.0, 3.0],
}


def set_nested_value(obj: dict[str, Any], path: str, value: Any) -> None:
    """Set a nested dict value using dot-separated path."""
    keys = path.split(".")
    for key in keys[:-1]:
        if key not in obj:
            obj[key] = {}
        if not isinstance(obj[key], dict):
            obj[key] = {}
        obj = obj[key]
    obj[keys[-1]] = value


def get_nested_value(obj: dict[str, Any], path: str) -> Any:
    """Get a nested dict value using dot-separated path."""
    keys = path.split(".")
    for key in keys:
        if isinstance(obj, dict):
            obj = obj.get(key)
        else:
            return None
    return obj


def compute_storefront_width(params: dict[str, Any]) -> float:
    """Compute storefront width as 80% of facade width."""
    facade_width = params.get("facade_width_m", 8.0)
    return facade_width * 0.8


def apply_fix(params: dict[str, Any], missing_field: str) -> bool:
    """
    Apply a single fix to a param dict.

    Returns True if a fix was applied, False otherwise.
    """
    # Special cases
    if missing_field == "storefront.width_m":
        set_nested_value(params, missing_field, compute_storefront_width(params))
        return True

    # Check for direct default
    if missing_field in DEFAULTS:
        default_val = DEFAULTS[missing_field]
        if default_val is not None:
            set_nested_value(params, missing_field, default_val)
            return True

    # Try to infer from context
    if missing_field.startswith("bay_window."):
        if "bay_window" not in params:
            params["bay_window"] = {}
        # Ensure bay_window is a dict
        if not isinstance(params["bay_window"], dict):
            params["bay_window"] = {}
        key = missing_field.split(".", 1)[1]
        if key in DEFAULTS:
            params["bay_window"][key] = DEFAULTS[f"bay_window.{key}"]
            return True

    if missing_field.startswith("storefront."):
        if "storefront" not in params:
            params["storefront"] = {}
        if not isinstance(params["storefront"], dict):
            params["storefront"] = {}
        key = missing_field.split(".", 1)[1]
        if key == "width_m":
            params["storefront"][key] = compute_storefront_width(params)
        elif f"storefront.{key}" in DEFAULTS:
            params["storefront"][key] = DEFAULTS[f"storefront.{key}"]
        return True

    if missing_field.startswith("decorative_elements."):
        if "decorative_elements" not in params:
            params["decorative_elements"] = {}
        if not isinstance(params["decorative_elements"], dict):
            params["decorative_elements"] = {}
        # e.g., "decorative_elements.cornice.type"
        parts = missing_field.split(".")
        if len(parts) == 3:
            category = parts[1]
            key = parts[2]
            if category not in params["decorative_elements"]:
                params["decorative_elements"][category] = {}
            if not isinstance(params["decorative_elements"][category], dict):
                params["decorative_elements"][category] = {}
            if f"decorative_elements.{category}.{key}" in DEFAULTS:
                params["decorative_elements"][category][key] = DEFAULTS[
                    f"decorative_elements.{category}.{key}"
                ]
                return True

    if missing_field.startswith("porch."):
        if "porch" not in params:
            params["porch"] = {}
        if not isinstance(params["porch"], dict):
            params["porch"] = {}
        key = missing_field.split(".", 1)[1]
        if f"porch.{key}" in DEFAULTS:
            params["porch"][key] = DEFAULTS[f"porch.{key}"]
            return True

    # Fallback
    if missing_field in ("roof_pitch_deg", "window_width_m", "window_height_m", "floor_heights_m"):
        params[missing_field] = DEFAULTS.get(missing_field, None)
        return True

    return False


def fix_building(params: dict[str, Any], warnings: list[dict[str, Any]]) -> dict[str, int]:
    """
    Apply fixes to a single building param dict.

    Returns counts: {fixed: int, failed: int}
    """
    counts = {"fixed": 0, "failed": 0}

    for warning in warnings:
        missing_field = warning["missing_field"]
        if apply_fix(params, missing_field):
            counts["fixed"] += 1
        else:
            counts["failed"] += 1

    # Stamp _meta
    if "fixed" > 0:
        if "_meta" not in params:
            params["_meta"] = {}
        if not isinstance(params["_meta"], dict):
            params["_meta"] = {}
        params["_meta"]["contract_gaps_fixed"] = True
        params["_meta"]["gaps_fixed_count"] = counts["fixed"]

    return counts


def main():
    """Main fix routine."""
    if not AUDIT_FILE.exists():
        print(f"Error: audit file not found at {AUDIT_FILE}")
        print("Run audit_generator_contracts.py first")
        sys.exit(1)

    with open(AUDIT_FILE, encoding="utf-8") as f:
        audit_data = json.load(f)

    warnings = audit_data.get("warnings", [])
    print(f"[FIX] Found {len(warnings)} warnings in audit")

    # Group warnings by building address
    warnings_by_address = {}
    for warning in warnings:
        address = warning["address"]
        if address not in warnings_by_address:
            warnings_by_address[address] = []
        warnings_by_address[address].append(warning)

    print(f"[FIX] Affecting {len(warnings_by_address)} buildings")

    # Apply fixes
    is_apply = "--apply" in sys.argv
    mode_str = "APPLY" if is_apply else "DRY-RUN"
    print(f"[FIX] Mode: {mode_str}")

    total_fixed = 0
    total_failed = 0
    fixed_buildings = 0

    for address, addr_warnings in sorted(warnings_by_address.items()):
        param_file = PARAMS_DIR / f"{address}.json"
        if not param_file.exists():
            print(f"  Warning: param file not found for {address}")
            continue

        try:
            with open(param_file, encoding="utf-8") as f:
                params = json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            print(f"  Error reading {address}: {e}")
            continue

        # Apply fixes
        counts = fix_building(params, addr_warnings)
        total_fixed += counts["fixed"]
        total_failed += counts["failed"]

        if counts["fixed"] > 0:
            fixed_buildings += 1
            if is_apply:
                with open(param_file, "w", encoding="utf-8") as f:
                    json.dump(params, f, indent=2, ensure_ascii=False)
                print(f"  [FIXED] {address}: {counts['fixed']} fields")
            else:
                print(f"  [WOULD FIX] {address}: {counts['fixed']} fields")

        if counts["failed"] > 0:
            print(f"    (Unable to auto-fix {counts['failed']} fields)")

    print(f"\n[FIX] Summary:")
    print(f"  Buildings with fixes: {fixed_buildings}")
    print(f"  Total fields fixed: {total_fixed}")
    print(f"  Total fields failed: {total_failed}")

    if not is_apply:
        print(f"\n  To apply fixes, run: python scripts/fix_generator_contract_gaps.py --apply")


if __name__ == "__main__":
    main()
