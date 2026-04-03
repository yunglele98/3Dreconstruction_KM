#!/usr/bin/env python3
"""Fuse photogrammetric mesh data into building params.

Reads retopologized meshes and updates params with precise dimensions,
records mesh paths, and sets generation_method to "photogrammetric".

Usage:
    python scripts/enrich/fuse_photogrammetry.py --meshes meshes/retopo/ --params params/
    python scripts/enrich/fuse_photogrammetry.py --meshes meshes/retopo/ --params params/ --apply
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)
REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def analyze_mesh(mesh_path: Path) -> dict | None:
    """Extract dimensions from a mesh file."""
    try:
        import trimesh
        loaded = trimesh.load(str(mesh_path), process=False)
        if isinstance(loaded, trimesh.Scene):
            meshes = [g for g in loaded.geometry.values() if isinstance(g, trimesh.Trimesh)]
            if not meshes:
                return None
            mesh = trimesh.util.concatenate(meshes)
        else:
            mesh = loaded

        bounds = mesh.bounds  # [[min_x, min_y, min_z], [max_x, max_y, max_z]]
        extents = mesh.extents  # [dx, dy, dz]

        return {
            "face_count": int(len(mesh.faces)),
            "vertex_count": int(len(mesh.vertices)),
            "width_m": round(float(extents[0]), 2),
            "depth_m": round(float(extents[1]), 2),
            "height_m": round(float(extents[2]), 2),
            "is_watertight": bool(mesh.is_watertight),
            "volume_m3": round(float(mesh.volume), 2) if mesh.is_watertight else None,
        }
    except ImportError:
        # Fallback: read PLY header
        if mesh_path.suffix.lower() == ".ply":
            return _analyze_ply(mesh_path)
        return None


def _analyze_ply(ply_path: Path) -> dict | None:
    """Quick PLY analysis without trimesh."""
    points = []
    in_data = False
    with open(ply_path, "r", encoding="utf-8", errors="replace") as f:
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
    if not points:
        return None
    pts = np.array(points)
    extents = pts.max(axis=0) - pts.min(axis=0)
    return {
        "vertex_count": len(pts),
        "face_count": 0,
        "width_m": round(float(extents[0]), 2),
        "depth_m": round(float(extents[1]), 2),
        "height_m": round(float(extents[2]), 2),
        "is_watertight": False,
        "volume_m3": None,
    }


def fuse_photogrammetry_into_params(
    meshes_dir: Path, params_dir: Path, apply: bool = False
) -> dict:
    """Fuse photogrammetric mesh dimensions into params."""
    stats = {"updated": 0, "skipped": 0, "no_mesh": 0}

    for param_file in sorted(params_dir.glob("*.json")):
        if param_file.name.startswith("_"):
            continue
        try:
            data = json.loads(param_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if data.get("skipped"):
            continue

        meta = data.get("_meta", {})
        if meta.get("has_photogrammetric_mesh"):
            stats["skipped"] += 1
            continue

        stem = param_file.stem
        mesh_path = None
        for ext in [".obj", ".ply", ".glb"]:
            candidate = meshes_dir / f"{stem}{ext}"
            if candidate.exists():
                mesh_path = candidate
                break

        if not mesh_path:
            stats["no_mesh"] += 1
            continue

        analysis = analyze_mesh(mesh_path)
        if not analysis:
            stats["no_mesh"] += 1
            continue

        # Update _meta
        if "_meta" not in data:
            data["_meta"] = {}
        data["_meta"]["has_photogrammetric_mesh"] = True
        data["_meta"]["photogrammetric_mesh_path"] = str(mesh_path)
        data["_meta"]["generation_method"] = "photogrammetric"

        if "fusion_applied" not in data["_meta"]:
            data["_meta"]["fusion_applied"] = []
        if "photogrammetry" not in data["_meta"]["fusion_applied"]:
            data["_meta"]["fusion_applied"].append("photogrammetry")

        # Store mesh analysis
        data["mesh_analysis"] = analysis

        if apply:
            param_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        stats["updated"] += 1

    return stats


def main():
    parser = argparse.ArgumentParser(description="Fuse photogrammetry meshes into params")
    parser.add_argument("--meshes", type=Path, default=REPO_ROOT / "meshes" / "retopo")
    parser.add_argument("--params", type=Path, default=REPO_ROOT / "params")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    stats = fuse_photogrammetry_into_params(args.meshes, args.params, args.apply)
    print(f"Photogrammetry fusion ({'APPLIED' if args.apply else 'DRY RUN'}): {stats}")


if __name__ == "__main__":
    main()
