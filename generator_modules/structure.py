"""Structural elements: porch, chimney, foundation, gutters.

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
    create_copper_patina_material, create_canvas_material, select_roof_material,
)
from generator_modules.geometry import (
    create_box, boolean_cut, create_arch_cutter, create_rect_cutter,
    _safe_tan, _clamp_positive,
)


def create_porch(params, facade_width):
    """Create a front porch with posts and optional roof."""
    porch_data = params.get("porch", {})
    if not isinstance(porch_data, dict):
        return []
    if not porch_data.get("present", porch_data.get("type")):
        return []

    porch_w = min(porch_data.get("width_m", facade_width), facade_width)
    porch_d = porch_data.get("depth_m", 2.0)
    porch_h = porch_data.get("height_m", 2.8)
    floor_h = porch_data.get("floor_height_above_grade_m",
              porch_data.get("deck_height_above_sidewalk_m", 0.5))

    objects = []

    # Porch floor/deck
    bpy.ops.mesh.primitive_cube_add(size=1)
    deck = bpy.context.active_object
    deck.name = "porch_deck"
    deck.scale = (porch_w, porch_d, 0.1)
    bpy.ops.object.transform_apply(scale=True)
    deck.location = (0, porch_d / 2, floor_h)

    wood_mat = create_wood_material("mat_wood", "#8B7355")
    assign_material(deck, wood_mat)
    objects.append(deck)

    # Posts
    posts_data = porch_data.get("posts", {})
    post_count = posts_data.get("count", 4) if isinstance(posts_data, dict) else 4
    post_colour = "#3A2A20"
    if isinstance(posts_data, dict):
        post_colour = posts_data.get("colour_hex", "#3A2A20")

    post_mat = create_wood_material(f"mat_post_{post_colour.lstrip('#')}", post_colour)

    # Porch beam (placed first so we know its z)
    beam_h = 0.12
    beam_z = porch_h
    bpy.ops.mesh.primitive_cube_add(size=1)
    beam = bpy.context.active_object
    beam.name = "porch_beam"
    beam.scale = (porch_w + 0.1, 0.1, beam_h)
    bpy.ops.object.transform_apply(scale=True)
    beam.location = (0, porch_d, beam_z)
    assign_material(beam, post_mat)
    objects.append(beam)

    # Posts — extend into beam to close gap
    post_h = porch_h - floor_h + beam_h / 2 + 0.06
    for i in range(post_count):
        x = -porch_w / 2 + (porch_w / max(1, post_count - 1)) * i if post_count > 1 else 0

        bpy.ops.mesh.primitive_cylinder_add(radius=0.05, depth=post_h)
        post = bpy.context.active_object
        post.name = f"porch_post_{i}"
        post.location = (x, porch_d, floor_h + post_h / 2)
        assign_material(post, post_mat)
        objects.append(post)

    # Porch roof (simple shed)
    bpy.ops.mesh.primitive_cube_add(size=1)
    proofroof = bpy.context.active_object
    proofroof.name = "porch_roof"
    proofroof.scale = (porch_w + 0.2, porch_d + 0.3, 0.08)
    bpy.ops.object.transform_apply(scale=True)
    proofroof.location = (0, porch_d / 2, beam_z + beam_h / 2 + 0.04)

    roof_mat = get_or_create_material("mat_roof_2E2E2E", colour_hex="#2E2E2E", roughness=0.9)
    assign_material(proofroof, roof_mat)
    objects.append(proofroof)

    # Steps — compute step position/width for railing gap calculation
    steps_data = porch_data.get("steps", porch_data.get("stairs", {}))
    step_w = 1.2
    step_x = 0.0
    step_count = 3
    run = 0.28
    if isinstance(steps_data, dict):
        step_count = steps_data.get("count", steps_data.get("rise_count", 3))
        step_w = steps_data.get("width_m", 1.2)
        step_pos = str(steps_data.get("position", "center")).lower()
        if "left" in step_pos:
            step_x = -porch_w / 4
        elif "right" in step_pos:
            step_x = porch_w / 4
        rise = floor_h / max(1, step_count)
        run = 0.28

        for s in range(step_count):
            bpy.ops.mesh.primitive_cube_add(size=1)
            step = bpy.context.active_object
            step.name = f"step_{s}"
            step.scale = (step_w, run, rise)
            bpy.ops.object.transform_apply(scale=True)
            step.location = (step_x, porch_d + run * (s + 0.5), rise * (step_count - s - 0.5))
            step_mat = create_stone_material("mat_porch_step", "#9A9A9A")
            assign_material(step, step_mat)
            objects.append(step)

    # Railing — front with entry gap, plus both sides
    railing_data = porch_data.get("railing", {})
    if isinstance(railing_data, dict) and railing_data.get("present", True):
        rail_h = railing_data.get("height_mm", 800) / 1000 if isinstance(railing_data.get("height_mm"), (int, float)) else 0.8
        rail_z = floor_h + rail_h

        # Entry gap in front railing (where steps are)
        gap_left = step_x - step_w / 2 - 0.05
        gap_right = step_x + step_w / 2 + 0.05

        # Front railing — LEFT section (from left edge to gap)
        left_rail_w = gap_left - (-porch_w / 2)
        if left_rail_w > 0.2:
            left_rail_cx = (-porch_w / 2 + gap_left) / 2
            bpy.ops.mesh.primitive_cube_add(size=1)
            rl = bpy.context.active_object
            rl.name = "rail_front_left"
            rl.scale = (left_rail_w, 0.04, 0.04)
            bpy.ops.object.transform_apply(scale=True)
            rl.location = (left_rail_cx, porch_d, rail_z)
            assign_material(rl, post_mat)
            objects.append(rl)

            # Bottom rail
            bpy.ops.mesh.primitive_cube_add(size=1)
            rbl = bpy.context.active_object
            rbl.name = "rail_front_left_bot"
            rbl.scale = (left_rail_w, 0.04, 0.03)
            bpy.ops.object.transform_apply(scale=True)
            rbl.location = (left_rail_cx, porch_d, floor_h + 0.05)
            assign_material(rbl, post_mat)
            objects.append(rbl)

            # Balusters for left section
            bal_count = max(1, int(left_rail_w / 0.12))
            for bi in range(bal_count):
                bx = -porch_w / 2 + (left_rail_w / bal_count) * (bi + 0.5)
                bpy.ops.mesh.primitive_cube_add(size=1)
                bal = bpy.context.active_object
                bal.name = f"bal_fl_{bi}"
                bal.scale = (0.025, 0.025, rail_h - 0.08)
                bpy.ops.object.transform_apply(scale=True)
                bal.location = (bx, porch_d, floor_h + (rail_h - 0.08) / 2 + 0.04)
                assign_material(bal, post_mat)
                objects.append(bal)

        # Front railing — RIGHT section (from gap to right edge)
        right_rail_w = porch_w / 2 - gap_right
        if right_rail_w > 0.2:
            right_rail_cx = (gap_right + porch_w / 2) / 2
            bpy.ops.mesh.primitive_cube_add(size=1)
            rr = bpy.context.active_object
            rr.name = "rail_front_right"
            rr.scale = (right_rail_w, 0.04, 0.04)
            bpy.ops.object.transform_apply(scale=True)
            rr.location = (right_rail_cx, porch_d, rail_z)
            assign_material(rr, post_mat)
            objects.append(rr)

            # Bottom rail
            bpy.ops.mesh.primitive_cube_add(size=1)
            rbr = bpy.context.active_object
            rbr.name = "rail_front_right_bot"
            rbr.scale = (right_rail_w, 0.04, 0.03)
            bpy.ops.object.transform_apply(scale=True)
            rbr.location = (right_rail_cx, porch_d, floor_h + 0.05)
            assign_material(rbr, post_mat)
            objects.append(rbr)

            # Balusters for right section
            bal_count = max(1, int(right_rail_w / 0.12))
            for bi in range(bal_count):
                bx = gap_right + (right_rail_w / bal_count) * (bi + 0.5)
                bpy.ops.mesh.primitive_cube_add(size=1)
                bal = bpy.context.active_object
                bal.name = f"bal_fr_{bi}"
                bal.scale = (0.025, 0.025, rail_h - 0.08)
                bpy.ops.object.transform_apply(scale=True)
                bal.location = (bx, porch_d, floor_h + (rail_h - 0.08) / 2 + 0.04)
                assign_material(bal, post_mat)
                objects.append(bal)

        # SIDE railings (left and right edges of porch)
        side_rail_len = porch_d - 0.1  # slightly shorter than porch depth
        for side_name, sx in [("left", -porch_w / 2), ("right", porch_w / 2)]:
            # Top rail
            bpy.ops.mesh.primitive_cube_add(size=1)
            sr = bpy.context.active_object
            sr.name = f"rail_side_{side_name}"
            sr.scale = (0.04, side_rail_len, 0.04)
            bpy.ops.object.transform_apply(scale=True)
            sr.location = (sx, porch_d / 2 + 0.05, rail_z)
            assign_material(sr, post_mat)
            objects.append(sr)

            # Bottom rail
            bpy.ops.mesh.primitive_cube_add(size=1)
            srb = bpy.context.active_object
            srb.name = f"rail_side_{side_name}_bot"
            srb.scale = (0.04, side_rail_len, 0.03)
            bpy.ops.object.transform_apply(scale=True)
            srb.location = (sx, porch_d / 2 + 0.05, floor_h + 0.05)
            assign_material(srb, post_mat)
            objects.append(srb)

            # Side balusters
            side_bal_count = max(1, int(side_rail_len / 0.12))
            for bi in range(side_bal_count):
                by = 0.1 + (side_rail_len / side_bal_count) * (bi + 0.5)
                bpy.ops.mesh.primitive_cube_add(size=1)
                sbal = bpy.context.active_object
                sbal.name = f"bal_s{side_name}_{bi}"
                sbal.scale = (0.025, 0.025, rail_h - 0.08)
                bpy.ops.object.transform_apply(scale=True)
                sbal.location = (sx, by, floor_h + (rail_h - 0.08) / 2 + 0.04)
                assign_material(sbal, post_mat)
                objects.append(sbal)

    # Brick piers at porch corners
    piers = porch_data.get("brick_piers", {})
    if isinstance(piers, dict) and piers.get("present", False):
        pier_w = piers.get("width_m", 0.4)
        pier_h = piers.get("height_m", 0.8)
        pier_count = piers.get("count", 2)
        pier_mat = create_brick_material("mat_pier_brick",
                                          get_facade_hex(params))
        for pi in range(pier_count):
            if pier_count == 2:
                px = (-porch_w / 2 + pier_w / 2) if pi == 0 else (porch_w / 2 - pier_w / 2)
            else:
                px = -porch_w / 2 + (porch_w / max(1, pier_count - 1)) * pi
            bpy.ops.mesh.primitive_cube_add(size=1)
            pier = bpy.context.active_object
            pier.name = f"brick_pier_{pi}"
            pier.scale = (pier_w, pier_w, pier_h)
            bpy.ops.object.transform_apply(scale=True)
            pier.location = (px, porch_d, pier_h / 2)
            assign_material(pier, pier_mat)
            objects.append(pier)
            # Stone cap on pier
            cap_hex = piers.get("cap_hex", "#C8B88A")
            cap_mat = get_or_create_material("mat_pier_cap", colour_hex=cap_hex, roughness=0.5)
            bpy.ops.mesh.primitive_cube_add(size=1)
            cap = bpy.context.active_object
            cap.name = f"pier_cap_{pi}"
            cap.scale = (pier_w + 0.04, pier_w + 0.04, 0.05)
            bpy.ops.object.transform_apply(scale=True)
            cap.location = (px, porch_d, pier_h + 0.025)
            assign_material(cap, cap_mat)
            objects.append(cap)

    return objects



def create_chimney(params, wall_h, ridge_height, width):
    """Create chimneys with corbelled cap and flue pot."""
    roof_detail = params.get("roof_detail", {})
    chimney_data = None

    if isinstance(roof_detail, dict):
        chimney_data = roof_detail.get("chimneys", {})

    if not chimney_data or not isinstance(chimney_data, dict):
        # Check roof_features
        features = params.get("roof_features", [])
        if any("chimney" in str(f).lower() for f in features):
            chimney_data = {"count": 1}
        else:
            # Check top-level chimneys field
            ch_top = params.get("chimneys", {})
            if isinstance(ch_top, dict) and ch_top.get("count", 0) > 0:
                chimney_data = ch_top
            elif isinstance(ch_top, int) and ch_top > 0:
                chimney_data = {"count": ch_top}
            else:
                return []

    count = chimney_data.get("count", 0)
    if count == 0:
        return []

    objects = []
    facade_hex = get_facade_hex(params)
    brick_mat = create_brick_material(f"mat_chimney_brick_{facade_hex.lstrip('#')}",
                                       facade_hex, "#8A8A8A", scale=12.0)
    cap_mat = create_stone_material("mat_chimney_cap", "#6A6A6A")

    hw = width / 2
    depth = params.get("facade_depth_m", DEFAULT_DEPTH)

    # Build chimney positions from data or defaults
    chimney_specs = []
    for key in ["left_chimney", "right_chimney"]:
        ch = chimney_data.get(key, {})
        if isinstance(ch, dict) and ch:
            chimney_specs.append((key, ch))

    # If no explicit left/right but count > 0, create defaults
    if not chimney_specs and count > 0:
        if count >= 2:
            chimney_specs.append(("left_chimney", {"position": "left", "width_m": 0.5, "depth_m": 0.4}))
            chimney_specs.append(("right_chimney", {"position": "right", "width_m": 0.5, "depth_m": 0.4}))
        else:
            chimney_specs.append(("right_chimney", {"position": "right", "width_m": 0.5, "depth_m": 0.4}))

    for key, ch in chimney_specs:
        ch_w = min(ch.get("width_m", 0.5), width * 0.4)  # cap at 40% of facade
        ch_d = min(ch.get("depth_m", 0.4), depth * 0.3)   # cap at 30% of depth
        above = ch.get("height_above_ridge_m", 1.0)
        above = min(above, 1.5)

        pos = str(ch.get("position", key)).lower()
        if "left" in pos:
            x = -hw + ch_w / 2
        elif "right" in pos:
            x = hw - ch_w / 2
        else:
            x = 0

        ch_bottom = wall_h + ridge_height * 0.3  # start where chimney exits the roof slope
        ch_top = wall_h + ridge_height + above
        ch_h = max(ch_top - ch_bottom, 0.5)
        ch_y = -depth * 0.3

        # Main chimney shaft
        bpy.ops.mesh.primitive_cube_add(size=1)
        chimney = bpy.context.active_object
        chimney.name = f"chimney_{key}"
        chimney.scale = (ch_w, ch_d, ch_h)
        bpy.ops.object.transform_apply(scale=True)
        chimney.location = (x, ch_y, ch_bottom + ch_h / 2)
        assign_material(chimney, brick_mat)
        objects.append(chimney)

        # Corbelled cap — wider band at top
        cap_proj = 0.04
        cap_h = 0.08
        bpy.ops.mesh.primitive_cube_add(size=1)
        corbel = bpy.context.active_object
        corbel.name = f"chimney_corbel_{key}"
        corbel.scale = (ch_w + cap_proj * 2, ch_d + cap_proj * 2, cap_h)
        bpy.ops.object.transform_apply(scale=True)
        corbel.location = (x, ch_y, ch_top - cap_h / 2)
        assign_material(corbel, brick_mat)
        objects.append(corbel)

        # Concrete cap slab
        bpy.ops.mesh.primitive_cube_add(size=1)
        slab = bpy.context.active_object
        slab.name = f"chimney_cap_{key}"
        slab.scale = (ch_w + cap_proj * 3, ch_d + cap_proj * 3, 0.04)
        bpy.ops.object.transform_apply(scale=True)
        slab.location = (x, ch_y, ch_top + 0.02)
        assign_material(slab, cap_mat)
        objects.append(slab)

        # Flue pot — small cylinder on top
        bpy.ops.mesh.primitive_cylinder_add(radius=0.08, depth=0.15, vertices=8)
        flue = bpy.context.active_object
        flue.name = f"chimney_flue_{key}"
        flue.location = (x, ch_y, ch_top + 0.04 + 0.075)
        assign_material(flue, cap_mat)
        objects.append(flue)

    return objects



def create_turned_posts(porch_objs, params, facade_width):
    """Replace simple cylinder porch posts with turned Victorian posts (vase-and-ring)."""
    porch_data = params.get("porch", {})
    if not isinstance(porch_data, dict):
        return porch_objs

    posts_data = porch_data.get("posts", {})
    if not isinstance(posts_data, dict):
        return porch_objs

    style = str(posts_data.get("style", posts_data.get("type", ""))).lower()
    if "turned" not in style and "victorian" not in style:
        return porch_objs

    post_colour = posts_data.get("colour_hex", "#3A2A20")
    post_mat = create_wood_material(f"mat_turned_post_{post_colour.lstrip('#')}",
                                    post_colour)

    # Find and replace existing porch_post objects
    new_objs = []
    for obj in porch_objs:
        if not obj or not obj.name.startswith("porch_post_"):
            new_objs.append(obj)
            continue

        # Get post position and dimensions from existing cylinder
        loc = obj.location.copy()
        sz = obj.dimensions.z  # post height

        # Remove old cylinder
        bpy.data.objects.remove(obj, do_unlink=True)

        # Build turned post with lathe-like profile using stacked segments
        post_parts = []
        base_r = 0.05
        # Start at bottom of post, extend slightly to close any gap
        z_bottom = loc.z - sz / 2
        z_top = loc.z + sz / 2 + 0.06  # extend into beam to ensure no gap
        total_h = z_top - z_bottom
        z_cursor = z_bottom

        # Square plinth base
        bpy.ops.mesh.primitive_cube_add(size=1)
        plinth = bpy.context.active_object
        plinth.name = f"turned_plinth_{loc.x:.1f}"
        plinth.scale = (0.09, 0.09, 0.08)
        bpy.ops.object.transform_apply(scale=True)
        plinth.location = (loc.x, loc.y, z_cursor + 0.04)
        assign_material(plinth, post_mat)
        post_parts.append(plinth)
        z_cursor += 0.08

        # Main shaft segments: ring-vase-ring-vase-ring profile
        shaft_h = total_h - 0.16  # minus plinth and cap
        seg_h = shaft_h / 7

        profiles = [
            (base_r * 0.8, seg_h * 0.5),   # thin ring
            (base_r * 1.2, seg_h * 1.5),   # vase bulge
            (base_r * 0.7, seg_h * 0.4),   # narrow neck
            (base_r * 0.9, seg_h * 1.2),   # ring
            (base_r * 0.7, seg_h * 0.4),   # narrow neck
            (base_r * 1.1, seg_h * 1.3),   # vase bulge
            (base_r * 0.8, seg_h * 0.7),   # thin ring top
        ]

        for radius, height in profiles:
            bpy.ops.mesh.primitive_cylinder_add(radius=radius, depth=height, vertices=8)
            seg = bpy.context.active_object
            seg.name = f"turned_seg_{loc.x:.1f}"
            seg.location = (loc.x, loc.y, z_cursor + height / 2)
            assign_material(seg, post_mat)
            post_parts.append(seg)
            z_cursor += height

        # Cap block
        bpy.ops.mesh.primitive_cube_add(size=1)
        cap = bpy.context.active_object
        cap.name = f"turned_cap_{loc.x:.1f}"
        cap.scale = (0.09, 0.09, 0.08)
        bpy.ops.object.transform_apply(scale=True)
        cap.location = (loc.x, loc.y, z_cursor + 0.04)
        assign_material(cap, post_mat)
        post_parts.append(cap)

        # Join all parts into a single smooth post
        if len(post_parts) > 1:
            bpy.ops.object.select_all(action='DESELECT')
            for p in post_parts:
                p.select_set(True)
            bpy.context.view_layer.objects.active = post_parts[0]
            bpy.ops.object.join()
            joined_post = bpy.context.active_object
            joined_post.name = f"turned_post_{loc.x:.1f}"
            # Smooth shading for seamless look
            bpy.ops.object.shade_smooth()
            new_objs.append(joined_post)
        else:
            new_objs.extend(post_parts)

    return new_objs



def create_foundation(params, width, depth, bldg_id=""):
    """Create visible foundation/water table at ground level with stone coursing."""
    foundation_h = params.get("foundation_height_m", 0.3)
    if not isinstance(foundation_h, (int, float)) or foundation_h <= 0:
        foundation_h = 0.3
    foundation_proj = 0.04  # projection from wall face

    # Foundation colour — typically grey limestone or rubble stone
    dfa = params.get("deep_facade_analysis", {})
    depth_notes = dfa.get("depth_notes", {}) if isinstance(dfa, dict) else {}
    if isinstance(depth_notes, dict) and depth_notes.get("foundation_height_m_est"):
        est_h = depth_notes["foundation_height_m_est"]
        if isinstance(est_h, (int, float)) and est_h > 0:
            foundation_h = est_h

    # Foundation colour based on construction era
    construction_date = params.get("hcd_data", {}).get("construction_date", "")
    if isinstance(construction_date, str):
        construction_date = construction_date.strip()

    # Select foundation colour by era
    if any(x in construction_date for x in ["Pre-1889", "pre-1889", "1889-1903"]):
        foundation_colour = "#7A7570"  # rubble stone
    elif any(x in construction_date for x in ["1904-1913"]):
        foundation_colour = "#7A7A78"  # dressed stone (current default)
    elif any(x in construction_date for x in ["1914-1930"]):
        foundation_colour = "#9A9690"  # concrete-like
    else:
        foundation_colour = "#7A7A78"  # default fallback

    stone_mat = create_stone_material(f"mat_foundation_{bldg_id}", foundation_colour)

    objects = []
    hw = width / 2
    party_left = params.get("party_wall_left", False)
    party_right = params.get("party_wall_right", False)

    # Front foundation wall
    bpy.ops.mesh.primitive_cube_add(size=1)
    ff = bpy.context.active_object
    ff.name = f"foundation_front_{bldg_id}"
    ff.scale = (width + foundation_proj * 2, foundation_proj * 2, foundation_h)
    bpy.ops.object.transform_apply(scale=True)
    ff.location = (0, foundation_proj, foundation_h / 2)
    assign_material(ff, stone_mat)
    objects.append(ff)

    # Back foundation wall
    bpy.ops.mesh.primitive_cube_add(size=1)
    fb = bpy.context.active_object
    fb.name = f"foundation_back_{bldg_id}"
    fb.scale = (width + foundation_proj * 2, foundation_proj * 2, foundation_h)
    bpy.ops.object.transform_apply(scale=True)
    fb.location = (0, -depth - foundation_proj, foundation_h / 2)
    assign_material(fb, stone_mat)
    objects.append(fb)

    # Left side (skip if party wall — neighbour's foundation is flush)
    if not party_left:
        bpy.ops.mesh.primitive_cube_add(size=1)
        fl = bpy.context.active_object
        fl.name = f"foundation_left_{bldg_id}"
        fl.scale = (foundation_proj * 2, depth + foundation_proj * 2, foundation_h)
        bpy.ops.object.transform_apply(scale=True)
        fl.location = (-hw - foundation_proj, -depth / 2, foundation_h / 2)
        assign_material(fl, stone_mat)
        objects.append(fl)

    # Right side (skip if party wall)
    if not party_right:
        bpy.ops.mesh.primitive_cube_add(size=1)
        fr = bpy.context.active_object
        fr.name = f"foundation_right_{bldg_id}"
        fr.scale = (foundation_proj * 2, depth + foundation_proj * 2, foundation_h)
        bpy.ops.object.transform_apply(scale=True)
        fr.location = (hw + foundation_proj, -depth / 2, foundation_h / 2)
        assign_material(fr, stone_mat)
        objects.append(fr)

    # Stone coursing lines on front face — horizontal grooves every ~0.15m
    groove_mat = get_or_create_material("mat_foundation_groove", colour_hex="#606060", roughness=0.95)
    course_h = 0.15
    z = course_h
    while z < foundation_h - 0.05:
        bpy.ops.mesh.primitive_cube_add(size=1)
        groove = bpy.context.active_object
        groove.name = f"foundation_course_{bldg_id}_{int(z*100)}"
        groove.scale = (width + foundation_proj * 2.5, 0.005, 0.01)
        bpy.ops.object.transform_apply(scale=True)
        groove.location = (0, foundation_proj + 0.005, z)
        assign_material(groove, groove_mat)
        objects.append(groove)
        z += course_h

    return objects



def create_gutters(params, wall_h, width, depth, bldg_id=""):
    """Create gutters along eaves, downspouts at corners, and elbow connectors."""
    roof_type = str(params.get("roof_type", "gable")).lower()
    if "flat" in roof_type:
        return []  # flat roofs have internal drainage

    # Copper gutters on buildings with copper roofing use the patina shader
    rm = str(params.get("roof_material", "")).lower()
    if any(kw in rm for kw in ("copper", "verdigris", "patina")):
        gutter_mat = create_copper_patina_material("mat_gutter_copper", "#B87333")
    else:
        gutter_mat = get_or_create_material("mat_gutter", colour_hex="#4A4A4A", roughness=0.35)
        # Metal gutters/downspouts: set metallic for PBR realism
        bsdf = gutter_mat.node_tree.nodes.get("Principled BSDF")
        if bsdf and "Metallic" in bsdf.inputs:
            bsdf.inputs["Metallic"].default_value = 0.85

    objects = []
    gutter_r = 0.04
    downspout_r = 0.025

    rd = params.get("roof_detail", {})
    eave_mm = 300
    if isinstance(rd, dict):
        eave_mm = rd.get("eave_overhang_mm", 300)
    else:
        eave_mm = params.get("eave_overhang_mm", 300)
    overhang = eave_mm / 1000.0

    party_left = params.get("party_wall_left", False)
    party_right = params.get("party_wall_right", False)
    hw = width / 2

    # Front gutter (horizontal along eave)
    bpy.ops.mesh.primitive_cylinder_add(radius=gutter_r, depth=width + overhang,
                                         vertices=8)
    gf = bpy.context.active_object
    gf.name = f"gutter_front_{bldg_id}"
    gf.rotation_euler.y = math.pi / 2
    gf.location = (0, overhang, wall_h - 0.02)
    assign_material(gf, gutter_mat)
    objects.append(gf)

    # Back gutter
    bpy.ops.mesh.primitive_cylinder_add(radius=gutter_r, depth=width + overhang,
                                         vertices=8)
    gb = bpy.context.active_object
    gb.name = f"gutter_back_{bldg_id}"
    gb.rotation_euler.y = math.pi / 2
    gb.location = (0, -depth - overhang, wall_h - 0.02)
    assign_material(gb, gutter_mat)
    objects.append(gb)

    # Downspouts at front corners (skip party wall sides)
    downspout_positions = []
    if not party_left:
        downspout_positions.append(("L", -hw - 0.02))
    if not party_right:
        downspout_positions.append(("R", hw + 0.02))

    for side, sx in downspout_positions:
        # Vertical downspout pipe
        bpy.ops.mesh.primitive_cylinder_add(radius=downspout_r, depth=wall_h - 0.3, vertices=6)
        ds = bpy.context.active_object
        ds.name = f"downspout_{side}_{bldg_id}"
        ds.location = (sx, overhang + 0.02, (wall_h - 0.3) / 2)
        assign_material(ds, gutter_mat)
        objects.append(ds)

        # Upper elbow — connects gutter to downspout
        bpy.ops.mesh.primitive_uv_sphere_add(radius=downspout_r * 1.3, segments=6, ring_count=4)
        elbow_top = bpy.context.active_object
        elbow_top.name = f"gutter_elbow_top_{side}_{bldg_id}"
        elbow_top.location = (sx, overhang + 0.02, wall_h - 0.05)
        assign_material(elbow_top, gutter_mat)
        objects.append(elbow_top)

        # Lower elbow — downspout to ground discharge
        bpy.ops.mesh.primitive_uv_sphere_add(radius=downspout_r * 1.3, segments=6, ring_count=4)
        elbow_bot = bpy.context.active_object
        elbow_bot.name = f"gutter_elbow_bot_{side}_{bldg_id}"
        elbow_bot.location = (sx, overhang + 0.02, 0.15)
        assign_material(elbow_bot, gutter_mat)
        objects.append(elbow_bot)

        # Ground discharge — short horizontal pipe
        bpy.ops.mesh.primitive_cylinder_add(radius=downspout_r, depth=0.2, vertices=6)
        discharge = bpy.context.active_object
        discharge.name = f"gutter_discharge_{side}_{bldg_id}"
        discharge.rotation_euler.x = math.pi / 2
        discharge.location = (sx, overhang + 0.12, 0.08)
        assign_material(discharge, gutter_mat)
        objects.append(discharge)

    return objects



def create_chimney_caps(params, wall_h, ridge_height, width, bldg_id=""):
    """Add flared corbelled caps to existing chimneys."""
    chimney_data = params.get("chimneys", params.get("roof_detail", {}).get("chimneys", {}))
    if not isinstance(chimney_data, dict):
        return []

    objects = []
    facade_hex = get_facade_hex(params)
    cap_mat = create_brick_material(f"mat_chimcap_{facade_hex.lstrip('#')}", facade_hex)
    stone_cap = get_or_create_material("mat_chimcap_stone", colour_hex="#8A8A88", roughness=0.7)

    depth = params.get("facade_depth_m", DEFAULT_DEPTH)
    hw = width / 2

    for key in chimney_data:
        ch = chimney_data[key]
        if not isinstance(ch, dict):
            continue

        ch_w = ch.get("width_m", 0.6)
        ch_d = ch.get("depth_m", 0.4)
        above = ch.get("height_above_ridge_m", 1.0)
        pos = str(ch.get("position", "")).lower()

        # Match chimney x position (flush at building edge)
        if "left" in pos:
            cx = -hw + ch_w / 2
        elif "right" in pos:
            cx = hw - ch_w / 2
        else:
            cx = 0

        # Match chimney y position
        ch_y = -depth * 0.3

        ch_top_z = wall_h + ridge_height + above

        # Corbelled flare (wider course below cap)
        bpy.ops.mesh.primitive_cube_add(size=1)
        flare = bpy.context.active_object
        flare.name = f"chimcap_flare_{key}_{bldg_id}"
        flare.scale = (ch_w + 0.08, ch_d + 0.08, 0.06)
        bpy.ops.object.transform_apply(scale=True)
        flare.location = (cx, ch_y, ch_top_z - 0.03)
        assign_material(flare, cap_mat)
        objects.append(flare)

        # Second corbel course
        bpy.ops.mesh.primitive_cube_add(size=1)
        flare2 = bpy.context.active_object
        flare2.name = f"chimcap_flare2_{key}_{bldg_id}"
        flare2.scale = (ch_w + 0.12, ch_d + 0.12, 0.04)
        bpy.ops.object.transform_apply(scale=True)
        flare2.location = (cx, ch_y, ch_top_z + 0.02)
        assign_material(flare2, cap_mat)
        objects.append(flare2)

        # Stone/concrete cap slab
        bpy.ops.mesh.primitive_cube_add(size=1)
        slab = bpy.context.active_object
        slab.name = f"chimcap_slab_{key}_{bldg_id}"
        slab.scale = (ch_w + 0.16, ch_d + 0.16, 0.04)
        bpy.ops.object.transform_apply(scale=True)
        slab.location = (cx, ch_y, ch_top_z + 0.06)
        assign_material(slab, stone_cap)
        objects.append(slab)

    return objects



def create_porch_lattice(params, facade_width, bldg_id=""):
    """Create lattice skirt panel under porch deck using contained diagonal bars."""
    porch_data = params.get("porch", {})
    if not isinstance(porch_data, dict):
        return []
    if not porch_data.get("present", porch_data.get("type")):
        return []

    porch_w = porch_data.get("width_m", facade_width)
    floor_h = porch_data.get("floor_height_above_grade_m",
              porch_data.get("deck_height_above_sidewalk_m", 0.5))

    if floor_h < 0.2:
        return []

    porch_d = porch_data.get("depth_m", 2.0)
    trim_hex = get_trim_hex(params)
    lattice_mat = create_wood_material(f"mat_lattice_{trim_hex.lstrip('#')}", trim_hex)

    objects = []

    # Front lattice — contained panel using bmesh for precise clipping
    # Create diagonal grid within the rectangle [0, floor_h] x [-porch_w/2, porch_w/2]
    bm = bmesh.new()
    bar_w = 0.012
    spacing = 0.1  # diamond spacing
    hw = porch_w / 2

    # Diagonal bars direction 1 (top-left to bottom-right)
    x = -hw
    while x < hw + floor_h:
        # Bar runs from top-left to bottom-right, clipped to panel bounds
        x0, z0 = x, floor_h
        x1, z1 = x + floor_h, 0

        # Clip to panel bounds
        if x0 < -hw:
            z0 = floor_h - (-hw - x0)
            x0 = -hw
        if x1 > hw:
            z1 = floor_h - (hw - x + floor_h) if (x + floor_h - hw) < floor_h else x1 - hw
            z1 = (x1 - hw) / floor_h * floor_h
            z1 = floor_h * (1.0 - (hw - x) / floor_h) if (hw - x) < floor_h else 0
            x1_new = min(x1, hw)
            z1 = max(0, z0 - (x1_new - x0))
            x1 = x1_new
        if z0 < 0:
            z0 = 0
        if z1 > floor_h:
            z1 = floor_h

        if x0 < hw and x1 > -hw and z0 > 0.01:
            v0 = bm.verts.new((x0 - bar_w / 2, 0, z0))
            v1 = bm.verts.new((x0 + bar_w / 2, 0, z0))
            v2 = bm.verts.new((x1 + bar_w / 2, 0, z1))
            v3 = bm.verts.new((x1 - bar_w / 2, 0, z1))
            bm.faces.new([v0, v1, v2, v3])

        x += spacing

    # Diagonal bars direction 2 (bottom-left to top-right — mirror of direction 1)
    x = -hw
    while x < hw + floor_h:
        # Bar runs from bottom-left to top-right
        x0, z0 = x, 0
        x1, z1 = x + floor_h, floor_h

        # Clip to panel bounds
        if x0 < -hw:
            z0 = -hw - x0
            x0 = -hw
        if x1 > hw:
            z1 = floor_h - (x1 - hw)
            x1 = hw
        if z0 < 0:
            z0 = 0
        if z1 > floor_h:
            z1 = floor_h
        if z0 > floor_h:
            x += spacing
            continue

        if x0 < hw and x1 > -hw and z1 > z0 + 0.01:
            v0 = bm.verts.new((x0 - bar_w / 2, 0, z0))
            v1 = bm.verts.new((x0 + bar_w / 2, 0, z0))
            v2 = bm.verts.new((x1 + bar_w / 2, 0, z1))
            v3 = bm.verts.new((x1 - bar_w / 2, 0, z1))
            bm.faces.new([v0, v1, v2, v3])

        x += spacing

    mesh = bpy.data.meshes.new(f"lattice_{bldg_id}")
    bm.to_mesh(mesh)
    bm.free()

    lattice_obj = bpy.data.objects.new(f"lattice_{bldg_id}", mesh)
    bpy.context.collection.objects.link(lattice_obj)
    lattice_obj.location = (0, porch_d, 0)

    # Give thickness
    mod = lattice_obj.modifiers.new("Solidify", 'SOLIDIFY')
    mod.thickness = 0.02
    mod.offset = 0
    bpy.context.view_layer.objects.active = lattice_obj
    bpy.ops.object.modifier_apply(modifier=mod.name)

    assign_material(lattice_obj, lattice_mat)
    objects.append(lattice_obj)

    # Frame border around lattice panel
    frame_mat = create_wood_material(f"mat_lattice_frame_{trim_hex.lstrip('#')}", trim_hex)
    for fname, fscale, floc in [
        ("top", (porch_w, 0.03, 0.03), (0, porch_d, floor_h)),
        ("bot", (porch_w, 0.03, 0.03), (0, porch_d, 0.015)),
        ("left", (0.03, 0.03, floor_h), (-porch_w / 2, porch_d, floor_h / 2)),
        ("right", (0.03, 0.03, floor_h), (porch_w / 2, porch_d, floor_h / 2)),
    ]:
        bpy.ops.mesh.primitive_cube_add(size=1)
        fr = bpy.context.active_object
        fr.name = f"lattice_frame_{fname}_{bldg_id}"
        fr.scale = fscale
        bpy.ops.object.transform_apply(scale=True)
        fr.location = floc
        assign_material(fr, frame_mat)
        objects.append(fr)

    return objects



def create_step_handrails(params, facade_width, bldg_id=""):
    """Create metal handrails alongside porch steps."""
    porch_data = params.get("porch", {})
    if not isinstance(porch_data, dict):
        return []
    if not porch_data.get("present", porch_data.get("type")):
        return []

    steps_data = porch_data.get("steps", porch_data.get("stairs", {}))
    if not isinstance(steps_data, dict):
        return []

    step_count = steps_data.get("count", 3)
    floor_h = porch_data.get("floor_height_above_grade_m", 0.5)
    porch_d = porch_data.get("depth_m", 2.0)
    step_w = steps_data.get("width_m", 1.2)
    run = 0.28

    # Step x-offset (must match create_porch step placement)
    step_pos = str(steps_data.get("position", "center")).lower()
    porch_w = porch_data.get("width_m", facade_width)
    if "left" in step_pos:
        step_x = -porch_w / 4
    elif "right" in step_pos:
        step_x = porch_w / 4
    else:
        step_x = 0.0

    if step_count < 2:
        return []

    rail_mat = get_or_create_material("mat_handrail", colour_hex="#2A2A2A", roughness=0.25)
    # Wrought iron handrails: set metallic
    bsdf = rail_mat.node_tree.nodes.get("Principled BSDF")
    if bsdf and "Metallic" in bsdf.inputs:
        bsdf.inputs["Metallic"].default_value = 0.90
    objects = []

    total_run = step_count * run
    rail_len = math.sqrt(total_run ** 2 + floor_h ** 2)
    rail_angle = math.atan2(floor_h, total_run)

    for side, sx in [("L", step_x - step_w / 2 - 0.04), ("R", step_x + step_w / 2 + 0.04)]:
        # Sloped top rail
        bpy.ops.mesh.primitive_cylinder_add(radius=0.02, depth=rail_len, vertices=8)
        rail = bpy.context.active_object
        rail.name = f"handrail_{side}_{bldg_id}"
        rail.rotation_euler.x = math.pi / 2 - rail_angle
        rail.location = (sx, porch_d + total_run / 2, floor_h / 2 + 0.4)
        assign_material(rail, rail_mat)
        objects.append(rail)

        # Bottom newel post — thicker, decorative
        bot_post_h = 0.95
        bpy.ops.mesh.primitive_cylinder_add(radius=0.02, depth=bot_post_h, vertices=8)
        bp = bpy.context.active_object
        bp.name = f"rail_post_bot_{side}_{bldg_id}"
        bp.location = (sx, porch_d + total_run, bot_post_h / 2)
        assign_material(bp, rail_mat)
        objects.append(bp)

        # Newel cap ball
        bpy.ops.mesh.primitive_uv_sphere_add(radius=0.03, segments=8, ring_count=6)
        bc = bpy.context.active_object
        bc.name = f"rail_newel_bot_{side}_{bldg_id}"
        bc.location = (sx, porch_d + total_run, bot_post_h + 0.01)
        assign_material(bc, rail_mat)
        objects.append(bc)

        # Top newel post
        top_post_h = 0.95
        bpy.ops.mesh.primitive_cylinder_add(radius=0.02, depth=top_post_h, vertices=8)
        tp = bpy.context.active_object
        tp.name = f"rail_post_top_{side}_{bldg_id}"
        tp.location = (sx, porch_d, floor_h + top_post_h / 2)
        assign_material(tp, rail_mat)
        objects.append(tp)

        # Top newel cap
        bpy.ops.mesh.primitive_uv_sphere_add(radius=0.03, segments=8, ring_count=6)
        tc = bpy.context.active_object
        tc.name = f"rail_newel_top_{side}_{bldg_id}"
        tc.location = (sx, porch_d, floor_h + top_post_h + 0.01)
        assign_material(tc, rail_mat)
        objects.append(tc)

        # Intermediate balusters along stair slope
        baluster_spacing = 0.15
        num_balusters = max(1, int(total_run / baluster_spacing))
        for bi in range(1, num_balusters):
            frac = bi / num_balusters
            by = porch_d + total_run * (1 - frac)
            bz_base = floor_h * frac
            bz_top = bz_base + 0.85
            bal_h = bz_top - bz_base
            bpy.ops.mesh.primitive_cylinder_add(radius=0.008, depth=bal_h, vertices=6)
            bal = bpy.context.active_object
            bal.name = f"rail_baluster_{side}_{bi}_{bldg_id}"
            bal.location = (sx, by, bz_base + bal_h / 2)
            assign_material(bal, rail_mat)
            objects.append(bal)

    return objects



