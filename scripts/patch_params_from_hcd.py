#!/usr/bin/env python3
"""Upgrade existing param JSON files with structured HCD-derived defaults."""

from __future__ import annotations

import json
import os
import tempfile
from copy import deepcopy
from pathlib import Path

from generate_hcd_params import infer_decorative_elements


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


def merge_missing_dict(target: dict, defaults: dict) -> bool:
    changed = False
    for key, value in defaults.items():
        if key not in target:
            target[key] = deepcopy(value)
            changed = True
        elif isinstance(target[key], dict) and isinstance(value, dict):
            changed = merge_missing_dict(target[key], value) or changed
    return changed


def upgrade_decorative_elements(data: dict, inferred: dict) -> bool:
    existing = data.get("decorative_elements")
    if not isinstance(existing, dict):
        data["decorative_elements"] = deepcopy(inferred)
        return bool(inferred)

    changed = False
    for key, value in inferred.items():
        if key not in existing:
            existing[key] = deepcopy(value)
            changed = True
            continue

        current = existing[key]
        if current is True and isinstance(value, dict):
            existing[key] = deepcopy(value)
            changed = True
        elif isinstance(current, dict) and isinstance(value, dict):
            changed = merge_missing_dict(current, value) or changed

    return changed


def ensure_bay_window(data: dict, features: list[str], typology: str) -> bool:
    if "bay_window" in data:
        return False

    feature_text = " | ".join(features).lower()
    typ_lower = typology.lower()
    if not any(term in feature_text for term in ["bay window", "bay windows", "double-height bay", "double-height bays"]):
        return False

    data["bay_window"] = {
        "present": True,
        "type": "Three-sided projecting bay" if "bay-and-gable" in typ_lower else "Projecting bay",
        "floors": [0, 1] if ("double-height" in feature_text or "bay-and-gable" in typ_lower) else [0],
        "width_m": 2.2,
        "projection_m": 0.6,
    }
    return True


def ensure_storefront(data: dict) -> bool:
    if not data.get("has_storefront") or "storefront" in data:
        return False

    floor_heights = data.get("floor_heights_m", [])
    height = floor_heights[0] if floor_heights else 3.5
    data["storefront"] = {
        "type": "Commercial ground floor",
        "width_m": data.get("facade_width_m", 6.0),
        "height_m": height,
    }
    return True


def enrich_windows_detail(data: dict) -> bool:
    windows_detail = data.get("windows_detail")
    windows_per_floor = data.get("windows_per_floor", [])
    if not isinstance(windows_detail, list) or not isinstance(windows_per_floor, list):
        return False

    changed = False
    default_width = data.get("window_width_m", 0.85)
    default_height = data.get("window_height_m", 1.3)
    window_type = str(data.get("window_type", "")).lower()
    head_shape = None
    if "segment" in window_type:
        head_shape = "segmental_arch"
    elif "arch" in window_type:
        head_shape = "semicircular_arch"

    for floor_data in windows_detail:
        if not isinstance(floor_data, dict):
            continue
        floor_label = str(floor_data.get("floor", "")).lower()
        if floor_label in {"all_upper", "upper", "upper_floors"}:
            continue
        if floor_data.get("windows") or "count" in floor_data or "estimated_count" in floor_data:
            continue

        floor_num = None
        if isinstance(floor_data.get("floor"), int):
            floor_num = floor_data["floor"]
        elif floor_label == "ground floor":
            floor_num = 1
        elif floor_label == "second floor":
            floor_num = 2
        elif floor_label == "third floor":
            floor_num = 3

        if floor_num and 1 <= floor_num <= len(windows_per_floor):
            count = windows_per_floor[floor_num - 1]
            if isinstance(count, int) and count > 0:
                floor_data["count"] = count
                floor_data.setdefault("width_m", default_width)
                floor_data.setdefault("height_m", default_height)
                if head_shape:
                    floor_data.setdefault("head_shape", head_shape)
                changed = True

    return changed


def patch_file(path: Path) -> tuple[bool, str]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    # Skip non-building photos
    if data.get("skipped"):
        return False, "non-building (skipped)"

    # Check _meta.patched flag for idempotency
    meta = data.get("_meta", {})
    if meta.get("patched"):
        return False, "already patched"

    hcd = data.get("hcd_data")
    if not isinstance(hcd, dict):
        return False, "no HCD data"

    features = hcd.get("building_features", [])
    typology = hcd.get("typology", "")

    print(f"DEBUG: patch_file: features={features}, typology='{typology}'")
    inferred_decorative, inferred_roof, inferred_windows = infer_decorative_elements(features, typology)
    print(f"DEBUG: inferred_decorative={inferred_decorative}")
    print(f"DEBUG: inferred_roof={inferred_roof}")
    print(f"DEBUG: inferred_windows={inferred_windows}")

    orig_data_dump = json.dumps(data, indent=2, ensure_ascii=False)
    changes_applied = []

    if upgrade_decorative_elements(data, inferred_decorative):
        changes_applied.append("decorative_elements")

    if inferred_roof:
        roof_features = data.get("roof_features")
        if roof_features is None:
            data["roof_features"] = sorted(set(inferred_roof))
            changes_applied.append("roof_features_init")
        elif isinstance(roof_features, list):
            existing = {str(item) for item in roof_features}
            for item in inferred_roof:
                if item not in existing:
                    roof_features.append(item)
                    changes_applied.append("roof_features_merge")

    if inferred_windows and not data.get("windows_detail"):
        data["windows_detail"] = deepcopy(inferred_windows)
        changes_applied.append("windows_detail")

    if ensure_bay_window(data, [str(f) for f in features], typology):
        changes_applied.append("bay_window")
    
    if ensure_storefront(data):
        changes_applied.append("storefront")
    
    if enrich_windows_detail(data):
        changes_applied.append("windows_detail_enrich")

    new_data_dump = json.dumps(data, indent=2, ensure_ascii=False)

    print(f"DEBUG: changes_applied before return: {changes_applied}")

    if orig_data_dump == new_data_dump:
        return False, "no changes needed"

    # Update metadata
    meta["patched"] = True
    meta["patches_applied"] = changes_applied if changes_applied else ["minor_adjustments"]
    data["_meta"] = meta

    _atomic_write_json(path, data)

    return True, ", ".join(meta["patches_applied"])


def main() -> None:
    changed_count = 0
    files = 0
    for path in sorted(PARAMS_DIR.glob("*.json")):
        if path.name.startswith("_"):
            continue
        files += 1
        is_changed, msg = patch_file(path)
        if is_changed:
            changed_count += 1
            print(f"[PATCH] {path.name}: {msg}")
        # else:
            # print(f"[NO CHANGE] {path.name}: {msg}") # Optional: print why it wasn't changed
    print(f"\nPatched {changed_count} of {files} files")


if __name__ == "__main__":
    main()
