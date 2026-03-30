#!/usr/bin/env python3
"""Create free masters for alley+garage element types."""

import argparse
import sys
from pathlib import Path

import bpy


TYPES = [
    "alley_shared_surface",
    "alley_vehicle_asphalt",
    "alley_vehicle_concrete",
    "alley_vehicle_gravel",
    "alley_service_lane",
    "alley_pedestrian_cutthrough",
    "alley_green_edge",
    "alley_degraded_patch",
    "alley_service_corridor",
    "alley_graffiti_wall",
    "alley_chainlink_edge",
    "alley_hazard_segment",
    "garage_single_modern",
    "garage_residential_pair",
    "garage_row_rollup_tagged",
    "garage_structured_entrance",
    "garage_structured_interior_marker",
]


def clear_scene():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)


def export_selected(path: Path):
    bpy.ops.export_scene.fbx(filepath=str(path), use_selection=True, apply_unit_scale=True, bake_space_transform=False, object_types={"MESH"})


def _join(objs):
    if len(objs) == 1:
        return objs[0]
    bpy.ops.object.select_all(action="DESELECT")
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]
    bpy.ops.object.join()
    return bpy.context.view_layer.objects.active


def _add_rollup_panel(x: float, y: float, z: float, sx: float, sy: float, sz: float):
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=(x, y, z))
    o = bpy.context.active_object
    o.scale = (sx, sy, sz)
    return o


def _add_garage_bay(center_x: float, scale: float, depth: float = 0.34, height: float = 0.95):
    objs = []
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=(center_x, 0, height * scale))
    shell = bpy.context.active_object
    shell.scale = (0.56 * scale, depth * scale, height * scale)
    objs.append(shell)

    # Roll-up door with visible slat rhythm.
    for i in range(8):
        z = (0.20 + i * 0.18) * scale
        slat = _add_rollup_panel(center_x, (depth + 0.01) * scale, z, 0.45 * scale, 0.015 * scale, 0.06 * scale)
        objs.append(slat)

    # Door side rails.
    left_rail = _add_rollup_panel(center_x - 0.47 * scale, (depth + 0.015) * scale, 0.90 * scale, 0.02 * scale, 0.015 * scale, 0.90 * scale)
    right_rail = _add_rollup_panel(center_x + 0.47 * scale, (depth + 0.015) * scale, 0.90 * scale, 0.02 * scale, 0.015 * scale, 0.90 * scale)
    header = _add_rollup_panel(center_x, (depth + 0.015) * scale, 1.82 * scale, 0.48 * scale, 0.015 * scale, 0.04 * scale)
    objs.extend([left_rail, right_rail, header])
    return objs


def _add_bollard(x: float, y: float, scale: float, h: float = 0.5):
    bpy.ops.mesh.primitive_cylinder_add(radius=0.045 * scale, depth=h * scale, location=(x, y, (h * 0.5) * scale))
    return bpy.context.active_object


def _add_chainlink_panel(x: float, y: float, z: float, scale: float):
    objs = []
    panel = _add_rollup_panel(x, y, z, 1.0 * scale, 0.01 * scale, 0.8 * scale)
    objs.append(panel)
    for dx in (-0.95, 0.95):
        bpy.ops.mesh.primitive_cylinder_add(radius=0.025 * scale, depth=1.7 * scale, location=(x + dx * scale, y, 0.85 * scale))
        objs.append(bpy.context.active_object)
    return objs


def make_obj(key: str, scale: float):
    if key.startswith("garage_row"):
        objs = []
        for i in range(3):
            x = (-1.2 + i * 1.2) * scale
            objs.extend(_add_garage_bay(x, scale, depth=0.34, height=0.95))
        objs.append(_add_bollard(-2.0 * scale, 0.52 * scale, scale, h=0.55))
        objs.append(_add_bollard(2.0 * scale, 0.52 * scale, scale, h=0.55))
        return _join(objs)
    if key.startswith("garage_residential"):
        objs = []
        for i in range(2):
            x = (-0.7 + i * 1.4) * scale
            objs.extend(_add_garage_bay(x, scale, depth=0.30, height=0.88))
        # Shared driveway apron.
        bpy.ops.mesh.primitive_plane_add(size=2.8 * scale, location=(0, 0.52 * scale, 0.01))
        objs.append(bpy.context.active_object)
        return _join(objs)
    if key.startswith("garage_single"):
        objs = _add_garage_bay(0.0, scale, depth=0.36, height=0.96)
        # Side man-door.
        side_door = _add_rollup_panel(0.63 * scale, 0.37 * scale, 0.52 * scale, 0.13 * scale, 0.02 * scale, 0.52 * scale)
        objs.append(side_door)
        return _join(objs)
    if key == "garage_structured_entrance":
        bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0, 0, 1.25 * scale))
        slab = bpy.context.active_object
        slab.scale = (1.5 * scale, 0.55 * scale, 0.14 * scale)
        bpy.ops.mesh.primitive_plane_add(size=2.8 * scale, location=(0, 0, 0.01))
        ramp = bpy.context.active_object
        # Height bar and twin bollards at ramp mouth.
        bar = _add_rollup_panel(0.0, 0.55 * scale, 1.9 * scale, 1.2 * scale, 0.03 * scale, 0.03 * scale)
        b1 = _add_bollard(-0.95 * scale, 0.62 * scale, scale, h=0.65)
        b2 = _add_bollard(0.95 * scale, 0.62 * scale, scale, h=0.65)
        return _join([slab, ramp, bar, b1, b2])
    if key == "garage_structured_interior_marker":
        bpy.ops.mesh.primitive_plane_add(size=3.0 * scale, location=(0, 0, 0.01))
        floor = bpy.context.active_object
        bpy.ops.mesh.primitive_cube_add(size=1.0, location=(-0.8 * scale, 0, 1.05 * scale))
        col = bpy.context.active_object
        col.scale = (0.2 * scale, 0.2 * scale, 1.05 * scale)
        # Ceiling pipe axis and lane stripe marker.
        pipe = _add_rollup_panel(0.0, -0.2 * scale, 2.0 * scale, 1.4 * scale, 0.03 * scale, 0.03 * scale)
        stripe = _add_rollup_panel(0.0, 0.6 * scale, 0.015, 1.0 * scale, 0.06 * scale, 0.01 * scale)
        return _join([floor, col, pipe, stripe])

    bpy.ops.mesh.primitive_plane_add(size=2.8 * scale, location=(0, 0, 0.01))
    base = bpy.context.active_object
    objs = [base]
    if key == "alley_graffiti_wall":
        bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0, -1.1 * scale, 1.2 * scale))
        w = bpy.context.active_object
        w.scale = (1.4 * scale, 0.08 * scale, 1.2 * scale)
        objs.append(w)
        tag_panel = _add_rollup_panel(-0.4 * scale, -1.0 * scale, 1.0 * scale, 0.45 * scale, 0.01 * scale, 0.45 * scale)
        objs.append(tag_panel)
    elif key == "alley_chainlink_edge":
        objs.extend(_add_chainlink_panel(0.0, -1.0 * scale, 0.8 * scale, scale))
    elif key == "alley_hazard_segment":
        bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0.5 * scale, 0, 0.05 * scale))
        b = bpy.context.active_object
        b.scale = (0.5 * scale, 0.06 * scale, 0.05 * scale)
        objs.append(b)
        cone = _add_rollup_panel(-0.2 * scale, 0.25 * scale, 0.16 * scale, 0.08 * scale, 0.08 * scale, 0.16 * scale)
        objs.append(cone)
    elif key == "alley_green_edge":
        bpy.ops.mesh.primitive_uv_sphere_add(radius=0.22 * scale, location=(0.9 * scale, 0.8 * scale, 0.24 * scale))
        shrub = bpy.context.active_object
        objs.append(shrub)
        planter = _add_rollup_panel(0.9 * scale, 0.8 * scale, 0.12 * scale, 0.24 * scale, 0.24 * scale, 0.12 * scale)
        objs.append(planter)
    elif key == "alley_service_lane":
        bpy.ops.mesh.primitive_cube_add(size=1.0, location=(1.0 * scale, 0, 0.45 * scale))
        bin_obj = bpy.context.active_object
        bin_obj.scale = (0.18 * scale, 0.2 * scale, 0.45 * scale)
        objs.append(bin_obj)
        objs.append(_add_bollard(0.4 * scale, 0.2 * scale, scale, h=0.5))
    elif key in {"alley_vehicle_asphalt", "alley_vehicle_concrete", "alley_vehicle_gravel", "alley_shared_surface", "alley_service_corridor"}:
        # Subtle curb and puddle strip to break flat-surface repetition.
        curb = _add_rollup_panel(-1.2 * scale, -1.0 * scale, 0.04 * scale, 0.25 * scale, 0.05 * scale, 0.04 * scale)
        puddle = _add_rollup_panel(0.8 * scale, 0.9 * scale, 0.012, 0.35 * scale, 0.20 * scale, 0.01 * scale)
        objs.extend([curb, puddle])

    return _join(objs)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out", default="outputs/alley_garages/masters")
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

    bpy.ops.wm.save_as_mainfile(filepath=str(out / "alley_garage_masters_free.blend"))
    print(f"[DONE] created={made}")


if __name__ == "__main__":
    main()
