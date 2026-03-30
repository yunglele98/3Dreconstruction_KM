#!/usr/bin/env python3
"""Create HERO FBX variants for listed species keys."""

import argparse
import sys
from pathlib import Path

import bpy


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


def import_or_create_base(species_key: str, masters_dir: Path):
    src = masters_dir / f"SM_{species_key}_A_mature.fbx"
    if src.exists():
        bpy.ops.import_scene.fbx(filepath=str(src))
        objs = list(bpy.context.selected_objects)
        if objs:
            obj = objs[0]
            bpy.ops.object.select_all(action="DESELECT")
            obj.select_set(True)
            bpy.context.view_layer.objects.active = obj
            if obj.type != "MESH":
                bpy.ops.object.convert(target="MESH")
                obj = bpy.context.view_layer.objects.active
            return obj

    # Fallback: create sapling.
    bpy.ops.curve.tree_add(do_update=True)
    obj = bpy.data.objects.get("tree") or bpy.context.active_object
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    if obj.type != "MESH":
        bpy.ops.object.convert(target="MESH")
        obj = bpy.context.view_layer.objects.active
    return obj


def create_hero(species_key: str, masters_dir: Path):
    clear_scene()
    obj = import_or_create_base(species_key, masters_dir)
    obj.name = f"SM_{species_key}_HERO"

    # Make hero slightly more prominent.
    obj.scale = (obj.scale[0] * 1.15, obj.scale[1] * 1.15, obj.scale[2] * 1.18)

    # Add an extra canopy mass for fuller silhouette.
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=2, radius=1.35, location=(0, 0, 3.4))
    can = bpy.context.active_object
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    can.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.join()
    obj = bpy.context.view_layer.objects.active
    obj.name = f"SM_{species_key}_HERO"
    return obj


def export_selected_fbx(obj, out_path: Path):
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
    parser.add_argument("--hero-species-file", required=True)
    parser.add_argument("--masters-dir", default="outputs/trees/masters")
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else [])

    species = [
        s.strip()
        for s in Path(args.hero_species_file).read_text(encoding="utf-8").splitlines()
        if s.strip()
    ]
    masters_dir = Path(args.masters_dir)
    masters_dir.mkdir(parents=True, exist_ok=True)

    has_sapling = try_enable_sapling()
    print(f"[INFO] sapling_available={has_sapling}")

    created = 0
    for key in species:
        out = masters_dir / f"SM_{key}_HERO.fbx"
        obj = create_hero(key, masters_dir)
        export_selected_fbx(obj, out)
        created += 1
        print(f"[OK] exported {out}")

    print(f"[DONE] hero_variants={created}")


if __name__ == "__main__":
    main()
