#!/usr/bin/env python3
"""Create LOD1/LOD2/BILLBOARD for HERO pole assets."""

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


def make_lod(obj, ratio: float, name: str):
    dup = obj.copy()
    dup.data = obj.data.copy()
    bpy.context.collection.objects.link(dup)
    dup.name = name
    bpy.ops.object.select_all(action="DESELECT")
    dup.select_set(True)
    bpy.context.view_layer.objects.active = dup
    mod = dup.modifiers.new(name="Decimate", type="DECIMATE")
    mod.ratio = ratio
    bpy.ops.object.modifier_apply(modifier=mod.name)
    return dup


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--hero-file", required=True)
    p.add_argument("--masters-dir", default="outputs/poles/masters")
    p.add_argument("--lod-dir", default="outputs/poles/lods")
    args = p.parse_args(sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else [])

    heroes = [s.strip() for s in Path(args.hero_file).read_text(encoding="utf-8").splitlines() if s.strip()]
    masters = Path(args.masters_dir)
    lod_dir = Path(args.lod_dir)
    lod_dir.mkdir(parents=True, exist_ok=True)
    made = 0
    for key in heroes:
        src = masters / f"SM_{key}_HERO.fbx"
        if not src.exists():
            continue
        clear_scene()
        base = import_fbx(src)
        if base is None:
            continue
        l1 = make_lod(base, 0.5, f"SM_{key}_LOD1")
        l2 = make_lod(base, 0.2, f"SM_{key}_LOD2")
        bpy.ops.mesh.primitive_plane_add(size=1.0, location=(0, 0, max(base.dimensions.z * 0.5, 1.0)))
        bb = bpy.context.active_object
        bb.name = f"SM_{key}_BILLBOARD"
        for obj, suffix in ((l1, "LOD1"), (l2, "LOD2"), (bb, "BILLBOARD")):
            bpy.ops.object.select_all(action="DESELECT")
            obj.select_set(True)
            bpy.context.view_layer.objects.active = obj
            out = lod_dir / f"SM_{key}_{suffix}.fbx"
            export_selected(out)
            print(f"[OK] exported {out}")
            made += 1
    print(f"[DONE] generated_files={made}")


if __name__ == "__main__":
    main()
