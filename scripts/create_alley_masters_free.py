#!/usr/bin/env python3
"""Create free alley masters."""

import argparse
import sys
from pathlib import Path

import bpy


TYPES = [
    "alley_vehicle_asphalt",
    "alley_vehicle_concrete",
    "alley_vehicle_gravel",
    "alley_shared",
    "alley_shared_green",
    "alley_service",
    "alley_pedestrian",
    "alley_degraded",
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
    bpy.ops.mesh.primitive_plane_add(size=3.0 * scale, location=(0, 0, 0.01))
    base = bpy.context.active_object

    if "green" in key:
        bpy.ops.mesh.primitive_cube_add(size=1.0, location=(-0.8 * scale, 0.8 * scale, 0.2 * scale))
        planter = bpy.context.active_object
        planter.scale = (0.25 * scale, 0.25 * scale, 0.2 * scale)
        bpy.ops.mesh.primitive_uv_sphere_add(radius=0.18 * scale, location=(-0.8 * scale, 0.8 * scale, 0.45 * scale))
        shrub = bpy.context.active_object
        objs = [base, planter, shrub]
    elif "service" in key:
        bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0.9 * scale, 0.0, 0.5 * scale))
        bin_obj = bpy.context.active_object
        bin_obj.scale = (0.22 * scale, 0.18 * scale, 0.5 * scale)
        objs = [base, bin_obj]
    elif "pedestrian" in key:
        bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0.7 * scale, 0.0, 0.4 * scale))
        bollard = bpy.context.active_object
        bollard.scale = (0.08 * scale, 0.08 * scale, 0.4 * scale)
        objs = [base, bollard]
    elif "degraded" in key:
        bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0.0, 0.0, 0.03 * scale))
        patch = bpy.context.active_object
        patch.scale = (0.5 * scale, 0.3 * scale, 0.03 * scale)
        objs = [base, patch]
    else:
        objs = [base]

    bpy.ops.object.select_all(action="DESELECT")
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = base
    bpy.ops.object.join()
    return bpy.context.view_layer.objects.active


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out", default="outputs/alleys/masters")
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

    bpy.ops.wm.save_as_mainfile(filepath=str(out / "alley_masters_free.blend"))
    print(f"[DONE] created={made}")


if __name__ == "__main__":
    main()
