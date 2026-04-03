#!/usr/bin/env python3
"""Calibrate parametric generation defaults from COLMAP reconstructions.

Reads sparse/dense COLMAP outputs, computes real-world measurements
(facade widths, storey heights, depth), and updates params/*.json
with calibrated values.

Usage:
    python scripts/reconstruct/calibrate_defaults.py
    python scripts/reconstruct/calibrate_defaults.py --street "Augusta Ave"
    python scripts/reconstruct/calibrate_defaults.py --model-path point_clouds/colmap_blocks/Augusta_Ave/sparse/12
    python scripts/reconstruct/calibrate_defaults.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PARAMS_DIR = REPO_ROOT / "params"
SPARSE_ROOT = REPO_ROOT / "point_clouds" / "colmap_blocks"
PHOTO_INDEX = REPO_ROOT / "PHOTOS KENSINGTON" / "csv" / "photo_address_index.csv"
DEFAULTS_OUTPUT = REPO_ROOT / "outputs" / "calibrated_defaults.json"


def load_reconstruction(model_path: str):
    """Load a COLMAP reconstruction via pycolmap."""
    try:
        import pycolmap
        return pycolmap.Reconstruction(model_path)
    except Exception as e:
        print(f"  Cannot load {model_path}: {e}")
        return None


def get_registered_images(rec) -> dict:
    """Extract registered image filenames and camera poses."""
    images = {}
    for img_id in rec.images:
        img = rec.images[img_id]
        cam = rec.cameras[img.camera_id]
        center = img.projection_center()
        images[img.name] = {
            "image_id": img_id,
            "center": center,
            "focal_length": cam.focal_length,
            "width": cam.width,
            "height": cam.height,
        }
    return images


def estimate_scene_scale(rec) -> dict:
    """Estimate scene scale from 3D point cloud extent."""
    points = []
    for pt_id in rec.points3D:
        points.append(rec.points3D[pt_id].xyz)
    if not points:
        return {"scale_valid": False}

    pts = np.array(points)
    extent = pts.max(axis=0) - pts.min(axis=0)
    centroid = pts.mean(axis=0)

    return {
        "scale_valid": True,
        "n_points": len(pts),
        "extent_x": float(extent[0]),
        "extent_y": float(extent[1]),
        "extent_z": float(extent[2]),
        "centroid": centroid.tolist(),
        "bbox_min": pts.min(axis=0).tolist(),
        "bbox_max": pts.max(axis=0).tolist(),
    }


def estimate_facade_width(pts: np.ndarray) -> float:
    """Estimate facade width from horizontal extent of point cloud."""
    # Project onto the dominant horizontal direction (PCA)
    pts_2d = pts[:, :2] - pts[:, :2].mean(axis=0)
    if len(pts_2d) < 3:
        return 0.0
    cov = np.cov(pts_2d.T)
    eigvals, eigvecs = np.linalg.eigh(cov)
    # Width along the principal axis
    proj = pts_2d @ eigvecs[:, -1]
    return float(proj.max() - proj.min())


def estimate_storey_height(pts: np.ndarray) -> float:
    """Estimate storey height from vertical distribution of points."""
    z = pts[:, 2]
    total_height = float(z.max() - z.min())
    if total_height < 2.0:
        return 3.0  # default
    # Assume 2-3 storeys for typical Kensington buildings
    n_storeys_est = max(1, round(total_height / 3.2))
    return total_height / n_storeys_est


def estimate_depth(pts: np.ndarray) -> float:
    """Estimate building depth from secondary horizontal axis."""
    pts_2d = pts[:, :2] - pts[:, :2].mean(axis=0)
    if len(pts_2d) < 3:
        return 0.0
    cov = np.cov(pts_2d.T)
    eigvals, eigvecs = np.linalg.eigh(cov)
    # Depth along the minor axis
    proj = pts_2d @ eigvecs[:, 0]
    return float(proj.max() - proj.min())


def load_photo_address_map() -> dict:
    """Map photo filenames to addresses from the CSV index."""
    import csv
    mapping = {}
    if not PHOTO_INDEX.exists():
        return mapping
    with open(PHOTO_INDEX, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            fname = (row.get("filename") or "").strip()
            addr = (row.get("address_or_location") or "").strip()
            if fname and addr:
                mapping[fname] = addr
    return mapping


def calibrate_from_model(model_path: str, photo_addr_map: dict) -> list:
    """Extract calibration measurements from a single COLMAP model."""
    rec = load_reconstruction(model_path)
    if rec is None:
        return []

    registered = get_registered_images(rec)
    scene_info = estimate_scene_scale(rec)

    if not scene_info.get("scale_valid"):
        return []

    # Group 3D points by the images that see them (and thus by address)
    addr_points = defaultdict(list)
    for pt_id in rec.points3D:
        pt = rec.points3D[pt_id]
        xyz = pt.xyz
        # Find which images see this point
        track = pt.track
        for elem in track.elements:
            img_id = elem.image_id
            if img_id in rec.images:
                img_name = rec.images[img_id].name
                addr = photo_addr_map.get(img_name, "")
                if addr:
                    addr_points[addr].append(xyz)

    results = []
    for addr, pts_list in addr_points.items():
        pts = np.array(pts_list)
        if len(pts) < 10:
            continue

        fw = estimate_facade_width(pts)
        sh = estimate_storey_height(pts)
        fd = estimate_depth(pts)
        total_h = float(pts[:, 2].max() - pts[:, 2].min())

        results.append({
            "address": addr,
            "n_points": len(pts),
            "facade_width_est": round(fw, 2),
            "storey_height_est": round(sh, 2),
            "facade_depth_est": round(fd, 2),
            "total_height_est": round(total_h, 2),
            "model_path": model_path,
        })

    return results


def update_params(calibrations: list, dry_run: bool = False):
    """Update params/*.json with calibrated measurements."""
    updated = 0
    for cal in calibrations:
        addr = cal["address"]
        stem = addr.replace(" ", "_").replace(",", "")
        param_file = PARAMS_DIR / f"{stem}.json"

        if not param_file.exists():
            continue

        try:
            params = json.loads(param_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue

        # Only update if we have a meaningful measurement
        changes = {}
        if cal["facade_width_est"] > 2.0:
            old = params.get("facade_width_m", 0)
            changes["facade_width_m"] = cal["facade_width_est"]
        if cal["storey_height_est"] > 2.0:
            old = params.get("storey_height_m", 0)
            changes["storey_height_m"] = cal["storey_height_est"]
        if cal["facade_depth_est"] > 1.0:
            old = params.get("facade_depth_m", 0)
            changes["facade_depth_m"] = cal["facade_depth_est"]

        if not changes:
            continue

        if dry_run:
            print(f"  [DRY] {addr}: {changes}")
            updated += 1
            continue

        # Store calibration metadata
        if "_meta" not in params:
            params["_meta"] = {}
        params["_meta"]["colmap_calibration"] = {
            "n_points": cal["n_points"],
            "model_path": cal["model_path"],
        }

        for key, val in changes.items():
            params[key] = val

        param_file.write_text(
            json.dumps(params, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        updated += 1
        print(f"  {addr}: {changes}")

    return updated


def parse_args():
    parser = argparse.ArgumentParser(
        description="Calibrate parametric defaults from COLMAP reconstructions."
    )
    parser.add_argument("--street", type=str, default="Augusta Ave")
    parser.add_argument("--model-path", type=str, default=None,
                        help="Path to a specific sparse model directory")
    parser.add_argument("--sparse-root", type=Path, default=SPARSE_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULTS_OUTPUT)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--update-params", action="store_true",
                        help="Write calibrated values back to params/*.json")
    return parser.parse_args()


def main():
    args = parse_args()

    photo_addr_map = load_photo_address_map()
    print(f"Photo-address map: {len(photo_addr_map)} entries")

    all_calibrations = []

    if args.model_path:
        # Single model
        cals = calibrate_from_model(args.model_path, photo_addr_map)
        all_calibrations.extend(cals)
    else:
        # All models for the street
        street_slug = args.street.replace(" ", "_")
        sparse_dir = args.sparse_root / street_slug / "sparse"
        if not sparse_dir.exists():
            print(f"ERROR: Sparse dir not found: {sparse_dir}")
            sys.exit(1)

        for d in sorted(os.listdir(sparse_dir), key=lambda x: int(x)):
            model_path = str(sparse_dir / d)
            cals = calibrate_from_model(model_path, photo_addr_map)
            all_calibrations.extend(cals)
            if cals:
                print(f"  Model {d}: {len(cals)} addresses calibrated")

    # Deduplicate: keep the calibration with most points per address
    best_by_addr = {}
    for cal in all_calibrations:
        addr = cal["address"]
        if addr not in best_by_addr or cal["n_points"] > best_by_addr[addr]["n_points"]:
            best_by_addr[addr] = cal

    calibrations = sorted(best_by_addr.values(), key=lambda c: -c["n_points"])
    print(f"\nCalibrated {len(calibrations)} addresses:")
    for cal in calibrations:
        addr_safe = cal['address'].encode('ascii', 'replace').decode('ascii')
        print(f"  {addr_safe}: W={cal['facade_width_est']}m "
              f"H={cal['total_height_est']}m D={cal['facade_depth_est']}m "
              f"({cal['n_points']} pts)")

    # Save calibration report
    args.output.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "street": args.street if not args.model_path else "custom",
        "total_calibrations": len(calibrations),
        "calibrations": calibrations,
    }
    args.output.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"\nReport: {args.output}")

    # Optionally update params
    if args.update_params:
        print("\nUpdating params files:")
        updated = update_params(calibrations, dry_run=args.dry_run)
        print(f"Updated {updated} param files")


if __name__ == "__main__":
    main()
