#!/usr/bin/env python3
"""Fuse photogrammetric mesh availability into building parameter files.

Checks for retopologized .obj meshes from Stage 2 (COLMAP/OpenMVS +
Instant Meshes) and sets `_meta.has_photogrammetric_mesh`,
`_meta.photogrammetric_mesh_path`, and `_meta.generation_method`.
"photogrammetry" is appended to `_meta.fusion_applied`.

Usage:
    python scripts/enrich/fuse_photogrammetry.py
    python scripts/enrich/fuse_photogrammetry.py --meshes meshes/retopo/ --params params/
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


def _find_mesh(mesh_dir, address):
    """Find a matching retopologized .obj mesh for an address.

    Tries exact stem match first, then case-insensitive glob.
    Also checks common suffixes like _retopo.
    """
    stem = _address_to_stem(address)
    # Direct match
    for ext in (".obj", ".OBJ"):
        candidate = mesh_dir / f"{stem}{ext}"
        if candidate.exists():
            return candidate
    # With _retopo suffix
    for ext in (".obj", ".OBJ"):
        candidate = mesh_dir / f"{stem}_retopo{ext}"
        if candidate.exists():
            return candidate
    # Case-insensitive search
    stem_lower = stem.lower()
    for f in mesh_dir.iterdir():
        if f.suffix.lower() != ".obj":
            continue
        f_stem_lower = f.stem.lower()
        if f_stem_lower == stem_lower or f_stem_lower == f"{stem_lower}_retopo":
            return f
    return None


def _get_mesh_stats(mesh_path):
    """Read basic stats from an OBJ file: vertex count, face count, file size."""
    try:
        vertex_count = 0
        face_count = 0
        with open(mesh_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                if line.startswith("v "):
                    vertex_count += 1
                elif line.startswith("f "):
                    face_count += 1
        file_size_mb = mesh_path.stat().st_size / (1024 * 1024)
        return {
            "vertex_count": vertex_count,
            "face_count": face_count,
            "file_size_mb": round(file_size_mb, 2),
        }
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def fuse_photogrammetry(mesh_dir, params_dir):
    """Fuse photogrammetric mesh metadata into all matching param files."""
    mesh_dir = Path(mesh_dir)
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
        if "photogrammetry" in fusion_applied:
            skipped_already += 1
            continue

        # Find matching mesh
        address = _sanitize_address(param_file.name)
        mesh_file = _find_mesh(mesh_dir, address)
        if mesh_file is None:
            skipped_no_data += 1
            continue

        # Set photogrammetric metadata
        meta["has_photogrammetric_mesh"] = True
        # Store path relative to repo root for portability
        try:
            rel_path = str(mesh_file.relative_to(REPO_ROOT))
        except ValueError:
            rel_path = str(mesh_file)
        meta["photogrammetric_mesh_path"] = rel_path
        meta["generation_method"] = "photogrammetric"

        # Gather mesh stats for reference
        mesh_stats = _get_mesh_stats(mesh_file)
        if mesh_stats:
            meta["photogrammetric_mesh_stats"] = mesh_stats

        fusion_applied.append("photogrammetry")

        _atomic_write_json(param_file, data)
        fused += 1

    print(f"Fused {fused} buildings, skipped {skipped_no_data} (no data), "
          f"skipped {skipped_already} (already fused)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Fuse photogrammetric mesh metadata into building params"
    )
    parser.add_argument(
        "--meshes", type=Path, default=REPO_ROOT / "meshes" / "retopo",
        help="Directory containing retopologized .obj meshes (default: meshes/retopo/)"
    )
    parser.add_argument(
        "--params", type=Path, default=REPO_ROOT / "params",
        help="Directory containing building param JSON files (default: params/)"
    )
    args = parser.parse_args()
    fuse_photogrammetry(args.meshes, args.params)
