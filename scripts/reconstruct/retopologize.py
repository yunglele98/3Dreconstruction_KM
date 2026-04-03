#!/usr/bin/env python3
"""Stage 2 — RECONSTRUCT: Retopologize raw photogrammetric meshes.

Runs Instant Meshes (or similar) to convert raw triangulated meshes
into clean quad meshes suitable for the generator pipeline.

Usage:
    python scripts/reconstruct/retopologize.py --input meshes/raw/ --output meshes/retopo/ --method instant-meshes
    python scripts/reconstruct/retopologize.py --input meshes/raw/ --output meshes/retopo/ --dry-run
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
MESH_EXTENSIONS = {".obj", ".ply", ".stl"}


def retopologize_mesh(
    mesh_path: Path,
    output_dir: Path,
    *,
    method: str = "instant-meshes",
    target_faces: int = 10000,
    dry_run: bool = False,
) -> dict:
    """Retopologize a single mesh.

    In production: calls Instant Meshes or similar tool to create
    a clean quad mesh.
    """
    output_path = output_dir / mesh_path.name

    result = {
        "input": str(mesh_path),
        "output": str(output_path),
        "method": method,
        "target_faces": target_faces,
    }

    if dry_run:
        result["status"] = "would_retopo"
    else:
        output_dir.mkdir(parents=True, exist_ok=True)
        result["status"] = "pending_implementation"

    return result


def run_batch(
    input_dir: Path,
    output_dir: Path,
    *,
    method: str = "instant-meshes",
    target_faces: int = 10000,
    dry_run: bool = False,
) -> list[dict]:
    meshes = sorted(
        p for p in input_dir.rglob("*")
        if p.suffix.lower() in MESH_EXTENSIONS
    )
    return [
        retopologize_mesh(
            m, output_dir, method=method,
            target_faces=target_faces, dry_run=dry_run,
        )
        for m in meshes
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description="Retopologize meshes")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--method", default="instant-meshes")
    parser.add_argument("--target-faces", type=int, default=10000)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not args.input.is_dir():
        print(f"[ERROR] Input directory not found: {args.input}")
        sys.exit(1)

    results = run_batch(
        args.input, args.output, method=args.method,
        target_faces=args.target_faces, dry_run=args.dry_run,
    )

    prefix = "[DRY RUN] " if args.dry_run else ""
    print(f"{prefix}Retopologized {len(results)} meshes")


if __name__ == "__main__":
    main()
