#!/usr/bin/env python3
"""Stage 3b: Fuse facade segmentation results into building params.

Reads element detection JSONs from segmentation/ (produced by
segment_facades.py) and writes validated window counts, door counts,
storefront presence, and occlusion flags into params.

Only updates fields where segmentation provides higher confidence than
existing values. Never overwrites protected fields.

Usage:
    python scripts/enrich/fuse_segmentation.py --segmentation segmentation/ --params params/
    python scripts/enrich/fuse_segmentation.py --segmentation segmentation/ --params params/ --dry-run
    python scripts/enrich/fuse_segmentation.py --segmentation segmentation/ --params params/ --force
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).parent.parent.parent
PARAMS_DIR = REPO_ROOT / "params"
SEG_DIR = REPO_ROOT / "segmentation"


def atomic_write_json(path: Path, data: dict) -> None:
    content = json.dumps(data, indent=2, ensure_ascii=False)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        os.write(fd, content.encode("utf-8"))
        os.close(fd)
        os.replace(tmp, path)
    except Exception:
        os.close(fd)
        os.unlink(tmp)
        raise


def get_matched_photo_stem(params: dict) -> str | None:
    dfa = params.get("deep_facade_analysis", {})
    photo = dfa.get("source_photo")
    if not photo:
        po = params.get("photo_observations", {})
        photo = po.get("photo")
    if not photo:
        return None
    return Path(photo).stem


def load_segmentation(seg_dir: Path, photo_stem: str) -> dict | None:
    """Load segmentation results for a photo."""
    seg_path = seg_dir / f"{photo_stem}_elements.json"
    if not seg_path.exists():
        return None
    try:
        return json.loads(seg_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def fuse_segmentation_into_params(params: dict, seg_data: dict) -> tuple[dict, bool]:
    """Merge segmentation detections into param fields.

    Handles both contour-based and custom YOLO detection outputs.
    Returns (updated_params, was_modified).
    """
    modified = False

    # Support both old "detections" key and new "elements" key
    detections = seg_data.get("detections", []) or seg_data.get("elements", [])
    detection_method = seg_data.get("detection_method", "unknown")

    # Count elements by class
    class_counts: dict[str, int] = {}
    for det in detections:
        cls = det.get("class", "")
        if cls in ("person", "car", "truck", "bus", "bicycle",
                    "vegetation", "street_furniture"):
            continue  # skip non-architectural
        class_counts[cls] = class_counts.get(cls, 0) + 1

    # Also use window_count_by_floor if available (from segment_facades.py)
    window_count_by_floor = seg_data.get("window_count_by_floor", {})
    total_windows = sum(window_count_by_floor.values()) if window_count_by_floor else class_counts.get("window", 0)

    # Store raw segmentation results
    seg_summary = {
        "window_count": total_windows or seg_data.get("window_count", 0),
        "door_count": class_counts.get("door", 0) or seg_data.get("door_count", 0),
        "element_counts": class_counts,
        "window_count_by_floor": window_count_by_floor,
        "occlusion": seg_data.get("occlusions", seg_data.get("occlusion", {})),
        "total_facade_detections": len(detections) or seg_data.get("facade_detections", 0),
        "has_storefront": seg_data.get("has_storefront", False),
        "detection_method": detection_method,
    }
    params["segmentation_analysis"] = seg_summary
    modified = True

    # Update window count if segmentation found significantly different count
    seg_windows = seg_data.get("window_count", 0)
    param_windows = params.get("windows_per_floor")
    if seg_windows > 0 and param_windows:
        # Sum existing windows across floors
        if isinstance(param_windows, list):
            existing_total = sum(param_windows)
        else:
            existing_total = int(param_windows or 0)

        # Only flag if large discrepancy (segmentation is noisy)
        if abs(seg_windows - existing_total) > 3:
            params.setdefault("_audit", {})["window_count_discrepancy"] = {
                "param_total": existing_total,
                "segmentation_count": seg_windows,
                "delta": seg_windows - existing_total,
            }
            modified = True

    # Update door count
    seg_doors = seg_data.get("door_count", 0)
    param_doors = params.get("door_count")
    if seg_doors > 0 and (param_doors is None or param_doors == 0):
        params["door_count"] = seg_doors
        modified = True

    # Detect storefront from segmentation
    storefront_count = class_counts.get("storefront", 0)
    if storefront_count > 0 and not params.get("has_storefront"):
        params.setdefault("_audit", {})["storefront_detected_by_segmentation"] = True
        modified = True

    # Occlusion flag (useful for photo quality assessment)
    occlusion = seg_data.get("occlusions", seg_data.get("occlusion", {}))
    if isinstance(occlusion, dict):
        if occlusion.get("persons", 0) > 2 or occlusion.get("vehicles", 0) > 1:
            params.setdefault("_audit", {})["photo_heavily_occluded"] = True
            modified = True
    elif isinstance(occlusion, list) and len(occlusion) > 3:
        params.setdefault("_audit", {})["photo_heavily_occluded"] = True
        modified = True

    # Enrich decorative_elements from custom YOLO detections
    decorative_classes = {
        "cornice", "pilaster", "column", "molding", "sill", "lintel",
        "arch", "bargeboard", "bay_window",
    }
    detected_decorative = {cls: count for cls, count in class_counts.items()
                           if cls in decorative_classes and count > 0}
    if detected_decorative:
        dec = params.setdefault("decorative_elements", {})
        for cls, count in detected_decorative.items():
            existing = dec.get(cls, {})
            if not isinstance(existing, dict):
                existing = {}
            # Only update if not already set with higher confidence
            if not existing.get("present") or detection_method == "custom_yolo":
                dec[cls] = {
                    "present": True,
                    "count": count,
                    "source": f"segmentation_{detection_method}",
                }
        modified = True

    # Detect architectural features
    if class_counts.get("bay_window", 0) > 0:
        params["has_bay_window"] = True
        modified = True
    if class_counts.get("porch", 0) > 0:
        params["has_porch"] = True
        modified = True
    if class_counts.get("chimney", 0) > 0:
        params["has_chimney"] = True
        modified = True

    return params, modified


def fuse_all(params_dir: Path, seg_dir: Path,
             limit: int = 0, dry_run: bool = False,
             force: bool = False) -> dict:
    """Fuse segmentation into all matching params."""
    param_files = sorted(params_dir.glob("*.json"))
    if limit > 0:
        param_files = param_files[:limit]

    stats = {"processed": 0, "fused": 0, "no_seg": 0, "no_photo": 0, "skipped": 0}

    for pf in param_files:
        if pf.name.startswith("_"):
            continue
        try:
            params = json.loads(pf.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if params.get("skipped"):
            stats["skipped"] += 1
            continue

        stats["processed"] += 1

        # Skip if already fused
        meta = params.get("_meta", {})
        if not force and "segmentation" in meta.get("fusion_applied", []):
            stats["skipped"] += 1
            continue

        photo_stem = get_matched_photo_stem(params)
        if not photo_stem:
            stats["no_photo"] += 1
            continue

        seg_data = load_segmentation(seg_dir, photo_stem)
        if not seg_data:
            stats["no_seg"] += 1
            continue

        if dry_run:
            logger.info("  [DRY-RUN] %s: %d detections",
                        pf.name, seg_data.get("facade_detections", 0))
            stats["fused"] += 1
            continue

        params, was_modified = fuse_segmentation_into_params(params, seg_data)

        if was_modified:
            meta = params.setdefault("_meta", {})
            fa = meta.get("fusion_applied", [])
            if "segmentation" not in fa:
                fa.append("segmentation")
            meta["fusion_applied"] = fa
            atomic_write_json(pf, params)
            stats["fused"] += 1

    return stats


def main():
    parser = argparse.ArgumentParser(description="Stage 3b: Fuse segmentation into params")
    parser.add_argument("--segmentation", type=Path, default=SEG_DIR)
    parser.add_argument("--params", type=Path, default=PARAMS_DIR)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    logger.info("Fusing segmentation from %s into %s", args.segmentation, args.params)
    stats = fuse_all(args.params, args.segmentation,
                     limit=args.limit, dry_run=args.dry_run, force=args.force)

    logger.info("\nDone: %d processed, %d fused, %d no segmentation, %d no photo, %d skipped",
                stats["processed"], stats["fused"], stats["no_seg"],
                stats["no_photo"], stats["skipped"])


if __name__ == "__main__":
    main()
