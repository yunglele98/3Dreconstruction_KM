#!/usr/bin/env python3
"""Create free intersection masters."""

import argparse
import sys
from pathlib import Path

import bpy


TYPES = [
    "intersection_signalized",
    "intersection_t_dangerous",
    "intersection_t_standard",
    "intersection_cross",
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
    bpy.ops.mesh.primitive_plane_add(size=3.6 * scale, location=(0, 0, 0.01))
    deck = bpy.context.active_object

    if key in {"intersection_signalized", "intersection_t_dangerous"}:
        bpy.ops.mesh.primitive_cylinder_add(radius=0.07 * scale, depth=2.2 * scale, location=(1.2 * scale, 1.2 * scale, 1.1 * scale))
        pole = bpy.context.active_object
        bpy.ops.mesh.primitive_cube_add(size=1.0, location=(1.2 * scale, 1.2 * scale, 2.0 * scale))
        signal = bpy.context.active_object
        signal.scale = (0.12 * scale, 0.12 * scale, 0.22 * scale)
    else:
        bpy.ops.mesh.primitive_cube_add(size=1.0, location=(1.3 * scale, 1.3 * scale, 0.55 * scale))
        pole = bpy.context.active_object
        pole.scale = (0.05 * scale, 0.05 * scale, 0.55 * scale)
        bpy.ops.mesh.primitive_plane_add(size=0.45 * scale, location=(1.3 * scale, 1.3 * scale, 1.0 * scale))
        signal = bpy.context.active_object

    bpy.ops.object.select_all(action="DESELECT")
    deck.select_set(True)
    pole.select_set(True)
    signal.select_set(True)
    bpy.context.view_layer.objects.active = deck
    bpy.ops.object.join()
    return bpy.context.view_layer.objects.active


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out", default="outputs/intersections/masters")
    args = p.parse_args(sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else [])

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    clear_scene()
    made = 0
    for key in TYPES:
        for vn, sc in [("A_standard", 1.0), ("B_compact", 0.86), ("C_large", 1.2)]:
            o = make_obj(key, sc)
            o.name = f"SM_{key}_{vn}"
            bpy.ops.object.select_all(action="DESELECT")
            o.select_set(True)
            bpy.context.view_layer.objects.active = o
            fbx = out / f"{o.name}.fbx"
            export_selected(fbx)
            made += 1
            print(f"[OK] exported {fbx}")

    bpy.ops.wm.save_as_mainfile(filepath=str(out / "intersection_masters_free.blend"))
    print(f"[DONE] created={made}")


if __name__ == "__main__":
    main()
