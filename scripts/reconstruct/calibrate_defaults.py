#!/usr/bin/env python3
"""Calibrate procedural generation defaults from scanned/extracted elements.

Analyzes element catalog (extracted from photogrammetry, LiDAR, or scans)
to compute better default dimensions for the parametric generator. For example,
if scanned windows average 1.1m wide, update the default from the assumed 0.9m.

Usage:
    python scripts/reconstruct/calibrate_defaults.py --elements assets/elements/metadata/element_catalog.json
    python scripts/reconstruct/calibrate_defaults.py --elements assets/elements/metadata/ --output calibrated_defaults.json
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# Current hardcoded defaults in generate_building.py
CURRENT_DEFAULTS = {
    "window_width_m": 0.9,
    "window_height_m": 1.5,
    "door_width_m": 0.9,
    "door_height_m": 2.1,
    "storefront_height_m": 3.0,
    "cornice_height_mm": 200,
    "cornice_projection_mm": 150,
    "string_course_width_mm": 100,
    "quoin_width_mm": 200,
    "eave_overhang_mm": 300,
    "foundation_height_m": 0.3,
    "floor_height_m": 3.0,
    "wall_thickness_m": 0.3,
    "porch_depth_m": 1.5,
    "bay_window_projection_m": 0.6,
}


def load_element_catalog(catalog_path: Path) -> list[dict]:
    """Load element observations from catalog file(s).

    Supports single JSON file or directory of JSON files.
    """
    elements = []
    if catalog_path.is_file():
        data = json.loads(catalog_path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            elements = data
        elif isinstance(data, dict):
            elements = data.get("elements", [])
    elif catalog_path.is_dir():
        for f in sorted(catalog_path.glob("*_elements.json")):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                elements.extend(data.get("elements", []))
            except (json.JSONDecodeError, OSError):
                pass
    return elements


def load_param_observations(params_dir: Path) -> list[dict]:
    """Extract dimension observations from building params.

    Uses windows_detail, doors_detail, and other measured fields
    to build a dataset of real-world element dimensions.
    """
    observations = []
    for f in sorted(params_dir.glob("*.json")):
        if f.name.startswith("_"):
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if data.get("skipped"):
            continue

        # Window dimensions from windows_detail
        for floor_data in data.get("windows_detail", []):
            for win in floor_data.get("windows", []):
                w = win.get("width_m", 0)
                h = win.get("height_m", 0)
                if 0.3 < w < 3.0:
                    observations.append({"type": "window", "dimension": "width_m", "value": w})
                if 0.5 < h < 3.0:
                    observations.append({"type": "window", "dimension": "height_m", "value": h})

        # Door dimensions from doors_detail
        for door in data.get("doors_detail", []):
            w = door.get("width_m", 0)
            h = door.get("height_m", 0)
            if 0.5 < w < 2.0:
                observations.append({"type": "door", "dimension": "width_m", "value": w})
            if 1.5 < h < 3.5:
                observations.append({"type": "door", "dimension": "height_m", "value": h})

        # Decorative elements
        dec = data.get("decorative_elements", {})
        if isinstance(dec, dict):
            cornice = dec.get("cornice", {})
            if isinstance(cornice, dict) and cornice.get("height_mm"):
                observations.append({"type": "cornice", "dimension": "height_mm",
                                     "value": cornice["height_mm"]})
            if isinstance(cornice, dict) and cornice.get("projection_mm"):
                observations.append({"type": "cornice", "dimension": "projection_mm",
                                     "value": cornice["projection_mm"]})

        # Eave overhang
        eave = data.get("roof_detail", {}).get("eave_overhang_mm")
        if eave and 100 < eave < 1000:
            observations.append({"type": "eave", "dimension": "overhang_mm", "value": eave})

    return observations


def calibrate(observations: list[dict]) -> dict:
    """Compute calibrated defaults from observations.

    Returns dict mapping default keys to calibrated values with stats.
    """
    # Group by type+dimension
    by_key: dict[str, list[float]] = defaultdict(list)
    for obs in observations:
        key = f"{obs['type']}_{obs['dimension']}"
        by_key[key].append(obs["value"])

    # Map observation keys to default keys
    KEY_MAP = {
        "window_width_m": "window_width_m",
        "window_height_m": "window_height_m",
        "door_width_m": "door_width_m",
        "door_height_m": "door_height_m",
        "cornice_height_mm": "cornice_height_mm",
        "cornice_projection_mm": "cornice_projection_mm",
        "eave_overhang_mm": "eave_overhang_mm",
    }

    calibrated = {}
    for obs_key, values in by_key.items():
        if len(values) < 5:
            continue  # Not enough data

        arr = np.array(values)
        # Remove outliers (beyond 2 sigma)
        mean = np.mean(arr)
        std = np.std(arr)
        if std > 0:
            arr = arr[np.abs(arr - mean) < 2 * std]

        if len(arr) < 3:
            continue

        default_key = KEY_MAP.get(obs_key)
        calibrated[obs_key] = {
            "median": round(float(np.median(arr)), 3),
            "mean": round(float(np.mean(arr)), 3),
            "std": round(float(np.std(arr)), 3),
            "count": len(arr),
            "current_default": CURRENT_DEFAULTS.get(default_key),
            "recommended": round(float(np.median(arr)), 3),
        }

    return calibrated


def main():
    parser = argparse.ArgumentParser(description="Calibrate procedural defaults from observations")
    parser.add_argument("--elements", type=Path,
                        default=REPO_ROOT / "assets" / "elements" / "metadata")
    parser.add_argument("--params", type=Path, default=REPO_ROOT / "params")
    parser.add_argument("--output", type=Path,
                        default=REPO_ROOT / "assets" / "elements" / "metadata" / "calibrated_defaults.json")
    args = parser.parse_args()

    # Collect observations from both sources
    catalog_obs = load_element_catalog(args.elements)
    param_obs = load_param_observations(args.params)
    all_obs = catalog_obs + param_obs

    print(f"Observations: {len(catalog_obs)} from element catalog, {len(param_obs)} from params")

    calibrated = calibrate(all_obs)

    print(f"\nCalibrated defaults ({len(calibrated)} dimensions):")
    for key, stats in sorted(calibrated.items()):
        current = stats.get("current_default")
        rec = stats["recommended"]
        delta = f" (delta: {rec - current:+.3f})" if current else ""
        print(f"  {key}: {rec} (n={stats['count']}, std={stats['std']}){delta}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(calibrated, indent=2), encoding="utf-8")
    print(f"\nOutput: {args.output}")


if __name__ == "__main__":
    main()
