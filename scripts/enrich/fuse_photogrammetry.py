#!/usr/bin/env python3
"""Stage 3 — ENRICH: Fuse photogrammetric mesh metadata into building params.

Reads retopologized meshes from meshes/retopo/ and updates params with
mesh availability, vertex count, and generation method selection.

Usage:
    python scripts/enrich/fuse_photogrammetry.py --meshes meshes/retopo/ --params params/
    python scripts/enrich/fuse_photogrammetry.py --meshes meshes/retopo/ --params params/ --dry-run
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_MESHES = REPO_ROOT / "meshes" / "retopo"
DEFAULT_PARAMS = REPO_ROOT / "params"

MESH_EXTENSIONS = {".obj", ".ply", ".stl"}


def discover_meshes(meshes_dir: Path) -> dict[str, Path]:
    """Map address stems to mesh files."""
    files = {}
    for f in meshes_dir.rglob("*"):
        if f.suffix.lower() in MESH_EXTENSIONS:
            files[f.stem] = f
    return files


def get_mesh_stats(mesh_path: Path) -> dict:
    """Get basic mesh statistics.

    In production: loads with trimesh to count vertices/faces.
    Currently returns file-level metadata.
    """
    return {
        "mesh_path": str(mesh_path),
        "format": mesh_path.suffix.lower(),
        "size_bytes": mesh_path.stat().st_size,
    }


def fuse_photogrammetry(
    meshes_dir: Path, params_dir: Path, *, dry_run: bool = False
) -> dict:
    """Fuse photogrammetric mesh data into params files."""
    meshes = discover_meshes(meshes_dir)
    stats = {"fused": 0, "no_match": 0, "errors": 0}

    for param_file in sorted(params_dir.glob("*.json")):
        if param_file.name.startswith("_"):
            continue
        data = json.loads(param_file.read_text(encoding="utf-8"))
        if data.get("skipped"):
            continue

        stem = param_file.stem
        mesh_path = meshes.get(stem)
        if mesh_path is None:
            stats["no_match"] += 1
            continue

        try:
            mesh_stats = get_mesh_stats(mesh_path)

            if dry_run:
                stats["fused"] += 1
                continue

            meta = data.setdefault("_meta", {})
            meta["has_photogrammetric_mesh"] = True
            meta["photogrammetric_mesh_path"] = str(mesh_path)
            meta["generation_method"] = "photogrammetric"

            fusion = meta.setdefault("fusion_applied", [])
            if "photogrammetry" not in fusion:
                fusion.append("photogrammetry")

            data["photogrammetry_stats"] = mesh_stats

            param_file.write_text(
                json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            stats["fused"] += 1
        except Exception:
            stats["errors"] += 1

    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Fuse photogrammetry data into params")
    parser.add_argument("--meshes", type=Path, default=DEFAULT_MESHES)
    parser.add_argument("--params", type=Path, default=DEFAULT_PARAMS)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not args.meshes.is_dir():
        print(f"[ERROR] Meshes directory not found: {args.meshes}")
        sys.exit(1)

    stats = fuse_photogrammetry(args.meshes, args.params, dry_run=args.dry_run)
    prefix = "[DRY RUN] " if args.dry_run else ""
    print(f"{prefix}Photogrammetry fusion: {stats['fused']} fused, "
          f"{stats['no_match']} unmatched, {stats['errors']} errors")


if __name__ == "__main__":
    main()
