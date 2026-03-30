"""
Apply photo textures to curated material names across all mesh objects.
Version 5 (Enhanced): Grouped mapping for urban elements (garages, poles, fences, facades).

Run from Blender:
blender --background <input.blend> --python scripts/apply_textures_v5.py -- --output-blend <out.blend>
"""

from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

import bpy


REPO_ROOT = Path(__file__).resolve().parents[1]
SORTED_DIR = REPO_ROOT / "PHOTOS KENSINGTON sorted"

# Mapping of material patterns to photo directories
MATERIAL_GROUPS = {
    "facade": {
        "patterns": ["mat_brick", "mat_facade", "mat_stone", "mat_lintel", "mat_quoins", "mat_foundation", "mat_bulkhead", "mat_parapet", "mat_coping"],
        "folders": ["brick", "concrete", "Toronto Fire Station 315", "Augusta Ave", "Bellevue Ave", "Baldwin St"],
        "scale": 0.05
    },
    "garage": {
        "patterns": ["mat_door_garage", "mat_garage", "mat_door_rolling"],
        "folders": ["Garages with graffiti, alley", "Keith Haring mural garage", "Parking garage exterior", "Portugal Auto Garage"],
        "scale": 0.1
    },
    "pole": {
        "patterns": ["mat_sidewalk_pole", "mat_custom_pole", "mat_sidewalk_light", "mat_door_knob", "mat_sf_mullion"],
        "folders": ["Detail _ Reference", "Utility box full view with posters"],
        "scale": 0.2
    },
    "fence": {
        "patterns": ["mat_fence_picket", "mat_custom_fence", "mat_custom_fence_mesh"],
        "folders": ["Garages with graffiti, alley", "Detail _ Reference"],
        "scale": 0.1
    },
    "roof": {
        "patterns": ["mat_roof", "mat_shingle", "mat_bargeboard", "mat_fascia", "mat_soffit", "mat_gutter"],
        "folders": ["Toronto Fire Station 315", "brick"],
        "scale": 0.1
    }
}

RNG = random.Random(42)


def parse_args() -> argparse.Namespace:
    argv = sys.argv
    if "--" in argv:
        argv = argv[argv.index("--") + 1 :]
    else:
        argv = []
    p = argparse.ArgumentParser()
    p.add_argument("--output-blend", required=True)
    p.add_argument("--count", type=int, default=12)
    p.add_argument("--projection-blend", type=float, default=0.3)
    return p.parse_args(argv)


def get_photos_from_folders(folders: list[str]) -> list[Path]:
    all_photos = []
    for f in folders:
        f_path = SORTED_DIR / f
        if f_path.exists():
            all_photos.extend(
                p for p in f_path.iterdir() if p.suffix.lower() in {".jpg", ".jpeg", ".png"}
            )
    return all_photos


def create_photo_materials(
    photos: list[Path], group_name: str, count: int, mapping_scale: float, projection_blend: float
) -> list[bpy.types.Material]:
    if not photos:
        return []
    
    shuffled = photos[:]
    RNG.shuffle(shuffled)

    mats: list[bpy.types.Material] = []
    for i, photo_path in enumerate(shuffled[: max(1, count)]):
        mat = bpy.data.materials.new(name=f"PhotoMat_{group_name}_{i}")
        mat.use_nodes = True
        nodes = mat.node_tree.nodes
        links = mat.node_tree.links
        bsdf = nodes.get("Principled BSDF")
        if bsdf is None:
            continue
        try:
            img = bpy.data.images.load(str(photo_path))
        except RuntimeError:
            continue

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
        bsdf.inputs["Roughness"].default_value = 0.8
        mats.append(mat)
    return mats


def apply_textures(group_mats: dict[str, list[bpy.types.Material]]) -> int:
    replaced = 0
    replacement_map: dict[str, bpy.types.Material] = {}
    
    for obj in bpy.data.objects:
        if obj.type != "MESH" or not obj.data.materials:
            continue
        
        for i, mat_slot in enumerate(obj.material_slots):
            mat = mat_slot.material
            if mat is None:
                continue
            
            # Find which group this material belongs to
            target_group = None
            for group_name, cfg in MATERIAL_GROUPS.items():
                if any(mat.name.startswith(p) or p in mat.name for p in cfg["patterns"]):
                    target_group = group_name
                    break
            
            if target_group and group_mats.get(target_group):
                if mat.name not in replacement_map:
                    replacement_map[mat.name] = RNG.choice(group_mats[target_group])
                obj.material_slots[i].material = replacement_map[mat.name]
                replaced += 1
                
    return replaced


def main() -> int:
    args = parse_args()

    group_mats = {}
    for group_name, cfg in MATERIAL_GROUPS.items():
        photos = get_photos_from_folders(cfg["folders"])
        mats = create_photo_materials(
            photos=photos,
            group_name=group_name,
            count=args.count,
            mapping_scale=cfg["scale"],
            projection_blend=args.projection_blend
        )
        if mats:
            group_mats[group_name] = mats
            print(f"[INFO] Created {len(mats)} materials for group '{group_name}'")
        else:
            print(f"[WARN] No photos found for group '{group_name}' in folders {cfg['folders']}")

    if not group_mats:
        raise SystemExit("No photo materials were created.")

    replaced = apply_textures(group_mats)
    out_path = Path(args.output_blend)
    bpy.ops.wm.save_as_mainfile(filepath=str(out_path))
    print(f"[OK] Replaced material slots: {replaced}")
    print(f"[OK] Saved: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
