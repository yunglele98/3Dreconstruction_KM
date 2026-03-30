#!/usr/bin/env python3
"""Build LOD1/LOD2 + billboard FBX for HERO species assets."""

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
    objs = [o for o in bpy.data.objects if o.name not in before]
    if not objs:
        return None
    obj = objs[-1]
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


def make_billboard(name: str):
    bpy.ops.mesh.primitive_plane_add(size=2.0, location=(0, 0, 2.0))
    bb = bpy.context.active_object
    bb.name = name
    return bb


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--hero-species-file", required=True)
    parser.add_argument("--masters-dir", default="outputs/trees/masters")
    parser.add_argument("--lod-dir", default="outputs/trees/lods")
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else [])

    heroes = [
        s.strip()
        for s in Path(args.hero_species_file).read_text(encoding="utf-8").splitlines()
        if s.strip()
    ]
    masters = Path(args.masters_dir)
    lod_dir = Path(args.lod_dir)
    lod_dir.mkdir(parents=True, exist_ok=True)

    generated = 0
    for key in heroes:
        src = masters / f"SM_{key}_HERO.fbx"
        if not src.exists():
            continue
        clear_scene()
        base = import_fbx(src)
        if base is None:
            continue
        base.name = f"SM_{key}_HERO"

        lod1 = make_lod(base, 0.45, f"SM_{key}_LOD1")
        lod2 = make_lod(base, 0.18, f"SM_{key}_LOD2")
        bb = make_billboard(f"SM_{key}_BILLBOARD")

        for obj, suffix in ((lod1, "LOD1"), (lod2, "LOD2"), (bb, "BILLBOARD")):
            bpy.ops.object.select_all(action="DESELECT")
            obj.select_set(True)
            bpy.context.view_layer.objects.active = obj
            out = lod_dir / f"SM_{key}_{suffix}.fbx"
            export_selected(out)
            generated += 1
            print(f"[OK] exported {out}")

    print(f"[DONE] generated_files={generated}")


if __name__ == "__main__":
    main()
