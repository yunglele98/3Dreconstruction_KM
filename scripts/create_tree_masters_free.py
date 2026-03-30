#!/usr/bin/env python3
"""Create free starter tree masters in Blender for Unreal foliage workflow.

Run:
  blender --background --python scripts/create_tree_masters_free.py -- --out outputs/trees/masters
"""

import argparse
import math
from pathlib import Path

import bpy


SPECIES_VARIANTS = [
    ("blue_spruce", "A_mature", 1.00),
    ("blue_spruce", "B_medium", 0.82),
    ("blue_spruce", "C_asymmetric", 0.95),
    ("white_spruce", "A_mature", 1.00),
    ("white_spruce", "B_medium", 0.85),
    ("white_spruce", "C_asymmetric", 0.95),
    ("eastern_white_pine", "A_mature", 1.20),
    ("eastern_white_pine", "B_medium", 0.95),
    ("eastern_white_pine", "C_asymmetric", 1.10),
    ("white_cedar", "A_mature", 0.90),
    ("white_cedar", "B_medium", 0.78),
    ("white_cedar", "C_asymmetric", 0.88),
    ("gleditsia_triacanthos", "A_mature", 1.05),
    ("gleditsia_triacanthos", "B_medium", 0.90),
    ("gleditsia_triacanthos", "C_asymmetric", 1.00),
    ("acer_platanoides", "A_mature", 1.08),
    ("acer_platanoides", "B_medium", 0.92),
    ("acer_platanoides", "C_asymmetric", 1.00),
    ("ulmus", "A_mature", 1.06),
    ("ulmus", "B_medium", 0.90),
    ("ulmus", "C_asymmetric", 1.00),
    ("tilia", "A_mature", 1.02),
    ("tilia", "B_medium", 0.88),
    ("tilia", "C_asymmetric", 0.98),
    ("platanus_x_acerifolia", "A_mature", 1.10),
    ("platanus_x_acerifolia", "B_medium", 0.94),
    ("platanus_x_acerifolia", "C_asymmetric", 1.03),
    ("ginkgo_biloba", "A_mature", 0.98),
    ("ginkgo_biloba", "B_medium", 0.86),
    ("ginkgo_biloba", "C_asymmetric", 0.94),
    ("quercus_rubra", "A_mature", 1.12),
    ("quercus_rubra", "B_medium", 0.96),
    ("quercus_rubra", "C_asymmetric", 1.04),
    ("acer_negundo", "A_mature", 1.03),
    ("acer_negundo", "B_medium", 0.90),
    ("acer_negundo", "C_asymmetric", 0.98),
    ("acer_saccharinum", "A_mature", 1.10),
    ("acer_saccharinum", "B_medium", 0.95),
    ("acer_saccharinum", "C_asymmetric", 1.02),
    ("allianthus_altissima", "A_mature", 1.07),
    ("allianthus_altissima", "B_medium", 0.92),
    ("allianthus_altissima", "C_asymmetric", 1.00),
]


def clear_scene():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for block in (bpy.data.meshes, bpy.data.curves, bpy.data.materials, bpy.data.images):
        for item in list(block):
            if item.users == 0:
                block.remove(item)


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


def ensure_mesh_active(obj):
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    if obj.type != "MESH":
        bpy.ops.object.convert(target="MESH")
        obj = bpy.context.view_layer.objects.active
    return obj


def create_proxy_tree(name: str, scale_factor: float):
    bpy.ops.mesh.primitive_cylinder_add(vertices=12, radius=0.12 * scale_factor, depth=2.2 * scale_factor)
    trunk = bpy.context.active_object
    trunk.name = f"{name}_trunk"
    trunk.location.z = 1.1 * scale_factor

    bpy.ops.mesh.primitive_cone_add(vertices=12, radius1=0.9 * scale_factor, depth=2.8 * scale_factor)
    canopy = bpy.context.active_object
    canopy.name = f"{name}_canopy"
    canopy.location.z = 3.0 * scale_factor

    bpy.ops.object.select_all(action="DESELECT")
    trunk.select_set(True)
    canopy.select_set(True)
    bpy.context.view_layer.objects.active = trunk
    bpy.ops.object.join()
    obj = bpy.context.active_object
    obj.name = name
    return obj


def add_deciduous_canopy(obj, scale_factor: float):
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=2, radius=1.1 * scale_factor, location=(0.0, 0.0, 3.0 * scale_factor))
    canopy = bpy.context.active_object
    canopy.name = f"{obj.name}_leafmass"
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    canopy.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.join()
    return bpy.context.active_object


def create_sapling_tree(name: str, species: str, scale_factor: float, index: int):
    # Defaults from Sapling, then shaped by scale + lightweight transforms.
    before = {o.name for o in bpy.data.objects}
    bpy.ops.curve.tree_add(do_update=True)
    after = [o for o in bpy.data.objects if o.name not in before]
    if after:
        obj = after[-1]
    else:
        obj = bpy.data.objects.get("tree")
    if obj is None:
        raise RuntimeError("Sapling tree_add finished but no new object was found.")
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    obj.name = name
    obj.rotation_euler[2] = math.radians((index * 29) % 360)
    height_boost = 1.08 if "pine" in species else 1.0
    if species in {
        "ulmus",
        "tilia",
        "platanus_x_acerifolia",
        "acer_platanoides",
        "gleditsia_triacanthos",
        "ginkgo_biloba",
        "quercus_rubra",
        "acer_negundo",
        "acer_saccharinum",
        "allianthus_altissima",
    }:
        height_boost = 1.12
    obj.scale = (scale_factor, scale_factor, scale_factor * height_boost)
    obj = ensure_mesh_active(obj)
    if species in {
        "ulmus",
        "tilia",
        "platanus_x_acerifolia",
        "acer_platanoides",
        "gleditsia_triacanthos",
        "ginkgo_biloba",
        "quercus_rubra",
        "acer_negundo",
        "acer_saccharinum",
        "allianthus_altissima",
    }:
        obj = add_deciduous_canopy(obj, scale_factor)
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
    parser.add_argument("--out", default="outputs/trees/masters")
    args, _unknown = parser.parse_known_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    clear_scene()
    has_sapling = try_enable_sapling()
    print(f"[INFO] sapling_available={has_sapling}")

    collection = bpy.data.collections.new("TreeMasters")
    bpy.context.scene.collection.children.link(collection)

    created = []
    for idx, (species, variant, scale_factor) in enumerate(SPECIES_VARIANTS, start=1):
        name = f"SM_{species}_{variant}"
        if has_sapling:
            obj = create_sapling_tree(name, species, scale_factor, idx)
        else:
            obj = create_proxy_tree(name, scale_factor)

        # Gentle asymmetry on C variants.
        if variant.endswith("asymmetric"):
            obj.scale[0] *= 0.92
            obj.scale[1] *= 1.06

        if obj.name in bpy.context.scene.collection.objects:
            bpy.context.scene.collection.objects.unlink(obj)
        collection.objects.link(obj)
        created.append(obj)

        fbx_path = out_dir / f"{name}.fbx"
        export_fbx(obj, fbx_path)
        print(f"[OK] exported {fbx_path}")

    blend_path = out_dir / "tree_masters_free.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))
    print(f"[OK] saved {blend_path}")
    print(f"[DONE] created {len(created)} trees")


if __name__ == "__main__":
    main()
