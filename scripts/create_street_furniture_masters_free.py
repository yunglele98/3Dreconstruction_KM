#!/usr/bin/env python3
"""Create free masters for unified street furniture types."""

import argparse
import sys
from pathlib import Path

import bpy


TYPES = [
    "bus_shelter_standard",
    "bus_shelter_glass",
    "public_art_mural",
    "public_art_sculpture",
    "public_art_installation",
    "terrace_platform",
    "terrace_patio",
    "terrace_module",
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
    if key.startswith("bus_shelter"):
        bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0, 0, 1.0 * scale))
        roof = bpy.context.active_object
        roof.scale = (1.8 * scale, 0.9 * scale, 0.08 * scale)
        bpy.ops.mesh.primitive_cube_add(size=1.0, location=(-1.3 * scale, 0, 0.6 * scale))
        p1 = bpy.context.active_object
        p1.scale = (0.07 * scale, 0.07 * scale, 0.6 * scale)
        bpy.ops.mesh.primitive_cube_add(size=1.0, location=(1.3 * scale, 0, 0.6 * scale))
        p2 = bpy.context.active_object
        p2.scale = (0.07 * scale, 0.07 * scale, 0.6 * scale)
        bpy.ops.object.select_all(action="DESELECT"); roof.select_set(True); p1.select_set(True); p2.select_set(True); bpy.context.view_layer.objects.active = roof; bpy.ops.object.join()
        o = bpy.context.view_layer.objects.active
    elif key == "public_art_mural":
        bpy.ops.mesh.primitive_plane_add(size=2.0 * scale, location=(0, 0, 1.6 * scale))
        o = bpy.context.active_object
    elif key == "public_art_sculpture":
        bpy.ops.mesh.primitive_uv_sphere_add(radius=0.6 * scale, location=(0, 0, 1.1 * scale))
        o = bpy.context.active_object
    elif key == "public_art_installation":
        bpy.ops.mesh.primitive_torus_add(major_radius=0.6 * scale, minor_radius=0.12 * scale, location=(0, 0, 1.2 * scale))
        o = bpy.context.active_object
    elif key == "terrace_platform":
        bpy.ops.mesh.primitive_cube_add(size=1.0)
        o = bpy.context.active_object
        o.scale = (1.8 * scale, 1.4 * scale, 0.18 * scale)
    elif key == "terrace_patio":
        bpy.ops.mesh.primitive_plane_add(size=2.4 * scale)
        o = bpy.context.active_object
    else:
        bpy.ops.mesh.primitive_cube_add(size=1.0)
        o = bpy.context.active_object
        o.scale = (1.4 * scale, 1.2 * scale, 0.16 * scale)
    return o


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out", default="outputs/street_furniture/masters")
    args = p.parse_args(sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else [])
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    clear_scene()
    made = 0
    for key in TYPES:
        for vn, sc in [("A_standard", 1.0), ("B_compact", 0.86), ("C_large", 1.2)]:
            o = make_obj(key, sc)
            o.name = f"SM_{key}_{vn}"
            bpy.ops.object.select_all(action="DESELECT"); o.select_set(True); bpy.context.view_layer.objects.active = o
            fbx = out / f"{o.name}.fbx"; export_selected(fbx); made += 1
            print(f"[OK] exported {fbx}")
    bpy.ops.wm.save_as_mainfile(filepath=str(out / "street_furniture_masters_free.blend"))
    print(f"[DONE] created={made}")


if __name__ == "__main__":
    main()
