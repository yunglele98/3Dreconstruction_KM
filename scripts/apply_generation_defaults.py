#!/usr/bin/env python3
"""
Apply generation_defaults.py constants to param files as missing-value fill.

For each active param file, fills any missing values that have sensible
defaults from generation_defaults.py. Never overwrites existing values.

Dry-run by default; pass --apply to write changes.
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PARAMS_DIR = ROOT / "params"

# Import constants from generation_defaults
sys.path.insert(0, str(ROOT / "scripts"))
from generation_defaults import (
    WALL_THICKNESS_M,
    DEFAULT_WINDOW_WIDTH_M,
    DEFAULT_WINDOW_HEIGHT_M,
    WINDOW_SILL_HEIGHT_M,
    DEFAULT_DOOR_WIDTH_M,
    DEFAULT_DOOR_HEIGHT_M,
    MORTAR_COLOUR_DEFAULT_HEX,
    DEFAULT_ROOF_PITCH_DEG,
    EAVE_OVERHANG_MM,
    FOUNDATION_HEIGHT_M,
    DEFAULT_PARAM_WINDOW_TYPE,
    DEFAULT_PARAM_CONDITION,
    DEFAULT_PARAM_FLOOR_HEIGHT_M,
    DEFAULT_DEPTH_M,
    DEFAULT_BAY_WINDOW_PROJECTION_M,
)


# Map of top-level param keys to default values
TOP_LEVEL_DEFAULTS = {
    "wall_thickness_m": WALL_THICKNESS_M,
    "window_width_m": DEFAULT_WINDOW_WIDTH_M,
    "window_height_m": DEFAULT_WINDOW_HEIGHT_M,
    "window_type": DEFAULT_PARAM_WINDOW_TYPE,
    "condition": DEFAULT_PARAM_CONDITION,
    "roof_pitch_deg": DEFAULT_ROOF_PITCH_DEG,
}

# Nested defaults: (parent_key, child_key, default_value)
NESTED_DEFAULTS = [
    ("facade_detail", "mortar_colour", "default"),
    ("facade_detail", "mortar_colour_hex", MORTAR_COLOUR_DEFAULT_HEX),
    ("facade_detail", "bond_pattern", "running bond"),
    ("roof_detail", "eave_overhang_mm", EAVE_OVERHANG_MM),
]


def fill_defaults(params: dict) -> list:
    """Fill missing defaults into params. Returns list of fields filled."""
    filled = []

    # Top-level defaults
    for key, default in TOP_LEVEL_DEFAULTS.items():
        if key not in params or params[key] is None:
            params[key] = default
            filled.append(key)

    # Nested defaults
    for parent_key, child_key, default in NESTED_DEFAULTS:
        parent = params.get(parent_key, {})
        if isinstance(parent, dict) and (child_key not in parent or parent[child_key] is None):
            parent[child_key] = default
            params[parent_key] = parent
            filled.append(f"{parent_key}.{child_key}")

    # Window defaults in windows_detail
    windows_detail = params.get("windows_detail", [])
    for floor_entry in windows_detail:
        for win in floor_entry.get("windows", []):
            if "width_m" not in win or win["width_m"] is None:
                win["width_m"] = DEFAULT_WINDOW_WIDTH_M
                if "windows_detail[].width_m" not in filled:
                    filled.append("windows_detail[].width_m")
            if "height_m" not in win or win["height_m"] is None:
                win["height_m"] = DEFAULT_WINDOW_HEIGHT_M
                if "windows_detail[].height_m" not in filled:
                    filled.append("windows_detail[].height_m")
            if "sill_height_m" not in win or win["sill_height_m"] is None:
                win["sill_height_m"] = WINDOW_SILL_HEIGHT_M
                if "windows_detail[].sill_height_m" not in filled:
                    filled.append("windows_detail[].sill_height_m")

    # Door defaults in doors_detail
    doors_detail = params.get("doors_detail", [])
    for door in doors_detail:
        if "width_m" not in door or door["width_m"] is None:
            door["width_m"] = DEFAULT_DOOR_WIDTH_M
            if "doors_detail[].width_m" not in filled:
                filled.append("doors_detail[].width_m")
        if "height_m" not in door or door["height_m"] is None:
            door["height_m"] = DEFAULT_DOOR_HEIGHT_M
            if "doors_detail[].height_m" not in filled:
                filled.append("doors_detail[].height_m")

    # Bay window projection default
    bay_window = params.get("bay_window", {})
    if isinstance(bay_window, dict) and bay_window.get("present"):
        if "projection_m" not in bay_window or bay_window["projection_m"] is None:
            bay_window["projection_m"] = DEFAULT_BAY_WINDOW_PROJECTION_M
            params["bay_window"] = bay_window
            filled.append("bay_window.projection_m")

    return filled


def process(apply: bool = False) -> None:
    stats = {"updated": 0, "skipped": 0, "no_change": 0}
    all_fields_filled = {}

    for param_file in sorted(PARAMS_DIR.glob("*.json")):
        if param_file.name.startswith("_") or "backup" in param_file.name:
            continue

        with open(param_file, encoding="utf-8") as f:
            params = json.load(f)

        if params.get("skipped"):
            stats["skipped"] += 1
            continue

        filled = fill_defaults(params)

        if not filled:
            stats["no_change"] += 1
            continue

        for f_name in filled:
            all_fields_filled[f_name] = all_fields_filled.get(f_name, 0) + 1

        action = "APPLY" if apply else "DRY-RUN"
        print(f"  {action}: {param_file.name}  filled: {filled}")

        if apply:
            meta = params.setdefault("_meta", {})
            meta["generation_defaults_applied"] = True
            fixes = meta.setdefault("handoff_fixes_applied", [])
            fixes.append({
                "fix": "apply_generation_defaults",
                "fields_filled": filled,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
            with open(param_file, "w", encoding="utf-8") as f:
                json.dump(params, f, indent=2, ensure_ascii=False)
                f.write("\n")

        stats["updated"] += 1

    print(f"\nSummary: {stats['updated']} {'updated' if apply else 'would update'}, "
          f"{stats['no_change']} no changes needed, "
          f"{stats['skipped']} skipped files")

    if all_fields_filled:
        print(f"\nFields filled (frequency):")
        for field, count in sorted(all_fields_filled.items(), key=lambda x: -x[1]):
            print(f"  {field}: {count}")


def main():
    parser = argparse.ArgumentParser(description="Apply generation defaults to param files")
    parser.add_argument("--apply", action="store_true", help="Write changes (default: dry-run)")
    args = parser.parse_args()
    process(apply=args.apply)


if __name__ == "__main__":
    main()
