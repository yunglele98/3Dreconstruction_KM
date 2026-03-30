#!/usr/bin/env python3
"""Create base pole masters in Blender."""

import argparse
import sys
from pathlib import Path

import bpy


POLES = {
    "streetlight_pole": (7.5, 0.09),
    "sign_pole": (3.2, 0.04),
    "utility_pole": (9.0, 0.14),
    "generic_pole": (5.0, 0.06),
}

VARIANTS = [("A_standard", 1.0), ("B_short", 0.86), ("C_tall", 1.15)]


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


def build_pole(name: str, h: float, r: float):
    bpy.ops.mesh.primitive_cylinder_add(vertices=14, radius=r, depth=h, location=(0, 0, h / 2.0))
    obj = bpy.context.active_object
    obj.name = name
    return obj


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="outputs/poles/masters")
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else [])
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    clear_scene()
    count = 0
    for key, (h, r) in POLES.items():
        for v_name, scale in VARIANTS:
            bpy.ops.object.select_all(action="DESELECT")
            obj = build_pole(f"SM_{key}_{v_name}", h * scale, r * (0.98 if v_name == "B_short" else 1.0))
            bpy.ops.object.select_all(action="DESELECT")
            obj.select_set(True)
            bpy.context.view_layer.objects.active = obj
            fbx = out / f"{obj.name}.fbx"
            export_selected(fbx)
            count += 1
            print(f"[OK] exported {fbx}")

    bpy.ops.wm.save_as_mainfile(filepath=str(out / "pole_masters_free.blend"))
    print(f"[DONE] created={count}")


if __name__ == "__main__":
    main()
