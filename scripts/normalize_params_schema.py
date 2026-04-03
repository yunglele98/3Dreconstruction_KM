#!/usr/bin/env python3
"""Normalize decorative/detail schema across existing param files."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from copy import deepcopy
from pathlib import Path


def _configure_utf8_stdout() -> None:
    """Avoid Windows cp1252 encode crashes when printing non-ASCII filenames."""
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def _atomic_write_json(filepath, data, ensure_ascii=False):
    """Write JSON atomically via temp file + rename to prevent corruption."""
    filepath = Path(filepath)
    with tempfile.NamedTemporaryFile(
        mode="w", dir=filepath.parent, delete=False,
        suffix=".tmp", encoding="utf-8",
    ) as tmp:
        json.dump(data, tmp, indent=2, ensure_ascii=ensure_ascii)
        tmp.write("\n")
        tmp_path = Path(tmp.name)
    os.replace(str(tmp_path), str(filepath))


PARAMS_DIR = Path(__file__).parent.parent / "params"


BOOLEAN_DECORATIVE_DEFAULTS = {
    "bargeboard": {"present": True, "type": "decorative", "colour_hex": "#4A3324", "width_mm": 220},
    "brackets": {"type": "paired_scroll", "count": 4, "projection_mm": 220, "height_mm": 320, "colour_hex": "#4A3324"},
    "gable_brackets": {"type": "paired_scroll", "count": 4, "projection_mm": 220, "height_mm": 320, "colour_hex": "#4A3324"},
    "corbelling": {"present": True, "course_count": 3},
    "string_courses": {"present": True, "width_mm": 140, "projection_mm": 25, "colour_hex": "#D4C9A8"},
    "quoins": {"present": True, "strip_width_mm": 200, "projection_mm": 15, "colour_hex": "#D4C9A8"},
    "voussoirs": {"present": True, "colour_hex": "#D4C9A8"},
    "brick_voussoirs": {"present": True, "colour_hex": "#B85A3A"},
    "stone_voussoirs": {"present": True, "colour_hex": "#D4C9A8"},
    "stone_lintels": {"present": True, "colour_hex": "#D4C9A8"},
    "gable_shingles": {"present": True, "colour_hex": "#6B4C3B", "exposure_mm": 110},
    "dormers": {"present": True},
}


def merge_missing(target: dict, defaults: dict) -> bool:
    changed = False
    for key, value in defaults.items():
        if key not in target:
            target[key] = deepcopy(value)
            changed = True
        elif isinstance(target[key], dict) and isinstance(value, dict):
            changed = merge_missing(target[key], value) or changed
    return changed


def normalize_bay_window(data: dict) -> bool:
    bay = data.get("bay_window")
    if not isinstance(bay, dict):
        return False
    changed = False
    
    # Process floors_spanned if present, regardless of 'floors' presence
    if "floors_spanned" in bay:
        fs = bay.pop("floors_spanned")
        if isinstance(fs, list):
            bay["floors"] = [max(0, int(v) - 1) if isinstance(v, int) else v for v in fs]
        elif isinstance(fs, str):
            text = fs.lower()
            if "ground" in text and "second" in text:
                bay["floors"] = [0, 1]
            elif "ground" in text:
                bay["floors"] = [0]
            elif "second" in text:
                bay["floors"] = [1]
        elif isinstance(fs, (int, float)): # Convert integer floors_spanned to a list of floors
            num_floors_spanned = int(fs)
            if num_floors_spanned > 0:
                # Assuming it spans from the ground floor upwards
                bay["floors"] = list(range(num_floors_spanned))
            else:
                bay["floors"] = []
        changed = True

    if "present" not in bay:
        bay["present"] = True
        changed = True
    if bay.get("type") == "projecting_three_sided_bay":
        bay["type"] = "Three-sided projecting bay"
        changed = True
    return changed


def normalize_roof_features(data: dict) -> bool:
    roof_features = data.get("roof_features")
    changed = False

    # If roof_features is a string, convert it to a list first
    if isinstance(roof_features, str):
        roof_features = [roof_features]
        data["roof_features"] = roof_features # Update data with the new list
        changed = True
    elif not isinstance(roof_features, list):
        return False # Not a list or string, cannot normalize

    normalized = []
    for item in roof_features:
        if isinstance(item, dict):
            normalized.append(item)
            continue
        text = str(item).strip()
        lower = text.lower()
        if "oculus" in lower:
            normalized.append({"type": "oculus_window", "description": text})
            changed = True
        else:
            normalized.append(text)
    if changed:
        data["roof_features"] = normalized
    return changed


def normalize_file(path: Path) -> tuple[bool, str]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    # Skip non-building photos
    if data.get("skipped"):
        return False, "non-building (skipped)"

    # Check _meta.normalized flag for idempotency
    meta = data.get("_meta", {})
    if meta.get("normalized"):
        return False, "already normalized"

    # Store original state for change detection
    orig_data_dump = json.dumps(data, indent=2, ensure_ascii=False)
    
    changes_applied = []
    changed_flag = False # Use a flag to track if any changes were truly made

    dec = data.get("decorative_elements")
    if not isinstance(dec, dict):
        dec = {}
        data["decorative_elements"] = dec
        changed_flag = True
        changes_applied.append("decorative_elements_init")

    # Move top-level cornice
    if "cornice" in data and "cornice" not in dec and isinstance(data["cornice"], dict):
        dec["cornice"] = deepcopy(data["cornice"])
        del data["cornice"]
        changed_flag = True
        changes_applied.append("top_level_cornice")
    
    # Move top-level string_course
    if "string_course" in data and "string_courses" not in dec and isinstance(data["string_course"], dict):
        dec["string_courses"] = deepcopy(data["string_course"])
        del data["string_course"]
        changed_flag = True
        changes_applied.append("top_level_string_course")

    # Convert boolean decorative elements to structured dicts
    for key, defaults in BOOLEAN_DECORATIVE_DEFAULTS.items():
        if dec.get(key) is True:
            dec[key] = deepcopy(defaults)
            changed_flag = True
            changes_applied.append(f"{key}_bool_to_dict")
        elif dec.get(key) is False: # Convert False to structured dict with present=False
            defaults_copy = deepcopy(defaults)
            defaults_copy["present"] = False
            dec[key] = defaults_copy
            changed_flag = True
            changes_applied.append(f"{key}_bool_to_dict_false")
    
    # Handle string cornice to dict conversion
    if "cornice" in dec and isinstance(dec["cornice"], str):
        cornice_str = dec["cornice"]
        if cornice_str == "ornate": # Example: specific string conversion
            dec["cornice"] = {"present": True, "type": "ornate"}
            changed_flag = True
            changes_applied.append("cornice_string_to_dict")
        # Add other string conversions as needed
        
    # Ensure 'present' key for existing decorative elements that are dicts
    for key in ["cornice", "string_courses", "quoins"]: # Expanded to include common ones
        if key in dec and isinstance(dec[key], dict) and "present" not in dec[key]:
            dec[key]["present"] = True
            changed_flag = True
            changes_applied.append(f"{key}_ensure_present")

    # Capture changes from sub-functions
    if normalize_bay_window(data):
        changed_flag = True
        changes_applied.append("bay_window_floors")
    
    if normalize_roof_features(data):
        changed_flag = True
        changes_applied.append("roof_features")


    # After all normalizations, check if the data has actually changed
    new_data_dump = json.dumps(data, indent=2, ensure_ascii=False)

    if orig_data_dump == new_data_dump:
        return False, "no changes needed"

    # Update metadata
    meta["normalized"] = True
    meta["normalizations_applied"] = changes_applied if changes_applied else ["minor_adjustments"]
    data["_meta"] = meta

    _atomic_write_json(path, data)
    return True, ", ".join(meta["normalizations_applied"])


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Normalize decorative/detail schema across param files")
    parser.add_argument("--params-dir", type=Path, default=PARAMS_DIR)
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    parser.add_argument("--street", type=str, default=None, help="Only process buildings on this street")
    args = parser.parse_args()

    _configure_utf8_stdout()
    params_dir = args.params_dir

    changed = 0
    total = 0
    for path in sorted(params_dir.glob("*.json")):
        if path.name.startswith("_"):
            continue
        if args.street:
            try:
                d = json.loads(path.read_text(encoding="utf-8"))
                street = d.get("site", {}).get("street", "")
                if args.street.lower() not in street.lower():
                    continue
            except (json.JSONDecodeError, OSError):
                continue
        total += 1
        if normalize_file(path):
            changed += 1
            print(f"[NORMALIZE] {path.name}")
    print(f"\nNormalized {changed} of {total} files")


if __name__ == "__main__":
    main()


