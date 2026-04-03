#!/usr/bin/env python3
"""Package and validate all deliverables for handoff.

Collects exports, renders, data files, reports, and web platform
into a structured deliverable package with checksums and manifest.

Usage:
    python scripts/export_deliverables.py
    python scripts/export_deliverables.py --output deliverables/
    python scripts/export_deliverables.py --format zip
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import shutil
import sys
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)
REPO_ROOT = Path(__file__).resolve().parent.parent

DELIVERABLE_SOURCES = {
    "params": ("params/", "Building parameter JSONs (1,050 buildings)"),
    "renders": ("outputs/buildings_renders_v1/", "Parametric render PNGs"),
    "exports_fbx": ("outputs/exports/", "FBX mesh exports"),
    "citygml": ("citygml/", "CityGML LOD2/LOD3"),
    "tiles_3d": ("tiles_3d/", "3D Tiles for CesiumJS"),
    "web_data": ("web/public/data/", "Web platform data (GeoJSON + app data)"),
    "scenarios": ("scenarios/", "Planning scenario overlays"),
    "coverage": ("outputs/coverage_matrix.json", "Pipeline coverage matrix"),
    "qa_report": ("outputs/qa_report.json", "QA gate report"),
    "calibration": ("assets/elements/metadata/calibrated_defaults.json", "Calibrated element defaults"),
}


def compute_checksum(path: Path) -> str:
    """Compute SHA256 checksum of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def collect_deliverable(source_key: str, source_path: str, output_dir: Path) -> dict:
    """Collect a single deliverable into the output directory."""
    src = REPO_ROOT / source_path
    if not src.exists():
        return {"key": source_key, "status": "missing", "path": source_path}

    dest = output_dir / source_key
    file_count = 0
    total_size = 0

    if src.is_file():
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest_file = output_dir / src.name
        shutil.copy2(src, dest_file)
        file_count = 1
        total_size = dest_file.stat().st_size
        checksum = compute_checksum(dest_file)
        return {
            "key": source_key, "status": "ok", "path": str(dest_file.relative_to(output_dir)),
            "files": 1, "size_mb": round(total_size / 1024 / 1024, 2), "checksum": checksum,
        }
    elif src.is_dir():
        dest.mkdir(parents=True, exist_ok=True)
        for f in src.rglob("*"):
            if f.is_file() and not f.name.startswith("."):
                rel = f.relative_to(src)
                dest_f = dest / rel
                dest_f.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(f, dest_f)
                file_count += 1
                total_size += f.stat().st_size
        return {
            "key": source_key, "status": "ok", "path": source_key,
            "files": file_count, "size_mb": round(total_size / 1024 / 1024, 2),
        }

    return {"key": source_key, "status": "error"}


def export_deliverables(output_dir: Path, do_zip: bool = False) -> dict:
    """Collect all deliverables into output directory.

    Args:
        output_dir: Destination directory.
        do_zip: Also create a zip archive.

    Returns:
        Manifest dict.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    manifest = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "project": "Kensington Market HCD 3D Reconstruction",
        "deliverables": [],
    }

    total_files = 0
    total_size = 0

    for key, (path, description) in DELIVERABLE_SOURCES.items():
        result = collect_deliverable(key, path, output_dir)
        result["description"] = description
        manifest["deliverables"].append(result)

        if result["status"] == "ok":
            total_files += result.get("files", 0)
            total_size += result.get("size_mb", 0)
            logger.info(f"  OK: {key} ({result.get('files', 0)} files, {result.get('size_mb', 0)} MB)")
        else:
            logger.warning(f"  MISSING: {key} ({path})")

    manifest["summary"] = {
        "total_deliverables": len(manifest["deliverables"]),
        "available": sum(1 for d in manifest["deliverables"] if d["status"] == "ok"),
        "missing": sum(1 for d in manifest["deliverables"] if d["status"] == "missing"),
        "total_files": total_files,
        "total_size_mb": round(total_size, 2),
    }

    # Write manifest
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    if do_zip:
        zip_path = output_dir.parent / f"{output_dir.name}.zip"
        shutil.make_archive(str(zip_path.with_suffix("")), "zip", output_dir)
        manifest["zip_path"] = str(zip_path)
        logger.info(f"  ZIP: {zip_path}")

    return manifest


def main():
    parser = argparse.ArgumentParser(description="Package deliverables for handoff")
    parser.add_argument("--output", type=Path, default=REPO_ROOT / "deliverables")
    parser.add_argument("--format", choices=["dir", "zip"], default="dir")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    manifest = export_deliverables(args.output, do_zip=(args.format == "zip"))

    s = manifest["summary"]
    print(f"\nDeliverables: {s['available']}/{s['total_deliverables']} available, "
          f"{s['total_files']} files, {s['total_size_mb']} MB")
    print(f"Output: {args.output}")


if __name__ == "__main__":
    main()
