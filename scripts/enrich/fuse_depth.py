#!/usr/bin/env python3
"""Stage 3b: Fuse monocular depth maps into building params.

Reads depth maps (.npy) produced by extract_depth.py and the matched photo
reference in each param file. Extracts relative depth features from the
facade region and writes estimates for:

- depth_notes.setback_m_est (facade plane distance relative to neighbours)
- depth_notes.foundation_height_m_est (ground-to-facade base distance)
- depth_notes.eave_overhang_mm_est (roof edge projection)
- depth_notes.bay_window_projection_m_est (bay window depth vs facade plane)

All values are relative estimates (monocular depth is scale-ambiguous).
Absolute calibration comes from LiDAR or known building dimensions.

Follows existing idempotent pattern: skip _-prefixed, skip skipped, only
write if modified, track in _meta.fusion_applied.

Usage:
    python scripts/enrich/fuse_depth.py --depth-maps depth_maps/ --params params/
    python scripts/enrich/fuse_depth.py --depth-maps depth_maps/ --params params/ --limit 10
    python scripts/enrich/fuse_depth.py --depth-maps depth_maps/ --params params/ --dry-run
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import tempfile
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).parent.parent.parent
PARAMS_DIR = REPO_ROOT / "params"
DEPTH_DIR = REPO_ROOT / "depth_maps"


def load_param(path: Path) -> dict | None:
    """Load a param JSON, skipping metadata and non-buildings."""
    if path.name.startswith("_"):
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if data.get("skipped"):
        return None
    return data


def get_matched_photo_stem(params: dict) -> str | None:
    """Get the photo filename stem from a param file."""
    dfa = params.get("deep_facade_analysis", {})
    photo = dfa.get("source_photo")
    if not photo:
        po = params.get("photo_observations", {})
        photo = po.get("photo")
    if not photo:
        return None
    return Path(photo).stem


def analyze_depth_map(depth: np.ndarray) -> dict:
    """Extract facade-relevant features from a depth map.

    The depth map is relative (closer = smaller values typically, but
    model-dependent). We normalize to 0-1 range and analyze regions.
    """
    h, w = depth.shape[:2]
    if h == 0 or w == 0:
        return {}

    # Normalize to 0-1
    d_min, d_max = float(depth.min()), float(depth.max())
    if d_max - d_min < 1e-6:
        return {}
    depth_norm = (depth - d_min) / (d_max - d_min)

    # Define regions
    # Facade centre: middle 60% horizontally, 20-80% vertically
    cy1, cy2 = int(h * 0.2), int(h * 0.8)
    cx1, cx2 = int(w * 0.2), int(w * 0.8)
    facade = depth_norm[cy1:cy2, cx1:cx2]

    # Foundation: bottom 15% of image, centre 60% horizontal
    fy1 = int(h * 0.85)
    foundation = depth_norm[fy1:, cx1:cx2]

    # Roof/eave: top 15%, centre 60%
    ry2 = int(h * 0.15)
    roof = depth_norm[:ry2, cx1:cx2]

    # Left edge (potential bay window): left 20%, middle 50% vertical
    bay_left = depth_norm[int(h * 0.25):int(h * 0.75), :int(w * 0.2)]

    # Right edge
    bay_right = depth_norm[int(h * 0.25):int(h * 0.75), int(w * 0.8):]

    facade_mean = float(facade.mean()) if facade.size > 0 else 0.5
    facade_std = float(facade.std()) if facade.size > 0 else 0.0
    foundation_mean = float(foundation.mean()) if foundation.size > 0 else facade_mean
    roof_mean = float(roof.mean()) if roof.size > 0 else facade_mean

    # Bay window detection: is there a region significantly closer than facade?
    bay_left_mean = float(bay_left.mean()) if bay_left.size > 0 else facade_mean
    bay_right_mean = float(bay_right.mean()) if bay_right.size > 0 else facade_mean

    # Relative depth differences (positive = closer to camera than facade plane)
    # Note: "closer" direction depends on model. We use relative differences.
    features = {
        "facade_depth_mean": round(facade_mean, 4),
        "facade_depth_std": round(facade_std, 4),
        "foundation_offset": round(foundation_mean - facade_mean, 4),
        "roof_offset": round(roof_mean - facade_mean, 4),
        "bay_left_offset": round(bay_left_mean - facade_mean, 4),
        "bay_right_offset": round(bay_right_mean - facade_mean, 4),
    }

    # Estimate facade planarity (low std = flat facade, high = lots of depth variation)
    features["facade_planarity"] = round(1.0 - min(facade_std * 5, 1.0), 3)

    # Estimate if bay window projects forward (either side significantly closer)
    bay_threshold = 0.05
    features["bay_window_detected"] = (
        abs(features["bay_left_offset"]) > bay_threshold
        or abs(features["bay_right_offset"]) > bay_threshold
    )

    # Estimate relative setback (facade depth relative to full image mean)
    full_mean = float(depth_norm.mean())
    features["setback_relative"] = round(facade_mean - full_mean, 4)

    return features


def estimate_physical_values(features: dict, params: dict) -> dict:
    """Convert relative depth features to physical estimates.

    Uses known building dimensions (facade_width_m, total_height_m) as
    scale anchors where available. Falls back to typical values.
    """
    estimates = {}

    facade_width = params.get("facade_width_m", 6.0)
    total_height = params.get("total_height_m", 8.0)

    # Setback estimate: relative depth → metres
    # Typical Kensington setback: 0-3m. Use facade_width as scale reference.
    setback_rel = features.get("setback_relative", 0)
    estimates["setback_m_est"] = round(max(0, setback_rel * facade_width * 2), 2)

    # Foundation height: bottom region offset → metres
    # Typical: 0.3-0.8m above grade
    foundation_offset = abs(features.get("foundation_offset", 0))
    estimates["foundation_height_m_est"] = round(
        max(0.2, min(foundation_offset * total_height, 1.2)), 2)

    # Eave overhang: roof region offset → mm
    # Typical: 200-600mm
    roof_offset = abs(features.get("roof_offset", 0))
    estimates["eave_overhang_mm_est"] = round(
        max(100, min(roof_offset * facade_width * 1000, 800)), 0)

    # Bay window projection: side region offset → metres
    # Typical: 0.3-0.8m
    if features.get("bay_window_detected"):
        bay_offset = max(abs(features.get("bay_left_offset", 0)),
                         abs(features.get("bay_right_offset", 0)))
        estimates["bay_window_projection_m_est"] = round(
            max(0.2, min(bay_offset * facade_width, 1.0)), 2)

    return estimates


def atomic_write_json(path: Path, data: dict) -> None:
    """Write JSON atomically via tempfile + rename."""
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


def fuse_depth_into_params(params_dir: Path, depth_dir: Path,
                           limit: int = 0, dry_run: bool = False,
                           force: bool = False) -> dict:
    """Main fusion: for each param with a matched photo + depth map, fuse."""
    param_files = sorted(params_dir.glob("*.json"))
    if limit > 0:
        param_files = param_files[:limit]

    stats = {"processed": 0, "fused": 0, "no_depth": 0, "no_photo": 0, "skipped": 0}

    for pf in param_files:
        params = load_param(pf)
        if params is None:
            stats["skipped"] += 1
            continue

        stats["processed"] += 1

        photo_stem = get_matched_photo_stem(params)
        if not photo_stem:
            stats["no_photo"] += 1
            continue

        depth_path = depth_dir / f"{photo_stem}.npy"
        if not depth_path.exists():
            stats["no_depth"] += 1
            continue

        # Skip if already fused (unless --force)
        meta = params.get("_meta", {})
        if not force and "depth" in meta.get("fusion_applied", []):
            stats["skipped"] += 1
            continue

        # Load and analyze depth map
        depth = np.load(depth_path)
        features = analyze_depth_map(depth)
        if not features:
            stats["no_depth"] += 1
            continue

        # Convert to physical estimates
        estimates = estimate_physical_values(features, params)

        if dry_run:
            logger.info("  [DRY-RUN] %s: %s", pf.name, estimates)
            stats["fused"] += 1
            continue

        # Merge into params
        modified = False

        # Write depth features
        if "depth_analysis" not in params:
            params["depth_analysis"] = {}
        params["depth_analysis"] = features
        modified = True

        # Write estimates into depth_notes (existing field)
        depth_notes = params.get("depth_notes", {})
        for key, value in estimates.items():
            if key not in depth_notes or depth_notes[key] is None:
                depth_notes[key] = value
                modified = True
        params["depth_notes"] = depth_notes

        # Track provenance
        meta = params.setdefault("_meta", {})
        fusion_applied = meta.get("fusion_applied", [])
        if "depth" not in fusion_applied:
            fusion_applied.append("depth")
            meta["fusion_applied"] = fusion_applied
            modified = True

        if modified:
            atomic_write_json(pf, params)
            stats["fused"] += 1

    return stats


def main():
    parser = argparse.ArgumentParser(description="Stage 3b: Fuse depth maps into params")
    parser.add_argument("--depth-maps", type=Path, default=DEPTH_DIR)
    parser.add_argument("--params", type=Path, default=PARAMS_DIR)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true",
                        help="Re-fuse even if already done")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    logger.info("Fusing depth maps from %s into %s", args.depth_maps, args.params)
    stats = fuse_depth_into_params(args.params, args.depth_maps,
                                    limit=args.limit, dry_run=args.dry_run,
                                    force=args.force)

    logger.info("\nDone: %d processed, %d fused, %d no depth map, %d no photo, %d skipped",
                stats["processed"], stats["fused"], stats["no_depth"],
                stats["no_photo"], stats["skipped"])


if __name__ == "__main__":
    main()
