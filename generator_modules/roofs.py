"""Roof creation for the Kensington building generator.

Gable, cross-gable, hip, flat roofs + gable walls.
Requires bpy and imports from materials, geometry, colours.

Extracted from generate_building.py.
"""

import bpy
import bmesh
import math
from mathutils import Vector

from generator_modules.colours import (
    get_facade_hex, get_roof_hex, get_trim_hex,
)
from generator_modules.geometry import _safe_tan
from generator_modules.materials import (
    assign_material, get_or_create_material,
    create_brick_material, create_painted_material,
    create_stone_material, select_roof_material,
)


def create_gable_walls(params, wall_h, width, depth, bldg_id=""):
    """Create triangular gable walls to fill the gap between wall top and roof."""
    pitch = params.get("roof_pitch_deg", 35)
    ridge_height = (width / 2) * _safe_tan(pitch)

    facade_hex = get_facade_hex(params)
    hex_id = facade_hex.lstrip('#')
    mat_type = str(params.get("facade_material", "brick")).lower()
    # Resolve bond pattern for gable walls (same as main facade)
    fd_gw = params.get("facade_detail", {})
    bond_gw = "running"
    if isinstance(fd_gw, dict):
        bp_gw = (fd_gw.get("bond_pattern") or "").lower()
        if bp_gw:
            bond_gw = bp_gw
    dfa_gw = params.get("deep_facade_analysis", {})
    if isinstance(dfa_gw, dict):
        bp_dfa_gw = (dfa_gw.get("brick_bond_observed") or "").lower()
        if bp_dfa_gw:
            bond_gw = bp_dfa_gw

    if "brick" in mat_type:
        mat = create_brick_material(f"mat_brick_{hex_id}", facade_hex,
                                    bond_pattern=bond_gw)
    elif "stone" in mat_type or "concrete" in mat_type:
        mat = create_stone_material(f"mat_stone_{hex_id}", facade_hex)
    elif (
        "paint" in mat_type
        or "stucco" in mat_type
        or "clapboard" in mat_type
        or "wood" in mat_type
        or "vinyl" in mat_type
        or "siding" in mat_type
    ):
        mat = create_painted_material(f"mat_painted_{hex_id}", facade_hex)
    else:
        mat = create_brick_material(f"mat_facade_{hex_id}", facade_hex,
                                    bond_pattern=bond_gw)

    objects = []
    wall_t = 0.3
    half_w = width / 2

    # Walls go from y=0 (front) to y=-depth (back)
    # Gable is a single triangle face + solidify, positioned flush with wall exterior
    for y_pos, solidify_offset, name in [(0, 1, "gable_front"), (-depth, -1, "gable_back")]:
        bm = bmesh.new()
        v0 = bm.verts.new((-half_w, 0, wall_h))
        v1 = bm.verts.new((half_w, 0, wall_h))
        v2 = bm.verts.new((0, 0, wall_h + ridge_height))
        bm.faces.new([v0, v1, v2])

        mesh = bpy.data.meshes.new(name)
        bm.to_mesh(mesh)
        bm.free()
        obj = bpy.data.objects.new(name, mesh)
        bpy.context.collection.objects.link(obj)
        obj.location.y = y_pos

        # Solidify inward (toward building interior)
        mod = obj.modifiers.new("Solidify", 'SOLIDIFY')
        mod.thickness = wall_t
        mod.offset = solidify_offset
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.modifier_apply(modifier=mod.name)

        assign_material(obj, mat)
        objects.append(obj)

    return objects


def create_gable_roof(params, wall_h, width, depth):
    """Create a gable roof."""
    pitch = params.get("roof_pitch_deg", 35)

    ridge_height = (width / 2) * _safe_tan(pitch)

    roof_hex = get_roof_hex(params)

    bm = bmesh.new()

    # Per-building eave overhang from params
    rd = params.get("roof_detail", {})
    eave_mm = 300
    if isinstance(rd, dict):
        eave_mm = rd.get("eave_overhang_mm", 300)
    else:
        eave_mm = params.get("eave_overhang_mm", 300)
    overhang_eave = eave_mm / 1000.0
    overhang_side = overhang_eave * 0.5
    half_w = width / 2 + overhang_side
    roof_thick = 0.08

    # Walls go from y=0 (front) to y=-depth (back)
    # Roof extends with overhang beyond both ends
    y_front = overhang_eave
    y_back = -depth - overhang_eave

    # Outer roof surface
    v0 = bm.verts.new((-half_w, y_back, wall_h))
    v1 = bm.verts.new((half_w, y_back, wall_h))
    v2 = bm.verts.new((half_w, y_front, wall_h))
    v3 = bm.verts.new((-half_w, y_front, wall_h))
    v4 = bm.verts.new((0, y_back, wall_h + ridge_height))
    v5 = bm.verts.new((0, y_front, wall_h + ridge_height))

    # Left slope
    bm.faces.new([v0, v3, v5, v4])
    # Right slope
    bm.faces.new([v1, v4, v5, v2])
    # Front gable triangle (roof underside visible)
    bm.faces.new([v0, v4, v1])
    # Back gable triangle
    bm.faces.new([v2, v5, v3])

    mesh = bpy.data.meshes.new("roof")
    bm.to_mesh(mesh)
    bm.free()

    obj = bpy.data.objects.new("roof", mesh)
    bpy.context.collection.objects.link(obj)

    # Give the roof some thickness via solidify
    mod = obj.modifiers.new("Solidify", 'SOLIDIFY')
    mod.thickness = roof_thick
    mod.offset = -1
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.modifier_apply(modifier=mod.name)

    mat = select_roof_material(f"mat_roof_{roof_hex.lstrip('#')}", roof_hex, params)
    assign_material(obj, mat)

    # Ridge cap — contrasting strip along the roof peak
    trim_hex = get_trim_hex(params)
    ridge_mat = get_or_create_material(f"mat_ridge_{trim_hex.lstrip('#')}",
                                        colour_hex=trim_hex, roughness=0.5)
    ridge_len = abs(y_front - y_back)
    bpy.ops.mesh.primitive_cube_add(size=1)
    ridge_cap = bpy.context.active_object
    ridge_cap.name = "ridge_cap"
    ridge_cap.scale = (0.08, ridge_len, 0.04)
    bpy.ops.object.transform_apply(scale=True)
    ridge_cap.location = (0, (y_front + y_back) / 2, wall_h + ridge_height + 0.02)
    assign_material(ridge_cap, ridge_mat)

    return obj, ridge_height


def create_cross_gable_roof(params, wall_h, width, depth):
    """Create a cross-gable roof for bay-and-gable buildings.

    Main roof: side gable (ridge runs left-right, parallel to facade).
    Secondary: front-facing cross-gable projecting forward from main roof.
    """
    pitch = params.get("roof_pitch_deg", 35)

    roof_hex = get_roof_hex(params)
    roof_thick = 0.08

    rd = params.get("roof_detail", {})
    eave_mm = 300
    if isinstance(rd, dict):
        eave_mm = rd.get("eave_overhang_mm", 300)
    else:
        eave_mm = params.get("eave_overhang_mm", 300)
    overhang = eave_mm / 1000.0

    # --- Main side gable (ridge parallel to facade, runs left-right) ---
    # Ridge height governed by width (shorter facade dimension), not depth.
    # Using depth would produce absurd heights on deep lots (e.g. 32m * tan(45°) = 16m).
    main_ridge_height = (width / 2) * _safe_tan(pitch)
    half_w = width / 2 + overhang * 0.5
    y_front = overhang
    y_back = -depth - overhang
    y_mid = -depth / 2  # ridge runs along this Y at wall_h + main_ridge_height

    bm = bmesh.new()

    # Main roof: 4 verts at eaves, 2 at ridge
    m0 = bm.verts.new((-half_w, y_front, wall_h))   # front-left
    m1 = bm.verts.new((half_w, y_front, wall_h))     # front-right
    m2 = bm.verts.new((half_w, y_back, wall_h))      # back-right
    m3 = bm.verts.new((-half_w, y_back, wall_h))     # back-left
    m4 = bm.verts.new((-half_w, y_mid, wall_h + main_ridge_height))  # ridge-left
    m5 = bm.verts.new((half_w, y_mid, wall_h + main_ridge_height))   # ridge-right

    # Front slope
    bm.faces.new([m0, m1, m5, m4])
    # Back slope
    bm.faces.new([m2, m3, m4, m5])
    # Left gable triangle
    bm.faces.new([m3, m0, m4])
    # Right gable triangle
    bm.faces.new([m1, m2, m5])

    mesh_main = bpy.data.meshes.new("roof_main")
    bm.to_mesh(mesh_main)
    bm.free()

    obj_main = bpy.data.objects.new("roof_main", mesh_main)
    bpy.context.collection.objects.link(obj_main)

    mod = obj_main.modifiers.new("Solidify", 'SOLIDIFY')
    mod.thickness = roof_thick
    mod.offset = -1
    bpy.context.view_layer.objects.active = obj_main
    bpy.ops.object.modifier_apply(modifier=mod.name)

    mat = select_roof_material(f"mat_roof_{roof_hex.lstrip('#')}", roof_hex, params)
    assign_material(obj_main, mat)

    # --- Secondary cross-gable (front-facing, projects forward) ---
    cross_w = width * 0.5  # roughly half facade width
    cross_ridge_height = (cross_w / 2) * _safe_tan(pitch)
    # Ensure cross ridge meets or slightly exceeds main ridge
    if cross_ridge_height < main_ridge_height:
        cross_ridge_height = main_ridge_height * 1.05

    # Cross-gable sits on the left side (above bay window area)
    cx_center = -width / 4  # left quarter of facade
    cx_half = cross_w / 2 + overhang * 0.5
    # Depth: from front of building to the main ridge line
    cy_front = overhang
    cy_back = y_mid  # meets main ridge

    bm2 = bmesh.new()

    c0 = bm2.verts.new((cx_center - cx_half, cy_front, wall_h))   # front-left
    c1 = bm2.verts.new((cx_center + cx_half, cy_front, wall_h))   # front-right
    c2 = bm2.verts.new((cx_center + cx_half, cy_back, wall_h))    # back-right
    c3 = bm2.verts.new((cx_center - cx_half, cy_back, wall_h))    # back-left
    c4 = bm2.verts.new((cx_center, cy_front, wall_h + cross_ridge_height))  # ridge-front
    c5 = bm2.verts.new((cx_center, cy_back, wall_h + cross_ridge_height))   # ridge-back

    # Left slope
    bm2.faces.new([c3, c0, c4, c5])
    # Right slope
    bm2.faces.new([c1, c2, c5, c4])
    # Front gable triangle
    bm2.faces.new([c0, c1, c4])
    # Back triangle (mostly hidden by main roof)
    bm2.faces.new([c2, c3, c5])

    mesh_cross = bpy.data.meshes.new("roof_cross_gable")
    bm2.to_mesh(mesh_cross)
    bm2.free()

    obj_cross = bpy.data.objects.new("roof_cross_gable", mesh_cross)
    bpy.context.collection.objects.link(obj_cross)

    mod2 = obj_cross.modifiers.new("Solidify", 'SOLIDIFY')
    mod2.thickness = roof_thick
    mod2.offset = -1
    bpy.context.view_layer.objects.active = obj_cross
    bpy.ops.object.modifier_apply(modifier=mod2.name)

    assign_material(obj_cross, mat)

    # Join cross-gable into main roof object
    bpy.context.view_layer.objects.active = obj_main
    obj_main.select_set(True)
    obj_cross.select_set(True)
    bpy.ops.object.join()

    ridge_height = max(main_ridge_height, cross_ridge_height)
    return obj_main, ridge_height


def create_hip_roof(params, wall_h, width, depth):
    """Create a hip roof."""
    pitch = params.get("roof_pitch_deg", 25)
    if pitch < 5:
        pitch = 25  # sensible default for hip roofs with missing/zero pitch

    hip_height = min(width, depth) / 2 * _safe_tan(pitch)
    ridge_len = abs(depth - width) / 2

    roof_hex = get_roof_hex(params)

    bm = bmesh.new()

    rd = params.get("roof_detail", {})
    eave_mm = 300
    if isinstance(rd, dict):
        eave_mm = rd.get("eave_overhang_mm", 300)
    else:
        eave_mm = params.get("eave_overhang_mm", 300)
    overhang = eave_mm / 1000.0
    hw = width / 2 + overhang

    # Walls go from y=0 (front) to y=-depth (back)
    y_front = overhang
    y_back = -depth - overhang
    y_mid = -depth / 2  # center of the building

    # Base corners
    v0 = bm.verts.new((-hw, y_back, wall_h))
    v1 = bm.verts.new((hw, y_back, wall_h))
    v2 = bm.verts.new((hw, y_front, wall_h))
    v3 = bm.verts.new((-hw, y_front, wall_h))

    if ridge_len > 0.1:
        # Ridge line centered on building
        v4 = bm.verts.new((0, y_mid - ridge_len, wall_h + hip_height))
        v5 = bm.verts.new((0, y_mid + ridge_len, wall_h + hip_height))

        bm.faces.new([v0, v4, v1])  # back hip
        bm.faces.new([v0, v3, v5, v4])  # left slope
        bm.faces.new([v1, v4, v5, v2])  # right slope
        bm.faces.new([v2, v5, v3])  # front hip
    else:
        # Pyramid
        v4 = bm.verts.new((0, y_mid, wall_h + hip_height))
        bm.faces.new([v0, v4, v1])
        bm.faces.new([v1, v4, v2])
        bm.faces.new([v2, v4, v3])
        bm.faces.new([v3, v4, v0])

    mesh = bpy.data.meshes.new("roof_hip")
    bm.to_mesh(mesh)
    bm.free()

    obj = bpy.data.objects.new("roof", mesh)
    bpy.context.collection.objects.link(obj)

    mat = select_roof_material(f"mat_roof_{roof_hex.lstrip('#')}", roof_hex, params)
    assign_material(obj, mat)

    return obj, hip_height


def create_flat_roof(params, wall_h, width, depth):
    """Create a flat roof with parapet walls, coping cap, and roof surface."""
    parapet_h = 0.3
    cornice = params.get("cornice", {})
    if isinstance(cornice, dict):
        parapet_h = cornice.get("height_mm", 300) / 1000
    parapet_h = max(0.2, min(parapet_h, 0.8))

    parapet_thickness = 0.15
    coping_proj = 0.03  # coping overhang beyond parapet

    roof_hex = get_roof_hex(params)
    roof_mat = select_roof_material(f"mat_roof_{roof_hex.lstrip('#')}", roof_hex, params)
    trim_hex = get_trim_hex(params)
    parapet_mat = get_or_create_material("mat_parapet", colour_hex=get_facade_hex(params), roughness=0.85)
    coping_mat = create_stone_material(f"mat_coping_{trim_hex.lstrip('#')}", trim_hex)

    hw = width / 2
    party_left = params.get("party_wall_left", False)
    party_right = params.get("party_wall_right", False)

    # Roof surface plane
    bpy.ops.mesh.primitive_plane_add(size=1)
    roof = bpy.context.active_object
    roof.name = "roof_flat"
    roof.scale = (width + 0.1, depth + 0.1, 1)
    bpy.ops.object.transform_apply(scale=True)
    roof.location = (0, -depth / 2, wall_h + 0.01)
    assign_material(roof, roof_mat)

    # Front parapet wall
    bpy.ops.mesh.primitive_cube_add(size=1)
    pf = bpy.context.active_object
    pf.name = "parapet_front"
    pf.scale = (width + 0.02, parapet_thickness, parapet_h)
    bpy.ops.object.transform_apply(scale=True)
    pf.location = (0, parapet_thickness / 2, wall_h + parapet_h / 2)
    assign_material(pf, parapet_mat)

    # Front coping cap
    bpy.ops.mesh.primitive_cube_add(size=1)
    cf = bpy.context.active_object
    cf.name = "coping_front"
    cf.scale = (width + coping_proj * 2 + 0.02, parapet_thickness + coping_proj * 2, 0.04)
    bpy.ops.object.transform_apply(scale=True)
    cf.location = (0, parapet_thickness / 2, wall_h + parapet_h + 0.02)
    assign_material(cf, coping_mat)

    # Side parapets (skip party wall sides)
    # Side parapet ratio — heritage buildings typically have side parapets at
    # 75-85% of front height, tapering toward the back.  Allow override from
    # roof_detail.side_parapet_ratio (0.0-1.0).
    rd = params.get("roof_detail", {})
    side_ratio = 0.80  # default
    if isinstance(rd, dict):
        sr = rd.get("side_parapet_ratio")
        if isinstance(sr, (int, float)) and 0.0 < sr <= 1.0:
            side_ratio = float(sr)
    side_parapet_h = parapet_h * side_ratio

    if not party_left:
        bpy.ops.mesh.primitive_cube_add(size=1)
        pl = bpy.context.active_object
        pl.name = "parapet_left"
        pl.scale = (parapet_thickness, depth, side_parapet_h)
        bpy.ops.object.transform_apply(scale=True)
        pl.location = (-hw, -depth / 2, wall_h + side_parapet_h / 2)
        assign_material(pl, parapet_mat)

    if not party_right:
        bpy.ops.mesh.primitive_cube_add(size=1)
        pr = bpy.context.active_object
        pr.name = "parapet_right"
        pr.scale = (parapet_thickness, depth, side_parapet_h)
        bpy.ops.object.transform_apply(scale=True)
        pr.location = (hw, -depth / 2, wall_h + side_parapet_h / 2)
        assign_material(pr, parapet_mat)

    return roof, parapet_h


