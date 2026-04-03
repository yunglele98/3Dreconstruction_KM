#!/usr/bin/env python3
"""Fuse segmentation observations into building parameter files.

Reads element JSON files from Stage 1 (YOLOv11+SAM2) and extracts
window counts per floor, door count, storefront presence, and detected
decorative elements. Results are written into each param's
`segmentation_observations` dict, and "segmentation" is appended to
`_meta.fusion_applied`.

Usage:
    python scripts/enrich/fuse_segmentation.py
    python scripts/enrich/fuse_segmentation.py --segmentation segmentation/ --params params/
"""

import argparse
import json
import os
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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


def _sanitize_address(filename):
    """Convert param filename to address key: strip .json, replace _ with space."""
    return Path(filename).stem.replace("_", " ")


def _address_to_stem(address):
    """Convert address string to filename stem (spaces to underscores)."""
    return address.replace(" ", "_")


def _find_segmentation(seg_dir, address):
    """Find a matching segmentation JSON file for an address.

    Tries exact stem match first, then case-insensitive glob.
    """
    stem = _address_to_stem(address)
    # Direct match
    candidate = seg_dir / f"{stem}.json"
    if candidate.exists():
        return candidate
    # Also check with _elements suffix
    candidate = seg_dir / f"{stem}_elements.json"
    if candidate.exists():
        return candidate
    # Case-insensitive search
    stem_lower = stem.lower()
    for f in seg_dir.glob("*.json"):
        f_stem_lower = f.stem.lower()
        if f_stem_lower == stem_lower or f_stem_lower == f"{stem_lower}_elements":
            return f
    return None


# Element class labels expected from YOLOv11+SAM2
WINDOW_LABELS = {"window", "window_frame", "bay_window", "arched_window"}
DOOR_LABELS = {"door", "entrance", "door_frame"}
STOREFRONT_LABELS = {"storefront", "shop_front", "commercial_window",
                     "display_window"}
DECORATIVE_LABELS = {"cornice", "string_course", "quoin", "voussoir",
                     "bracket", "bargeboard", "finial", "pilaster",
                     "decorative_brick", "ornamental_shingle"}


def _extract_observations(seg_data):
    """Extract structured observations from segmentation JSON.

    Expects seg_data to be a dict or list of detected elements, each with
    at least 'label'/'class' and optionally 'bbox'/'floor'/'confidence'.
    """
    observations = {}

    # Normalize: handle both list-of-elements and dict-with-elements-key
    elements = seg_data
    if isinstance(seg_data, dict):
        elements = seg_data.get("elements", seg_data.get("detections", []))
        if isinstance(elements, dict):
            elements = []

    if not isinstance(elements, list):
        return {}

    # Count by label category
    window_count = 0
    door_count = 0
    storefront_detected = False
    decorative_elements = []
    windows_by_floor = {}

    for elem in elements:
        if not isinstance(elem, dict):
            continue

        label = (elem.get("label") or elem.get("class") or "").lower().strip()
        floor = elem.get("floor")
        confidence = elem.get("confidence")

        # Skip low-confidence detections
        if confidence is not None and confidence < 0.3:
            continue

        if label in WINDOW_LABELS or "window" in label:
            window_count += 1
            if floor is not None:
                floor_key = str(floor)
                windows_by_floor[floor_key] = windows_by_floor.get(floor_key, 0) + 1

        elif label in DOOR_LABELS or "door" in label:
            door_count += 1

        elif label in STOREFRONT_LABELS or "storefront" in label:
            storefront_detected = True

        elif label in DECORATIVE_LABELS:
            if label not in decorative_elements:
                decorative_elements.append(label)

    observations["windows_total"] = window_count
    observations["door_count"] = door_count
    observations["has_storefront"] = storefront_detected

    if windows_by_floor:
        observations["windows_by_floor"] = windows_by_floor

    if decorative_elements:
        observations["decorative_elements_detected"] = sorted(decorative_elements)

    observations["total_elements_detected"] = len(elements)

    return observations


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def fuse_segmentation(seg_dir, params_dir):
    """Fuse segmentation data into all matching param files."""
    seg_dir = Path(seg_dir)
    params_dir = Path(params_dir)

    fused = 0
    skipped_no_data = 0
    skipped_already = 0
    skipped_other = 0

    for param_file in sorted(params_dir.glob("*.json")):
        # Skip metadata files
        if param_file.name.startswith("_"):
            skipped_other += 1
            continue

        with open(param_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Skip non-building entries
        if data.get("skipped"):
            skipped_other += 1
            continue

        # Check idempotency
        meta = data.setdefault("_meta", {})
        fusion_applied = meta.setdefault("fusion_applied", [])
        if "segmentation" in fusion_applied:
            skipped_already += 1
            continue

        # Find matching segmentation file
        address = _sanitize_address(param_file.name)
        seg_file = _find_segmentation(seg_dir, address)
        if seg_file is None:
            skipped_no_data += 1
            continue

        try:
            with open(seg_file, "r", encoding="utf-8") as f:
                seg_data = json.load(f)
        except (json.JSONDecodeError, OSError):
            skipped_no_data += 1
            continue

        observations = _extract_observations(seg_data)
        if not observations:
            skipped_no_data += 1
            continue

        observations["source_file"] = seg_file.name

        # Write into params
        data["segmentation_observations"] = observations
        fusion_applied.append("segmentation")

        _atomic_write_json(param_file, data)
        fused += 1

    print(f"Fused {fused} buildings, skipped {skipped_no_data} (no data), "
          f"skipped {skipped_already} (already fused)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Fuse segmentation observations into building params"
    )
    parser.add_argument(
        "--segmentation", type=Path, default=REPO_ROOT / "segmentation",
        help="Directory containing segmentation JSON files (default: segmentation/)"
    )
    parser.add_argument(
        "--params", type=Path, default=REPO_ROOT / "params",
        help="Directory containing building param JSON files (default: params/)"
    )
    args = parser.parse_args()
    fuse_segmentation(args.segmentation, args.params)
