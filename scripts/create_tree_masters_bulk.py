#!/usr/bin/env python3
"""Bulk-create missing tree masters in Blender from species key list.

Run:
  blender --background --python scripts/create_tree_masters_bulk.py -- \
    --species-file outputs/trees/missing_species_keys.txt \
    --out outputs/trees/masters
"""

import argparse
import math
from pathlib import Path
import sys

import bpy


CONIFER_HINTS = ("spruce", "pine", "cedar", "fir", "thuja", "juniper", "picea", "pinus")


def clear_scene():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)


def try_enable_sapling() -> bool:
    try:
        import addon_utils
    except Exception:
        return False
    for module in ("add_curve_sapling", "add_curve_sapling_3"):
        try:
            addon_utils.enable(module, default_set=False, persistent=False)
        except Exception:
            continue
        if hasattr(bpy.ops.curve, "tree_add"):
            return True
    return hasattr(bpy.ops.curve, "tree_add")


def ensure_mesh(obj):
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    if obj.type != "MESH":
        bpy.ops.object.convert(target="MESH")
        obj = bpy.context.view_layer.objects.active
    return obj


def create_proxy(name: str, scale_factor: float, is_conifer: bool):
    bpy.ops.mesh.primitive_cylinder_add(vertices=10, radius=0.1 * scale_factor, depth=2.4 * scale_factor)
    trunk = bpy.context.active_object
    trunk.location.z = 1.2 * scale_factor
    if is_conifer:
        bpy.ops.mesh.primitive_cone_add(vertices=12, radius1=0.9 * scale_factor, depth=3.0 * scale_factor)
        canopy = bpy.context.active_object
        canopy.location.z = 3.2 * scale_factor
    else:
        bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=2, radius=1.3 * scale_factor)
        canopy = bpy.context.active_object
        canopy.location.z = 3.2 * scale_factor
    bpy.ops.object.select_all(action="DESELECT")
    trunk.select_set(True)
    canopy.select_set(True)
    bpy.context.view_layer.objects.active = trunk
    bpy.ops.object.join()
    obj = bpy.context.active_object
    obj.name = name
    return obj


def create_sapling(name: str, species_key: str, idx: int):
    before = {o.name for o in bpy.data.objects}
    bpy.ops.curve.tree_add(do_update=True)
    created = [o for o in bpy.data.objects if o.name not in before]
    obj = created[-1] if created else bpy.data.objects.get("tree")
    if obj is None:
        raise RuntimeError("Sapling tree_add completed but no object found.")
    obj = ensure_mesh(obj)
    obj.name = name
    obj.rotation_euler[2] = math.radians((idx * 23) % 360)

    is_conifer = any(h in species_key for h in CONIFER_HINTS)
    if is_conifer:
        obj.scale = (0.9, 0.9, 1.15)
    else:
        obj.scale = (1.05, 1.05, 1.12)
        bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=1, radius=1.15, location=(0, 0, 3.0))
        leaf = bpy.context.active_object
        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        leaf.select_set(True)
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.join()
        obj = bpy.context.active_object
        obj.name = name
    return obj


def export_fbx(obj, out_path: Path):
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.export_scene.fbx(
        filepath=str(out_path),
        use_selection=True,
        apply_unit_scale=True,
        bake_space_transform=False,
        object_types={"MESH"},
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--species-file", required=True)
    parser.add_argument("--out", default="outputs/trees/masters")
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    args = parser.parse_args(argv)

    species_file = Path(args.species_file)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    species_keys = [
        line.strip()
        for line in species_file.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if not species_keys:
        print("[OK] No unresolved species to generate.")
        return

    clear_scene()
    has_sapling = try_enable_sapling()
    print(f"[INFO] sapling_available={has_sapling}")
    created = 0

    for idx, key in enumerate(species_keys, start=1):
        name = f"SM_{key}_A_mature"
        fbx_path = out_dir / f"{name}.fbx"
        if fbx_path.exists():
            continue
        is_conifer = any(h in key for h in CONIFER_HINTS)
        if has_sapling:
            obj = create_sapling(name, key, idx)
        else:
            obj = create_proxy(name, 1.0, is_conifer)
        export_fbx(obj, fbx_path)
        created += 1
        print(f"[OK] exported {fbx_path}")

    blend_path = out_dir / "tree_masters_bulk.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))
    print(f"[OK] saved {blend_path}")
    print(f"[DONE] created_new={created}")


if __name__ == "__main__":
    main()
