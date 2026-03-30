#!/usr/bin/env python3
"""Create free bike rack masters in Blender."""

import argparse
import sys
from pathlib import Path

import bpy


RACKS = ["u_rack", "spiral_rack", "ring_rack", "multi_rack", "generic_rack"]


def clear_scene():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)


def export_selected(path: Path):
    bpy.ops.export_scene.fbx(
        filepath=str(path),
        use_selection=True,
        apply_unit_scale=True,
        bake_space_transform=False,
        object_types={"MESH"},
    )


def make_rack(name: str, key: str, scale: float):
    if key == "u_rack":
        bpy.ops.mesh.primitive_torus_add(major_radius=0.35 * scale, minor_radius=0.03 * scale, location=(0, 0, 0.45 * scale), rotation=(1.57, 0, 0))
    elif key == "spiral_rack":
        bpy.ops.mesh.primitive_torus_add(major_radius=0.25 * scale, minor_radius=0.03 * scale, location=(0, 0, 0.45 * scale), rotation=(1.57, 0.7, 0))
    elif key == "ring_rack":
        bpy.ops.mesh.primitive_torus_add(major_radius=0.28 * scale, minor_radius=0.028 * scale, location=(0, 0, 0.5 * scale), rotation=(1.57, 0, 0))
    elif key == "multi_rack":
        bpy.ops.mesh.primitive_torus_add(major_radius=0.35 * scale, minor_radius=0.03 * scale, location=(-0.35 * scale, 0, 0.45 * scale), rotation=(1.57, 0, 0))
        a = bpy.context.active_object
        bpy.ops.mesh.primitive_torus_add(major_radius=0.35 * scale, minor_radius=0.03 * scale, location=(0.35 * scale, 0, 0.45 * scale), rotation=(1.57, 0, 0))
        b = bpy.context.active_object
        bpy.ops.object.select_all(action="DESELECT")
        a.select_set(True); b.select_set(True); bpy.context.view_layer.objects.active = a
        bpy.ops.object.join()
    else:
        bpy.ops.mesh.primitive_cube_add(size=0.7 * scale, location=(0, 0, 0.35 * scale))
    obj = bpy.context.active_object
    obj.name = name
    return obj


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out", default="outputs/bikeracks/masters")
    args = p.parse_args(sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else [])
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    clear_scene()
    made = 0
    for key in RACKS:
        for v_name, scl in [("A_standard", 1.0), ("B_compact", 0.88), ("C_wide", 1.15)]:
            obj = make_rack(f"SM_{key}_{v_name}", key, scl)
            bpy.ops.object.select_all(action="DESELECT")
            obj.select_set(True)
            bpy.context.view_layer.objects.active = obj
            fbx = out / f"{obj.name}.fbx"
            export_selected(fbx)
            made += 1
            print(f"[OK] exported {fbx}")
    bpy.ops.wm.save_as_mainfile(filepath=str(out / "bikerack_masters_free.blend"))
    print(f"[DONE] created={made}")


if __name__ == "__main__":
    main()
