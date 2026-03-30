#!/usr/bin/env python3
"""Create base vertical hardscape masters in Blender."""

import argparse
import sys
from pathlib import Path

import bpy


KEYS = [
    "foundation_wall_segment",
    "retaining_wall_segment",
    "curb_vertical_segment",
    "stair_module",
    "loading_edge",
]


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


def make_obj(key: str, scale: float):
    if key == "foundation_wall_segment":
        bpy.ops.mesh.primitive_cube_add(size=1.0)
        o = bpy.context.active_object
        o.scale = (1.0 * scale, 0.18 * scale, 0.55 * scale)
    elif key == "retaining_wall_segment":
        bpy.ops.mesh.primitive_cube_add(size=1.0)
        o = bpy.context.active_object
        o.scale = (1.0 * scale, 0.26 * scale, 0.9 * scale)
    elif key == "curb_vertical_segment":
        bpy.ops.mesh.primitive_cube_add(size=1.0)
        o = bpy.context.active_object
        o.scale = (0.8 * scale, 0.22 * scale, 0.22 * scale)
    elif key == "stair_module":
        bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0, 0, 0.1))
        a = bpy.context.active_object
        a.scale = (0.65 * scale, 0.45 * scale, 0.1 * scale)
        bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0, 0.35 * scale, 0.3))
        b = bpy.context.active_object
        b.scale = (0.65 * scale, 0.45 * scale, 0.1 * scale)
        bpy.ops.object.select_all(action="DESELECT"); a.select_set(True); b.select_set(True); bpy.context.view_layer.objects.active = a; bpy.ops.object.join()
        o = bpy.context.view_layer.objects.active
    else:  # loading_edge
        bpy.ops.mesh.primitive_cube_add(size=1.0)
        o = bpy.context.active_object
        o.scale = (0.9 * scale, 0.24 * scale, 0.3 * scale)
    return o


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out", default="outputs/vertical_hardscape/masters")
    args = p.parse_args(sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else [])
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    clear_scene()
    made = 0
    for key in KEYS:
        for vn, sc in [("A_standard", 1.0), ("B_compact", 0.85), ("C_tall", 1.18)]:
            o = make_obj(key, sc)
            o.name = f"SM_{key}_{vn}"
            bpy.ops.object.select_all(action="DESELECT"); o.select_set(True); bpy.context.view_layer.objects.active = o
            fbx = out / f"{o.name}.fbx"; export_selected(fbx); made += 1
            print(f"[OK] exported {fbx}")
    bpy.ops.wm.save_as_mainfile(filepath=str(out / "vertical_hardscape_masters_free.blend"))
    print(f"[DONE] created={made}")


if __name__ == "__main__":
    main()
