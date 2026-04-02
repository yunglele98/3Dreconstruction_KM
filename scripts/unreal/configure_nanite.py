#!/usr/bin/env python3
"""Generate Nanite configuration JSON for batch-enabling Nanite on all static meshes.

Produces per-building Nanite settings and a master config for UE5 import.
Buildings with high vertex counts get Nanite enabled; simple LOD3 bounding boxes
stay as traditional LOD (Nanite overhead not worth it for <100 verts).

Usage:
    python scripts/unreal/configure_nanite.py
    python scripts/unreal/configure_nanite.py --output outputs/unreal/nanite_config.json
    python scripts/unreal/configure_nanite.py --threshold 5000
"""
import argparse
import json
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).parent.parent.parent
EXPORTS_DIR = REPO / "outputs" / "exports"

# Nanite is beneficial above this vertex count (per-mesh)
DEFAULT_NANITE_THRESHOLD = 5000


def scan_exports(exports_dir, threshold):
    """Scan FBX exports and determine Nanite eligibility."""
    buildings = []
    nanite_count = 0
    traditional_count = 0

    for d in sorted(exports_dir.iterdir()):
        if not d.is_dir() or d.name.startswith("_") or d.name == "collision":
            continue
        fbx = d / f"{d.name}.fbx"
        if not fbx.exists():
            continue

        meta_path = d / "export_meta.json"
        vertex_count = 0
        face_count = 0
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                vertex_count = meta.get("vertex_count", 0)
                face_count = meta.get("face_count", 0)
            except (json.JSONDecodeError, OSError):
                pass

        # Nanite eligibility
        enable_nanite = vertex_count >= threshold
        if enable_nanite:
            nanite_count += 1
        else:
            traditional_count += 1

        # LOD files
        lods = {}
        for lod_num in range(4):
            lod_file = d / f"{d.name}_LOD{lod_num}.fbx"
            if lod_file.exists():
                lods[f"LOD{lod_num}"] = str(lod_file.relative_to(exports_dir))

        collision = d / f"{d.name}_collision.fbx"

        entry = {
            "address": d.name.replace("_", " "),
            "fbx": str(fbx.relative_to(exports_dir)),
            "vertex_count": vertex_count,
            "face_count": face_count,
            "enable_nanite": enable_nanite,
            "nanite_settings": {
                "position_precision": 0 if enable_nanite else -1,
                "percent_triangles": 100,
                "trim_relative_error": 0.0,
                "fallback_relative_error": 1.0,
                "displacement_uv_channel": 0,
            } if enable_nanite else None,
            "lod_settings": {
                "num_lods": len(lods),
                "lod_files": lods,
                "screen_sizes": [1.0, 0.5, 0.25, 0.1][:len(lods)],
                "auto_lod": not enable_nanite,
            },
            "collision": str(collision.relative_to(exports_dir)) if collision.exists() else None,
        }
        buildings.append(entry)

    return buildings, nanite_count, traditional_count


def main():
    parser = argparse.ArgumentParser(description="Configure Nanite for UE5 import")
    parser.add_argument("--threshold", type=int, default=DEFAULT_NANITE_THRESHOLD,
                        help=f"Vertex count threshold for Nanite (default: {DEFAULT_NANITE_THRESHOLD})")
    parser.add_argument("--output", type=Path,
                        default=REPO / "outputs" / "unreal" / "nanite_config.json")
    args = parser.parse_args()

    buildings, nanite_count, traditional_count = scan_exports(EXPORTS_DIR, args.threshold)

    config = {
        "_meta": {
            "generator": "kensington-pipeline",
            "generated_at": datetime.now().isoformat(),
            "ue_version": "5.4+",
            "vertex_threshold": args.threshold,
        },
        "global_settings": {
            "nanite_enabled": True,
            "virtual_shadow_maps": True,
            "proxy_lod_mesh_reduction_screen_size": 0.25,
            "distance_field_resolution": 1.0,
        },
        "stats": {
            "total_buildings": len(buildings),
            "nanite_enabled": nanite_count,
            "traditional_lod": traditional_count,
        },
        "buildings": buildings,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(config, indent=2), encoding="utf-8")
    print(f"Nanite config: {args.output}")
    print(f"  Total: {len(buildings)} buildings")
    print(f"  Nanite: {nanite_count} (>= {args.threshold} verts)")
    print(f"  Traditional LOD: {traditional_count}")


if __name__ == "__main__":
    main()
