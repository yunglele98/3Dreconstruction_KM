"""Wall creation for the Kensington building generator.

create_walls with party wall, water table support.
Requires bpy and imports from materials, geometry, colours.

Extracted from generate_building.py.
"""

import bpy
import bmesh
import math
from mathutils import Vector

from generator_modules.colours import (
    get_facade_hex, get_trim_hex, get_condition_roughness_bias,
)
from generator_modules.materials import (
    assign_material, get_or_create_material,
    create_brick_material, create_wood_material,
    create_stone_material, create_painted_material,
)
from generator_modules.geometry import create_box, boolean_cut, _clamp_positive


def create_walls(params, depth=None):
    """Create the main building walls as a hollow box with water table and party wall blanking."""
    width = _clamp_positive(params.get("facade_width_m"), 6.0, minimum=1.0)
    if depth is None:
        depth = _clamp_positive(params.get("facade_depth_m"), DEFAULT_DEPTH, minimum=1.0)
    else:
        depth = _clamp_positive(depth, DEFAULT_DEPTH, minimum=1.0)
    total_h = _clamp_positive(params.get("total_height_m"), 9.0, minimum=2.0)

    # Get wall height (up to eave, not gable peak)
    floor_heights = params.get("floor_heights_m", [3.0])
    if not floor_heights or not isinstance(floor_heights, list):
        floor_heights = [3.0]
    wall_h = sum(max(0.5, float(fh)) for fh in floor_heights)

    wall_thickness = params.get("wall_thickness_m", 0.3)

    # Outer box
    outer = create_box("walls_outer", width, depth, wall_h, location=(0, 0, 0))

    # Inner box (for hollow walls) — cut all the way through to avoid interior floor
    inner = create_box("walls_inner",
                       width - 2 * wall_thickness,
                       depth - 2 * wall_thickness,
                       wall_h + 0.02,
                       location=(0, -wall_thickness, -0.01))

    boolean_cut(outer, inner)
    outer.name = "walls"

    # Fix normals after boolean — ensures textures show on exterior
    bpy.context.view_layer.objects.active = outer
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.mesh.normals_make_consistent(inside=False)
    bpy.ops.object.mode_set(mode='OBJECT')

    # Get facade material — use procedural textures based on material type
    facade_hex = get_facade_hex(params)
    hex_id = facade_hex.lstrip('#')
    mat_type = str(params.get("facade_material", "brick")).lower()
    mortar_hex = "#B0A898"
    fd = params.get("facade_detail", {})
    if isinstance(fd, dict):
        mc = fd.get("mortar_colour", "")
        if "grey" in str(mc).lower():
            mortar_hex = "#8A8A8A"
        elif "light" in str(mc).lower():
            mortar_hex = "#C0B8A8"
        elif isinstance(mc, str) and mc.startswith("#"):
            mortar_hex = mc

    # Bond pattern from facade_detail or deep_facade_analysis
    bond_pattern = "running"
    if isinstance(fd, dict):
        bp = (fd.get("bond_pattern") or "").lower()
        if bp:
            bond_pattern = bp
    dfa = params.get("deep_facade_analysis", {})
    if isinstance(dfa, dict):
        bp_dfa = (dfa.get("brick_bond_observed") or "").lower()
        if bp_dfa:
            bond_pattern = bp_dfa

    # Polychromatic brick accent colour (Victorian decorative banding)
    polychrome_hex = None
    if isinstance(dfa, dict):
        poly = dfa.get("polychromatic_brick")
        if isinstance(poly, dict):
            ph = poly.get("accent_hex", "")
            if ph and ph.startswith("#"):
                polychrome_hex = ph
    de = params.get("decorative_elements", {})
    if isinstance(de, dict) and not polychrome_hex:
        poly_de = de.get("polychromatic_brick")
        if isinstance(poly_de, dict):
            ph = poly_de.get("colour_hex", "")
            if ph and ph.startswith("#"):
                polychrome_hex = ph

    condition = (params.get("condition") or "fair").lower()

    if "brick" in mat_type:
        mat = create_brick_material(f"mat_brick_{hex_id}", facade_hex, mortar_hex,
                                    bond_pattern=bond_pattern,
                                    polychrome_hex=polychrome_hex)
    elif "stone" in mat_type or "concrete" in mat_type:
        mat = create_stone_material(f"mat_stone_{hex_id}", facade_hex,
                                    condition=condition)
    elif "clapboard" in mat_type or "wood siding" in mat_type:
        mat = create_wood_material(f"mat_wood_{hex_id}", facade_hex)
    elif (
        "paint" in mat_type
        or "stucco" in mat_type
        or "wood" in mat_type
        or "vinyl" in mat_type
        or "siding" in mat_type
    ):
        mat = create_painted_material(f"mat_painted_{hex_id}", facade_hex,
                                      condition=condition)
    else:
        mat = create_brick_material(f"mat_facade_{hex_id}", facade_hex, mortar_hex,
                                    bond_pattern=bond_pattern,
                                    polychrome_hex=polychrome_hex)

    # Condition-based weathering: bias base roughness by building condition
    roughness_bias = get_condition_roughness_bias(params)
    if roughness_bias != 0.0:
        bsdf = mat.node_tree.nodes.get("Principled BSDF")
        if bsdf:
            base_r = bsdf.inputs["Roughness"].default_value
            if isinstance(base_r, float):
                bsdf.inputs["Roughness"].default_value = max(0.1, min(1.0, base_r + roughness_bias))

    assign_material(outer, mat)

    # Water table — subtle stone band at base of facade (above foundation)
    foundation_h = params.get("foundation_height_m", 0.3)
    wt_h = 0.08  # water table height
    wt_proj = 0.02  # slight projection
    trim_hex = get_trim_hex(params)
    wt_mat = create_stone_material(f"mat_watertable_{trim_hex.lstrip('#')}",
                                    trim_hex, condition=condition)
    bpy.ops.mesh.primitive_cube_add(size=1)
    wt = bpy.context.active_object
    wt.name = "water_table"
    wt.scale = (width + wt_proj * 2, wt_proj * 2, wt_h)
    bpy.ops.object.transform_apply(scale=True)
    wt.location = (0, wt_proj, foundation_h + wt_h / 2)
    assign_material(wt, wt_mat)

    # Party wall blanking — close off exposed side walls with flat material
    party_left = params.get("party_wall_left", False)
    party_right = params.get("party_wall_right", False)
    pw_mat = get_or_create_material("mat_party_wall", colour_hex="#6A6A6A", roughness=0.95)
    hw = width / 2

    if party_left:
        bpy.ops.mesh.primitive_plane_add(size=1)
        pw = bpy.context.active_object
        pw.name = "party_wall_left"
        pw.scale = (1, depth, wall_h)
        bpy.ops.object.transform_apply(scale=True)
        pw.rotation_euler.y = math.pi / 2
        pw.location = (-hw - 0.005, -depth / 2, wall_h / 2)
        assign_material(pw, pw_mat)

    if party_right:
        bpy.ops.mesh.primitive_plane_add(size=1)
        pw = bpy.context.active_object
        pw.name = "party_wall_right"
        pw.scale = (1, depth, wall_h)
        bpy.ops.object.transform_apply(scale=True)
        pw.rotation_euler.y = math.pi / 2
        pw.location = (hw + 0.005, -depth / 2, wall_h / 2)
        assign_material(pw, pw_mat)

    return outer, wall_h, width, depth


