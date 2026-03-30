#!/usr/bin/env python3
"""Create HERO pole FBX variants for top pole types."""

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


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--hero-file", required=True)
    p.add_argument("--masters-dir", default="outputs/poles/masters")
    args = p.parse_args(sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else [])

    masters = Path(args.masters_dir)
    heroes = [s.strip() for s in Path(args.hero_file).read_text(encoding="utf-8").splitlines() if s.strip()]
    created = 0
    for key in heroes:
        clear_scene()
        base = masters / f"SM_{key}_A_standard.fbx"
        obj = import_fbx(base)
        if obj is None:
            continue
        obj.scale = (obj.scale[0] * 1.1, obj.scale[1] * 1.1, obj.scale[2] * 1.12)
        # Top cap for detail.
        bpy.ops.mesh.primitive_uv_sphere_add(radius=0.08, location=(0, 0, obj.dimensions.z + 0.08))
        cap = bpy.context.active_object
        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        cap.select_set(True)
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.join()
        obj = bpy.context.view_layer.objects.active
        obj.name = f"SM_{key}_HERO"
        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        out = masters / f"SM_{key}_HERO.fbx"
        export_selected(out)
        created += 1
        print(f"[OK] exported {out}")
    print(f"[DONE] hero_variants={created}")


if __name__ == "__main__":
    main()
