#!/usr/bin/env python3
"""Create HERO variants for top street furniture types."""

import argparse
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
    bpy.ops.object.select_all(action="DESELECT"); obj.select_set(True); bpy.context.view_layer.objects.active = obj
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


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--hero-file", required=True)
    p.add_argument("--masters-dir", default="outputs/street_furniture/masters")
    args = p.parse_args(sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else [])
    masters = Path(args.masters_dir)
    hero = [s.strip() for s in Path(args.hero_file).read_text(encoding="utf-8").splitlines() if s.strip()]
    made = 0
    for k in hero:
        clear_scene()
        obj = import_fbx(masters / f"SM_{k}_A_standard.fbx")
        if obj is None:
            continue
        obj.scale = (obj.scale[0] * 1.12, obj.scale[1] * 1.12, obj.scale[2] * 1.1)
        obj.name = f"SM_{k}_HERO"
        bpy.ops.object.select_all(action="DESELECT"); obj.select_set(True); bpy.context.view_layer.objects.active = obj
        out = masters / f"SM_{k}_HERO.fbx"; export_selected(out); made += 1
        print(f"[OK] exported {out}")
    print(f"[DONE] hero_variants={made}")


if __name__ == "__main__":
    main()
