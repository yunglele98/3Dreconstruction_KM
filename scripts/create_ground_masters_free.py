#!/usr/bin/env python3
"""Create free asphalt/concrete ground masters in Blender."""

import argparse
import sys
from pathlib import Path

import bpy


GROUND_KEYS = [
    "road_asphalt",
    "alley_asphalt",
    "sidewalk_concrete",
    "parking_private",
    "parking_public",
    "parking_hardscape",
    "intersection_hardscape",
    "asphalt_patch_decal",
    "concrete_patch_decal",
    "manhole_cover",
    "storm_drain",
    "curb_segment",
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


def make_mesh(key: str, variant_scale: float):
    if key in {"road_asphalt", "alley_asphalt", "sidewalk_concrete", "parking_private", "parking_public", "parking_hardscape", "intersection_hardscape", "asphalt_patch_decal", "concrete_patch_decal"}:
        bpy.ops.mesh.primitive_plane_add(size=2.0 * variant_scale)
        obj = bpy.context.active_object
        if "decal" in key:
            obj.scale = (0.6 * variant_scale, 0.6 * variant_scale, 1.0)
    elif key == "manhole_cover":
        bpy.ops.mesh.primitive_cylinder_add(vertices=28, radius=0.38 * variant_scale, depth=0.08)
        obj = bpy.context.active_object
    elif key == "storm_drain":
        bpy.ops.mesh.primitive_cube_add(size=0.7 * variant_scale)
        obj = bpy.context.active_object
        obj.scale[2] = 0.08
    elif key == "curb_segment":
        bpy.ops.mesh.primitive_cube_add(size=1.0 * variant_scale)
        obj = bpy.context.active_object
        obj.scale = (0.8 * variant_scale, 0.2 * variant_scale, 0.18 * variant_scale)
    else:
        bpy.ops.mesh.primitive_plane_add(size=1.0 * variant_scale)
        obj = bpy.context.active_object
    return obj


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out", default="outputs/ground/masters")
    args = p.parse_args(sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else [])
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    clear_scene()
    made = 0
    for key in GROUND_KEYS:
        for v_name, scale in [("A_standard", 1.0), ("B_compact", 0.85), ("C_wide", 1.2)]:
            obj = make_mesh(key, scale)
            obj.name = f"SM_{key}_{v_name}"
            bpy.ops.object.select_all(action="DESELECT")
            obj.select_set(True); bpy.context.view_layer.objects.active = obj
            fbx = out / f"{obj.name}.fbx"
            export_selected(fbx)
            made += 1
            print(f"[OK] exported {fbx}")
    bpy.ops.wm.save_as_mainfile(filepath=str(out / "ground_masters_free.blend"))
    print(f"[DONE] created={made}")


if __name__ == "__main__":
    main()
