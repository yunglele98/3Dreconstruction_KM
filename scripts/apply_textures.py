"""
Apply photo-driven materials to Fire Station scene meshes.

Run from Blender:
blender --background <input.blend> --python scripts/apply_textures.py -- --output-blend <out.blend>
"""

from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

import bpy


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PHOTO_DIR = REPO_ROOT / "PHOTOS KENSINGTON sorted" / "Toronto Fire Station 315"
RNG = random.Random(42)


def parse_args() -> argparse.Namespace:
    argv = sys.argv
    if "--" in argv:
        argv = argv[argv.index("--") + 1 :]
    else:
        argv = []
    p = argparse.ArgumentParser()
    p.add_argument("--photo-dir", default=str(DEFAULT_PHOTO_DIR))
    p.add_argument("--output-blend", required=True)
    p.add_argument("--bucket-count", type=int, default=4)
    p.add_argument("--mapping-scale", type=float, default=0.1)
    p.add_argument("--projection-blend", type=float, default=0.4)
    return p.parse_args(argv)


def create_directional_materials(
    photo_dir: Path, bucket_count: int, mapping_scale: float, projection_blend: float
) -> list[bpy.types.Material]:
    photos = sorted(
        p for p in photo_dir.iterdir() if p.suffix.lower() in {".jpg", ".jpeg", ".png"}
    )
    if not photos:
        return []

    shuffled = photos[:]
    RNG.shuffle(shuffled)
    buckets = [[] for _ in range(max(1, bucket_count))]
    for i, photo in enumerate(shuffled):
        buckets[i % len(buckets)].append(photo)

    mats: list[bpy.types.Material] = []
    directions = ["North", "East", "South", "West"]
    for i, bucket in enumerate(buckets):
        if not bucket:
            continue
        mat_name = f"PhotoMat_{directions[i % len(directions)]}_{i}"
        mat = bpy.data.materials.new(name=mat_name)
        mat.use_nodes = True
        nodes = mat.node_tree.nodes
        links = mat.node_tree.links
        bsdf = nodes.get("Principled BSDF")
        if bsdf is None:
            continue

        img = bpy.data.images.load(str(bucket[0]))
        tex_image = nodes.new("ShaderNodeTexImage")
        tex_image.image = img
        tex_image.projection = "BOX"
        tex_image.projection_blend = projection_blend

        tex_coord = nodes.new("ShaderNodeTexCoord")
        mapping = nodes.new("ShaderNodeMapping")
        mapping.inputs["Scale"].default_value = (mapping_scale, mapping_scale, mapping_scale)

        links.new(tex_coord.outputs["Object"], mapping.inputs["Vector"])
        links.new(mapping.outputs["Vector"], tex_image.inputs["Vector"])
        links.new(tex_image.outputs["Color"], bsdf.inputs["Base Color"])
        bsdf.inputs["Roughness"].default_value = 0.9
        mats.append(mat)
    return mats


def assign_materials_by_direction(
    obj: bpy.types.Object, photo_mats: list[bpy.types.Material]
) -> int:
    if not photo_mats or not obj.data.materials:
        return 0

    applied = 0
    material_map: dict[str, bpy.types.Material] = {}
    shuffled = photo_mats[:]
    RNG.shuffle(shuffled)

    for i, mat_slot in enumerate(obj.material_slots):
        original_mat = mat_slot.material
        if original_mat is None:
            continue
        mat_name = original_mat.name.lower()
        if "brick" not in mat_name and "quoin" not in mat_name and "lintel" not in mat_name:
            continue
        if original_mat.name not in material_map:
            material_map[original_mat.name] = shuffled[len(material_map) % len(shuffled)]
        obj.material_slots[i].material = material_map[original_mat.name]
        applied += 1
    return applied


def find_building_collection() -> bpy.types.Collection | None:
    for coll in bpy.data.collections:
        if coll.name.startswith("building_"):
            return coll
    return None


def main() -> int:
    args = parse_args()
    photo_dir = Path(args.photo_dir)
    if not photo_dir.exists():
        raise SystemExit(f"Photo directory missing: {photo_dir}")

    photo_mats = create_directional_materials(
        photo_dir=photo_dir,
        bucket_count=args.bucket_count,
        mapping_scale=args.mapping_scale,
        projection_blend=args.projection_blend,
    )
    if not photo_mats:
        raise SystemExit("No photo materials could be created.")

    building_collection = find_building_collection()
    if building_collection is None:
        raise SystemExit("Could not find any collection matching 'building_*'.")

    total_slots = 0
    for obj in building_collection.objects:
        if obj.type == "MESH":
            total_slots += assign_materials_by_direction(obj, photo_mats)

    out_path = Path(args.output_blend)
    bpy.ops.wm.save_as_mainfile(filepath=str(out_path))
    print(f"[OK] Created photo materials: {len(photo_mats)}")
    print(f"[OK] Updated material slots: {total_slots}")
    print(f"[OK] Saved: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
