#!/usr/bin/env python3
"""Package Gaussian splats for web viewer (SuperSplat/gsplat.js).

Converts trained splat models to .splat format and generates a manifest
for the web platform viewer.

Usage:
    python scripts/export/package_splats.py --input splats/ --output web/public/splats/
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SPLAT_DIR = REPO_ROOT / "splats"
OUTPUT_DIR = REPO_ROOT / "web" / "public" / "splats"
PARAMS_DIR = REPO_ROOT / "params"


def find_splat_files(splat_dir):
    """Find all trained splat outputs."""
    splats = []
    for d in sorted(splat_dir.iterdir()):
        if not d.is_dir():
            continue
        # Look for common splat output formats
        for ext in ["*.splat", "*.ply", "*.npz"]:
            files = list(d.rglob(ext))
            if files:
                splats.append({"name": d.name, "path": files[0], "format": files[0].suffix})
                break
    return splats


def package_splat(splat_info, output_dir):
    """Copy/convert splat to web-ready format."""
    src = splat_info["path"]
    name = splat_info["name"]
    dst = output_dir / f"{name}.splat"

    if src.suffix == ".splat":
        shutil.copy2(src, dst)
    elif src.suffix == ".ply":
        # PLY splats can be loaded directly by some viewers
        shutil.copy2(src, output_dir / f"{name}.ply")
        dst = output_dir / f"{name}.ply"
    else:
        shutil.copy2(src, output_dir / src.name)
        dst = output_dir / src.name

    return dst


def get_building_coords(name):
    """Look up building coordinates from params."""
    stem = name.replace(" ", "_")
    param_file = PARAMS_DIR / f"{stem}.json"
    if param_file.exists():
        try:
            p = json.loads(param_file.read_text(encoding="utf-8"))
            site = p.get("site", {})
            return site.get("lon"), site.get("lat")
        except (json.JSONDecodeError, OSError):
            pass
    return None, None


def main():
    parser = argparse.ArgumentParser(description="Package Gaussian splats for web viewer.")
    parser.add_argument("--input", type=Path, default=SPLAT_DIR)
    parser.add_argument("--output", type=Path, default=OUTPUT_DIR)
    args = parser.parse_args()

    if not args.input.exists():
        print(f"No splats directory: {args.input}")
        print("  Train splats first: python scripts/reconstruct/train_splats.py")
        return

    args.output.mkdir(parents=True, exist_ok=True)

    splats = find_splat_files(args.input)
    print(f"Packaging {len(splats)} splats for web viewer")

    manifest = []
    for s in splats:
        dst = package_splat(s, args.output)
        lon, lat = get_building_coords(s["name"])
        manifest.append({
            "name": s["name"],
            "file": dst.name,
            "format": dst.suffix,
            "size_mb": round(dst.stat().st_size / 1024 / 1024, 2),
            "lon": lon,
            "lat": lat,
        })
        print(f"  {s['name']}: {dst.name} ({manifest[-1]['size_mb']} MB)")

    manifest_path = args.output / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"\nManifest: {manifest_path} ({len(manifest)} splats)")


if __name__ == "__main__":
    main()
