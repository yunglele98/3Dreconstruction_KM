#!/usr/bin/env python3
"""Normalize decorative/detail schema across existing param files."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path


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
    if "floors_spanned" in bay and "floors" not in bay:
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
    if not isinstance(roof_features, list):
        return False
    changed = False
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


def normalize_file(path: Path) -> bool:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    # Skip non-building photos
    if data.get("skipped"):
        return False

    changed = False

    dec = data.get("decorative_elements")
    if not isinstance(dec, dict):
        dec = {}
        data["decorative_elements"] = dec
        changed = True

    if "cornice" in data and "cornice" not in dec and isinstance(data["cornice"], dict):
        dec["cornice"] = deepcopy(data["cornice"])
        changed = True
    if "string_course" in data and "string_courses" not in dec and isinstance(data["string_course"], dict):
        dec["string_courses"] = deepcopy(data["string_course"])
        changed = True

    for key, defaults in BOOLEAN_DECORATIVE_DEFAULTS.items():
        if dec.get(key) is True:
            dec[key] = deepcopy(defaults)
            changed = True

    if "cornice" in dec and isinstance(dec["cornice"], dict) and "present" not in dec["cornice"]:
        dec["cornice"]["present"] = True
        changed = True
    if "string_courses" in dec and isinstance(dec["string_courses"], dict) and "present" not in dec["string_courses"]:
        dec["string_courses"]["present"] = True
        changed = True
    if "quoins" in dec and isinstance(dec["quoins"], dict) and "present" not in dec["quoins"]:
        dec["quoins"]["present"] = True
        changed = True

    changed = normalize_bay_window(data) or changed
    changed = normalize_roof_features(data) or changed

    if changed:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
    return changed


def main() -> None:
    changed = 0
    total = 0
    for path in sorted(PARAMS_DIR.glob("*.json")):
        if path.name.startswith("_"):
            continue
        total += 1
        if normalize_file(path):
            changed += 1
            print(f"[NORMALIZE] {path.name}")
    print(f"\nNormalized {changed} of {total} files")


if __name__ == "__main__":
    main()
