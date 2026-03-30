#!/usr/bin/env python3
"""Create LOD1/LOD2/BILLBOARD for HERO parking assets."""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

import bpy


def clear_scene():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)


def import_fbx(path: Path):
    before = {o.name for o in bpy.data.objects}
    bpy.ops.import_scene.fbx(filepath=str(path))
    new = [o for o in bpy.data.objects if o.name not in before]
    if not new:
        return None
    obj = new[-1]
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    if obj.type != "MESH":
        bpy.ops.object.convert(target="MESH")
        obj = bpy.context.view_layer.objects.active
    return obj


def export_selected(path: Path):
    bpy.ops.export_scene.fbx(
        filepath=str(path),
        use_selection=True,
        apply_unit_scale=True,
        bake_space_transform=False,
        object_types={"MESH"},
    )


def make_lod(obj, ratio: float, name: str):
    d = obj.copy()
    d.data = obj.data.copy()
    bpy.context.collection.objects.link(d)
    d.name = name
    bpy.ops.object.select_all(action="DESELECT")
    d.select_set(True)
    bpy.context.view_layer.objects.active = d
    mod = d.modifiers.new(name="Decimate", type="DECIMATE")
    mod.ratio = ratio
    bpy.ops.object.modifier_apply(modifier=mod.name)
    return d


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--hero-file", required=True)
    p.add_argument("--masters-dir", default="outputs/parking/masters")
    p.add_argument("--lod-dir", default="outputs/parking/lods")
    args = p.parse_args(sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else [])

    hero = [s.strip() for s in Path(args.hero_file).read_text(encoding="utf-8").splitlines() if s.strip()]
    masters = Path(args.masters_dir)
    lod_dir = Path(args.lod_dir)
    lod_dir.mkdir(parents=True, exist_ok=True)

    manifest_rows = []
    made = 0
    for key in hero:
        clear_scene()
        base = import_fbx(masters / f"SM_{key}_HERO.fbx")
        if base is None:
            continue

        lod1 = make_lod(base, 0.55, f"SM_{key}_LOD1")
        lod2 = make_lod(base, 0.22, f"SM_{key}_LOD2")
        bpy.ops.mesh.primitive_plane_add(size=1.2, location=(0, 0, 1.1))
        bb = bpy.context.active_object
        bb.name = f"SM_{key}_BILLBOARD"

        for obj, suffix in ((lod1, "LOD1"), (lod2, "LOD2"), (bb, "BILLBOARD")):
            bpy.ops.object.select_all(action="DESELECT")
            obj.select_set(True)
            bpy.context.view_layer.objects.active = obj
            out = lod_dir / f"SM_{key}_{suffix}.fbx"
            export_selected(out)
            made += 1
            manifest_rows.append(
                {
                    "parking_key": key,
                    "lod_level": suffix,
                    "fbx_path": str(out.resolve()),
                    "triangle_ratio_target": 0.55 if suffix == "LOD1" else (0.22 if suffix == "LOD2" else 0.0),
                }
            )
            print(f"[OK] exported {out}")

    manifest = lod_dir.parent / "unreal_parking_lod_manifest.csv"
    with manifest.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(manifest_rows[0].keys()) if manifest_rows else ["parking_key", "lod_level", "fbx_path", "triangle_ratio_target"])
        w.writeheader()
        if manifest_rows:
            w.writerows(manifest_rows)

    print(f"[OK] Wrote {manifest}")
    print(f"[DONE] generated_files={made}")


if __name__ == "__main__":
    main()
