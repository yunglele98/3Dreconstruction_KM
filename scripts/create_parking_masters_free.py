#!/usr/bin/env python3
"""Create free parking infrastructure masters."""

import argparse
import sys
from pathlib import Path

import bpy


TYPES = [
    "parking_lot",
    "parking_lot_paid",
    "parking_meter",
    "parking_accessible_bay",
    "parking_private_pad",
    "parking_surface_public",
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
    if key in {"parking_lot", "parking_lot_paid", "parking_surface_public", "parking_private_pad"}:
        bpy.ops.mesh.primitive_plane_add(size=2.6 * scale, location=(0, 0, 0.01))
        base = bpy.context.active_object
        if key == "parking_lot_paid":
            bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0.7 * scale, 0.0, 0.75 * scale))
            kiosk = bpy.context.active_object
            kiosk.scale = (0.16 * scale, 0.12 * scale, 0.72 * scale)
            bpy.ops.object.select_all(action="DESELECT")
            base.select_set(True)
            kiosk.select_set(True)
            bpy.context.view_layer.objects.active = base
            bpy.ops.object.join()
            return bpy.context.view_layer.objects.active
        return base
    if key == "parking_meter":
        bpy.ops.mesh.primitive_cylinder_add(radius=0.06 * scale, depth=1.35 * scale, location=(0, 0, 0.68 * scale))
        pole = bpy.context.active_object
        bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0, 0, 1.35 * scale))
        head = bpy.context.active_object
        head.scale = (0.12 * scale, 0.1 * scale, 0.12 * scale)
        bpy.ops.object.select_all(action="DESELECT")
        pole.select_set(True)
        head.select_set(True)
        bpy.context.view_layer.objects.active = pole
        bpy.ops.object.join()
        return bpy.context.view_layer.objects.active
    bpy.ops.mesh.primitive_plane_add(size=2.4 * scale, location=(0, 0, 0.01))
    bay = bpy.context.active_object
    bpy.ops.mesh.primitive_cylinder_add(radius=0.05 * scale, depth=1.8 * scale, location=(0.9 * scale, 0.0, 0.9 * scale))
    post = bpy.context.active_object
    bpy.ops.mesh.primitive_plane_add(size=0.45 * scale, location=(0.9 * scale, 0.0, 1.7 * scale))
    sign = bpy.context.active_object
    bpy.ops.object.select_all(action="DESELECT")
    bay.select_set(True)
    post.select_set(True)
    sign.select_set(True)
    bpy.context.view_layer.objects.active = bay
    bpy.ops.object.join()
    return bpy.context.view_layer.objects.active


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out", default="outputs/parking/masters")
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

    bpy.ops.wm.save_as_mainfile(filepath=str(out / "parking_masters_free.blend"))
    print(f"[DONE] created={made}")


if __name__ == "__main__":
    main()
