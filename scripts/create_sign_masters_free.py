#!/usr/bin/env python3
"""Create free street sign masters in Blender."""

import argparse
import sys
from pathlib import Path

import bpy


SIGNS = ["generic_sign", "info_sign", "speed_sign", "restriction_sign", "warning_sign", "oneway_sign"]


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


def make_sign(key: str, scale: float):
    # pole
    bpy.ops.mesh.primitive_cylinder_add(vertices=12, radius=0.03 * scale, depth=2.5 * scale, location=(0, 0, 1.25 * scale))
    pole = bpy.context.active_object
    # sign board
    if key in {"warning_sign"}:
        bpy.ops.mesh.primitive_plane_add(size=0.55 * scale, location=(0, 0.035 * scale, 2.0 * scale), rotation=(0.0, 0.0, 0.785))
    elif key in {"oneway_sign", "restriction_sign"}:
        bpy.ops.mesh.primitive_plane_add(size=0.6 * scale, location=(0, 0.035 * scale, 2.0 * scale))
    elif key in {"speed_sign"}:
        bpy.ops.mesh.primitive_circle_add(vertices=24, radius=0.28 * scale, fill_type="NGON", location=(0, 0.035 * scale, 2.0 * scale))
    else:
        bpy.ops.mesh.primitive_plane_add(size=0.7 * scale, location=(0, 0.035 * scale, 2.0 * scale))
    board = bpy.context.active_object
    bpy.ops.object.select_all(action="DESELECT")
    pole.select_set(True); board.select_set(True); bpy.context.view_layer.objects.active = pole
    bpy.ops.object.join()
    return bpy.context.view_layer.objects.active


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out", default="outputs/signs/masters")
    args = p.parse_args(sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else [])
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    clear_scene()
    made = 0
    for key in SIGNS:
        for vn, sc in [("A_standard", 1.0), ("B_compact", 0.88), ("C_tall", 1.15)]:
            o = make_sign(key, sc)
            o.name = f"SM_{key}_{vn}"
            bpy.ops.object.select_all(action="DESELECT"); o.select_set(True); bpy.context.view_layer.objects.active = o
            fbx = out / f"{o.name}.fbx"; export_selected(fbx); made += 1
            print(f"[OK] exported {fbx}")
    bpy.ops.wm.save_as_mainfile(filepath=str(out / "sign_masters_free.blend"))
    print(f"[DONE] created={made}")


if __name__ == "__main__":
    main()
