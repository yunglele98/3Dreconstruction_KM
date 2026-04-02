"""Storefront creation for the Kensington building generator.

create_storefront, create_storefront_awning.
Extracted from generate_building.py.
"""

import bpy
import bmesh
import math
from mathutils import Vector

from generator_modules.colours import (
    hex_to_rgb, colour_name_to_hex, get_facade_hex, get_trim_hex,
    get_accent_hex, get_stone_element_hex, get_roof_hex,
    get_condition_roughness_bias, get_condition_saturation_shift,
    get_era_defaults, get_typology_hints,
)
from generator_modules.materials import (
    assign_material, get_or_create_material, _get_bsdf,
    create_brick_material, create_wood_material, create_stone_material,
    create_painted_material, create_glass_material, create_metal_roof_material,
    create_canvas_material, select_roof_material,
)
from generator_modules.geometry import (
    create_box, boolean_cut, create_arch_cutter, create_rect_cutter,
    _safe_tan, _clamp_positive,
)


def create_storefront(params, wall_obj, facade_width):
    """Create commercial storefront: cut large opening, add glass panels, mullions, awning."""
    sf = params.get("storefront", {})
    if not isinstance(sf, dict) or not params.get("has_storefront"):
        return []

    objects = []

    # Storefront dimensions
    sf_w = sf.get("width_m", facade_width * 0.85)
    # Clamp storefront width to facade width
    sf_w = min(sf_w, facade_width - 0.1)
    sf_h = sf.get("height_m", 2.5)
    bulkhead_h = 0.0
    bulkhead = sf.get("bulkhead", {})
    if isinstance(bulkhead, dict) and bulkhead.get("present", True):
        bulkhead_h = bulkhead.get("height_m", sf.get("bulkhead_height_m", 0.4))

    # Cap storefront top to ground floor height so it doesn't cut into second floor
    floor_heights = params.get("floor_heights_m", [3.5])
    ground_floor_h = float(floor_heights[0]) if floor_heights else 3.5
    if bulkhead_h + sf_h > ground_floor_h - 0.15:
        sf_h = max(1.5, ground_floor_h - bulkhead_h - 0.15)

    # Cut the storefront opening from the wall
    cutter = create_rect_cutter("sf_cut", sf_w, sf_h, depth=0.8)
    cutter.location.x = 0
    cutter.location.y = 0.01
    cutter.location.z = bulkhead_h + sf_h / 2
    boolean_cut(wall_obj, cutter)

    # Glass panel (full storefront)
    glass_mat = create_glass_material("mat_sf_glass", glass_type="storefront")
    bpy.ops.mesh.primitive_plane_add(size=1)
    gp = bpy.context.active_object
    gp.name = "storefront_glass"
    gp.scale = (sf_w * 0.95, 1, sf_h * 0.95)
    bpy.ops.object.transform_apply(scale=True)
    gp.rotation_euler.x = math.pi / 2
    gp.location = (0, -0.05, bulkhead_h + sf_h / 2)
    assign_material(gp, glass_mat)
    objects.append(gp)

    # Mullions (vertical dividers)
    glazing = sf.get("glazing", {})
    panel_count = 2
    if isinstance(glazing, dict):
        panel_count = glazing.get("panel_count", 2)
    else:
        panel_count = max(2, int(sf_w / 2.0))

    mullion_hex = "#3A3A3A"
    frame_desc = sf.get("frame", str(glazing.get("frame", "")) if isinstance(glazing, dict) else "")
    if "bronze" in str(frame_desc).lower():
        mullion_hex = "#4A3A2A"

    mullion_mat = get_or_create_material("mat_sf_mullion", colour_hex=mullion_hex,
                                         roughness=0.3, metallic=0.85)

    # Vertical mullions
    for mi in range(panel_count + 1):
        mx = -sf_w / 2 + (sf_w / panel_count) * mi
        bpy.ops.mesh.primitive_cube_add(size=1)
        mul = bpy.context.active_object
        mul.name = f"sf_mullion_v_{mi}"
        mul.scale = (0.04, 0.06, sf_h)
        bpy.ops.object.transform_apply(scale=True)
        mul.location = (mx, 0.02, bulkhead_h + sf_h / 2)
        assign_material(mul, mullion_mat)
        objects.append(mul)

    # Horizontal frame at top and bottom
    for hz, hname in [(bulkhead_h + sf_h, "sf_head"), (bulkhead_h, "sf_sill")]:
        bpy.ops.mesh.primitive_cube_add(size=1)
        hf = bpy.context.active_object
        hf.name = hname
        hf.scale = (sf_w + 0.1, 0.06, 0.05)
        bpy.ops.object.transform_apply(scale=True)
        hf.location = (0, 0.02, hz)
        assign_material(hf, mullion_mat)
        objects.append(hf)

    # Bulkhead (solid base panel below glass)
    if bulkhead_h > 0.1:
        facade_hex = get_facade_hex(params)
        bk_mat_str = str(bulkhead.get("material", "brick") if isinstance(bulkhead, dict) else "brick").lower()
        if "brick" in bk_mat_str:
            bk_mat = create_brick_material(f"mat_bulkhead_{facade_hex.lstrip('#')}", facade_hex)
        else:
            bk_mat = get_or_create_material("mat_bulkhead", colour_hex=facade_hex)
        bpy.ops.mesh.primitive_cube_add(size=1)
        bk = bpy.context.active_object
        bk.name = "sf_bulkhead"
        bk.scale = (sf_w, 0.3, bulkhead_h)
        bpy.ops.object.transform_apply(scale=True)
        bk.location = (0, 0, bulkhead_h / 2)
        assign_material(bk, bk_mat)
        objects.append(bk)

    # Transom bar — horizontal divider between storefront glass and upper facade
    transom_z = bulkhead_h + sf_h
    bpy.ops.mesh.primitive_cube_add(size=1)
    tb = bpy.context.active_object
    tb.name = "sf_transom_bar"
    tb.scale = (sf_w + 0.15, 0.08, 0.06)
    bpy.ops.object.transform_apply(scale=True)
    tb.location = (0, 0.03, transom_z)
    assign_material(tb, mullion_mat)
    objects.append(tb)

    # Signage band — above transom bar for commercial buildings
    signage = sf.get("signage", {})
    if isinstance(signage, dict) and signage.get("text"):
        sign_h = signage.get("height_m", 0.5)
        sign_w = signage.get("width_m", sf_w * 0.8)
        sign_hex = signage.get("colour_hex", "#F0EDE8")
        sign_mat = get_or_create_material("mat_signage", colour_hex=sign_hex, roughness=0.4)
        bpy.ops.mesh.primitive_cube_add(size=1)
        sign_obj = bpy.context.active_object
        sign_obj.name = "sf_signage"
        sign_obj.scale = (sign_w, 0.03, sign_h)
        bpy.ops.object.transform_apply(scale=True)
        sign_obj.location = (0, 0.04, transom_z + 0.03 + sign_h / 2)
        assign_material(sign_obj, sign_mat)
        objects.append(sign_obj)

    # Recessed entrance — if entrance data exists, cut a deeper recess
    entrance = sf.get("entrance", {})
    if isinstance(entrance, dict) and entrance.get("width_m"):
        ent_w = entrance.get("width_m", 1.2)
        ent_h = entrance.get("height_m", 2.4)
        ent_pos = str(entrance.get("position", "center")).lower()
        if "left" in ent_pos:
            ent_x = -sf_w / 2 + ent_w / 2 + 0.3
        elif "right" in ent_pos:
            ent_x = sf_w / 2 - ent_w / 2 - 0.3
        else:
            ent_x = 0

        # Recess floor — darker threshold
        threshold_mat = get_or_create_material("mat_threshold", colour_hex="#4A4A4A", roughness=0.7)
        bpy.ops.mesh.primitive_cube_add(size=1)
        recess = bpy.context.active_object
        recess.name = "sf_recess_floor"
        recess.scale = (ent_w + 0.1, 0.3, 0.02)
        bpy.ops.object.transform_apply(scale=True)
        recess.location = (ent_x, -0.15, 0.01)
        assign_material(recess, threshold_mat)
        objects.append(recess)

    # Security grille — rolling shutter track
    grille = sf.get("security_grille", {})
    if isinstance(grille, dict) and grille.get("present"):
        grille_mat = get_or_create_material("mat_grille_track", colour_hex="#5A5A5A", roughness=0.3)
        _bsdf = grille_mat.node_tree.nodes.get("Principled BSDF")
        if _bsdf and "Metallic" in _bsdf.inputs:
            _bsdf.inputs["Metallic"].default_value = 0.85
        # Track channels on each side
        for gx in [-sf_w / 2 - 0.02, sf_w / 2 + 0.02]:
            bpy.ops.mesh.primitive_cube_add(size=1)
            track = bpy.context.active_object
            track.name = f"sf_grille_track"
            track.scale = (0.03, 0.05, sf_h)
            bpy.ops.object.transform_apply(scale=True)
            track.location = (gx, 0.03, bulkhead_h + sf_h / 2)
            assign_material(track, grille_mat)
            objects.append(track)
        # Housing box at top
        bpy.ops.mesh.primitive_cube_add(size=1)
        housing = bpy.context.active_object
        housing.name = "sf_grille_housing"
        housing.scale = (sf_w + 0.1, 0.12, 0.1)
        bpy.ops.object.transform_apply(scale=True)
        housing.location = (0, 0.06, transom_z + 0.05)
        assign_material(housing, grille_mat)
        objects.append(housing)

    # Awning
    awning = sf.get("awning", {})
    if isinstance(awning, dict) and awning.get("present", awning.get("type")):
        aw_w = awning.get("width_m", facade_width)
        aw_proj = awning.get("projection_m", 1.2)
        aw_h_top = awning.get("height_at_fascia_m", 2.8)
        aw_h_bot = awning.get("height_at_drip_edge_m", aw_h_top - 0.5)

        aw_colour = awning.get("colour", "blue")
        aw_hex = awning.get("colour_hex") if "colour_hex" in awning else colour_name_to_hex(str(aw_colour))

        bm = bmesh.new()
        v0 = bm.verts.new((-aw_w / 2, 0, aw_h_top))
        v1 = bm.verts.new((aw_w / 2, 0, aw_h_top))
        v2 = bm.verts.new((aw_w / 2, aw_proj, aw_h_bot))
        v3 = bm.verts.new((-aw_w / 2, aw_proj, aw_h_bot))
        bm.faces.new([v0, v1, v2, v3])

        mesh = bpy.data.meshes.new("awning")
        bm.to_mesh(mesh)
        bm.free()

        aw_obj = bpy.data.objects.new("awning", mesh)
        bpy.context.collection.objects.link(aw_obj)

        aw_mat = create_canvas_material(f"mat_awning_{aw_hex.lstrip('#')}", aw_hex)
        assign_material(aw_obj, aw_mat)
        objects.append(aw_obj)

    return objects



def create_storefront_awning(params, facade_width, bldg_id=""):
    """Create commercial storefront awning with signage."""
    sf_data = params.get("storefront", {})
    if not isinstance(sf_data, dict):
        return []

    awning_data = sf_data.get("awning", {})
    if not isinstance(awning_data, dict) or not awning_data:
        return []

    objects = []

    aw_w = awning_data.get("width_m", facade_width)
    aw_proj = awning_data.get("projection_m", 1.2)
    aw_h_top = awning_data.get("height_at_fascia_m", 2.8)
    aw_h_bot = awning_data.get("height_at_drip_edge_m", 2.3)
    aw_colour = str(awning_data.get("colour", "blue")).lower()

    # Map colour name to hex
    awning_colours = {
        "blue": "#2060A0", "red": "#A02020", "green": "#206020",
        "yellow": "#C0A020", "white": "#E8E8E8", "black": "#2A2A2A",
    }
    aw_hex = "#2060A0"
    for key, val in awning_colours.items():
        if key in aw_colour:
            aw_hex = val
            break

    aw_mat = create_canvas_material(f"mat_awning_{aw_hex.lstrip('#')}", aw_hex)

    # Awning as a sloped plane
    bm = bmesh.new()
    hw = aw_w / 2
    v0 = bm.verts.new((-hw, 0, aw_h_top))
    v1 = bm.verts.new((hw, 0, aw_h_top))
    v2 = bm.verts.new((hw, aw_proj, aw_h_bot))
    v3 = bm.verts.new((-hw, aw_proj, aw_h_bot))
    bm.faces.new([v0, v1, v2, v3])

    mesh = bpy.data.meshes.new(f"awning_{bldg_id}")
    bm.to_mesh(mesh)
    bm.free()

    aw_obj = bpy.data.objects.new(f"awning_{bldg_id}", mesh)
    bpy.context.collection.objects.link(aw_obj)

    # Solidify for thickness
    mod = aw_obj.modifiers.new("Solidify", 'SOLIDIFY')
    mod.thickness = 0.03
    mod.offset = -1
    bpy.context.view_layer.objects.active = aw_obj
    bpy.ops.object.modifier_apply(modifier=mod.name)

    assign_material(aw_obj, aw_mat)
    objects.append(aw_obj)

    # Valance (scalloped bottom edge) — simple strip along the front
    bpy.ops.mesh.primitive_cube_add(size=1)
    val = bpy.context.active_object
    val.name = f"awning_valance_{bldg_id}"
    val.scale = (aw_w, 0.015, 0.12)
    bpy.ops.object.transform_apply(scale=True)
    val.location = (0, aw_proj, aw_h_bot - 0.06)
    assign_material(val, aw_mat)
    objects.append(val)

    # Signage
    signage = sf_data.get("signage", {})
    primary = signage.get("primary", {}) if isinstance(signage, dict) else {}
    if isinstance(primary, dict) and primary:
        sign_w = primary.get("width_m", 4.0)
        sign_h = primary.get("height_m", 0.5)
        sign_bg = primary.get("background", "white").lower()
        sign_hex = "#F0F0F0" if "white" in sign_bg else "#3A3A3A"

        sign_mat = get_or_create_material(f"mat_sign_{bldg_id}", colour_hex=sign_hex, roughness=0.4)

        bpy.ops.mesh.primitive_cube_add(size=1)
        sign = bpy.context.active_object
        sign.name = f"sign_{bldg_id}"
        sign.scale = (sign_w, 0.03, sign_h)
        bpy.ops.object.transform_apply(scale=True)
        sign.location = (0, 0.02, aw_h_top + sign_h / 2 + 0.05)
        assign_material(sign, sign_mat)
        objects.append(sign)

    return objects



