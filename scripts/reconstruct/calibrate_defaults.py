#!/usr/bin/env python3
"""Calibrate procedural generator defaults from scanned element dimensions.

Reads an element catalog (from extract_elements.py or iPad LiDAR scans),
computes average dimensions by element type, and writes a default_dimensions
file used to calibrate the procedural generator.

Usage:
    python scripts/reconstruct/calibrate_defaults.py --elements assets/elements/metadata/element_catalog.json
    python scripts/reconstruct/calibrate_defaults.py --scan-dir assets/elements/
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
CATALOG_DEFAULT = REPO_ROOT / "assets" / "elements" / "metadata" / "element_catalog.json"
ELEMENTS_DIR = REPO_ROOT / "assets" / "elements"
OUTPUT_DEFAULT = REPO_ROOT / "assets" / "elements" / "metadata" / "default_dimensions.json"

# Generator default dimensions to calibrate
GENERATOR_DEFAULTS = {
    "window": {
        "width_m": 0.9,
        "height_m": 1.5,
        "sill_height_m": 0.9,
        "frame_width_mm": 50,
    },
    "door": {
        "width_m": 0.9,
        "height_m": 2.1,
        "frame_width_mm": 75,
    },
    "bay_window": {
        "width_m": 2.0,
        "projection_m": 0.5,
        "height_m": 2.5,
    },
    "cornice": {
        "height_mm": 200,
        "projection_mm": 150,
    },
    "string_course": {
        "width_mm": 75,
        "projection_mm": 30,
    },
    "quoin": {
        "strip_width_mm": 150,
        "projection_mm": 20,
    },
    "bracket": {
        "height_mm": 250,
        "projection_mm": 200,
        "width_mm": 100,
    },
    "dormer": {
        "width_m": 1.2,
        "height_m": 1.5,
    },
    "chimney": {
        "width_m": 0.6,
        "depth_m": 0.6,
        "height_m": 1.5,
    },
    "porch": {
        "depth_m": 1.5,
        "height_m": 2.7,
        "column_diameter_mm": 150,
    },
    "foundation": {
        "height_m": 0.4,
    },
    "storefront": {
        "height_m": 3.5,
        "entrance_width_m": 1.2,
    },
}


def load_catalog(catalog_path):
    """Load element catalog JSON."""
    if not catalog_path.exists():
        return None
    try:
        return json.loads(catalog_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        print(f"WARNING: Could not load catalog: {e}")
        return None


def scan_element_directories(elements_dir):
    """Build a catalog from element directory structure.

    Scans assets/elements/ for per-building element manifests
    and aggregates dimension data.
    """
    catalog = []

    # Scan by_type directory
    by_type_dir = elements_dir / "by_type"
    if by_type_dir.exists():
        for type_dir in sorted(by_type_dir.iterdir()):
            if not type_dir.is_dir():
                continue
            for obj_file in type_dir.glob("*.obj"):
                dims = measure_obj_bounds(obj_file)
                if dims:
                    catalog.append({
                        "type": type_dir.name,
                        "source": str(obj_file),
                        "dimensions": dims,
                    })

    # Scan per-building element extractions
    for building_dir in sorted(elements_dir.iterdir()):
        if not building_dir.is_dir():
            continue
        manifest = building_dir / "elements.json"
        if not manifest.exists():
            continue

        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue

        for element_type in data.get("elements", {}):
            obj_path = building_dir / f"{element_type}.obj"
            if obj_path.exists():
                dims = measure_obj_bounds(obj_path)
                if dims:
                    catalog.append({
                        "type": element_type,
                        "source": str(obj_path),
                        "building": building_dir.name,
                        "dimensions": dims,
                    })

    return catalog


def measure_obj_bounds(obj_path):
    """Measure bounding box dimensions of an OBJ file."""
    xs, ys, zs = [], [], []

    try:
        with open(obj_path, encoding="utf-8") as f:
            for line in f:
                if line.startswith("v "):
                    parts = line.strip().split()
                    if len(parts) >= 4:
                        xs.append(float(parts[1]))
                        ys.append(float(parts[2]))
                        zs.append(float(parts[3]))
    except (OSError, ValueError):
        return None

    if not xs:
        return None

    return {
        "width_m": round(max(xs) - min(xs), 4),
        "depth_m": round(max(ys) - min(ys), 4),
        "height_m": round(max(zs) - min(zs), 4),
    }


def compute_averages(catalog):
    """Compute average dimensions by element type."""
    by_type = defaultdict(list)

    for entry in catalog:
        element_type = entry.get("type", "unknown").lower()
        dims = entry.get("dimensions", {})
        if dims:
            by_type[element_type].append(dims)

    averages = {}
    for element_type, dim_list in sorted(by_type.items()):
        if not dim_list:
            continue

        avg = {}
        # Collect all dimension keys
        all_keys = set()
        for d in dim_list:
            all_keys.update(d.keys())

        for key in sorted(all_keys):
            values = [d[key] for d in dim_list if key in d and d[key] > 0]
            if values:
                avg[key] = round(sum(values) / len(values), 4)
                avg[f"{key}_min"] = round(min(values), 4)
                avg[f"{key}_max"] = round(max(values), 4)
                avg[f"{key}_count"] = len(values)

        averages[element_type] = avg

    return averages


def merge_with_generator_defaults(averages):
    """Merge scanned averages with generator defaults.

    Scanned data takes priority where available;
    generator defaults fill gaps.
    """
    calibrated = {}

    for element_type, defaults in GENERATOR_DEFAULTS.items():
        entry = dict(defaults)  # start with generator defaults
        entry["source"] = "generator_default"

        if element_type in averages:
            scanned = averages[element_type]
            # Map scanned dimensions to generator parameter names
            dim_mapping = {
                "width_m": "width_m",
                "height_m": "height_m",
                "depth_m": "depth_m",
            }
            for scanned_key, gen_key in dim_mapping.items():
                if scanned_key in scanned and gen_key in entry:
                    entry[gen_key] = scanned[scanned_key]
                    entry["source"] = "scanned"

            # Include stats
            entry["_scanned_stats"] = {
                k: v for k, v in scanned.items()
                if k.endswith("_min") or k.endswith("_max") or k.endswith("_count")
            }

        calibrated[element_type] = entry

    # Include any scanned types not in generator defaults
    for element_type, scanned in averages.items():
        if element_type not in calibrated:
            calibrated[element_type] = {
                "width_m": scanned.get("width_m"),
                "height_m": scanned.get("height_m"),
                "depth_m": scanned.get("depth_m"),
                "source": "scanned",
                "_scanned_stats": {
                    k: v for k, v in scanned.items()
                    if k.endswith("_min") or k.endswith("_max") or k.endswith("_count")
                },
            }

    return calibrated


def main():
    parser = argparse.ArgumentParser(
        description="Calibrate procedural generator defaults from scanned element dimensions."
    )
    parser.add_argument("--elements", type=Path, default=CATALOG_DEFAULT,
                        help="Element catalog JSON file")
    parser.add_argument("--scan-dir", type=Path, default=ELEMENTS_DIR,
                        help="Directory to scan for element meshes (fallback)")
    parser.add_argument("--output", type=Path, default=OUTPUT_DEFAULT,
                        help="Output default dimensions JSON")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    # Load or build catalog
    catalog = load_catalog(args.elements)

    if not catalog:
        print(f"No catalog at {args.elements}, scanning element directories...")
        if args.scan_dir.exists():
            catalog = scan_element_directories(args.scan_dir)
        else:
            catalog = []

    if not catalog:
        print("No element data found. Writing generator defaults only.")
        calibrated = {k: dict(v, source="generator_default") for k, v in GENERATOR_DEFAULTS.items()}
    else:
        print(f"Loaded {len(catalog)} element entries")

        # Compute averages
        averages = compute_averages(catalog)
        print(f"  Element types with scanned data: {len(averages)}")
        for etype, avg in sorted(averages.items()):
            count = max(
                (avg.get(f"{k}_count", 0) for k in ["width_m", "height_m", "depth_m"]),
                default=0,
            )
            print(f"    {etype}: {count} samples")

        # Merge with generator defaults
        calibrated = merge_with_generator_defaults(averages)

    if args.dry_run:
        print("\nCalibrated defaults (dry run):")
        print(json.dumps(calibrated, indent=2, ensure_ascii=False))
        return

    # Write output
    args.output.parent.mkdir(parents=True, exist_ok=True)

    output_data = {
        "description": "Calibrated element dimensions from scanned data + generator defaults",
        "catalog_entries": len(catalog) if catalog else 0,
        "defaults": calibrated,
    }

    args.output.write_text(
        json.dumps(output_data, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"\nWrote calibrated defaults to {args.output}")
    print(f"  {len(calibrated)} element types")
    scanned_count = sum(1 for v in calibrated.values() if v.get("source") == "scanned")
    print(f"  {scanned_count} calibrated from scans, {len(calibrated) - scanned_count} generator defaults")


if __name__ == "__main__":
    main()
