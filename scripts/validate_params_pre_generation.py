#!/usr/bin/env python3
"""Validate param files before Blender generation to catch issues early.

Checks that all required fields exist and have valid types/ranges
so generate_building.py won't crash. Runs in seconds vs minutes for Blender.

Usage:
    python scripts/validate_params_pre_generation.py
    python scripts/validate_params_pre_generation.py --address "22 Lippincott St"
    python scripts/validate_params_pre_generation.py --strict  # treat warnings as errors
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PARAMS_DIR = ROOT / "params"

# Fields required by generate_building() to produce valid geometry
REQUIRED_FIELDS = {
    "floors": (int, float),
    "facade_width_m": (int, float),
    "facade_depth_m": (int, float),
    "total_height_m": (int, float),
}

# Fields that must be valid if present
VALIDATED_FIELDS = {
    "roof_type": {"flat", "gable", "cross-gable", "hip", "mansard",
                  "Flat", "Gable", "Cross-gable", "Hip", "Mansard"},
    "facade_material": {"brick", "paint", "painted", "stucco", "clapboard",
                        "stone", "concrete", "wood", "vinyl", "siding",
                        "Brick", "Paint", "Painted", "Stucco", "Clapboard",
                        "Stone", "Concrete", "Wood", "Vinyl", "Siding"},
    "condition": {"good", "fair", "poor", "Good", "Fair", "Poor"},
}

# Dimension ranges that indicate likely data errors
DIMENSION_RANGES = {
    "facade_width_m": (1.5, 50.0),
    "facade_depth_m": (2.0, 50.0),
    "total_height_m": (2.5, 80.0),
    "floors": (1, 20),
}


def validate_param(fpath, strict=False):
    """Validate a single param file. Returns (errors, warnings)."""
    errors = []
    warnings = []

    try:
        data = json.loads(fpath.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        return [f"JSON parse error: {e}"], []

    if data.get("skipped"):
        return [], []

    # Required fields
    for field, types in REQUIRED_FIELDS.items():
        val = data.get(field)
        if val is None:
            errors.append(f"missing required field: {field}")
        elif not isinstance(val, types):
            errors.append(f"{field}: expected number, got {type(val).__name__} ({val!r})")
        elif val <= 0:
            errors.append(f"{field}: must be positive, got {val}")

    # Dimension ranges
    for field, (lo, hi) in DIMENSION_RANGES.items():
        val = data.get(field)
        if isinstance(val, (int, float)) and (val < lo or val > hi):
            warnings.append(f"{field}={val} outside typical range [{lo}, {hi}]")

    # Validated enum fields
    for field, valid_values in VALIDATED_FIELDS.items():
        val = data.get(field)
        if val is not None and isinstance(val, str) and val not in valid_values:
            clean = val.strip().lower()
            if not any(clean == v.lower() for v in valid_values):
                warnings.append(f"{field}={val!r} not in valid set")

    # floor_heights_m consistency
    fh = data.get("floor_heights_m", [])
    floors = data.get("floors", 0)
    if isinstance(fh, list) and isinstance(floors, (int, float)):
        if fh and len(fh) != int(floors):
            warnings.append(
                f"floor_heights_m length ({len(fh)}) != floors ({int(floors)})"
            )
        if fh and any(not isinstance(h, (int, float)) or h <= 0 for h in fh):
            errors.append("floor_heights_m contains non-positive or non-numeric values")

    # windows_per_floor consistency
    wpf = data.get("windows_per_floor", [])
    if isinstance(wpf, list) and isinstance(floors, (int, float)):
        if wpf and len(wpf) != int(floors):
            warnings.append(
                f"windows_per_floor length ({len(wpf)}) != floors ({int(floors)})"
            )

    # Nested dict type checks
    for field in ("hcd_data", "facade_detail", "decorative_elements",
                  "colour_palette", "site", "_meta"):
        val = data.get(field)
        if val is not None and not isinstance(val, dict):
            warnings.append(f"{field}: expected dict, got {type(val).__name__}")

    # doors_detail / windows_detail should be lists
    for field in ("doors_detail", "windows_detail"):
        val = data.get(field)
        if val is not None and not isinstance(val, list):
            warnings.append(f"{field}: expected list, got {type(val).__name__}")

    if strict:
        errors.extend(warnings)
        warnings = []

    return errors, warnings


def main():
    parser = argparse.ArgumentParser(
        description="Validate params before Blender generation"
    )
    parser.add_argument("--address", help="Validate single address")
    parser.add_argument(
        "--strict", action="store_true",
        help="Treat warnings as errors"
    )
    parser.add_argument(
        "--params-dir", type=Path, default=PARAMS_DIR,
        help="Params directory"
    )
    args = parser.parse_args()

    params_dir = args.params_dir

    if args.address:
        fname = args.address.replace(" ", "_") + ".json"
        files = [params_dir / fname]
    else:
        files = sorted(params_dir.glob("*.json"))

    total = 0
    error_count = 0
    warning_count = 0
    error_files = []

    for fpath in files:
        if fpath.name.startswith("_"):
            continue
        total += 1
        errors, warnings = validate_param(fpath, strict=args.strict)
        if errors:
            error_count += 1
            error_files.append((fpath.name, errors, warnings))
            print(f"  ERROR {fpath.name}:")
            for e in errors:
                print(f"    - {e}")
        if warnings and not errors:
            warning_count += 1
            if args.address:
                print(f"  WARN {fpath.name}:")
                for w in warnings:
                    print(f"    - {w}")

    print(f"\nValidated {total} files: {error_count} errors, {warning_count} warnings")
    if error_count == 0:
        print("All params ready for generation.")
    else:
        print(f"\n{error_count} files have errors that will cause generation failures.")
        sys.exit(1)


if __name__ == "__main__":
    main()
