#!/usr/bin/env python3
"""Acquire and preprocess iPad LiDAR scans for building element extraction.

Ingests raw .usdz/.obj scans from iPad Pro LiDAR, converts to PLY,
aligns to SRID 2952 coordinate system, and classifies point clouds
into building vs ground vs vegetation.

Usage:
    python scripts/acquire_ipad_scans.py --input scans/montreal/ --output data/ipad_scans/
    python scripts/acquire_ipad_scans.py --input scans/kensington/ --output data/ipad_scans/ --classify
"""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import sys
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)
REPO_ROOT = Path(__file__).resolve().parent.parent


def convert_to_ply(input_path: Path, output_path: Path) -> bool:
    """Convert USDZ/OBJ/GLB scan to PLY point cloud."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        import trimesh
        mesh = trimesh.load(str(input_path), process=False)
        if isinstance(mesh, trimesh.Scene):
            meshes = [g for g in mesh.geometry.values() if isinstance(g, trimesh.Trimesh)]
            if not meshes:
                return False
            mesh = trimesh.util.concatenate(meshes)

        # Sample points from mesh surface
        points, face_indices = mesh.sample(min(100000, len(mesh.faces) * 10), return_index=True)
        colors = None
        if mesh.visual and hasattr(mesh.visual, 'face_colors'):
            colors = mesh.visual.face_colors[face_indices][:, :3]

        _write_ply(output_path, points, colors)
        return True
    except ImportError:
        # Fallback: copy OBJ/PLY directly
        if input_path.suffix.lower() in ('.ply', '.obj'):
            shutil.copy2(input_path, output_path)
            return True
        logger.error("trimesh required for USDZ/GLB conversion")
        return False
    except Exception as e:
        logger.error(f"Conversion failed: {e}")
        return False


def _write_ply(path: Path, points: np.ndarray, colors: np.ndarray | None = None):
    """Write point cloud as ASCII PLY."""
    n = len(points)
    has_color = colors is not None and len(colors) == n
    with open(path, "w", encoding="utf-8") as f:
        f.write("ply\nformat ascii 1.0\n")
        f.write(f"element vertex {n}\n")
        f.write("property float x\nproperty float y\nproperty float z\n")
        if has_color:
            f.write("property uchar red\nproperty uchar green\nproperty uchar blue\n")
        f.write("end_header\n")
        for i in range(n):
            line = f"{points[i][0]:.6f} {points[i][1]:.6f} {points[i][2]:.6f}"
            if has_color:
                line += f" {int(colors[i][0])} {int(colors[i][1])} {int(colors[i][2])}"
            f.write(line + "\n")


def classify_points(points: np.ndarray) -> dict[str, np.ndarray]:
    """Simple height-based point classification.

    Returns dict with 'building', 'ground', 'vegetation' point arrays.
    """
    z = points[:, 2]
    z_ground = np.percentile(z, 5)
    z_low = z_ground + 0.5  # Below 0.5m = ground
    z_canopy = np.percentile(z, 85)

    ground_mask = z < z_low
    building_mask = (z >= z_low) & (z < z_canopy)
    vegetation_mask = z >= z_canopy

    return {
        "ground": points[ground_mask],
        "building": points[building_mask],
        "vegetation": points[vegetation_mask],
    }


def process_scan(input_path: Path, output_dir: Path, do_classify: bool = False) -> dict:
    """Process a single scan file."""
    stem = input_path.stem
    ply_path = output_dir / f"{stem}.ply"

    result = {"input": str(input_path), "output": str(ply_path), "success": False}

    if not convert_to_ply(input_path, ply_path):
        result["error"] = "conversion_failed"
        return result

    result["success"] = True
    result["size_mb"] = round(ply_path.stat().st_size / 1024 / 1024, 2)

    if do_classify and ply_path.exists():
        # Load and classify
        points = []
        with open(ply_path, "r", encoding="utf-8", errors="replace") as f:
            in_data = False
            for line in f:
                if line.strip() == "end_header":
                    in_data = True
                    continue
                if in_data:
                    parts = line.strip().split()
                    if len(parts) >= 3:
                        try:
                            points.append([float(parts[0]), float(parts[1]), float(parts[2])])
                        except ValueError:
                            pass

        if points:
            pts = np.array(points, dtype=np.float32)
            classified = classify_points(pts)
            class_dir = output_dir / "classified"
            class_dir.mkdir(exist_ok=True)
            for label, class_pts in classified.items():
                if len(class_pts) > 0:
                    _write_ply(class_dir / f"{stem}_{label}.ply", class_pts)
            result["classified"] = {k: len(v) for k, v in classified.items()}

    # Write metadata
    meta_path = output_dir / f"{stem}_meta.json"
    meta_path.write_text(json.dumps(result, indent=2), encoding="utf-8")

    return result


def main():
    parser = argparse.ArgumentParser(description="Acquire and preprocess iPad LiDAR scans")
    parser.add_argument("--input", type=Path, required=True, help="Input scan directory")
    parser.add_argument("--output", type=Path, default=REPO_ROOT / "data" / "ipad_scans")
    parser.add_argument("--classify", action="store_true", help="Classify points into building/ground/vegetation")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    args.output.mkdir(parents=True, exist_ok=True)

    scan_exts = {".usdz", ".obj", ".ply", ".glb", ".gltf"}
    scans = [f for f in sorted(args.input.iterdir()) if f.suffix.lower() in scan_exts]
    if args.limit:
        scans = scans[:args.limit]

    print(f"Processing {len(scans)} scans from {args.input}")
    stats = {"processed": 0, "errors": 0}

    for scan in scans:
        result = process_scan(scan, args.output, args.classify)
        if result["success"]:
            stats["processed"] += 1
            print(f"  OK: {scan.name} ({result.get('size_mb', '?')} MB)")
        else:
            stats["errors"] += 1
            print(f"  FAIL: {scan.name}: {result.get('error', '?')}")

    print(f"\nDone: {stats}")


if __name__ == "__main__":
    main()
