"""Decorative architectural elements for the Kensington building generator.

String courses, quoins, cornices, brackets, bargeboard, dormers, and 25+ more.
Extracted from generate_building.py.
"""

import bpy
import bmesh
import math
from mathutils import Vector

from generator_modules.colours import (
    hex_to_rgb, colour_name_to_hex, infer_hex_from_text,
    get_facade_hex, get_trim_hex,
    get_accent_hex, get_stone_element_hex, get_roof_hex,
    get_condition_roughness_bias, get_condition_saturation_shift,
    get_era_defaults, get_typology_hints,
)
from generator_modules.materials import (
    assign_material, get_or_create_material, _get_bsdf,
    create_brick_material, create_wood_material, create_stone_material,
    create_painted_material, create_glass_material, create_metal_roof_material,
    create_canvas_material, create_roof_material, select_roof_material,
)
from generator_modules.geometry import (
    create_box, boolean_cut, create_arch_cutter, create_rect_cutter,
    _safe_tan, _clamp_positive,
)
from generator_modules.windows import (
    _normalize_floor_index, get_effective_windows_detail,
)


def create_string_courses(params, wall_h, width, depth, bldg_id=""):
    """Create horizontal string courses / belt courses between floors."""
    dec = params.get("decorative_elements", {})
    if not isinstance(dec, dict):
        return []

    sc = dec.get("string_courses", {})
    if not isinstance(sc, dict) or not sc.get("present", False):
        # Also check top-level string_course
        sc = params.get("string_course", {})
        if not isinstance(sc, dict):
            return []

    objects = []
    sc_hex = sc.get("colour_hex", get_accent_hex(params))
    sc_h = sc.get("height_mm", sc.get("width_mm", 120))
    if isinstance(sc_h, (int, float)):
        sc_h = sc_h / 1000
    else:
        sc_h = 0.12
    sc_proj = sc.get("projection_mm", 20)
    if isinstance(sc_proj, (int, float)):
        sc_proj = sc_proj / 1000
    else:
        sc_proj = 0.02

    sc_mat = create_stone_material(f"mat_stone_{sc_hex.lstrip('#')}", sc_hex)

    floor_heights = params.get("floor_heights_m", [3.0])
    z_positions = []
    z = 0
    for fh in floor_heights[:-1]:
        z += fh
        z_positions.append(z)

    positions = sc.get("positions", [])
    if isinstance(positions, list):
        pos_text = " ".join(str(p).lower() for p in positions)
        if "parapet_base" in pos_text or "parapet base" in pos_text:
            z_positions.append(wall_h - sc_h / 2)

    party_left = params.get("party_wall_left", False)
    party_right = params.get("party_wall_right", False)
    hw = width / 2

    seen = set()
    for i, z in enumerate(sorted(z_positions)):
        z_key = round(z, 4)
        if z_key in seen:
            continue
        seen.add(z_key)

        # Front band
        bpy.ops.mesh.primitive_cube_add(size=1)
        band = bpy.context.active_object
        band.name = f"string_course_{i}_{bldg_id}"
        band.scale = (width + sc_proj * 2, sc_proj, sc_h)
        bpy.ops.object.transform_apply(scale=True)
        band.location = (0, sc_proj / 2, z)
        assign_material(band, sc_mat)
        objects.append(band)

        # Side return bands (wrap around corners, skip party walls)
        return_depth = min(0.3, depth * 0.05)  # short return, not full depth
        if not party_left:
            bpy.ops.mesh.primitive_cube_add(size=1)
            lr = bpy.context.active_object
            lr.name = f"string_course_{i}_left_{bldg_id}"
            lr.scale = (sc_proj, return_depth, sc_h)
            bpy.ops.object.transform_apply(scale=True)
            lr.location = (-hw - sc_proj / 2, -return_depth / 2, z)
            assign_material(lr, sc_mat)
            objects.append(lr)

        if not party_right:
            bpy.ops.mesh.primitive_cube_add(size=1)
            rr = bpy.context.active_object
            rr.name = f"string_course_{i}_right_{bldg_id}"
            rr.scale = (sc_proj, return_depth, sc_h)
            bpy.ops.object.transform_apply(scale=True)
            rr.location = (hw + sc_proj / 2, -return_depth / 2, z)
            assign_material(rr, sc_mat)
            objects.append(rr)

    return objects



def _create_corbel_band(name_prefix, cx, y_face, z_base, width, course_count=3,
                        brick_w=0.22, brick_h=0.075, base_proj=0.035,
                        step_proj=0.02, colour_hex="#B85A3A"):
    """Create a simple stepped corbel table along a front-facing wall."""
    if width < 0.1:
        return []
    objects = []
    mat = create_brick_material(f"mat_{name_prefix}_{colour_hex.lstrip('#')}", colour_hex)
    count = max(3, int(width / max(brick_w, 0.18)))
    spacing = width / count

    for course in range(course_count):
        proj = base_proj + course * step_proj
        z = z_base + course * brick_h
        for i in range(count):
            x = cx - width / 2 + spacing * (i + 0.5)
            bpy.ops.mesh.primitive_cube_add(size=1)
            corbel = bpy.context.active_object
            corbel.name = f"{name_prefix}_{course}_{i}"
            corbel.scale = (spacing * 0.46, proj, brick_h * 0.48)
            bpy.ops.object.transform_apply(scale=True)
            corbel.location = (x, y_face + proj / 2, z + brick_h / 2)
            assign_material(corbel, mat)
            objects.append(corbel)

    return objects



def _create_arch_voussoirs(name_prefix, cx, y_face, sill_z, width, height, spring_h,
                           count=11, colour_hex="#C8C0B0", depth=0.12):
    """Create wedge-like voussoir blocks around a front-facing arch."""
    objects = []
    mat = create_stone_material(f"mat_{name_prefix}_{colour_hex.lstrip('#')}", colour_hex)
    radius = width / 2 + 0.08
    center_z = sill_z + spring_h
    stone_w = max(0.08, width * 0.06)
    stone_h = max(0.10, height * 0.08)

    for si in range(count):
        angle = math.pi * si / max(1, count - 1)
        sx = cx + radius * math.cos(angle)
        sz = center_z + radius * math.sin(angle)
        bpy.ops.mesh.primitive_cube_add(size=1)
        stone = bpy.context.active_object
        stone.name = f"{name_prefix}_{si}"
        stone.scale = (stone_w, depth, stone_h)
        bpy.ops.object.transform_apply(scale=True)
        stone.location = (sx, y_face + depth / 2, sz)
        stone.rotation_euler.y = math.pi / 2 - angle
        assign_material(stone, mat)
        objects.append(stone)

    return objects



def create_corbelling(params, wall_h, width, depth, bldg_id=""):
    """Create corbel tables on front and exposed sides."""
    dec = params.get("decorative_elements", {})
    if not isinstance(dec, dict):
        return []

    corbelling = dec.get("corbelling", {})
    if corbelling is False:
        return []
    if not isinstance(corbelling, dict) or not corbelling:
        return []

    course_count = corbelling.get("course_count", 3)
    if not isinstance(course_count, int):
        text = json.dumps(corbelling).lower()
        if "5 course" in text or "5-course" in text:
            course_count = 5
        elif "4 course" in text or "4-course" in text:
            course_count = 4
        else:
            course_count = 3

    facade_hex = get_facade_hex(params)
    z_base = wall_h - 0.28
    objects = _create_corbel_band(f"corbel_front_{bldg_id}", 0, 0.02, z_base, width,
                                  course_count=course_count, colour_hex=facade_hex)

    # Side corbelling on exposed (non-party-wall) sides
    party_left = params.get("party_wall_left", False)
    party_right = params.get("party_wall_right", False)
    hw = width / 2

    if not party_left:
        side_objs = _create_corbel_band(f"corbel_left_{bldg_id}", -hw - 0.02, -depth * 0.15,
                                         z_base, depth * 0.3,
                                         course_count=course_count, colour_hex=facade_hex)
        objects.extend(side_objs)

    if not party_right:
        side_objs = _create_corbel_band(f"corbel_right_{bldg_id}", hw + 0.02, -depth * 0.15,
                                         z_base, depth * 0.3,
                                         course_count=course_count, colour_hex=facade_hex)
        objects.extend(side_objs)

    return objects



def create_tower(params, bldg_id=""):
    """Create a clock tower (for fire station or similar)."""
    volumes = params.get("volumes", [])
    tower_data = None
    for vol in volumes:
        if isinstance(vol, dict) and "tower" in vol.get("id", "").lower():
            tower_data = vol
            break

    if not tower_data:
        return []

    objects = []
    tw = tower_data.get("width_m", 3.5)
    td = tower_data.get("depth_m", 3.5)
    th = tower_data.get("total_height_m", 22.0)

    # Tower position relative to heritage hall
    # Place it at the right side of the building
    facade_w = params.get("facade_width_m", 18.0)
    tx = facade_w / 2 - tw / 2

    facade_hex = get_facade_hex(params)
    hex_id = facade_hex.lstrip('#')
    tower_mat = get_or_create_material(f"mat_facade_{hex_id}", colour_hex=facade_hex, roughness=0.85)

    # Main tower shaft
    bpy.ops.mesh.primitive_cube_add(size=1)
    shaft = bpy.context.active_object
    shaft.name = "tower_shaft"
    shaft.scale = (tw, td, th)
    bpy.ops.object.transform_apply(scale=True)
    shaft.location = (tx, -td / 2, th / 2)
    assign_material(shaft, tower_mat)
    objects.append(shaft)

    # String courses between tower levels
    levels = tower_data.get("level_details", [])
    sc_mat = get_or_create_material(f"mat_tower_sc_{bldg_id}", colour_hex=get_accent_hex(params), roughness=0.6)
    z = 0
    for lvl in levels:
        if isinstance(lvl, dict):
            lvl_h = lvl.get("height_m", 4.0)
            z += lvl_h
            bpy.ops.mesh.primitive_cube_add(size=1)
            band = bpy.context.active_object
            band.name = f"tower_band_{lvl.get('level', 0)}"
            band.scale = (tw + 0.06, td + 0.06, 0.1)
            bpy.ops.object.transform_apply(scale=True)
            band.location = (tx, -td / 2, z)
            assign_material(band, sc_mat)
            objects.append(band)

            # Clock face(s)
            clock = lvl.get("clock_face", {})
            if isinstance(clock, dict) and clock.get("type"):
                diameter = clock.get("diameter_m", 1.5)
                faces_count = clock.get("faces_count", 1)
                clock_mat = get_or_create_material("mat_clock", colour_hex="#F0F0E0", roughness=0.3)
                clock_z = z - lvl_h / 2

                # Front face (Y+) — always created
                face_defs = [
                    ("clock_face_front", {"rx": math.pi / 2, "ry": 0},
                     (tx, -td / 2 + td / 2 + 0.05, clock_z)),
                ]
                if faces_count >= 4:
                    # Back face (Y-)
                    face_defs.append(
                        ("clock_face_back", {"rx": -math.pi / 2, "ry": 0},
                         (tx, -td / 2 - td / 2 - 0.05, clock_z))
                    )
                    # Left face (X-)
                    face_defs.append(
                        ("clock_face_left", {"rx": 0, "ry": math.pi / 2},
                         (tx - tw / 2 - 0.05, -td / 2, clock_z))
                    )
                    # Right face (X+)
                    face_defs.append(
                        ("clock_face_right", {"rx": 0, "ry": -math.pi / 2},
                         (tx + tw / 2 + 0.05, -td / 2, clock_z))
                    )

                for cf_name, rot, loc in face_defs:
                    bpy.ops.mesh.primitive_cylinder_add(radius=diameter / 2, depth=0.1, vertices=32)
                    cf = bpy.context.active_object
                    cf.name = cf_name
                    cf.rotation_euler.x = rot["rx"]
                    cf.rotation_euler.y = rot["ry"]
                    cf.location = loc
                    assign_material(cf, clock_mat)
                    objects.append(cf)

    # Tower parapet cap
    bpy.ops.mesh.primitive_cube_add(size=1)
    cap = bpy.context.active_object
    cap.name = "tower_cap"
    cap.scale = (tw + 0.15, td + 0.15, 0.15)
    bpy.ops.object.transform_apply(scale=True)
    cap.location = (tx, -td / 2, th + 0.075)
    assign_material(cap, sc_mat)
    objects.append(cap)

    return objects



def create_quoins(params, wall_h, width, depth, bldg_id=""):
    """Create vertical quoin strips at building corners."""
    dec = params.get("decorative_elements", {})
    if not isinstance(dec, dict):
        return []

    quoins = dec.get("quoins", {})
    if not isinstance(quoins, dict) or not quoins.get("present", False):
        return []

    objects = []
    q_hex = quoins.get("colour_hex", get_accent_hex(params))
    q_w = quoins.get("strip_width_mm", 200) / 1000
    q_proj = quoins.get("projection_mm", 15) / 1000

    q_mat = get_or_create_material(f"mat_quoins_{bldg_id}", colour_hex=q_hex, roughness=0.6)

    hw = width / 2
    positions = [(-hw, "quoin_left"), (hw, "quoin_right")]

    total_strips = quoins.get("total_vertical_strips")
    locations = quoins.get("locations", [])
    if isinstance(total_strips, int) and total_strips >= 3:
        positions = []
        spacing = width / max(1, total_strips - 1)
        for idx in range(total_strips):
            x = -hw + spacing * idx
            positions.append((x, f"quoin_strip_{idx}"))
    elif isinstance(locations, list) and any("between_bays" in str(loc).lower() for loc in locations):
        positions = [
            (-hw, "quoin_left"),
            (-width / 6, "quoin_inner_left"),
            (width / 6, "quoin_inner_right"),
            (hw, "quoin_right"),
        ]

    # Create alternating block pattern (long/short stones stacked)
    block_h_long = 0.25
    block_h_short = 0.18
    block_w_long = q_w
    block_w_short = q_w * 0.65

    for x, name in positions:
        z = 0
        block_idx = 0
        while z < wall_h - 0.1:
            is_long = (block_idx % 2 == 0)
            bh = block_h_long if is_long else block_h_short
            bw = block_w_long if is_long else block_w_short

            bpy.ops.mesh.primitive_cube_add(size=1)
            q = bpy.context.active_object
            q.name = f"{name}_{block_idx}"
            q.scale = (bw, q_proj, bh - 0.005)  # small gap between blocks
            bpy.ops.object.transform_apply(scale=True)
            q.location = (x, q_proj / 2, z + bh / 2)
            assign_material(q, q_mat)
            objects.append(q)

            z += bh
            block_idx += 1

    return objects



def create_bargeboard(params, wall_h, width, depth, bldg_id=""):
    """Create decorative bargeboard along gable rake edges."""
    dec = params.get("decorative_elements", {})
    if not isinstance(dec, dict):
        dec = {}

    bb = dec.get("bargeboard", {})
    # Also check roof_detail.bargeboard for detailed dimensions
    rd_bb = params.get("roof_detail", {}).get("bargeboard", {})
    if isinstance(rd_bb, dict) and rd_bb:
        # Merge: roof_detail.bargeboard has priority for dimensions
        merged = dict(bb) if isinstance(bb, dict) else {}
        merged.update(rd_bb)
        bb = merged

    if not isinstance(bb, dict) or not bb.get("present", True):
        # Check roof_features for bargeboard mentions
        rf = params.get("roof_features", [])
        has_bb = any("bargeboard" in str(f).lower() or "rake" in str(f).lower() for f in rf)
        if not has_bb:
            return []
        bb = {"type": "simple", "colour_hex": "#3E2A1A"}

    pitch = params.get("roof_pitch_deg", 35)
    ridge_height = (width / 2) * _safe_tan(pitch)

    # Get eave overhang for positioning
    rd = params.get("roof_detail", {})
    eave_mm = rd.get("eave_overhang_mm", 300) if isinstance(rd, dict) else 300
    overhang = eave_mm / 1000.0

    bb_hex = bb.get("colour_hex", bb.get("colour", "#3E2A1A"))
    if not bb_hex.startswith("#"):
        bb_hex = colour_name_to_hex(str(bb_hex))
    bb_width = bb.get("width_mm", 220) / 1000
    bb_proj = overhang  # bargeboard hangs at the eave overhang
    bb_thick = 0.04

    bb_mat = create_wood_material(f"mat_bargeboard_{bb_hex.lstrip('#')}", bb_hex)

    objects = []
    half_w = width / 2
    rake_len = math.sqrt((half_w) ** 2 + ridge_height ** 2)
    rake_angle = math.atan2(ridge_height, half_w)

    # Front gable bargeboard (y ~ 0)
    for side in [-1, 1]:  # left and right rake
        bm = bmesh.new()
        # Board as a flat rectangle, then rotate to follow rake
        hw = rake_len / 2
        hh = bb_width / 2

        v0 = bm.verts.new((-hw, 0, -hh))
        v1 = bm.verts.new((hw, 0, -hh))
        v2 = bm.verts.new((hw, 0, hh))
        v3 = bm.verts.new((-hw, 0, hh))
        # Front face
        bm.faces.new([v0, v1, v2, v3])
        # Back face (give thickness)
        v4 = bm.verts.new((-hw, -bb_thick, -hh))
        v5 = bm.verts.new((hw, -bb_thick, -hh))
        v6 = bm.verts.new((hw, -bb_thick, hh))
        v7 = bm.verts.new((-hw, -bb_thick, hh))
        bm.faces.new([v7, v6, v5, v4])
        # Sides
        bm.faces.new([v0, v4, v5, v1])
        bm.faces.new([v1, v5, v6, v2])
        bm.faces.new([v2, v6, v7, v3])
        bm.faces.new([v3, v7, v4, v0])

        # Add scalloped cutouts along bottom edge if ornate
        bb_type = str(bb.get("type", "")).lower()
        if "scallop" in bb_type or "fretwork" in bb_type or "scroll" in bb_type:
            pattern_repeat = bb.get("pattern_repeat_mm", 150) / 1000
            n_scallops = max(3, int(rake_len / pattern_repeat))
            scallop_r = pattern_repeat * 0.35
            for si in range(n_scallops):
                cx = -hw + pattern_repeat * (si + 0.5)
                if cx > hw:
                    break
                # Create semicircular cutout vertices (approximate with 6 segments)
                cut_verts_f = []
                cut_verts_b = []
                for seg in range(7):
                    angle = math.pi * seg / 6
                    sx = cx + scallop_r * math.cos(angle)
                    sz = -hh + scallop_r * math.sin(angle)
                    cut_verts_f.append(bm.verts.new((sx, 0.01, sz)))
                    cut_verts_b.append(bm.verts.new((sx, -bb_thick - 0.01, sz)))

        mesh = bpy.data.meshes.new(f"bargeboard_{side}")
        bm.to_mesh(mesh)
        bm.free()

        obj = bpy.data.objects.new(f"bargeboard_{side}", mesh)
        bpy.context.collection.objects.link(obj)

        # Position: center of rake line, hanging from eave overhang
        cx = side * half_w / 2
        cz = wall_h + ridge_height / 2
        obj.location = (cx, bb_proj + 0.05, cz)  # in front of wall at eave edge
        obj.rotation_euler.y = side * rake_angle
        assign_material(obj, bb_mat)
        objects.append(obj)

    return objects



def create_cornice_band(params, wall_h, width, depth, bldg_id=""):
    """Create projecting cornice moulding at the eave line."""
    cornice = params.get("cornice", {})
    if not cornice:
        dec = params.get("decorative_elements", {})
        if isinstance(dec, dict):
            cornice = dec.get("cornice", {})
    if isinstance(cornice, str):
        if "none" in cornice.lower():
            return []
        cornice = {"type": cornice}
    if not isinstance(cornice, dict):
        return []
    if cornice.get("type", "") == "none":
        return []

    # Get cornice dimensions
    proj = cornice.get("projection_mm", 80)
    if isinstance(proj, (int, float)):
        proj = proj / 1000
    else:
        proj = 0.08
    height = cornice.get("height_mm", 150)
    if isinstance(height, (int, float)):
        height = height / 1000
    else:
        height = 0.15

    # Cornice colour — usually matches trim or accent stone
    cornice_hex = cornice.get("colour_hex", "")
    if not isinstance(cornice_hex, str) or not cornice_hex.startswith("#"):
        colour_palette = params.get("colour_palette", {})
        trim = colour_palette.get("trim", {})
        cornice_hex = get_accent_hex(params)
        if isinstance(trim, dict):
            cornice_hex = trim.get("hex_approx", cornice_hex)
        else:
            cornice_hex = get_trim_hex(params)

    mat = create_stone_material(f"mat_cornice_{cornice_hex.lstrip('#')}", cornice_hex)

    objects = []

    party_left = params.get("party_wall_left", False)
    party_right = params.get("party_wall_right", False)

    # Front cornice — main band
    bpy.ops.mesh.primitive_cube_add(size=1)
    c = bpy.context.active_object
    c.name = f"cornice_front_{bldg_id}"
    c.scale = (width + proj * 2, proj, height)
    bpy.ops.object.transform_apply(scale=True)
    c.location = (0, proj / 2, wall_h + height / 2)
    assign_material(c, mat)
    objects.append(c)

    # Soffit — sheltered underside, smoother than exposed cornice top
    soffit_mat = get_or_create_material("mat_soffit", colour_hex=cornice_hex, roughness=0.45)
    bpy.ops.mesh.primitive_cube_add(size=1)
    soffit = bpy.context.active_object
    soffit.name = f"cornice_soffit_{bldg_id}"
    soffit.scale = (width + proj * 2, proj, 0.015)
    bpy.ops.object.transform_apply(scale=True)
    soffit.location = (0, proj / 2, wall_h + 0.008)
    assign_material(soffit, soffit_mat)
    objects.append(soffit)

    # Dentil course — small repeating blocks below main band (Pre-1889 and ornate styles)
    cornice_type = str(cornice.get("type", "simple")).lower()
    era = str(params.get("hcd_data", {}).get("construction_date", "")).lower() if isinstance(params.get("hcd_data"), dict) else ""
    if cornice_type in ("dentil", "decorative", "bracketed") or "pre-1889" in era:
        dentil_w = 0.04
        dentil_h = 0.04
        dentil_spacing = 0.08
        dentil_z = wall_h + 0.01
        num_dentils = int(width / dentil_spacing)
        for di in range(num_dentils):
            dx = -width / 2 + dentil_spacing / 2 + di * dentil_spacing
            bpy.ops.mesh.primitive_cube_add(size=1)
            d = bpy.context.active_object
            d.name = f"dentil_{bldg_id}_{di}"
            d.scale = (dentil_w, proj * 0.6, dentil_h)
            bpy.ops.object.transform_apply(scale=True)
            d.location = (dx, proj * 0.3, dentil_z)
            assign_material(d, mat)
            objects.append(d)

    # Side cornices (skip party wall sides)
    if not party_left:
        bpy.ops.mesh.primitive_cube_add(size=1)
        sc = bpy.context.active_object
        sc.name = f"cornice_left_{bldg_id}"
        sc.scale = (proj, depth, height)
        bpy.ops.object.transform_apply(scale=True)
        sc.location = (-width / 2 - proj / 2, -depth / 2, wall_h + height / 2)
        assign_material(sc, mat)
        objects.append(sc)

    if not party_right:
        bpy.ops.mesh.primitive_cube_add(size=1)
        sc = bpy.context.active_object
        sc.name = f"cornice_right_{bldg_id}"
        sc.scale = (proj, depth, height)
        bpy.ops.object.transform_apply(scale=True)
        sc.location = (width / 2 + proj / 2, -depth / 2, wall_h + height / 2)
        assign_material(sc, mat)
        objects.append(sc)

    # Optional storefront head/cornice band
    sf = params.get("storefront", {})
    if params.get("has_storefront") and isinstance(sf, dict):
        sf_h = sf.get("height_m", 3.2)
        bulkhead_h = sf.get("bulkhead_height_m", 0.0)
        storefront_z = bulkhead_h + sf_h + height / 2
        sf_proj = max(proj * 0.8, 0.08)
        bpy.ops.mesh.primitive_cube_add(size=1)
        sh = bpy.context.active_object
        sh.name = f"storefront_cornice_{bldg_id}"
        sh.scale = (width + sf_proj * 1.5, sf_proj, height * 0.9)
        bpy.ops.object.transform_apply(scale=True)
        sh.location = (0, sf_proj / 2, storefront_z)
        assign_material(sh, mat)
        objects.append(sh)

    return objects



def create_stained_glass_transoms(params, facade_width, bldg_id=""):
    """Create simple stained-glass transom panels for storefronts/entries."""
    dec = params.get("decorative_elements", {})
    if not isinstance(dec, dict):
        return []
    transom = dec.get("stained_glass_transoms", {})
    if not isinstance(transom, dict) or not transom.get("present", False):
        return []

    sf = params.get("storefront", {})
    if not params.get("has_storefront") or not isinstance(sf, dict):
        return []

    sf_h = sf.get("height_m", 3.2)
    bulkhead_h = sf.get("bulkhead_height_m", 0.0)
    transom_h = min(0.45, max(0.25, sf_h * 0.12))
    y = 0.03
    z = bulkhead_h + sf_h - transom_h / 2 - 0.08
    palette = str(transom.get("colour_palette", "amber_green_red")).lower()
    colours = ["#A96F2D", "#5C7A3A", "#8E2F2F"] if "amber" in palette else ["#6A6A8A", "#8A6A4A", "#6A8A6A"]

    objects = []
    panel_count = 3
    panel_w = facade_width / (panel_count + 2)
    start_x = -panel_w
    for i in range(panel_count):
        bpy.ops.mesh.primitive_plane_add(size=1)
        panel = bpy.context.active_object
        panel.name = f"transom_{i}_{bldg_id}"
        panel.scale = (panel_w * 0.42, 1, transom_h * 0.48)
        bpy.ops.object.transform_apply(scale=True)
        panel.rotation_euler.x = math.pi / 2
        panel.location = (start_x + i * panel_w, y, z)
        mat = get_or_create_material(f"mat_transom_{i}_{bldg_id}", colour_hex=colours[i % len(colours)], roughness=0.15)
        assign_material(panel, mat)
        objects.append(panel)

    return objects



def create_hip_rooflet(params, wall_h, width, depth, bldg_id=""):
    """Create a small hip-roofed rooftop element from roof_detail.hip_element."""
    rd = params.get("roof_detail", {})
    if not isinstance(rd, dict):
        return []
    hip = rd.get("hip_element", {})
    if not isinstance(hip, dict) or not hip.get("present", False):
        return []

    pitch = hip.get("pitch_deg", 20)
    base_w = max(1.2, min(width * 0.22, 2.5))
    base_d = max(1.2, min(depth * 0.18, 2.2))
    rise = min(base_w, base_d) * 0.35 * _safe_tan(pitch)
    x = width * 0.28 if "corner" in str(hip.get("location", "")).lower() else 0
    y = -depth * 0.28
    z = wall_h

    bm = bmesh.new()
    hw = base_w / 2
    hd = base_d / 2
    v0 = bm.verts.new((x - hw, y - hd, z))
    v1 = bm.verts.new((x + hw, y - hd, z))
    v2 = bm.verts.new((x + hw, y + hd, z))
    v3 = bm.verts.new((x - hw, y + hd, z))
    v4 = bm.verts.new((x, y, z + rise))
    bm.faces.new([v0, v1, v4])
    bm.faces.new([v1, v2, v4])
    bm.faces.new([v2, v3, v4])
    bm.faces.new([v3, v0, v4])

    mesh = bpy.data.meshes.new(f"hip_rooflet_{bldg_id}")
    bm.to_mesh(mesh)
    bm.free()

    rooflet = bpy.data.objects.new(f"hip_rooflet_{bldg_id}", mesh)
    bpy.context.collection.objects.link(rooflet)
    mat = create_roof_material(f"mat_hip_rooflet_{bldg_id}", infer_hex_from_text(hip.get("colour", ""), hip.get("material", ""), default="#3A3A3A"))
    assign_material(rooflet, mat)
    return [rooflet]



def create_window_lintels(params, wall_h, facade_width, bldg_id=""):
    """Create projecting lintels above windows and sills below."""
    windows_detail = get_effective_windows_detail(params)
    floor_heights = params.get("floor_heights_m", [3.0])
    if not windows_detail:
        return []

    # Check if building has lintels described
    dec = params.get("decorative_elements", {})
    has_lintels = False
    if isinstance(dec, dict):
        for key in ["lintels", "stone_lintels", "window_hoods"]:
            if dec.get(key):
                has_lintels = True
                break

    # Also check individual window specs for lintel/sill data
    for fd in windows_detail:
        if isinstance(fd, dict):
            for w in fd.get("windows", []):
                if isinstance(w, dict) and (w.get("lintel") or w.get("sill") or w.get("surround")):
                    has_lintels = True

    if not has_lintels:
        return []

    # Lintel material — usually stone/cream, uses colour_palette.accent as fallback
    lintel_hex = get_accent_hex(params)
    if isinstance(dec, dict):
        lint = dec.get("lintels", dec.get("stone_lintels", {}))
        if isinstance(lint, dict):
            lintel_hex = lint.get("colour_hex", lint.get("colour", lintel_hex))
            if not lintel_hex.startswith("#"):
                lintel_hex = colour_name_to_hex(str(lintel_hex))

    mat = create_stone_material(f"mat_lintel_{lintel_hex.lstrip('#')}", lintel_hex)
    objects = []

    for floor_data in windows_detail:
        if not isinstance(floor_data, dict):
            continue

        floor_idx = _normalize_floor_index(floor_data.get("floor", 1), floor_heights)

        z_base = sum(floor_heights[:max(0, int(floor_idx) - 1)])

        windows = floor_data.get("windows", [])
        if not windows and "count" in floor_data:
            count = floor_data.get("count", 0)
            w = floor_data.get("width_m", 0.8)
            h = floor_data.get("height_m", 1.3)
            windows = [{"count": count, "width_m": w, "height_m": h}]

        for win_spec in windows:
            if not isinstance(win_spec, dict):
                continue
            count = win_spec.get("count", 1)
            if count == 0:
                continue
            w = win_spec.get("width_m", win_spec.get("width_each_m", 0.8))
            h = win_spec.get("height_m", 1.3)

            fi = max(0, int(floor_idx) - 1)
            fi = min(fi, len(floor_heights) - 1)
            floor_h = floor_heights[fi] if floor_heights else 3.0
            sill_h = z_base + max(0.8, (floor_h - h) / 2)

            total_win_w = count * w + (count - 1) * max(0.3, (facade_width - count * w) / (count + 1))
            start_x = -total_win_w / 2 + w / 2
            spacing = (total_win_w - w) / max(1, count - 1) if count > 1 else 0

            # Check arch type for lintel shape
            arch_type = str(win_spec.get("arch_type", win_spec.get("head_shape", "flat"))).lower()

            for i in range(count):
                x = start_x + i * spacing if count > 1 else 0

                # Lintel (above window)
                bpy.ops.mesh.primitive_cube_add(size=1)
                lt = bpy.context.active_object
                lt.name = f"lintel_{floor_idx}_{i}_{bldg_id}"
                lt.scale = (w + 0.08, 0.06, 0.07)
                bpy.ops.object.transform_apply(scale=True)
                lt.location = (x, 0.03, sill_h + h + 0.035)
                assign_material(lt, mat)
                objects.append(lt)

                # Keystone for segmental/arched lintels
                if "segmental" in arch_type or "arch" in arch_type or "round" in arch_type:
                    bpy.ops.mesh.primitive_cube_add(size=1)
                    ks = bpy.context.active_object
                    ks.name = f"keystone_{floor_idx}_{i}_{bldg_id}"
                    ks.scale = (0.08, 0.07, 0.12)
                    bpy.ops.object.transform_apply(scale=True)
                    ks.location = (x, 0.035, sill_h + h + 0.06)
                    assign_material(ks, mat)
                    objects.append(ks)

                # Drip mould — small shelf above lintel to shed water
                bpy.ops.mesh.primitive_cube_add(size=1)
                dm = bpy.context.active_object
                dm.name = f"drip_mould_{floor_idx}_{i}_{bldg_id}"
                dm.scale = (w + 0.12, 0.03, 0.015)
                bpy.ops.object.transform_apply(scale=True)
                dm.location = (x, 0.05, sill_h + h + 0.075)
                assign_material(dm, mat)
                objects.append(dm)

                # Sill (below window) — slightly wider, more projecting, with nose
                bpy.ops.mesh.primitive_cube_add(size=1)
                sl = bpy.context.active_object
                sl.name = f"sill_{floor_idx}_{i}_{bldg_id}"
                sl.scale = (w + 0.1, 0.08, 0.04)
                bpy.ops.object.transform_apply(scale=True)
                sl.location = (x, 0.04, sill_h - 0.02)
                assign_material(sl, mat)
                objects.append(sl)

                # Sill nose — projecting front edge
                bpy.ops.mesh.primitive_cube_add(size=1)
                sn = bpy.context.active_object
                sn.name = f"sill_nose_{floor_idx}_{i}_{bldg_id}"
                sn.scale = (w + 0.12, 0.02, 0.02)
                bpy.ops.object.transform_apply(scale=True)
                sn.location = (x, 0.09, sill_h - 0.03)
                assign_material(sn, mat)
                objects.append(sn)

    return objects



def create_brackets(params, wall_h, width, depth, bldg_id=""):
    """Create decorative brackets at gable eave or porch."""
    dec = params.get("decorative_elements", {})
    if not isinstance(dec, dict):
        return []

    objects = []

    # Gable brackets
    gb = dec.get("gable_brackets", dec.get("brackets", {}))
    if isinstance(gb, dict) and gb.get("type"):
        proj = gb.get("projection_mm", 200) / 1000
        bracket_h = gb.get("height_mm", 300) / 1000
        bracket_w = 0.06
        bracket_hex = gb.get("colour_hex", "#3E2A1A")
        if not bracket_hex.startswith("#"):
            bracket_hex = colour_name_to_hex(str(bracket_hex))

        br_mat = get_or_create_material(f"mat_bracket_{bracket_hex.lstrip('#')}", colour_hex=bracket_hex, roughness=0.6)

        # Place brackets under eave at regular intervals
        count = gb.get("count", 4)
        half_w = width / 2
        for i in range(count):
            x = -half_w + (width / max(1, count - 1)) * i if count > 1 else 0

            # Bracket as a right-triangle profile (scroll bracket shape)
            bm = bmesh.new()
            v0 = bm.verts.new((-bracket_w / 2, 0, 0))
            v1 = bm.verts.new((-bracket_w / 2, 0, bracket_h))
            v2 = bm.verts.new((-bracket_w / 2, proj, 0))
            v3 = bm.verts.new((bracket_w / 2, 0, 0))
            v4 = bm.verts.new((bracket_w / 2, 0, bracket_h))
            v5 = bm.verts.new((bracket_w / 2, proj, 0))
            bm.faces.new([v0, v1, v2])  # left
            bm.faces.new([v3, v5, v4])  # right
            bm.faces.new([v0, v2, v5, v3])  # bottom
            bm.faces.new([v1, v4, v5, v2])  # slope
            bm.faces.new([v0, v3, v4, v1])  # back

            mesh = bpy.data.meshes.new(f"bracket_{i}")
            bm.to_mesh(mesh)
            bm.free()

            obj = bpy.data.objects.new(f"bracket_{i}", mesh)
            bpy.context.collection.objects.link(obj)
            obj.location = (x, 0, wall_h - bracket_h)
            assign_material(obj, br_mat)
            objects.append(obj)

    # Porch brackets
    pb = dec.get("porch_brackets", {})
    if isinstance(pb, dict) and pb.get("type"):
        proj = pb.get("projection_mm", 200) / 1000
        bracket_h = pb.get("height_mm", 250) / 1000
        bracket_hex = pb.get("colour_hex", "#3E2A1A")
        if not bracket_hex.startswith("#"):
            bracket_hex = colour_name_to_hex(str(bracket_hex))

        pb_mat = get_or_create_material(f"mat_pbracket_{bracket_hex.lstrip('#')}", colour_hex=bracket_hex, roughness=0.6)
        porch = params.get("porch", {})
        porch_h = porch.get("height_m", 2.8) if isinstance(porch, dict) else 2.8
        porch_d = porch.get("depth_m", 2.0) if isinstance(porch, dict) else 2.0

        count = pb.get("count", 4)
        porch_w = porch.get("width_m", width) if isinstance(porch, dict) else width

        for i in range(count):
            x = -porch_w / 2 + (porch_w / max(1, count - 1)) * i if count > 1 else 0

            bm = bmesh.new()
            bw = 0.05
            v0 = bm.verts.new((-bw / 2, 0, 0))
            v1 = bm.verts.new((-bw / 2, 0, bracket_h))
            v2 = bm.verts.new((-bw / 2, proj, 0))
            v3 = bm.verts.new((bw / 2, 0, 0))
            v4 = bm.verts.new((bw / 2, 0, bracket_h))
            v5 = bm.verts.new((bw / 2, proj, 0))
            bm.faces.new([v0, v1, v2])
            bm.faces.new([v3, v5, v4])
            bm.faces.new([v0, v2, v5, v3])
            bm.faces.new([v1, v4, v5, v2])
            bm.faces.new([v0, v3, v4, v1])

            mesh = bpy.data.meshes.new(f"porch_bracket_{i}")
            bm.to_mesh(mesh)
            bm.free()

            obj = bpy.data.objects.new(f"porch_bracket_{i}", mesh)
            bpy.context.collection.objects.link(obj)
            obj.location = (x, porch_d, porch_h - bracket_h)
            assign_material(obj, pb_mat)
            objects.append(obj)

    return objects



def create_ridge_finial(params, wall_h, width, depth, bldg_id=""):
    """Create decorative finial at gable ridge peak."""
    # Check for finial data
    dec = params.get("decorative_elements", {})
    ridge_el = None
    if isinstance(dec, dict):
        ridge_el = dec.get("ridge_element", dec.get("finial", {}))

    # Also check roof_features
    if not ridge_el:
        rf = params.get("roof_features", [])
        for f in rf:
            if isinstance(f, dict) and ("finial" in str(f.get("type", "")).lower() or
                                         "ridge" in str(f.get("type", "")).lower()):
                ridge_el = f
                break

    if not ridge_el or not isinstance(ridge_el, dict):
        return []

    pitch = params.get("roof_pitch_deg", 35)
    ridge_height = (width / 2) * _safe_tan(pitch)

    finial_h = ridge_el.get("height_m", 0.3)
    finial_hex = ridge_el.get("colour_hex", "#4A4A4A")
    if isinstance(finial_hex, str) and not finial_hex.startswith("#"):
        finial_hex = colour_name_to_hex(str(finial_hex))

    mat = get_or_create_material(f"mat_finial_{finial_hex.lstrip('#')}", colour_hex=finial_hex, roughness=0.4)

    objects = []

    # Front gable finial — cone + sphere at ridge peak
    peak_z = wall_h + ridge_height

    # Cone/spike
    bpy.ops.mesh.primitive_cone_add(radius1=0.06, radius2=0.01, depth=finial_h, vertices=8)
    cone = bpy.context.active_object
    cone.name = f"finial_{bldg_id}"
    cone.location = (0, 0, peak_z + finial_h / 2)
    assign_material(cone, mat)
    objects.append(cone)

    # Small ball on top
    bpy.ops.mesh.primitive_uv_sphere_add(radius=0.04, segments=8, ring_count=6)
    ball = bpy.context.active_object
    ball.name = f"finial_ball_{bldg_id}"
    ball.location = (0, 0, peak_z + finial_h + 0.02)
    assign_material(ball, mat)
    objects.append(ball)

    return objects



def create_voussoirs(params, wall_h, facade_width, bldg_id=""):
    """Create voussoir (wedge-shaped arch stones) around arched window openings."""
    windows_detail = get_effective_windows_detail(params)
    floor_heights = params.get("floor_heights_m", [3.0])
    trim_hex = get_trim_hex(params)

    # Check if building explicitly has voussoirs (contrasting stone arch details)
    dec = params.get("decorative_elements", {})
    has_voussoirs = False
    stone_hex = trim_hex
    if isinstance(dec, dict):
        vous = dec.get("voussoirs", {})
        if isinstance(vous, dict) and vous.get("present", False):
            has_voussoirs = True
            stone_hex = vous.get("colour_hex", vous.get("material_hex", trim_hex))
            if not stone_hex.startswith("#"):
                stone_hex = colour_name_to_hex(stone_hex)
        # Also check stone_voussoirs key (used by 20 Denison)
        sv = dec.get("stone_voussoirs", {})
        if isinstance(sv, dict) and sv.get("present", False):
            has_voussoirs = True
            stone_hex = sv.get("colour_hex", trim_hex)
            if not stone_hex.startswith("#"):
                stone_hex = colour_name_to_hex(stone_hex)

    # Don't generate voussoirs if explicitly disabled or not present
    if not has_voussoirs:
        return []

    mat = create_stone_material(f"mat_voussoir_{stone_hex.lstrip('#')}", stone_hex)
    objects = []

    for fd in windows_detail:
        if not isinstance(fd, dict):
            continue

        floor_idx = int(_normalize_floor_index(fd.get("floor", 1), floor_heights))
        z_base = sum(floor_heights[:max(0, floor_idx - 1)])

        wins = fd.get("windows", [])
        for w in wins:
            if not isinstance(w, dict):
                continue

            count = w.get("count", 1)
            win_w = w.get("width_m", 0.8)
            win_h = w.get("height_m", 1.3)
            sill_h = w.get("sill_height_m", 0.8)
            arch_type = str(w.get("arch_type", w.get("head_shape", "flat"))).lower()

            spacing = facade_width / (count + 1)
            for ci in range(count):
                cx = -facade_width / 2 + spacing * (ci + 1)
                win_top_z = z_base + sill_h + win_h

                if "segmental" in arch_type or "round" in arch_type or "semi" in arch_type:
                    # Full arched voussoir ring
                    num_stones = 9
                    radius = win_w / 2 + 0.04
                    stone_w = 0.08
                    stone_d = 0.12
                    for si in range(num_stones):
                        angle = math.pi * si / (num_stones - 1)
                        sx = cx + radius * math.cos(angle)
                        sz = win_top_z - win_w / 2 + radius * math.sin(angle)

                        bpy.ops.mesh.primitive_cube_add(size=1)
                        stone = bpy.context.active_object
                        stone.name = f"voussoir_{bldg_id}_{floor_idx}_{ci}_{si}"
                        stone.scale = (stone_w, stone_d, 0.06)
                        stone.location = (sx, 0.16, sz)
                        stone.rotation_euler.y = -(angle - math.pi / 2)
                        assign_material(stone, mat)
                        objects.append(stone)
                else:
                    # Flat brick voussoirs — row of angled bricks above window
                    num_bricks = max(5, int(win_w / 0.08))
                    brick_w = win_w / num_bricks
                    brick_h = 0.10
                    for bi in range(num_bricks):
                        bx = cx - win_w / 2 + brick_w / 2 + bi * brick_w
                        # Fan angle: bricks angle from center outward
                        fan_angle = (bi - num_bricks / 2) / num_bricks * 0.3

                        bpy.ops.mesh.primitive_cube_add(size=1)
                        brick = bpy.context.active_object
                        brick.name = f"voussoir_flat_{bldg_id}_{floor_idx}_{ci}_{bi}"
                        brick.scale = (brick_w - 0.003, 0.06, brick_h)
                        bpy.ops.object.transform_apply(scale=True)
                        brick.location = (bx, 0.03, win_top_z + brick_h / 2 + 0.01)
                        brick.rotation_euler.y = fan_angle
                        assign_material(brick, mat)
                        objects.append(brick)

    return objects



def create_gable_shingles(params, wall_h, width, depth, bldg_id=""):
    """Create fish-scale ornamental shingle infill in gable triangle."""
    dec = params.get("decorative_elements", {})
    if not isinstance(dec, dict):
        return []

    shingles = dec.get("ornamental_shingles", {})
    if not isinstance(shingles, dict) or not shingles:
        # Also check roof features
        rf = params.get("roof_features", [])
        for f in rf:
            if isinstance(f, dict):
                infill = f.get("ornamental_shingle_infill", {})
                if isinstance(infill, dict) and infill:
                    shingles = infill
                    break

    if not shingles:
        return []

    shingle_hex = shingles.get("colour_hex", None)
    if not shingle_hex:
        colour = str(shingles.get("colour", "")).lower()
        shingle_hex = get_facade_hex(params)  # default to facade colour

    pitch = params.get("roof_pitch_deg", 35)
    half_w = width / 2
    ridge_h = half_w * _safe_tan(pitch)

    mat = get_or_create_material(f"mat_shingle_{shingle_hex.lstrip('#')}", colour_hex=shingle_hex, roughness=0.7)

    objects = []
    exposure = shingles.get("exposure_mm", 100) / 1000.0  # convert to metres
    shingle_radius = exposure * 0.6

    # Fill gable triangle with rows of half-round shingles
    # Start above any gable window and go up to near the peak
    start_z = wall_h + ridge_h * 0.35  # above gable window
    end_z = wall_h + ridge_h * 0.92   # near peak

    row = 0
    z = start_z
    while z < end_z:
        # Width at this height (narrowing triangle)
        frac = (z - wall_h) / ridge_h
        row_half_w = half_w * (1.0 - frac) - 0.1  # inset from rake edge

        if row_half_w < shingle_radius * 2:
            break

        # Place shingles across the row
        x = -row_half_w
        col = 0
        # Offset every other row
        offset_x = shingle_radius if (row % 2) else 0
        x += offset_x

        while x < row_half_w:
            bpy.ops.mesh.primitive_uv_sphere_add(
                radius=shingle_radius, segments=8, ring_count=4,
                location=(x, 0.16, z)
            )
            sh = bpy.context.active_object
            sh.name = f"shingle_{bldg_id}_{row}_{col}"
            sh.scale.y = 0.3  # flatten into the wall
            sh.scale.z = 0.8  # slightly oval
            assign_material(sh, mat)
            objects.append(sh)
            x += shingle_radius * 1.8
            col += 1

        z += exposure
        row += 1

    return objects



def create_dormer(params, wall_h, width, depth, bldg_id=""):
    """Create a gable dormer on a flat or sloped roof."""
    dormer_data = params.get("dormer", {})
    if not isinstance(dormer_data, dict) or not dormer_data:
        return []

    d_type = str(dormer_data.get("type", "gable")).lower()
    d_count = dormer_data.get("count", 1)
    d_w = dormer_data.get("width_m", 2.0)
    d_h = dormer_data.get("height_m", 2.5)
    d_pitch = dormer_data.get("gable_pitch_deg", 45)
    d_depth = d_w * 0.8  # dormer depth proportional to width

    # Dormer wall material
    wall_col = str(dormer_data.get("wall_colour", "")).lower()
    if wall_col:
        d_wall_hex = colour_name_to_hex(wall_col)
    else:
        d_wall_hex = get_facade_hex(params)

    roof_col = str(dormer_data.get("roof_colour", "dark_grey")).lower()
    d_roof_hex = colour_name_to_hex(roof_col) if roof_col else "#3A3A3A"

    trim_hex = get_trim_hex(params)

    objects = []

    for di in range(d_count):
        # Position dormer(s) along the roof
        if d_count == 1:
            dx = 0
        else:
            spacing = width / (d_count + 1)
            dx = -width / 2 + spacing * (di + 1)

        # Dormer sits on the roof surface — for flat roofs, at wall_h
        # For pitched roofs, partway up the slope
        roof_type = str(params.get("roof_type", "")).lower()
        if "flat" in roof_type:
            dz_base = wall_h
        else:
            pitch = params.get("roof_pitch_deg", 35)
            dz_base = wall_h + (width / 2) * _safe_tan(pitch) * 0.3

        dy = -depth * 0.3  # set back from front

        # Dormer front wall (cheek walls)
        wall_mat = create_brick_material(f"mat_dormer_wall_{d_wall_hex.lstrip('#')}",
                                          d_wall_hex)

        bpy.ops.mesh.primitive_cube_add(size=1)
        front_wall = bpy.context.active_object
        front_wall.name = f"dormer_wall_{bldg_id}_{di}"
        front_wall.scale = (d_w, 0.15, d_h * 0.6)
        bpy.ops.object.transform_apply(scale=True)
        front_wall.location = (dx, dy + d_depth / 2, dz_base + d_h * 0.3)
        assign_material(front_wall, wall_mat)
        objects.append(front_wall)

        # Left cheek wall
        bpy.ops.mesh.primitive_cube_add(size=1)
        lw = bpy.context.active_object
        lw.name = f"dormer_cheek_L_{bldg_id}_{di}"
        lw.scale = (0.12, d_depth, d_h * 0.6)
        bpy.ops.object.transform_apply(scale=True)
        lw.location = (dx - d_w / 2, dy, dz_base + d_h * 0.3)
        assign_material(lw, wall_mat)
        objects.append(lw)

        # Right cheek wall
        bpy.ops.mesh.primitive_cube_add(size=1)
        rw = bpy.context.active_object
        rw.name = f"dormer_cheek_R_{bldg_id}_{di}"
        rw.scale = (0.12, d_depth, d_h * 0.6)
        bpy.ops.object.transform_apply(scale=True)
        rw.location = (dx + d_w / 2, dy, dz_base + d_h * 0.3)
        assign_material(rw, wall_mat)
        objects.append(rw)

        # Dormer roof
        top_z = dz_base + d_h * 0.6

        if "turret" in d_type:
            # Conical turret roof (octagonal cone)
            cone_h = d_w * 0.6
            bpy.ops.mesh.primitive_cone_add(
                vertices=8,
                radius1=d_w / 2 + 0.05,
                radius2=0.0,
                depth=cone_h
            )
            cone = bpy.context.active_object
            cone.name = f"dormer_turret_{bldg_id}_{di}"
            cone.location = (dx, dy, top_z + cone_h / 2)
            d_roof_mat = create_roof_material(f"mat_droof_{d_roof_hex.lstrip('#')}", d_roof_hex)
            assign_material(cone, d_roof_mat)
            objects.append(cone)
        elif "shed" in d_type:
            # Shed dormer — single slope from front (high) to back (low)
            shed_rise = d_depth * _safe_tan(min(d_pitch, 25))
            bm = bmesh.new()
            hw = d_w / 2 + 0.05
            y_f = dy + d_depth / 2 + 0.05
            y_b = dy - d_depth / 2 - 0.05

            # Front edge is higher, back edge meets main roof
            v0 = bm.verts.new((-hw + dx, y_b, top_z))
            v1 = bm.verts.new((hw + dx, y_b, top_z))
            v2 = bm.verts.new((hw + dx, y_f, top_z + shed_rise))
            v3 = bm.verts.new((-hw + dx, y_f, top_z + shed_rise))

            bm.faces.new([v0, v1, v2, v3])  # single slope

            d_mesh = bpy.data.meshes.new(f"dormer_shed_roof_{di}")
            bm.to_mesh(d_mesh)
            bm.free()

            d_roof_obj = bpy.data.objects.new(f"dormer_shed_roof_{bldg_id}_{di}", d_mesh)
            bpy.context.collection.objects.link(d_roof_obj)

            mod = d_roof_obj.modifiers.new("Solidify", 'SOLIDIFY')
            mod.thickness = 0.05
            mod.offset = -1
            bpy.context.view_layer.objects.active = d_roof_obj
            bpy.ops.object.modifier_apply(modifier=mod.name)

            d_roof_mat = create_roof_material(f"mat_droof_{d_roof_hex.lstrip('#')}", d_roof_hex)
            assign_material(d_roof_obj, d_roof_mat)
            objects.append(d_roof_obj)
        elif "hip" in d_type:
            # Hipped dormer — four-sided roof with ridgeline shorter than base
            d_ridge = (d_w / 2) * _safe_tan(d_pitch) * 0.7
            bm = bmesh.new()
            hw = d_w / 2 + 0.05
            y_f = dy + d_depth / 2 + 0.05
            y_b = dy - d_depth / 2 - 0.05
            ridge_inset = d_depth * 0.3  # hip ridgeline shorter than base

            v0 = bm.verts.new((-hw + dx, y_b, top_z))
            v1 = bm.verts.new((hw + dx, y_b, top_z))
            v2 = bm.verts.new((hw + dx, y_f, top_z))
            v3 = bm.verts.new((-hw + dx, y_f, top_z))
            # Ridge endpoints inset from front/back
            v4 = bm.verts.new((dx, y_b + ridge_inset, top_z + d_ridge))
            v5 = bm.verts.new((dx, y_f - ridge_inset, top_z + d_ridge))

            bm.faces.new([v0, v3, v5, v4])  # left slope
            bm.faces.new([v1, v4, v5, v2])  # right slope
            bm.faces.new([v2, v5, v3])      # front hip triangle
            bm.faces.new([v0, v4, v1])      # back hip triangle

            d_mesh = bpy.data.meshes.new(f"dormer_hip_roof_{di}")
            bm.to_mesh(d_mesh)
            bm.free()

            d_roof_obj = bpy.data.objects.new(f"dormer_hip_roof_{bldg_id}_{di}", d_mesh)
            bpy.context.collection.objects.link(d_roof_obj)

            mod = d_roof_obj.modifiers.new("Solidify", 'SOLIDIFY')
            mod.thickness = 0.05
            mod.offset = -1
            bpy.context.view_layer.objects.active = d_roof_obj
            bpy.ops.object.modifier_apply(modifier=mod.name)

            d_roof_mat = create_roof_material(f"mat_droof_{d_roof_hex.lstrip('#')}", d_roof_hex)
            assign_material(d_roof_obj, d_roof_mat)
            objects.append(d_roof_obj)
        else:
            # Standard gable roof (default)
            d_ridge = (d_w / 2) * _safe_tan(d_pitch)
            bm = bmesh.new()
            hw = d_w / 2 + 0.05
            y_f = dy + d_depth / 2 + 0.05
            y_b = dy - d_depth / 2 - 0.05

            v0 = bm.verts.new((-hw + dx, y_b, top_z))
            v1 = bm.verts.new((hw + dx, y_b, top_z))
            v2 = bm.verts.new((hw + dx, y_f, top_z))
            v3 = bm.verts.new((-hw + dx, y_f, top_z))
            v4 = bm.verts.new((dx, y_b, top_z + d_ridge))
            v5 = bm.verts.new((dx, y_f, top_z + d_ridge))

            bm.faces.new([v0, v3, v5, v4])  # left slope
            bm.faces.new([v1, v4, v5, v2])  # right slope
            bm.faces.new([v2, v5, v3])      # front triangle
            bm.faces.new([v0, v4, v1])      # back triangle

            d_mesh = bpy.data.meshes.new(f"dormer_roof_{di}")
            bm.to_mesh(d_mesh)
            bm.free()

            d_roof_obj = bpy.data.objects.new(f"dormer_roof_{bldg_id}_{di}", d_mesh)
            bpy.context.collection.objects.link(d_roof_obj)

            # Solidify
            mod = d_roof_obj.modifiers.new("Solidify", 'SOLIDIFY')
            mod.thickness = 0.05
            mod.offset = -1
            bpy.context.view_layer.objects.active = d_roof_obj
            bpy.ops.object.modifier_apply(modifier=mod.name)

            d_roof_mat = create_roof_material(f"mat_droof_{d_roof_hex.lstrip('#')}", d_roof_hex)
            assign_material(d_roof_obj, d_roof_mat)
            objects.append(d_roof_obj)

        # Dormer window
        gwin = dormer_data.get("gable_window", {})
        if isinstance(gwin, dict):
            gw_w = gwin.get("width_m", 0.6)
            gw_h = gwin.get("height_m", 0.7)

            # Glass pane
            bpy.ops.mesh.primitive_cube_add(size=1)
            glass = bpy.context.active_object
            glass.name = f"dormer_glass_{bldg_id}_{di}"
            glass.scale = (gw_w, 0.02, gw_h)
            bpy.ops.object.transform_apply(scale=True)
            glass.location = (dx, dy + d_depth / 2 + 0.08, dz_base + d_h * 0.3)
            glass_mat = create_glass_material()
            assign_material(glass, glass_mat)
            objects.append(glass)

            # Frame
            frame_col = str(gwin.get("frame_colour", "white")).lower()
            frame_hex = colour_name_to_hex(frame_col) if frame_col else trim_hex
            frame_mat = get_or_create_material(f"mat_dframe_{frame_hex.lstrip('#')}",
                                                colour_hex=frame_hex, roughness=0.5)
            frame_thick = 0.04
            for fname, fscale, floc in [
                ("top", (gw_w + frame_thick * 2, 0.03, frame_thick),
                 (dx, dy + d_depth / 2 + 0.08, dz_base + d_h * 0.3 + gw_h / 2)),
                ("bot", (gw_w + frame_thick * 2, 0.03, frame_thick),
                 (dx, dy + d_depth / 2 + 0.08, dz_base + d_h * 0.3 - gw_h / 2)),
                ("left", (frame_thick, 0.03, gw_h),
                 (dx - gw_w / 2 - frame_thick / 2, dy + d_depth / 2 + 0.08, dz_base + d_h * 0.3)),
                ("right", (frame_thick, 0.03, gw_h),
                 (dx + gw_w / 2 + frame_thick / 2, dy + d_depth / 2 + 0.08, dz_base + d_h * 0.3)),
            ]:
                bpy.ops.mesh.primitive_cube_add(size=1)
                fr = bpy.context.active_object
                fr.name = f"dormer_frame_{fname}_{bldg_id}_{di}"
                fr.scale = fscale
                bpy.ops.object.transform_apply(scale=True)
                fr.location = floc
                assign_material(fr, frame_mat)
                objects.append(fr)

    return objects



def create_fascia_boards(params, wall_h, width, depth, bldg_id=""):
    """Create fascia and soffit boards along eaves and rakes of gable roofs."""
    roof_type = str(params.get("roof_type", "gable")).lower()
    if "flat" in roof_type:
        return []

    trim_hex = get_trim_hex(params)
    # Check for fascia colour in params
    rd = params.get("roof_detail", {})
    fascia_hex = trim_hex
    if isinstance(rd, dict):
        fc = rd.get("fascia_colour_hex", "")
        if fc and fc.startswith("#"):
            fascia_hex = fc

    mat = create_wood_material(f"mat_fascia_{fascia_hex.lstrip('#')}", fascia_hex)

    pitch = params.get("roof_pitch_deg", 35)
    ridge_h = (width / 2) * _safe_tan(pitch)

    rd2 = params.get("roof_detail", {})
    eave_mm = 300
    if isinstance(rd2, dict):
        eave_mm = rd2.get("eave_overhang_mm", 300)
    else:
        eave_mm = params.get("eave_overhang_mm", 300)
    overhang_eave = eave_mm / 1000.0
    overhang_side = overhang_eave * 0.5
    half_w = width / 2 + overhang_side

    fascia_h = 0.12  # fascia board height
    fascia_d = 0.025  # fascia board thickness

    objects = []

    # Eave fascia — front horizontal board
    bpy.ops.mesh.primitive_cube_add(size=1)
    f_front = bpy.context.active_object
    f_front.name = f"fascia_front_{bldg_id}"
    f_front.scale = (half_w * 2, fascia_d, fascia_h)
    bpy.ops.object.transform_apply(scale=True)
    f_front.location = (0, overhang_eave, wall_h - fascia_h)
    assign_material(f_front, mat)
    objects.append(f_front)

    # Eave fascia — back
    bpy.ops.mesh.primitive_cube_add(size=1)
    f_back = bpy.context.active_object
    f_back.name = f"fascia_back_{bldg_id}"
    f_back.scale = (half_w * 2, fascia_d, fascia_h)
    bpy.ops.object.transform_apply(scale=True)
    f_back.location = (0, -depth - overhang_eave, wall_h - fascia_h)
    assign_material(f_back, mat)
    objects.append(f_back)

    # Rake boards (along gable slope) — front gable, left and right
    rake_len = math.sqrt((width / 2 + overhang_side) ** 2 + ridge_h ** 2)
    rake_angle = math.atan2(ridge_h, width / 2 + overhang_side)

    for side, sign in [("L", -1), ("R", 1)]:
        bpy.ops.mesh.primitive_cube_add(size=1)
        rake = bpy.context.active_object
        rake.name = f"fascia_rake_{side}_{bldg_id}"
        rake.scale = (rake_len, fascia_d, fascia_h)
        bpy.ops.object.transform_apply(scale=True)
        # Position at midpoint of rake
        mid_x = sign * (width / 4 + overhang_side / 2)
        mid_z = wall_h + ridge_h / 2
        rake.location = (mid_x, overhang_eave + fascia_d, mid_z)
        rake.rotation_euler.y = sign * rake_angle
        assign_material(rake, mat)
        objects.append(rake)

    # Soffit boards (horizontal underside of overhang) — front
    bpy.ops.mesh.primitive_cube_add(size=1)
    soffit = bpy.context.active_object
    soffit.name = f"soffit_front_{bldg_id}"
    soffit.scale = (half_w * 2, overhang_eave, 0.015)
    bpy.ops.object.transform_apply(scale=True)
    soffit.location = (0, overhang_eave / 2, wall_h - fascia_h)
    soffit_mat = get_or_create_material("mat_soffit", colour_hex="#E8E0D0", roughness=0.6)
    assign_material(soffit, soffit_mat)
    objects.append(soffit)

    # Soffit — back
    bpy.ops.mesh.primitive_cube_add(size=1)
    soffit_b = bpy.context.active_object
    soffit_b.name = f"soffit_back_{bldg_id}"
    soffit_b.scale = (half_w * 2, overhang_eave, 0.015)
    bpy.ops.object.transform_apply(scale=True)
    soffit_b.location = (0, -depth - overhang_eave / 2, wall_h - fascia_h)
    assign_material(soffit_b, soffit_mat)
    objects.append(soffit_b)

    return objects



def create_parapet_coping(params, wall_h, width, depth, bldg_id=""):
    """Create parapet walls with metal coping cap for flat-roofed buildings."""
    roof_type = str(params.get("roof_type", "")).lower()
    if "flat" not in roof_type:
        return []

    # Get parapet dimensions
    rd = params.get("roof_detail", {})
    parapet_h = 0.3
    parapet_material = "brick"
    coping = True

    if isinstance(rd, dict):
        parapet_h = rd.get("parapet_height_mm", 300) / 1000.0
        parapet_material = str(rd.get("parapet_material", "brick")).lower()
        if rd.get("parapet") is False:
            return []
    else:
        # Check top-level cornice
        cornice = params.get("cornice", {})
        if isinstance(cornice, dict):
            parapet_h = cornice.get("height_mm", 300) / 1000.0

    facade_hex = get_facade_hex(params)
    wall_thick = 0.2

    if "brick" in parapet_material:
        parapet_mat = create_brick_material(f"mat_parapet_{facade_hex.lstrip('#')}",
                                             facade_hex)
    else:
        parapet_mat = get_or_create_material(f"mat_parapet_{facade_hex.lstrip('#')}",
                                              colour_hex=facade_hex)

    coping_mat = get_or_create_material("mat_coping", colour_hex="#8A8A8A", roughness=0.3)

    objects = []

    # Four parapet walls
    segments = [
        ("front", (width, wall_thick, parapet_h), (0, 0, wall_h + parapet_h / 2)),
        ("back", (width, wall_thick, parapet_h), (0, -depth, wall_h + parapet_h / 2)),
        ("left", (wall_thick, depth, parapet_h), (-width / 2, -depth / 2, wall_h + parapet_h / 2)),
        ("right", (wall_thick, depth, parapet_h), (width / 2, -depth / 2, wall_h + parapet_h / 2)),
    ]

    for name, scale, loc in segments:
        bpy.ops.mesh.primitive_cube_add(size=1)
        pw = bpy.context.active_object
        pw.name = f"parapet_{name}_{bldg_id}"
        pw.scale = scale
        bpy.ops.object.transform_apply(scale=True)
        pw.location = loc
        assign_material(pw, parapet_mat)
        objects.append(pw)

    # Metal coping cap on top of parapet
    coping_h = 0.04
    coping_overhang = 0.03
    coping_segments = [
        ("front", (width + coping_overhang * 2, wall_thick + coping_overhang * 2, coping_h),
         (0, 0, wall_h + parapet_h + coping_h / 2)),
        ("back", (width + coping_overhang * 2, wall_thick + coping_overhang * 2, coping_h),
         (0, -depth, wall_h + parapet_h + coping_h / 2)),
        ("left", (wall_thick + coping_overhang * 2, depth + wall_thick * 2 + coping_overhang * 2, coping_h),
         (-width / 2, -depth / 2, wall_h + parapet_h + coping_h / 2)),
        ("right", (wall_thick + coping_overhang * 2, depth + wall_thick * 2 + coping_overhang * 2, coping_h),
         (width / 2, -depth / 2, wall_h + parapet_h + coping_h / 2)),
    ]

    for name, scale, loc in coping_segments:
        bpy.ops.mesh.primitive_cube_add(size=1)
        cap = bpy.context.active_object
        cap.name = f"coping_{name}_{bldg_id}"
        cap.scale = scale
        bpy.ops.object.transform_apply(scale=True)
        cap.location = loc
        assign_material(cap, coping_mat)
        objects.append(cap)

    return objects



def create_gabled_parapet(params, wall_h, width, depth, bldg_id=""):
    """Create a gabled parapet — a decorative wall extending above roofline at the facade."""
    rd = params.get("roof_detail", {})
    gp = None
    if isinstance(rd, dict):
        gp = rd.get("gabled_parapet", {})
    if not isinstance(gp, dict) or not gp.get("present", False):
        return []

    objects = []
    parapet_h = gp.get("height_m", 0.8)
    facade_hex = get_facade_hex(params)
    wall_mat = create_brick_material(f"mat_gparapet_{facade_hex.lstrip('#')}", facade_hex)

    # Triangular parapet wall at the front face, extending above the eave line
    # with a small gable peak centred on the facade
    half_w = width / 2
    peak_z = wall_h + parapet_h
    eave_z = wall_h
    wall_thick = 0.15

    bm = bmesh.new()
    # Front face vertices (triangular gable shape)
    v0 = bm.verts.new((-half_w, 0, eave_z))
    v1 = bm.verts.new((half_w, 0, eave_z))
    v2 = bm.verts.new((half_w, 0, eave_z + parapet_h * 0.3))
    v3 = bm.verts.new((0, 0, peak_z))
    v4 = bm.verts.new((-half_w, 0, eave_z + parapet_h * 0.3))

    # Back face vertices (offset by wall thickness)
    v5 = bm.verts.new((-half_w, -wall_thick, eave_z))
    v6 = bm.verts.new((half_w, -wall_thick, eave_z))
    v7 = bm.verts.new((half_w, -wall_thick, eave_z + parapet_h * 0.3))
    v8 = bm.verts.new((0, -wall_thick, peak_z))
    v9 = bm.verts.new((-half_w, -wall_thick, eave_z + parapet_h * 0.3))

    # Front face
    bm.faces.new([v0, v4, v3, v2, v1])
    # Back face
    bm.faces.new([v5, v6, v7, v8, v9])
    # Top left slope
    bm.faces.new([v4, v9, v8, v3])
    # Top right slope
    bm.faces.new([v3, v8, v7, v2])
    # Left side
    bm.faces.new([v0, v5, v9, v4])
    # Right side
    bm.faces.new([v1, v2, v7, v6])
    # Bottom
    bm.faces.new([v0, v1, v6, v5])

    mesh = bpy.data.meshes.new(f"gabled_parapet_{bldg_id}")
    bm.to_mesh(mesh)
    bm.free()

    parapet_obj = bpy.data.objects.new(f"gabled_parapet_{bldg_id}", mesh)
    bpy.context.collection.objects.link(parapet_obj)
    assign_material(parapet_obj, wall_mat)
    objects.append(parapet_obj)

    # Optional coping strip along the gable edges
    trim_hex = get_trim_hex(params)
    coping_mat = get_or_create_material(f"mat_gp_coping_{trim_hex.lstrip('#')}",
                                         colour_hex=trim_hex, roughness=0.3)
    slope_len = math.sqrt((half_w) ** 2 + (parapet_h * 0.7) ** 2)
    slope_angle = math.atan2(parapet_h * 0.7, half_w)

    for side in (-1, 1):
        bpy.ops.mesh.primitive_cube_add(size=1)
        coping = bpy.context.active_object
        coping.name = f"gp_coping_{'L' if side == -1 else 'R'}_{bldg_id}"
        coping.scale = (slope_len, wall_thick + 0.02, 0.04)
        bpy.ops.object.transform_apply(scale=True)
        coping.location = (side * half_w / 2, -wall_thick / 2, eave_z + parapet_h * 0.3 + (parapet_h * 0.7) / 2)
        coping.rotation_euler = (0, side * slope_angle, 0)
        assign_material(coping, coping_mat)
        objects.append(coping)

    return objects



def create_window_shutters(params, wall_h, facade_width, bldg_id=""):
    """Create decorative shutters flanking windows (common Pre-1889 houses)."""
    dec = params.get("decorative_elements", {})
    if not isinstance(dec, dict):
        return []
    shutters = dec.get("shutters", {})
    if not isinstance(shutters, dict) or not shutters.get("present", False):
        return []

    shutter_hex = shutters.get("colour_hex", get_trim_hex(params))
    shutter_mat = get_or_create_material(f"mat_shutter_{shutter_hex.lstrip('#')}",
                                          colour_hex=shutter_hex, roughness=0.6)
    objects = []
    floor_heights = params.get("floor_heights_m", [3.0])
    windows_detail = get_effective_windows_detail(params)

    for fd in windows_detail:
        if not isinstance(fd, dict):
            continue
        floor_idx = int(_normalize_floor_index(fd.get("floor", 1), floor_heights))
        z_base = sum(floor_heights[:max(0, floor_idx - 1)])
        for w in fd.get("windows", []):
            if not isinstance(w, dict):
                continue
            count = w.get("count", 1)
            win_w = w.get("width_m", 0.85)
            win_h = w.get("height_m", 1.3)
            fi = max(0, min(floor_idx - 1, len(floor_heights) - 1))
            floor_h = floor_heights[fi] if floor_heights else 3.0
            sill_h = z_base + max(0.8, (floor_h - win_h) / 2)
            spacing = facade_width / (count + 1)
            for ci in range(count):
                cx = -facade_width / 2 + spacing * (ci + 1)
                # Left shutter
                for side, sx in [("L", cx - win_w / 2 - 0.06), ("R", cx + win_w / 2 + 0.06)]:
                    bpy.ops.mesh.primitive_cube_add(size=1)
                    sh = bpy.context.active_object
                    sh.name = f"shutter_{side}_{floor_idx}_{ci}_{bldg_id}"
                    sh.scale = (0.05, 0.02, win_h * 0.95)
                    bpy.ops.object.transform_apply(scale=True)
                    sh.location = (sx, 0.01, sill_h + win_h / 2)
                    assign_material(sh, shutter_mat)
                    objects.append(sh)
                    # Louver lines on shutter face
                    louver_count = int(win_h / 0.08)
                    for li in range(louver_count):
                        lz = sill_h + 0.04 + li * 0.08
                        bpy.ops.mesh.primitive_cube_add(size=1)
                        lv = bpy.context.active_object
                        lv.name = f"louver_{side}_{floor_idx}_{ci}_{li}"
                        lv.scale = (0.045, 0.005, 0.003)
                        bpy.ops.object.transform_apply(scale=True)
                        lv.location = (sx, 0.025, lz)
                        assign_material(lv, shutter_mat)
                        objects.append(lv)
    return objects



def create_address_plaque(params, facade_width, bldg_id=""):
    """Create a small address number plaque near the front door."""
    building_name = params.get("building_name", "")
    if not building_name:
        return []

    # Extract house number
    import re as _re
    m = _re.match(r"(\d+[A-Za-z]?)", building_name)
    if not m:
        return []

    objects = []
    plaque_mat = get_or_create_material("mat_plaque", colour_hex="#2A2A2A", roughness=0.3)

    # Position near the door — right side, at eye height
    plaque_x = min(facade_width / 4, 1.0)
    plaque_z = 2.0  # eye height

    # Plaque backing
    bpy.ops.mesh.primitive_cube_add(size=1)
    plaque = bpy.context.active_object
    plaque.name = f"address_plaque_{bldg_id}"
    plaque.scale = (0.2, 0.015, 0.12)
    bpy.ops.object.transform_apply(scale=True)
    plaque.location = (plaque_x, 0.015, plaque_z)
    assign_material(plaque, plaque_mat)
    objects.append(plaque)

    return objects



def create_utility_box(params, facade_width, bldg_id=""):
    """Create a utility meter box on the facade — ubiquitous in Kensington."""
    objects = []
    # Only add on residential buildings
    ctx = params.get("context", {})
    if ctx.get("building_type") == "institutional":
        return []

    box_mat = get_or_create_material("mat_utility_box", colour_hex="#8A8A8A", roughness=0.4)
    _bsdf = box_mat.node_tree.nodes.get("Principled BSDF")
    if _bsdf and "Metallic" in _bsdf.inputs:
        _bsdf.inputs["Metallic"].default_value = 0.70

    # Position: low on facade, to one side
    box_x = facade_width / 3
    box_z = 1.2

    bpy.ops.mesh.primitive_cube_add(size=1)
    box = bpy.context.active_object
    box.name = f"utility_meter_{bldg_id}"
    box.scale = (0.3, 0.12, 0.4)
    bpy.ops.object.transform_apply(scale=True)
    box.location = (box_x, 0.06, box_z)
    assign_material(box, box_mat)
    objects.append(box)

    # Conduit pipe running up from box
    pipe_mat = get_or_create_material("mat_conduit", colour_hex="#6A6A6A", roughness=0.3)
    _bsdf = pipe_mat.node_tree.nodes.get("Principled BSDF")
    if _bsdf and "Metallic" in _bsdf.inputs:
        _bsdf.inputs["Metallic"].default_value = 0.80
    bpy.ops.mesh.primitive_cylinder_add(radius=0.015, depth=1.5, vertices=6)
    pipe = bpy.context.active_object
    pipe.name = f"utility_conduit_{bldg_id}"
    pipe.location = (box_x + 0.1, 0.03, box_z + 0.2 + 0.75)
    assign_material(pipe, pipe_mat)
    objects.append(pipe)

    return objects



def create_window_frames(params, wall_h, facade_width, bldg_id=""):
    """Create visible window frame surrounds (trim boards) around each window opening."""
    windows_detail = get_effective_windows_detail(params)
    floor_heights = params.get("floor_heights_m", [3.0])
    if not windows_detail:
        return []

    trim_hex = get_trim_hex(params)
    frame_mat = get_or_create_material(f"mat_window_frame_{trim_hex.lstrip('#')}",
                                        colour_hex=trim_hex, roughness=0.5)
    objects = []
    frame_w = 0.05  # frame width
    frame_d = 0.03  # frame depth/projection

    for fd in windows_detail:
        if not isinstance(fd, dict):
            continue
        floor_idx = int(_normalize_floor_index(fd.get("floor", 1), floor_heights))
        z_base = sum(floor_heights[:max(0, floor_idx - 1)])

        for w in fd.get("windows", []):
            if not isinstance(w, dict):
                continue
            count = w.get("count", 1)
            if count == 0:
                continue
            win_w = w.get("width_m", 0.85)
            win_h = w.get("height_m", 1.3)
            fi = max(0, min(floor_idx - 1, len(floor_heights) - 1))
            floor_h = floor_heights[fi] if floor_heights else 3.0
            sill_h = z_base + max(0.8, (floor_h - win_h) / 2)

            spacing = facade_width / (count + 1)
            for ci in range(count):
                cx = -facade_width / 2 + spacing * (ci + 1)
                z_mid = sill_h + win_h / 2

                # Top frame (header)
                bpy.ops.mesh.primitive_cube_add(size=1)
                top = bpy.context.active_object
                top.name = f"frame_top_{floor_idx}_{ci}_{bldg_id}"
                top.scale = (win_w + frame_w * 2, frame_d, frame_w)
                bpy.ops.object.transform_apply(scale=True)
                top.location = (cx, frame_d / 2, sill_h + win_h + frame_w / 2)
                assign_material(top, frame_mat)
                objects.append(top)

                # Bottom frame
                bpy.ops.mesh.primitive_cube_add(size=1)
                bot = bpy.context.active_object
                bot.name = f"frame_bot_{floor_idx}_{ci}_{bldg_id}"
                bot.scale = (win_w + frame_w * 2, frame_d, frame_w)
                bpy.ops.object.transform_apply(scale=True)
                bot.location = (cx, frame_d / 2, sill_h - frame_w / 2)
                assign_material(bot, frame_mat)
                objects.append(bot)

                # Left side frame
                bpy.ops.mesh.primitive_cube_add(size=1)
                left = bpy.context.active_object
                left.name = f"frame_left_{floor_idx}_{ci}_{bldg_id}"
                left.scale = (frame_w, frame_d, win_h)
                bpy.ops.object.transform_apply(scale=True)
                left.location = (cx - win_w / 2 - frame_w / 2, frame_d / 2, z_mid)
                assign_material(left, frame_mat)
                objects.append(left)

                # Right side frame
                bpy.ops.mesh.primitive_cube_add(size=1)
                right = bpy.context.active_object
                right.name = f"frame_right_{floor_idx}_{ci}_{bldg_id}"
                right.scale = (frame_w, frame_d, win_h)
                bpy.ops.object.transform_apply(scale=True)
                right.location = (cx + win_w / 2 + frame_w / 2, frame_d / 2, z_mid)
                assign_material(right, frame_mat)
                objects.append(right)

                # Meeting rail — horizontal bar at mid-height (double-hung windows)
                win_type = str(w.get("type", "double_hung")).lower()
                if "double" in win_type or "hung" in win_type:
                    bpy.ops.mesh.primitive_cube_add(size=1)
                    rail = bpy.context.active_object
                    rail.name = f"frame_meeting_{floor_idx}_{ci}_{bldg_id}"
                    rail.scale = (win_w, frame_d, 0.025)
                    bpy.ops.object.transform_apply(scale=True)
                    rail.location = (cx, frame_d / 2 + 0.005, z_mid)
                    assign_material(rail, frame_mat)
                    objects.append(rail)

    return objects



def create_downpipe_brackets(params, wall_h, width, bldg_id=""):
    """Create small wall brackets holding downspout pipes."""
    party_left = params.get("party_wall_left", False)
    party_right = params.get("party_wall_right", False)
    roof_type = str(params.get("roof_type", "gable")).lower()
    if "flat" in roof_type:
        return []

    bracket_mat = get_or_create_material("mat_pipe_bracket", colour_hex="#4A4A4A", roughness=0.4)
    _bsdf = bracket_mat.node_tree.nodes.get("Principled BSDF")
    if _bsdf and "Metallic" in _bsdf.inputs:
        _bsdf.inputs["Metallic"].default_value = 0.75
    objects = []
    hw = width / 2

    rd = params.get("roof_detail", {})
    overhang = (rd.get("eave_overhang_mm", 300) if isinstance(rd, dict) else 300) / 1000.0

    positions = []
    if not party_left:
        positions.append(-hw - 0.02)
    if not party_right:
        positions.append(hw + 0.02)

    for sx in positions:
        # Brackets at regular intervals up the wall
        bracket_z = 0.5
        while bracket_z < wall_h - 0.3:
            bpy.ops.mesh.primitive_cube_add(size=1)
            br = bpy.context.active_object
            br.name = f"pipe_bracket_{bldg_id}_{int(bracket_z*10)}"
            br.scale = (0.06, 0.04, 0.02)
            bpy.ops.object.transform_apply(scale=True)
            br.location = (sx, overhang + 0.02, bracket_z)
            assign_material(br, bracket_mat)
            objects.append(br)
            bracket_z += 1.5

    return objects



def create_balconies(params, wall_h, facade_width, bldg_id=""):
    """Create balconies — projecting platforms with railings on upper floors."""
    balcony_type = str(params.get("balcony_type", "")).lower()
    balcony_count = params.get("balconies", 0)
    if isinstance(balcony_count, dict):
        balcony_count = balcony_count.get("count", 0)
    if not balcony_type and not balcony_count:
        return []
    if isinstance(balcony_count, bool):
        balcony_count = 1 if balcony_count else 0
    if not balcony_count or balcony_count < 1:
        balcony_count = 1

    floor_heights = params.get("floor_heights_m", [3.0, 3.0])
    if len(floor_heights) < 2:
        return []  # balconies need at least 2 floors

    objects = []
    trim_hex = get_trim_hex(params)
    rail_mat = get_or_create_material("mat_balcony_rail", colour_hex="#2A2A2A", roughness=0.3)
    _bsdf = rail_mat.node_tree.nodes.get("Principled BSDF")
    if _bsdf and "Metallic" in _bsdf.inputs:
        _bsdf.inputs["Metallic"].default_value = 0.90
    deck_mat = get_or_create_material(f"mat_balcony_deck_{trim_hex.lstrip('#')}",
                                       colour_hex="#6A6A6A", roughness=0.7)

    # Balcony at second floor level
    z_base = floor_heights[0]
    bal_w = min(facade_width * 0.5, 3.0)
    bal_proj = 1.0
    bal_thick = 0.08
    rail_h = 1.0

    for bi in range(min(balcony_count, 3)):
        if balcony_count == 1:
            bx = 0
        else:
            bx = -facade_width / 4 + (facade_width / 2) * bi / max(1, balcony_count - 1)

        # Deck slab
        bpy.ops.mesh.primitive_cube_add(size=1)
        deck = bpy.context.active_object
        deck.name = f"balcony_deck_{bi}_{bldg_id}"
        deck.scale = (bal_w, bal_proj, bal_thick)
        bpy.ops.object.transform_apply(scale=True)
        deck.location = (bx, bal_proj / 2, z_base - bal_thick / 2)
        assign_material(deck, deck_mat)
        objects.append(deck)

        # Underside bracket supports (two triangular brackets)
        bracket_mat = get_or_create_material("mat_balcony_bracket", colour_hex="#4A4A4A", roughness=0.5)
        for side, sx in [("L", bx - bal_w / 3), ("R", bx + bal_w / 3)]:
            bm = bmesh.new()
            v0 = bm.verts.new((sx - 0.03, 0, z_base - bal_thick))
            v1 = bm.verts.new((sx + 0.03, 0, z_base - bal_thick))
            v2 = bm.verts.new((sx + 0.03, bal_proj * 0.7, z_base - bal_thick))
            v3 = bm.verts.new((sx - 0.03, 0, z_base - bal_thick - 0.4))
            v4 = bm.verts.new((sx + 0.03, 0, z_base - bal_thick - 0.4))
            bm.faces.new([v0, v1, v2])
            bm.faces.new([v0, v3, v4, v1])
            bm.faces.new([v3, v0, v2])
            bm.faces.new([v1, v4, v2])
            bm.faces.new([v3, v2, v4])
            mesh = bpy.data.meshes.new(f"bal_bracket_{side}_{bi}")
            bm.to_mesh(mesh)
            bm.free()
            br_obj = bpy.data.objects.new(f"bal_bracket_{side}_{bi}_{bldg_id}", mesh)
            bpy.context.collection.objects.link(br_obj)
            assign_material(br_obj, bracket_mat)
            objects.append(br_obj)

        # Railing — front and sides
        # Front rail
        bpy.ops.mesh.primitive_cylinder_add(radius=0.02, depth=bal_w, vertices=8)
        fr = bpy.context.active_object
        fr.name = f"balcony_rail_front_{bi}_{bldg_id}"
        fr.rotation_euler.y = math.pi / 2
        fr.location = (bx, bal_proj, z_base + rail_h)
        assign_material(fr, rail_mat)
        objects.append(fr)

        # Side rails
        for side, sx in [("L", bx - bal_w / 2), ("R", bx + bal_w / 2)]:
            bpy.ops.mesh.primitive_cylinder_add(radius=0.02, depth=bal_proj, vertices=8)
            sr = bpy.context.active_object
            sr.name = f"balcony_rail_{side}_{bi}_{bldg_id}"
            sr.rotation_euler.x = math.pi / 2
            sr.location = (sx, bal_proj / 2, z_base + rail_h)
            assign_material(sr, rail_mat)
            objects.append(sr)

        # Vertical balusters on front
        num_bal = max(3, int(bal_w / 0.12))
        for vi in range(num_bal + 1):
            vx = bx - bal_w / 2 + (bal_w / num_bal) * vi
            bpy.ops.mesh.primitive_cylinder_add(radius=0.01, depth=rail_h, vertices=6)
            vb = bpy.context.active_object
            vb.name = f"balcony_baluster_{bi}_{vi}_{bldg_id}"
            vb.location = (vx, bal_proj, z_base + rail_h / 2)
            assign_material(vb, rail_mat)
            objects.append(vb)

    return objects



def create_decorative_brickwork(params, wall_h, width, depth, bldg_id=""):
    """Create decorative brick patterns — raised bands, diamond inserts, header courses."""
    dec = params.get("decorative_elements", {})
    if not isinstance(dec, dict):
        return []
    db = dec.get("decorative_brickwork", {})
    if not db:
        return []
    if isinstance(db, dict) and db.get("present") is False:
        return []

    objects = []
    facade_hex = get_facade_hex(params)
    # Decorative brick is same material but slightly darker/contrasting
    r, g, b = hex_to_rgb(facade_hex)
    contrast_hex = "#{:02X}{:02X}{:02X}".format(
        max(0, int(r * 0.7 * 255)), max(0, int(g * 0.65 * 255)), max(0, int(b * 0.6 * 255)))
    brick_mat = get_or_create_material(f"mat_dec_brick_{bldg_id}", colour_hex=contrast_hex, roughness=0.85)

    floor_heights = params.get("floor_heights_m", [3.0])

    # Decorative band between floors — soldier course (bricks turned on end)
    band_h = 0.065  # one brick height turned on end
    band_proj = 0.015
    z = 0
    for i, fh in enumerate(floor_heights[:-1]):
        z += fh
        bpy.ops.mesh.primitive_cube_add(size=1)
        band = bpy.context.active_object
        band.name = f"dec_brick_band_{i}_{bldg_id}"
        band.scale = (width + band_proj, band_proj * 2, band_h)
        bpy.ops.object.transform_apply(scale=True)
        band.location = (0, band_proj, z)
        assign_material(band, brick_mat)
        objects.append(band)

    # Diamond brick pattern in gable (if gable roof)
    roof_type = str(params.get("roof_type", "")).lower()
    diamond_count = 0
    if isinstance(db, dict):
        diamond_count = db.get("diamond_brick_count", 0)
        if not diamond_count and db.get("diamond_pattern"):
            diamond_count = 1
    if "gable" in roof_type and diamond_count > 0:
        pitch = params.get("roof_pitch_deg", 35)
        ridge_h = (width / 2) * _safe_tan(pitch)
        gable_center_z = wall_h + ridge_h * 0.4
        bpy.ops.mesh.primitive_cube_add(size=1)
        diamond = bpy.context.active_object
        diamond.name = f"dec_diamond_{bldg_id}"
        diamond.scale = (0.15, 0.02, 0.15)
        bpy.ops.object.transform_apply(scale=True)
        diamond.rotation_euler.y = math.pi / 4  # rotate 45 degrees
        diamond.location = (0, 0.02, gable_center_z)
        assign_material(diamond, brick_mat)
        objects.append(diamond)

    return objects



def create_pilasters(params, wall_h, width, depth, bldg_id=""):
    """Create pilasters — flat columns projecting from the facade."""
    dec = params.get("decorative_elements", {})
    if not isinstance(dec, dict):
        return []
    pil = dec.get("pilasters", {})
    if not isinstance(pil, dict) or not pil:
        return []

    objects = []
    pil_w = pil.get("width_mm", 200) / 1000
    pil_proj = pil.get("projection_mm", 40) / 1000
    pil_hex = pil.get("colour_hex", get_facade_hex(params))
    pil_mat = get_or_create_material(f"mat_pilaster_{pil_hex.lstrip('#')}", colour_hex=pil_hex, roughness=0.8)

    # Default: pilasters flanking the facade
    count = pil.get("count", 2)
    hw = width / 2

    if count == 2:
        positions = [(-hw + pil_w / 2, "pilaster_left"), (hw - pil_w / 2, "pilaster_right")]
    elif count == 4:
        third = width / 3
        positions = [
            (-hw + pil_w / 2, "pilaster_far_left"),
            (-third / 2, "pilaster_inner_left"),
            (third / 2, "pilaster_inner_right"),
            (hw - pil_w / 2, "pilaster_far_right"),
        ]
    else:
        spacing = width / max(1, count - 1)
        positions = [(-hw + spacing * i, f"pilaster_{i}") for i in range(count)]

    for x, name in positions:
        # Main shaft
        bpy.ops.mesh.primitive_cube_add(size=1)
        shaft = bpy.context.active_object
        shaft.name = f"{name}_{bldg_id}"
        shaft.scale = (pil_w, pil_proj, wall_h - 0.2)
        bpy.ops.object.transform_apply(scale=True)
        shaft.location = (x, pil_proj / 2, wall_h / 2)
        assign_material(shaft, pil_mat)
        objects.append(shaft)

        # Capital (top detail) — wider flared top
        bpy.ops.mesh.primitive_cube_add(size=1)
        cap = bpy.context.active_object
        cap.name = f"{name}_cap_{bldg_id}"
        cap.scale = (pil_w + 0.04, pil_proj + 0.02, 0.08)
        bpy.ops.object.transform_apply(scale=True)
        cap.location = (x, pil_proj / 2, wall_h - 0.04)
        assign_material(cap, pil_mat)
        objects.append(cap)

        # Base (bottom plinth)
        bpy.ops.mesh.primitive_cube_add(size=1)
        base = bpy.context.active_object
        base.name = f"{name}_base_{bldg_id}"
        base.scale = (pil_w + 0.03, pil_proj + 0.015, 0.1)
        bpy.ops.object.transform_apply(scale=True)
        base.location = (x, pil_proj / 2, 0.05)
        assign_material(base, pil_mat)
        objects.append(base)

    return objects



def create_window_hoods(params, wall_h, facade_width, bldg_id=""):
    """Create projecting window hoods / label moulds above windows."""
    dec = params.get("decorative_elements", {})
    if not isinstance(dec, dict):
        return []
    hoods = dec.get("window_hoods", {})
    if not hoods:
        return []
    if isinstance(hoods, dict) and hoods.get("present") is False:
        return []

    hood_hex = get_accent_hex(params)
    if isinstance(hoods, dict):
        hood_hex = hoods.get("colour_hex", get_trim_hex(params))
    hood_mat = get_or_create_material(f"mat_hood_{hood_hex.lstrip('#')}", colour_hex=hood_hex, roughness=0.5)

    objects = []
    floor_heights = params.get("floor_heights_m", [3.0])
    windows_detail = get_effective_windows_detail(params)

    for fd in windows_detail:
        if not isinstance(fd, dict):
            continue
        floor_idx = int(_normalize_floor_index(fd.get("floor", 1), floor_heights))
        z_base = sum(floor_heights[:max(0, floor_idx - 1)])
        for w in fd.get("windows", []):
            if not isinstance(w, dict):
                continue
            count = w.get("count", 1)
            win_w = w.get("width_m", 0.85)
            win_h = w.get("height_m", 1.3)
            fi = max(0, min(floor_idx - 1, len(floor_heights) - 1))
            floor_h = floor_heights[fi] if floor_heights else 3.0
            sill_h = z_base + max(0.8, (floor_h - win_h) / 2)
            spacing = facade_width / (count + 1)

            for ci in range(count):
                cx = -facade_width / 2 + spacing * (ci + 1)
                hood_z = sill_h + win_h + 0.02

                # Hood shelf — projecting ledge above window
                bpy.ops.mesh.primitive_cube_add(size=1)
                shelf = bpy.context.active_object
                shelf.name = f"hood_shelf_{floor_idx}_{ci}_{bldg_id}"
                shelf.scale = (win_w + 0.15, 0.08, 0.04)
                bpy.ops.object.transform_apply(scale=True)
                shelf.location = (cx, 0.06, hood_z + 0.02)
                assign_material(shelf, hood_mat)
                objects.append(shelf)

                # Hood back plate — vertical face above window
                bpy.ops.mesh.primitive_cube_add(size=1)
                back = bpy.context.active_object
                back.name = f"hood_back_{floor_idx}_{ci}_{bldg_id}"
                back.scale = (win_w + 0.12, 0.02, 0.1)
                bpy.ops.object.transform_apply(scale=True)
                back.location = (cx, 0.01, hood_z + 0.07)
                assign_material(back, hood_mat)
                objects.append(back)

                # Small end brackets (corbels supporting the hood)
                for side, sx in [("L", cx - win_w / 2 - 0.04), ("R", cx + win_w / 2 + 0.04)]:
                    bpy.ops.mesh.primitive_cube_add(size=1)
                    cb = bpy.context.active_object
                    cb.name = f"hood_corbel_{side}_{floor_idx}_{ci}_{bldg_id}"
                    cb.scale = (0.04, 0.06, 0.08)
                    bpy.ops.object.transform_apply(scale=True)
                    cb.location = (sx, 0.04, hood_z)
                    assign_material(cb, hood_mat)
                    objects.append(cb)

    return objects



def create_sign_band(params, wall_h, width, bldg_id=""):
    """Create a sign band / signage fascia at parapet level (31 commercial buildings)."""
    rf = params.get("roof_features", [])
    has_sign_band = any("sign_band" in str(f).lower() or "sign band" in str(f).lower()
                        for f in (rf if isinstance(rf, list) else []))
    if not has_sign_band:
        return []

    objects = []
    sign_hex = "#E8E0D0"
    sign_mat = get_or_create_material(f"mat_sign_band_{bldg_id}", colour_hex=sign_hex, roughness=0.4)
    frame_mat = get_or_create_material("mat_sign_frame", colour_hex="#3A3A3A", roughness=0.5)
    _bsdf = frame_mat.node_tree.nodes.get("Principled BSDF")
    if _bsdf and "Metallic" in _bsdf.inputs:
        _bsdf.inputs["Metallic"].default_value = 0.70

    sign_h = 0.6
    sign_proj = 0.03

    # Sign panel
    bpy.ops.mesh.primitive_cube_add(size=1)
    panel = bpy.context.active_object
    panel.name = f"sign_band_panel_{bldg_id}"
    panel.scale = (width * 0.9, sign_proj, sign_h)
    bpy.ops.object.transform_apply(scale=True)
    panel.location = (0, sign_proj / 2, wall_h + sign_h / 2 + 0.05)
    assign_material(panel, sign_mat)
    objects.append(panel)

    # Frame border around sign
    border_w = 0.03
    for part, sx, sy, sw, sh in [
        ("top", 0, sign_proj / 2, width * 0.9 + border_w * 2, border_w),
        ("bot", 0, sign_proj / 2, width * 0.9 + border_w * 2, border_w),
    ]:
        bpy.ops.mesh.primitive_cube_add(size=1)
        fr = bpy.context.active_object
        fr.name = f"sign_band_frame_{part}_{bldg_id}"
        fr.scale = (sw, sign_proj + 0.01, sh)
        bpy.ops.object.transform_apply(scale=True)
        z_fr = wall_h + sign_h + 0.05 + border_w / 2 if part == "top" else wall_h + 0.05 - border_w / 2
        fr.location = (sx, sy, z_fr)
        assign_material(fr, frame_mat)
        objects.append(fr)

    return objects



def create_sill_noses(params, wall_h, facade_width, bldg_id=""):
    """Create projecting drip edges on all window sills (prevents water damage)."""
    windows_detail = get_effective_windows_detail(params)
    floor_heights = params.get("floor_heights_m", [3.0])
    if not windows_detail:
        return []

    trim_hex = get_trim_hex(params)
    sill_mat = get_or_create_material(f"mat_sill_{trim_hex.lstrip('#')}", colour_hex=trim_hex, roughness=0.5)
    objects = []

    for fd in windows_detail:
        if not isinstance(fd, dict):
            continue
        floor_idx = int(_normalize_floor_index(fd.get("floor", 1), floor_heights))
        z_base = sum(floor_heights[:max(0, floor_idx - 1)])
        for w in fd.get("windows", []):
            if not isinstance(w, dict):
                continue
            count = w.get("count", 1)
            if count == 0:
                continue
            win_w = w.get("width_m", 0.85)
            win_h = w.get("height_m", 1.3)
            fi = max(0, min(floor_idx - 1, len(floor_heights) - 1))
            floor_h = floor_heights[fi] if floor_heights else 3.0
            sill_h = z_base + max(0.8, (floor_h - win_h) / 2)
            spacing = facade_width / (count + 1)

            for ci in range(count):
                cx = -facade_width / 2 + spacing * (ci + 1)
                # Projecting stone sill with drip groove
                bpy.ops.mesh.primitive_cube_add(size=1)
                sill = bpy.context.active_object
                sill.name = f"sill_proj_{floor_idx}_{ci}_{bldg_id}"
                sill.scale = (win_w + 0.08, 0.07, 0.035)
                bpy.ops.object.transform_apply(scale=True)
                sill.location = (cx, 0.05, sill_h - 0.018)
                assign_material(sill, sill_mat)
                objects.append(sill)

    return objects



def create_door_transoms(params, facade_width, bldg_id=""):
    """Create glazed transom windows above doors (1,311 doors have transom data)."""
    doors = params.get("doors_detail", [])
    if not doors:
        return []
    glass_mat = create_glass_material("mat_glass")
    trim_hex = get_trim_hex(params)
    frame_mat = get_or_create_material(f"mat_transom_frame_{trim_hex.lstrip('#')}",
                                        colour_hex=trim_hex, roughness=0.5)
    objects = []
    for di, door in enumerate(doors):
        if not isinstance(door, dict):
            continue
        transom = door.get("transom", {})
        if not isinstance(transom, dict) or not transom.get("present", False):
            continue
        t_h = transom.get("height_m", 0.4)
        door_w = door.get("width_m", 1.0)
        door_h = door.get("height_m", 2.2)
        pos = str(door.get("position", "center")).lower()
        dx = -facade_width / 4 if "left" in pos else facade_width / 4 if "right" in pos else 0
        transom_z = door_h + t_h / 2
        bpy.ops.mesh.primitive_plane_add(size=1)
        tg = bpy.context.active_object
        tg.name = f"transom_glass_{di}_{bldg_id}"
        tg.scale = (door_w * 0.9, 1, t_h * 0.8)
        bpy.ops.object.transform_apply(scale=True)
        tg.rotation_euler.x = math.pi / 2
        tg.location = (dx, -0.02, transom_z)
        assign_material(tg, glass_mat)
        objects.append(tg)
        bpy.ops.mesh.primitive_cube_add(size=1)
        tf = bpy.context.active_object
        tf.name = f"transom_frame_{di}_{bldg_id}"
        tf.scale = (door_w + 0.04, 0.04, t_h + 0.03)
        bpy.ops.object.transform_apply(scale=True)
        tf.location = (dx, 0.01, transom_z)
        assign_material(tf, frame_mat)
        objects.append(tf)
        # Center mullion
        bpy.ops.mesh.primitive_cube_add(size=1)
        mul = bpy.context.active_object
        mul.name = f"transom_mul_{di}_{bldg_id}"
        mul.scale = (0.015, 0.02, t_h * 0.75)
        bpy.ops.object.transform_apply(scale=True)
        mul.location = (dx, -0.01, transom_z)
        assign_material(mul, frame_mat)
        objects.append(mul)
    return objects



def create_ground_floor_arches(params, wall_h, facade_width, bldg_id=""):
    """Create arched openings at ground floor (328 buildings)."""
    gfa = params.get("ground_floor_arches", {})
    arch_type = str(params.get("ground_floor_arch_type", "none")).lower()
    if arch_type == "none" and not gfa:
        return []
    if not isinstance(gfa, dict):
        gfa = {}
    objects = []
    trim_hex = get_trim_hex(params)
    arch_mat = create_stone_material(f"mat_arch_{trim_hex.lstrip('#')}", trim_hex)
    for key in ["left_arch", "centre_arch", "right_arch"]:
        arch = gfa.get(key, {})
        if not isinstance(arch, dict) or not arch:
            continue
        a_w = arch.get("total_width_m", 2.0)
        a_h = arch.get("total_height_m", 2.5)
        a_type = str(arch.get("type", arch_type)).lower()
        ax = -facade_width / 3 if "left" in key else facade_width / 3 if "right" in key else 0
        for side, sx in [("L", ax - a_w / 2 - 0.05), ("R", ax + a_w / 2 + 0.05)]:
            bpy.ops.mesh.primitive_cube_add(size=1)
            j = bpy.context.active_object
            j.name = f"arch_jamb_{side}_{key}_{bldg_id}"
            j.scale = (0.1, 0.06, a_h)
            bpy.ops.object.transform_apply(scale=True)
            j.location = (sx, 0.03, a_h / 2)
            assign_material(j, arch_mat)
            objects.append(j)
        if "round" in a_type or "segmental" in a_type:
            num_stones = 11
            radius = a_w / 2 + 0.06
            for si in range(num_stones):
                angle = math.pi * si / (num_stones - 1)
                sx = ax + radius * math.cos(angle)
                sz = a_h - a_w / 2 + radius * math.sin(angle)
                bpy.ops.mesh.primitive_cube_add(size=1)
                stone = bpy.context.active_object
                stone.name = f"arch_stone_{key}_{si}_{bldg_id}"
                stone.scale = (0.1, 0.07, 0.08)
                bpy.ops.object.transform_apply(scale=True)
                stone.location = (sx, 0.04, sz)
                stone.rotation_euler.y = -(angle - math.pi / 2)
                assign_material(stone, arch_mat)
                objects.append(stone)
            bpy.ops.mesh.primitive_cube_add(size=1)
            ks = bpy.context.active_object
            ks.name = f"arch_keystone_{key}_{bldg_id}"
            ks.scale = (0.12, 0.08, 0.15)
            bpy.ops.object.transform_apply(scale=True)
            ks.location = (ax, 0.04, a_h + 0.05)
            assign_material(ks, arch_mat)
            objects.append(ks)
        else:
            bpy.ops.mesh.primitive_cube_add(size=1)
            lt = bpy.context.active_object
            lt.name = f"arch_lintel_{key}_{bldg_id}"
            lt.scale = (a_w + 0.2, 0.06, 0.1)
            bpy.ops.object.transform_apply(scale=True)
            lt.location = (ax, 0.03, a_h + 0.05)
            assign_material(lt, arch_mat)
            objects.append(lt)
    return objects



def create_eave_returns(params, wall_h, width, depth, bldg_id=""):
    """Create eave returns at gable ends."""
    roof_type = str(params.get("roof_type", "")).lower()
    if "gable" not in roof_type:
        return []
    party_left = params.get("party_wall_left", False)
    party_right = params.get("party_wall_right", False)
    trim_hex = get_trim_hex(params)
    mat = get_or_create_material(f"mat_eave_return_{trim_hex.lstrip('#')}",
                                  colour_hex=trim_hex, roughness=0.5)
    objects = []
    hw = width / 2
    rd = params.get("roof_detail", {})
    overhang = (rd.get("eave_overhang_mm", 300) if isinstance(rd, dict) else 300) / 1000.0
    for side, sx, skip in [("L", -hw - overhang * 0.5, party_left),
                            ("R", hw + overhang * 0.5, party_right)]:
        if skip:
            continue
        bpy.ops.mesh.primitive_cube_add(size=1)
        ret = bpy.context.active_object
        ret.name = f"eave_return_{side}_{bldg_id}"
        ret.scale = (overhang, 0.25, 0.1)
        bpy.ops.object.transform_apply(scale=True)
        ret.location = (sx, overhang - 0.125, wall_h + 0.05)
        assign_material(ret, mat)
        objects.append(ret)
    return objects



def create_drip_edge(params, wall_h, width, bldg_id=""):
    """Create metal drip edge along eave line."""
    if "flat" in str(params.get("roof_type", "")).lower():
        return []
    objects = []
    drip_mat = get_or_create_material("mat_drip_edge", colour_hex="#5A5A5A", roughness=0.3)
    # Galvanised metal flashing
    _bsdf = drip_mat.node_tree.nodes.get("Principled BSDF")
    if _bsdf and "Metallic" in _bsdf.inputs:
        _bsdf.inputs["Metallic"].default_value = 0.80
    rd = params.get("roof_detail", {})
    overhang = (rd.get("eave_overhang_mm", 300) if isinstance(rd, dict) else 300) / 1000.0
    depth = params.get("facade_depth_m", 10.0)
    for name, y in [("front", overhang + 0.008), ("back", -depth - overhang - 0.008)]:
        bpy.ops.mesh.primitive_cube_add(size=1)
        de = bpy.context.active_object
        de.name = f"drip_edge_{name}_{bldg_id}"
        de.scale = (width + overhang * 2, 0.015, 0.025)
        bpy.ops.object.transform_apply(scale=True)
        de.location = (0, y, wall_h - 0.01)
        assign_material(de, drip_mat)
        objects.append(de)
    return objects



def create_door_surround(params, facade_width, bldg_id=""):
    """Create decorative door surround with pilasters and entablature."""
    doors = params.get("doors_detail", [])
    if not doors:
        return []
    era = str((params.get("hcd_data") or {}).get("construction_date", "")).lower()
    if "1914" in era or "1930" in era or "post" in era:
        return []
    objects = []
    trim_hex = get_trim_hex(params)
    mat = get_or_create_material(f"mat_door_surround_{trim_hex.lstrip('#')}",
                                  colour_hex=trim_hex, roughness=0.5)
    door = doors[0] if isinstance(doors[0], dict) else {}
    door_w = door.get("width_m", 1.0)
    door_h = door.get("height_m", 2.2)
    pos = str(door.get("position", "center")).lower()
    dx = -facade_width / 4 if "left" in pos else facade_width / 4 if "right" in pos else 0
    pil_w, pil_proj = 0.08, 0.04
    for side, sx in [("L", dx - door_w / 2 - pil_w / 2 - 0.02),
                     ("R", dx + door_w / 2 + pil_w / 2 + 0.02)]:
        bpy.ops.mesh.primitive_cube_add(size=1)
        pil = bpy.context.active_object
        pil.name = f"door_pil_{side}_{bldg_id}"
        pil.scale = (pil_w, pil_proj, door_h)
        bpy.ops.object.transform_apply(scale=True)
        pil.location = (sx, pil_proj / 2, door_h / 2)
        assign_material(pil, mat)
        objects.append(pil)
    ent_w = door_w + pil_w * 2 + 0.12
    bpy.ops.mesh.primitive_cube_add(size=1)
    ent = bpy.context.active_object
    ent.name = f"door_ent_{bldg_id}"
    ent.scale = (ent_w, pil_proj + 0.02, 0.08)
    bpy.ops.object.transform_apply(scale=True)
    ent.location = (dx, pil_proj / 2, door_h + 0.04)
    assign_material(ent, mat)
    objects.append(ent)
    bpy.ops.mesh.primitive_cube_add(size=1)
    cap = bpy.context.active_object
    cap.name = f"door_cap_{bldg_id}"
    cap.scale = (ent_w + 0.06, pil_proj + 0.04, 0.03)
    bpy.ops.object.transform_apply(scale=True)
    cap.location = (dx, pil_proj / 2 + 0.01, door_h + 0.095)
    assign_material(cap, mat)
    objects.append(cap)
    return objects



def create_soffit_vents(params, wall_h, width, depth, bldg_id=""):
    """Create soffit vents in eave overhang."""
    if "flat" in str(params.get("roof_type", "")).lower():
        return []
    objects = []
    vent_mat = get_or_create_material("mat_soffit_vent", colour_hex="#3A3A3A", roughness=0.5)
    rd = params.get("roof_detail", {})
    overhang = (rd.get("eave_overhang_mm", 300) if isinstance(rd, dict) else 300) / 1000.0
    if overhang < 0.15:
        return []
    num_vents = max(1, int(width / 1.5))
    for vi in range(num_vents):
        vx = -width / 2 + 1.5 / 2 + vi * 1.5
        if vx > width / 2:
            break
        bpy.ops.mesh.primitive_cube_add(size=1)
        vent = bpy.context.active_object
        vent.name = f"soffit_vent_{vi}_{bldg_id}"
        vent.scale = (0.15, overhang * 0.4, 0.005)
        bpy.ops.object.transform_apply(scale=True)
        vent.location = (vx, overhang * 0.5, wall_h - 0.12)
        assign_material(vent, vent_mat)
        objects.append(vent)
    return objects



def create_vent_pipes(params, wall_h, width, depth, bldg_id=""):
    """Create plumbing vent pipes through roof."""
    objects = []
    pipe_mat = get_or_create_material("mat_vent_pipe", colour_hex="#5A5A5A", roughness=0.4)
    pitch = params.get("roof_pitch_deg", 35)
    ridge_h = (width / 2) * _safe_tan(pitch)
    pipe_h = 0.6
    pipe_x = width * 0.15
    pipe_y = -depth * 0.6
    pipe_z = wall_h + ridge_h * 0.3
    bpy.ops.mesh.primitive_cylinder_add(radius=0.04, depth=pipe_h, vertices=8)
    pipe = bpy.context.active_object
    pipe.name = f"vent_pipe_{bldg_id}"
    pipe.location = (pipe_x, pipe_y, pipe_z + pipe_h / 2)
    assign_material(pipe, pipe_mat)
    objects.append(pipe)
    bpy.ops.mesh.primitive_cylinder_add(radius=0.06, depth=0.02, vertices=8)
    cap = bpy.context.active_object
    cap.name = f"vent_cap_{bldg_id}"
    cap.location = (pipe_x, pipe_y, pipe_z + pipe_h + 0.01)
    assign_material(cap, pipe_mat)
    objects.append(cap)
    return objects



def create_mail_slot(params, facade_width, bldg_id=""):
    """Create brass mail slot in front door."""
    if params.get("has_storefront"):
        return []
    objects = []
    slot_mat = get_or_create_material("mat_mail_slot", colour_hex="#C0A030", roughness=0.25)
    # Brass mail slot
    _bsdf = slot_mat.node_tree.nodes.get("Principled BSDF")
    if _bsdf and "Metallic" in _bsdf.inputs:
        _bsdf.inputs["Metallic"].default_value = 0.95
    doors = params.get("doors_detail", [])
    dx = 0
    if doors and isinstance(doors[0], dict):
        pos = str(doors[0].get("position", "center")).lower()
        dx = -facade_width / 4 if "left" in pos else facade_width / 4 if "right" in pos else 0
    bpy.ops.mesh.primitive_cube_add(size=1)
    slot = bpy.context.active_object
    slot.name = f"mail_slot_{bldg_id}"
    slot.scale = (0.2, 0.015, 0.04)
    bpy.ops.object.transform_apply(scale=True)
    slot.location = (dx, -0.02, 1.1)
    assign_material(slot, slot_mat)
    objects.append(slot)
    return objects



def create_kick_plate(params, facade_width, bldg_id=""):
    """Create metal kick plate at bottom of front door."""
    doors = params.get("doors_detail", [])
    if not doors:
        return []
    objects = []
    plate_mat = get_or_create_material("mat_kick_plate", colour_hex="#C0A060", roughness=0.25)
    # Brass/bronze kick plate
    _bsdf = plate_mat.node_tree.nodes.get("Principled BSDF")
    if _bsdf and "Metallic" in _bsdf.inputs:
        _bsdf.inputs["Metallic"].default_value = 0.90
    for di, door in enumerate(doors):
        if not isinstance(door, dict):
            continue
        door_w = door.get("width_m", 1.0)
        pos = str(door.get("position", "center")).lower()
        dx = -facade_width / 4 if "left" in pos else facade_width / 4 if "right" in pos else 0
        bpy.ops.mesh.primitive_cube_add(size=1)
        kp = bpy.context.active_object
        kp.name = f"kick_plate_{di}_{bldg_id}"
        kp.scale = (door_w * 0.9, 0.01, 0.2)
        bpy.ops.object.transform_apply(scale=True)
        kp.location = (dx, -0.01, 0.1)
        assign_material(kp, plate_mat)
        objects.append(kp)
    return objects


# ---------------------------------------------------------------------------
# Main building generator
# ---------------------------------------------------------------------------


