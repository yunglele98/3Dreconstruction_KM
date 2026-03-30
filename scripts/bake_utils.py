"""
Shared texture baking utilities for FBX export pipelines.

Extracted from export_building_fbx.py and batch_export_unreal.py to eliminate
code duplication. Both scripts import these functions instead of duplicating them.

Runs inside Blender's Python environment (requires bpy).
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

import bpy


def _atomic_write_json(filepath, data, ensure_ascii=False):
    """Write JSON atomically via temp file + rename to prevent corruption."""
    filepath = Path(filepath)
    filepath.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", dir=filepath.parent, delete=False,
        suffix=".tmp", encoding="utf-8",
    ) as tmp:
        json.dump(data, tmp, indent=2, ensure_ascii=ensure_ascii)
        tmp.write("\n")
        tmp_path = Path(tmp.name)
    os.replace(str(tmp_path), str(filepath))


def sanitize_address(address: str) -> str:
    """Convert address to safe filename."""
    return address.replace(" ", "_").replace("/", "-")


def extract_address_from_blend(blend_path: str | Path) -> str:
    """Extract address from blend filename (e.g., '22_Lippincott_St.blend' -> '22 Lippincott St')."""
    filename = Path(blend_path).stem
    return filename.replace("_", " ")


def apply_all_modifiers() -> None:
    """Apply all modifiers on all mesh objects in the scene."""
    for obj in bpy.data.objects:
        if obj.type == "MESH":
            with bpy.context.temp_override(object=obj):
                for modifier in obj.modifiers:
                    try:
                        bpy.ops.object.modifier_apply(modifier=modifier.name)
                    except RuntimeError:
                        pass


def get_material_for_object(obj: bpy.types.Object) -> str | None:
    """Get the primary material name for a mesh object."""
    if obj.type != "MESH" or not obj.data.materials:
        return None
    mat = obj.data.materials[0]
    return mat.name if mat else None


def join_meshes_by_material() -> None:
    """Join mesh objects that share the same material."""
    material_groups: dict[str | None, list[bpy.types.Object]] = {}
    for obj in bpy.data.objects:
        if obj.type != "MESH":
            continue
        mat_name = get_material_for_object(obj)
        if mat_name not in material_groups:
            material_groups[mat_name] = []
        material_groups[mat_name].append(obj)

    for mat_name, objs in material_groups.items():
        if len(objs) <= 1:
            continue

        for obj in objs:
            obj.select_set(True)

        bpy.context.view_layer.objects.active = objs[0]
        bpy.ops.object.join()
        bpy.ops.object.select_all(action="DESELECT")


def get_unique_materials() -> list[bpy.types.Material]:
    """Get all unique materials used by mesh objects."""
    materials = set()
    for obj in bpy.data.objects:
        if obj.type == "MESH":
            for mat in obj.data.materials:
                if mat:
                    materials.add(mat)
    return list(materials)


# ---------------------------------------------------------------------------
# Texture baking
# ---------------------------------------------------------------------------

BAKE_PASSES = ("diffuse", "roughness", "normal", "metallic", "ao")


def bake_material_textures(
    material: bpy.types.Material,
    texture_size: int,
    export_dir: Path,
    passes: tuple[str, ...] | None = None,
) -> dict[str, Path]:
    """Bake procedural material to texture images.

    Args:
        material: Blender material to bake.
        texture_size: Pixel resolution for baked textures.
        export_dir: Root export directory (textures go into export_dir/textures/).
        passes: Tuple of pass names to bake. Defaults to BAKE_PASSES.

    Returns:
        Dict mapping pass names to saved image file paths.
    """
    if passes is None:
        passes = BAKE_PASSES

    # Ensure Cycles is active (required for baking)
    bpy.context.scene.render.engine = "CYCLES"
    bpy.context.scene.cycles.device = "GPU"
    bpy.context.scene.cycles.samples = 4  # low samples for fast bake

    texture_dir = export_dir / "textures"
    texture_dir.mkdir(parents=True, exist_ok=True)

    result_paths: dict[str, Path] = {}

    # Create images for each pass
    image_data: dict[str, bpy.types.Image] = {}
    for pass_name in passes:
        img_name = f"{sanitize_address(material.name)}_{pass_name}"
        if img_name in bpy.data.images:
            bpy.data.images.remove(bpy.data.images[img_name])
        img = bpy.data.images.new(name=img_name, width=texture_size, height=texture_size)
        image_data[pass_name] = img

    if not material.node_tree:
        return {}
    nodes = material.node_tree.nodes

    for pass_name, img in image_data.items():
        # Find or create image texture node
        img_tex_node = None
        for node in nodes:
            if node.type == "TEX_IMAGE" and node.image == img:
                img_tex_node = node
                break
        if not img_tex_node:
            img_tex_node = nodes.new(type="ShaderNodeTexImage")
            img_tex_node.image = img
        nodes.active = img_tex_node

        # Configure bake type
        bake_type_map = {
            "diffuse": "DIFFUSE",
            "normal": "NORMAL",
            "roughness": "ROUGHNESS",
            "metallic": "EMIT",
            "ao": "AO",
        }
        bpy.context.scene.cycles.bake_type = bake_type_map.get(pass_name, "DIFFUSE")

        # Select mesh objects using this material and ensure UVs
        bpy.ops.object.select_all(action="DESELECT")
        target_obj = None
        for obj in bpy.data.objects:
            if obj.type == "MESH" and material.name in [m.name for m in obj.data.materials if m]:
                obj.select_set(True)
                target_obj = obj
                if not obj.data.uv_layers:
                    obj.data.uv_layers.new(name="UVMap")
                    bpy.context.view_layer.objects.active = obj
                    bpy.ops.object.mode_set(mode="EDIT")
                    bpy.ops.mesh.select_all(action="SELECT")
                    bpy.ops.uv.smart_project(angle_limit=66, island_margin=0.02)
                    bpy.ops.object.mode_set(mode="OBJECT")
        if target_obj:
            bpy.context.view_layer.objects.active = target_obj

        # Metallic workaround: temporarily set emission (Cycles has no direct metallic bake)
        bsdf = None
        original_emission = None
        if pass_name == "metallic":
            for node in material.node_tree.nodes:
                if node.type == "BSDF" and "Principled" in node.name:
                    bsdf = node
                    break
            if bsdf:
                original_emission = bsdf.inputs["Emission Strength"].default_value
                bsdf.inputs["Emission Strength"].default_value = 1.0

        # Bake
        try:
            bpy.ops.object.bake(type=bpy.context.scene.cycles.bake_type)
        except RuntimeError as e:
            print(f"    Warning: Bake failed for {pass_name}: {e}")
            if pass_name == "metallic" and bsdf and original_emission is not None:
                bsdf.inputs["Emission Strength"].default_value = original_emission
            continue

        # Restore metallic emission
        if pass_name == "metallic" and bsdf and original_emission is not None:
            bsdf.inputs["Emission Strength"].default_value = original_emission

        # Save image
        img.filepath_raw = str(texture_dir / f"{img.name}.png")
        img.file_format = "PNG"
        img.save()
        result_paths[pass_name] = texture_dir / f"{img.name}.png"

    return result_paths


def replace_material_with_baked(
    material: bpy.types.Material,
    texture_paths: dict[str, Path],
) -> None:
    """Replace procedural material with Principled BSDF using baked textures."""
    if not material.node_tree:
        return
    nodes = material.node_tree.nodes
    links = material.node_tree.links

    bsdf = nodes.get("Principled BSDF")
    output = nodes.get("Material Output")

    # If missing Principled BSDF, try to find any BSDF node
    if bsdf is None:
        for node in nodes:
            if node.type == "BSDF_PRINCIPLED":
                bsdf = node
                break
    if bsdf is None:
        print(f"    [WARN] No Principled BSDF in material '{material.name}', skipping baked replacement")
        return

    # Clear all nodes except Principled BSDF and Material Output
    for node in list(nodes):
        if node not in (bsdf, output):
            nodes.remove(node)

    if "diffuse" in texture_paths:
        diffuse_img = bpy.data.images.load(str(texture_paths["diffuse"]))
        diffuse_node = nodes.new(type="ShaderNodeTexImage")
        diffuse_node.image = diffuse_img
        links.new(diffuse_node.outputs["Color"], bsdf.inputs["Base Color"])

    if "roughness" in texture_paths:
        roughness_img = bpy.data.images.load(str(texture_paths["roughness"]))
        roughness_node = nodes.new(type="ShaderNodeTexImage")
        roughness_node.image = roughness_img
        roughness_node.image.colorspace_settings.name = "Non-Color"
        links.new(roughness_node.outputs["Color"], bsdf.inputs["Roughness"])

    if "normal" in texture_paths:
        normal_img = bpy.data.images.load(str(texture_paths["normal"]))
        normal_node = nodes.new(type="ShaderNodeTexImage")
        normal_node.image = normal_img
        normal_node.image.colorspace_settings.name = "Non-Color"
        normal_map = nodes.new(type="ShaderNodeNormalMap")
        links.new(normal_node.outputs["Color"], normal_map.inputs["Color"])
        links.new(normal_map.outputs["Normal"], bsdf.inputs["Normal"])

    if "metallic" in texture_paths:
        metallic_img = bpy.data.images.load(str(texture_paths["metallic"]))
        metallic_node = nodes.new(type="ShaderNodeTexImage")
        metallic_node.image = metallic_img
        metallic_node.image.colorspace_settings.name = "Non-Color"
        links.new(metallic_node.outputs["Color"], bsdf.inputs["Metallic"])

    if "ao" in texture_paths:
        ao_img = bpy.data.images.load(str(texture_paths["ao"]))
        ao_node = nodes.new(type="ShaderNodeTexImage")
        ao_node.image = ao_img
        ao_node.image.colorspace_settings.name = "Non-Color"
        # AO multiplied into base colour via MixRGB Multiply
        if "diffuse" in texture_paths:
            # Find the diffuse node output going to Base Color
            for link in list(links):
                if link.to_socket == bsdf.inputs["Base Color"]:
                    diffuse_out = link.from_socket
                    links.remove(link)
                    ao_mix = nodes.new(type="ShaderNodeMixRGB")
                    ao_mix.blend_type = "MULTIPLY"
                    ao_mix.inputs["Fac"].default_value = 1.0
                    links.new(diffuse_out, ao_mix.inputs["Color1"])
                    links.new(ao_node.outputs["Color"], ao_mix.inputs["Color2"])
                    links.new(ao_mix.outputs["Color"], bsdf.inputs["Base Color"])
                    break


def bake_all_materials(texture_size: int, export_dir: Path) -> None:
    """Bake all materials in the scene and replace with baked textures."""
    materials = get_unique_materials()
    print(f"  Found {len(materials)} unique materials")

    for material in materials:
        print(f"  Baking material '{material.name}'...")
        texture_paths = bake_material_textures(material, texture_size, export_dir)
        replace_material_with_baked(material, texture_paths)


# ---------------------------------------------------------------------------
# Mesh stats and FBX export
# ---------------------------------------------------------------------------

def get_mesh_stats() -> dict[str, Any]:
    """Compute mesh statistics (vertex/face count, bounding box)."""
    stats: dict[str, Any] = {
        "mesh_count": 0,
        "vertex_count": 0,
        "face_count": 0,
        "bbox_min": [float("inf")] * 3,
        "bbox_max": [float("-inf")] * 3,
    }

    for obj in bpy.data.objects:
        if obj.type != "MESH":
            continue

        stats["mesh_count"] += 1
        mesh = obj.data
        stats["vertex_count"] += len(mesh.vertices)
        stats["face_count"] += len(mesh.polygons)

        for vertex in mesh.vertices:
            world_pos = obj.matrix_world @ vertex.co
            for i in range(3):
                stats["bbox_min"][i] = min(stats["bbox_min"][i], world_pos[i])
                stats["bbox_max"][i] = max(stats["bbox_max"][i], world_pos[i])

    return stats


def export_fbx(address: str, export_dir: Path) -> Path:
    """Export scene to FBX file."""
    safe_address = sanitize_address(address)
    fbx_path = export_dir / f"{safe_address}.fbx"
    export_dir.mkdir(parents=True, exist_ok=True)

    bpy.ops.object.select_all(action="SELECT")

    # Build FBX export kwargs (apply_scalings removed in Blender 5.x)
    fbx_kwargs = dict(
        filepath=str(fbx_path),
        use_selection=True,
        axis_forward="-Y",
        axis_up="Z",
        global_scale=1.0,
        mesh_smooth_type="FACE",
        bake_anim=False,
    )
    try:
        bpy.ops.export_scene.fbx(**fbx_kwargs, apply_scalings="FBX_SCALE_ALL")
    except TypeError:
        bpy.ops.export_scene.fbx(**fbx_kwargs)

    return fbx_path


def export_glb(address: str, export_dir: Path) -> Path:
    """Export scene selection to GLB for validator/toolchain compatibility."""
    safe_address = sanitize_address(address)
    glb_path = export_dir / f"{safe_address}.glb"
    export_dir.mkdir(parents=True, exist_ok=True)

    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.export_scene.gltf(
        filepath=str(glb_path),
        export_format="GLB",
        use_selection=True,
        export_apply=True,
    )
    return glb_path


def write_export_metadata(
    address: str,
    export_dir: Path,
    fbx_path: Path,
    texture_size: int,
    glb_path: Path | None = None,
) -> dict[str, Any]:
    """Write export metadata JSON and return metadata dict."""
    safe_address = sanitize_address(address)
    meta_path = export_dir / "export_meta.json"

    texture_dir = export_dir / "textures"
    texture_files = []
    if texture_dir.exists():
        texture_files = [f.name for f in texture_dir.glob("*.png")]

    stats = get_mesh_stats()
    materials = [mat.name for mat in get_unique_materials()]

    metadata: dict[str, Any] = {
        "address": address,
        "safe_address": safe_address,
        "source_blend": str(bpy.data.filepath),
        "fbx_path": str(fbx_path),
        "glb_path": str(glb_path) if glb_path else None,
        "texture_size": texture_size,
        "mesh_count": stats["mesh_count"],
        "vertex_count": stats["vertex_count"],
        "face_count": stats["face_count"],
        "bounding_box": {
            "min": stats["bbox_min"],
            "max": stats["bbox_max"],
            "width": stats["bbox_max"][0] - stats["bbox_min"][0],
            "height": stats["bbox_max"][1] - stats["bbox_min"][1],
            "depth": stats["bbox_max"][2] - stats["bbox_min"][2],
        },
        "materials": materials,
        "material_count": len(materials),
        "texture_files": texture_files,
        "texture_count": len(texture_files),
        "export_timestamp": datetime.now().isoformat(),
    }

    _atomic_write_json(meta_path, metadata)

    return metadata


# ---------------------------------------------------------------------------
# Material property sidecar
# ---------------------------------------------------------------------------

def write_material_sidecar(export_dir: Path) -> Path:
    """Write per-material PBR property JSON sidecar alongside FBX exports.

    Captures the Principled BSDF values for each material so game engines
    can import with correct roughness, metallic, transmission, etc.

    Returns:
        Path to the written materials.json file.
    """
    materials_data = []

    for mat in get_unique_materials():
        entry: dict[str, Any] = {"name": mat.name}
        bsdf = None
        if mat.node_tree:
            bsdf = mat.node_tree.nodes.get("Principled BSDF")
            # Fallback: search by type
            if bsdf is None:
                for node in mat.node_tree.nodes:
                    if node.type == "BSDF_PRINCIPLED":
                        bsdf = node
                        break
        if bsdf:
            entry["base_color"] = list(bsdf.inputs["Base Color"].default_value[:3])
            entry["roughness"] = bsdf.inputs["Roughness"].default_value
            entry["metallic"] = bsdf.inputs["Metallic"].default_value

            # Alpha
            if "Alpha" in bsdf.inputs:
                entry["alpha"] = bsdf.inputs["Alpha"].default_value

            # Transmission
            for key in ("Transmission Weight", "Transmission"):
                if key in bsdf.inputs:
                    entry["transmission"] = bsdf.inputs[key].default_value
                    break

            # Specular
            for key in ("Specular IOR Level", "Specular"):
                if key in bsdf.inputs:
                    entry["specular"] = bsdf.inputs[key].default_value
                    break

            # Emission strength
            if "Emission Strength" in bsdf.inputs:
                entry["emission_strength"] = bsdf.inputs["Emission Strength"].default_value

        # Texture files associated with this material
        texture_dir = export_dir / "textures"
        safe_mat = sanitize_address(mat.name)
        entry["textures"] = {}
        if texture_dir.exists():
            for pass_name in BAKE_PASSES:
                tex_path = texture_dir / f"{safe_mat}_{pass_name}.png"
                if tex_path.exists():
                    entry["textures"][pass_name] = tex_path.name

        materials_data.append(entry)

    sidecar_path = export_dir / "materials.json"
    _atomic_write_json(sidecar_path, materials_data)

    return sidecar_path
