"""
Step 2: Parametric Blender building generator.

Reads JSON building parameter files from Step 1 and creates detailed 3D
architectural geometry in Blender — walls, windows, doors, roofs, porches,
and decorative elements as actual mesh geometry.

Usage (run inside Blender):
    blender --background --python generate_building.py -- --params params/22_Lippincott_St.json
    blender --python generate_building.py -- --params params/  (all buildings)

Or from Blender scripting tab:
    exec(open('generate_building.py').read())
"""

import bpy
import bmesh
import addon_utils
import json
import math
import os
import sys
import time
from pathlib import Path
from mathutils import Vector, Matrix

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
PARAMS_DIR = Path(__file__).parent / "params" if "__file__" in dir() else Path("params")
DEFAULT_DEPTH = 10.0  # default building depth when not specified

# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------

def clear_scene():
    """Remove all objects from the scene."""
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    # Clean orphan data
    for block in bpy.data.meshes:
        if block.users == 0:
            bpy.data.meshes.remove(block)
    for block in bpy.data.materials:
        if block.users == 0:
            bpy.data.materials.remove(block)


def _safe_tan(degrees, lo=5.0, hi=85.0):
    """Return tan(degrees) with the angle clamped to [lo, hi] to avoid infinity.

    Roof pitches of 0° produce zero ridge height (harmless but wrong) and 90°
    makes tan() explode.  Clamping to 5-85° keeps geometry sane for the full
    param dataset.
    """
    clamped = max(lo, min(hi, float(degrees)))
    return math.tan(math.radians(clamped))


def _clamp_positive(value, default, minimum=0.5):
    """Return *value* if it is a positive number >= *minimum*, else *default*.

    Prevents zero-width / zero-depth / zero-height geometry that would crash
    bmesh boolean or produce degenerate cubes.
    """
    try:
        v = float(value)
        return v if v >= minimum else default
    except (TypeError, ValueError):
        return default



# ---------------------------------------------------------------------------
# Extracted modules
# ---------------------------------------------------------------------------
from generator_modules.colours import (  # noqa: E402
    hex_to_rgb, colour_name_to_hex, infer_hex_from_text,
    get_stone_hex, get_roof_hex, get_facade_hex, get_trim_hex,
    get_accent_hex, get_stone_element_hex,
    get_condition_roughness_bias, get_condition_saturation_shift,
    get_era_defaults, get_typology_hints, get_utility_anchor_height,
)
from generator_modules.materials import (  # noqa: E402
    _get_bsdf, get_or_create_material, _add_wall_coords,
    create_brick_material, create_wood_material,
    create_roof_material, create_metal_roof_material,
    create_copper_patina_material, select_roof_material,
    create_glass_material, create_stone_material,
    create_painted_material, create_canvas_material,
    assign_material,
)


from generator_modules.geometry import (  # noqa: E402
    create_box, _clean_mesh, boolean_cut,
    create_arch_cutter, create_rect_cutter,
)


def _merge_missing_dict(target, defaults):
    """Recursively merge dict defaults without overwriting explicit params."""
    for key, value in defaults.items():
        if key not in target:
            target[key] = value
        elif isinstance(target[key], dict) and isinstance(value, dict):
            _merge_missing_dict(target[key], value)


def apply_hcd_guide_defaults(params):
    """Derive structured generator hints from HCD guide metadata."""
    if not isinstance(params, dict):
        return params

    hcd = params.get("hcd_data", {})
    if not isinstance(hcd, dict):
        return params

    features = [str(f).lower() for f in hcd.get("building_features", [])]
    statement = str(hcd.get("statement_of_contribution", "")).lower()
    typology = str(hcd.get("typology", "")).lower()
    combined = features + [statement]

    def has(*phrases):
        return any(any(p in text for p in phrases) for text in combined)

    decorative = params.setdefault("decorative_elements", {})
    if not isinstance(decorative, dict):
        decorative = {}
        params["decorative_elements"] = decorative

    # Resolve stone decorative element colour from colour_palette.accent
    stone_hex = get_accent_hex(params)

    if has("string course", "string courses") and "string_courses" not in decorative:
        decorative["string_courses"] = {
            "present": True,
            "width_mm": 140,
            "projection_mm": 25,
            "colour_hex": stone_hex,
        }

    if has("quoin", "quoining") and "quoins" not in decorative:
        decorative["quoins"] = {
            "present": True,
            "strip_width_mm": 220,
            "projection_mm": 18,
            "colour_hex": stone_hex,
        }

    if has("voussoir", "voussoirs") and "stone_voussoirs" not in decorative and "voussoirs" not in decorative:
        decorative["stone_voussoirs"] = {
            "present": True,
            "colour_hex": stone_hex,
        }

    if has("stone lintel", "stone lintels", "stone sills") and "stone_lintels" not in decorative:
        decorative["stone_lintels"] = {
            "present": True,
            "colour_hex": stone_hex,
        }

    if has("bargeboard") and "bargeboard" not in decorative:
        decorative["bargeboard"] = {
            "present": True,
            "type": "decorative",
            "colour_hex": "#4A3324",
            "width_mm": 220,
        }

    if has("bracket", "brackets") and "gable_brackets" not in decorative:
        decorative["gable_brackets"] = {
            "type": "paired_scroll",
            "count": 4,
            "projection_mm": 220,
            "height_mm": 320,
            "colour_hex": "#4A3324",
        }

    if has("shingle", "shingles in gable") and "ornamental_shingles" not in decorative:
        decorative["ornamental_shingles"] = {
            "present": True,
            "colour_hex": "#6B4C3B",
            "exposure_mm": 110,
        }

    if has("cornice") and "cornice" not in decorative:
        decorative["cornice"] = {
            "present": True,
            "projection_mm": 180,
            "height_mm": 220,
            "colour_hex": stone_hex,
        }

    if has("bay window", "bay windows", "double-height bay", "double-height bays") and "bay_window" not in params:
        params["bay_window"] = {
            "present": True,
            "type": "Three-sided projecting bay" if "bay-and-gable" in typology else "Projecting bay",
            "floors": [0, 1] if ("bay-and-gable" in typology or has("double-height bay", "double-height bays")) else [0],
            "width_m": min(2.6, max(1.8, params.get("facade_width_m", 5.0) * 0.42)),
            "projection_m": 0.6,
        }

    if has("commercial storefront", "storefront", "commercial glazing") and not params.get("has_storefront"):
        params["has_storefront"] = True

    if params.get("has_storefront"):
        storefront = params.setdefault("storefront", {})
        if isinstance(storefront, dict):
            _merge_missing_dict(storefront, {
                "type": "Commercial ground floor",
                "width_m": params.get("facade_width_m", 6.0),
                "height_m": params.get("floor_heights_m", [3.5])[0] if params.get("floor_heights_m") else 3.5,
            })

    roof_features = params.setdefault("roof_features", [])
    if isinstance(roof_features, list):
        if has("dormer", "dormers") and "dormers" not in roof_features:
            roof_features.append("dormers")
        if has("chimney", "chimneys") and "chimney" not in roof_features:
            roof_features.append("chimney")
        if has("turret") and "tower" not in roof_features:
            roof_features.append("tower")

    roof_type = str(params.get("roof_type", ""))
    if not roof_type and "mansard" in statement:
        params["roof_type"] = "Mansard"

    return params


# ---------------------------------------------------------------------------
# Building element generators
# ---------------------------------------------------------------------------

from generator_modules.walls import create_walls  # noqa: E402
from generator_modules.windows import (  # noqa: E402
    _normalize_floor_index, _floor_has_window_spec,
    get_effective_windows_detail, cut_windows,
    create_bay_window, _create_box_bay, _create_canted_bay,
)
from generator_modules.doors import _resolve_doors, cut_doors  # noqa: E402
from generator_modules.roofs import (  # noqa: E402
    create_gable_walls, create_gable_roof,
    create_cross_gable_roof, create_hip_roof, create_flat_roof,
)

from generator_modules.storefront import (  # noqa: E402
    create_storefront, create_storefront_awning,
)
from generator_modules.structure import (  # noqa: E402
    create_porch, create_chimney, create_turned_posts,
    create_foundation, create_gutters, create_chimney_caps,
    create_porch_lattice, create_step_handrails,
)
from generator_modules.decorative import (  # noqa: E402
    create_string_courses,
    _create_corbel_band,
    _create_arch_voussoirs,
    create_corbelling,
    create_tower,
    create_quoins,
    create_bargeboard,
    create_cornice_band,
    create_stained_glass_transoms,
    create_hip_rooflet,
    create_window_lintels,
    create_brackets,
    create_ridge_finial,
    create_voussoirs,
    create_gable_shingles,
    create_dormer,
    create_fascia_boards,
    create_parapet_coping,
    create_gabled_parapet,
    create_window_shutters,
    create_address_plaque,
    create_utility_box,
    create_window_frames,
    create_downpipe_brackets,
    create_balconies,
    create_decorative_brickwork,
    create_pilasters,
    create_window_hoods,
    create_sign_band,
    create_sill_noses,
    create_door_transoms,
    create_ground_floor_arches,
    create_eave_returns,
    create_drip_edge,
    create_door_surround,
    create_soffit_vents,
    create_vent_pipes,
    create_mail_slot,
    create_kick_plate,
)

def generate_multi_volume(params, offset=(0, 0, 0)):
    """Generate a multi-volume building (like 132 Bellevue fire station)."""
    address = "unknown"
    meta = params.get("_meta", {})
    if isinstance(meta, dict):
        address = meta.get("address", "unknown")

    bldg_id = address.replace(" ", "_").replace(",", "").replace(".", "")
    print(f"[GENERATE MULTI-VOLUME] {address}")

    volumes = params.get("volumes", [])
    all_objs = []

    # Resolve bond pattern and polychrome for all volumes (inherited from main params)
    mv_bond = "running"
    fd_mv = params.get("facade_detail", {})
    if isinstance(fd_mv, dict):
        bp_mv = (fd_mv.get("bond_pattern") or "").lower()
        if bp_mv:
            mv_bond = bp_mv
    dfa_mv = params.get("deep_facade_analysis", {})
    if isinstance(dfa_mv, dict):
        bp_dfa_mv = (dfa_mv.get("brick_bond_observed") or "").lower()
        if bp_dfa_mv:
            mv_bond = bp_dfa_mv
    mv_polychrome = None
    if isinstance(dfa_mv, dict):
        poly_mv = dfa_mv.get("polychromatic_brick")
        if isinstance(poly_mv, dict):
            ph_mv = poly_mv.get("accent_hex", "")
            if ph_mv and ph_mv.startswith("#"):
                mv_polychrome = ph_mv

    # Track x position for placing volumes side by side
    total_width = 0
    for v in volumes:
        if not isinstance(v, dict):
            continue
        if v.get("stack_with_previous"):
            continue
        total_width += v.get("width_m", 5)
    x_cursor = -total_width / 2
    prev_cx = None

    def log_volume_feature(name, before_count):
        delta = len(all_objs) - before_count
        if delta > 0:
            print(f"    {name}: {delta} elements")

    def _obj_valid(o):
        try:
            return o is not None and o.name is not None
        except ReferenceError:
            return False

    def join_by_prefix(prefix, objs_list):
        """Join all objects whose name starts with prefix into a single mesh."""
        targets = []
        for o in objs_list:
            try:
                if o and o.name.startswith(prefix):
                    targets.append(o)
            except ReferenceError:
                continue
        if len(targets) < 2:
            return objs_list
        bpy.ops.object.select_all(action='DESELECT')
        for o in targets:
            o.select_set(True)
        bpy.context.view_layer.objects.active = targets[0]
        bpy.ops.object.join()
        joined = bpy.context.active_object
        joined.name = f"{prefix}{bldg_id}"
        new_list = [o for o in objs_list if _obj_valid(o) and o not in targets]
        new_list.append(joined)
        return new_list

    for vi, vol in enumerate(volumes):
        vol_id = vol.get("id", f"vol_{vi}")
        vol_w = _clamp_positive(vol.get("width_m"), 5.0, minimum=1.0)
        vol_d = _clamp_positive(vol.get("depth_m"), 10.0, minimum=1.0)
        vol_floors = vol.get("floor_heights_m", [3.5])
        if not vol_floors or not isinstance(vol_floors, list):
            vol_floors = [3.5]
        vol_h = sum(max(0.5, float(fh)) for fh in vol_floors)
        vol_total_h = _clamp_positive(vol.get("total_height_m"), vol_h, minimum=2.0)

        print(f"  Volume: {vol_id} ({vol_w}m x {vol_d}m x {vol_total_h}m)")

        # Volume center x
        stack_with_previous = bool(vol.get("stack_with_previous", False))
        if stack_with_previous and prev_cx is not None:
            vol_cx = prev_cx
        else:
            vol_cx = x_cursor + vol_w / 2
        vol_cx += float(vol.get("x_offset_m", 0.0))
        vol_y_off = float(vol.get("y_offset_m", 0.0))
        vol_z_off = float(vol.get("z_offset_m", 0.0))
        vol_start_idx = len(all_objs)

        # Facade material
        fc = str(vol.get("facade_colour", vol.get("facade_material", "brick"))).lower()
        if "glass" in fc or "curtain" in fc:
            vol_hex = "#5A6A7A"
        else:
            vol_hex = infer_hex_from_text(vol.get("facade_colour", ""), vol.get("facade_material", ""), default=get_facade_hex(params))

        mat_type = str(vol.get("facade_material", "brick")).lower()
        mortar_hex = "#8A8A8A"

        if vol_id == "clock_tower":
            # Tall square tower
            outer = create_box(f"tower_walls_{bldg_id}", vol_w, vol_d, vol_total_h,
                               location=(vol_cx, 0, 0))
            inner = create_box(f"tower_inner_{bldg_id}",
                               vol_w - 0.5, vol_d - 0.5, vol_total_h + 0.02,
                               location=(vol_cx, 0, -0.01))
            boolean_cut(outer, inner)
            outer.name = f"tower_{bldg_id}"

            tower_mat = create_brick_material(f"mat_tower_{vol_hex.lstrip('#')}",
                                               vol_hex, mortar_hex,
                                               bond_pattern=mv_bond,
                                               polychrome_hex=mv_polychrome)
            assign_material(outer, tower_mat)
            all_objs.append(outer)
            tower_string_course_count = 0

            # Corner treatment: shallow brick pilaster/quoins
            corner_text = json.dumps(vol.get("decorative_elements", {})).lower()
            if "corner_treatment" in vol.get("decorative_elements", {}) or "quoin" in corner_text or "pilaster" in corner_text:
                corner_start = len(all_objs)
                pil_w = 0.12
                pil_proj = 0.04
                for sx in (-1, 1):
                    for sy in (-1, 1):
                        bpy.ops.mesh.primitive_cube_add(size=1)
                        pil = bpy.context.active_object
                        pil.name = f"tower_corner_{sx}_{sy}_{bldg_id}"
                        pil.scale = (pil_w, pil_proj, vol_total_h)
                        bpy.ops.object.transform_apply(scale=True)
                        pil.location = (
                            vol_cx + sx * (vol_w / 2 - pil_w / 2),
                            -vol_d / 2 + sy * (vol_d / 2 - pil_proj / 2),
                            vol_total_h / 2,
                        )
                        assign_material(pil, tower_mat)
                        all_objs.append(pil)
                log_volume_feature("Tower corner treatment", corner_start)

            # String courses between levels
            level_details = vol.get("level_details", [])
            z_acc = 0
            for li, ld in enumerate(level_details):
                lh = ld.get("height_m", 3.5)
                z_acc += lh
                if li < len(level_details) - 1:
                    bpy.ops.mesh.primitive_cube_add(size=1)
                    sc = bpy.context.active_object
                    sc.name = f"tower_sc_{li}_{bldg_id}"
                    sc.scale = (vol_w + 0.06, vol_d + 0.06, 0.06)
                    bpy.ops.object.transform_apply(scale=True)
                    sc.location = (vol_cx, -vol_d / 2, z_acc)
                    stone_mat = create_stone_material("mat_stone_sc", "#C0B8A0")
                    assign_material(sc, stone_mat)
                    all_objs.append(sc)
                    tower_string_course_count += 1
                win_start = len(all_objs)
                # Windows for this level
                wins = ld.get("windows", [])
                for wi, w_spec in enumerate(wins):
                    if not isinstance(w_spec, dict):
                        continue
                    ww = w_spec.get("width_m", 0.5)
                    wh = w_spec.get("height_m", 0.7)
                    wz = z_acc - lh / 2
                    # Glass + frame on front face
                    bpy.ops.mesh.primitive_plane_add(size=1)
                    gl = bpy.context.active_object
                    gl.name = f"tower_glass_{li}_{bldg_id}"
                    gl.scale = (ww * 0.85, 1, wh * 0.85)
                    bpy.ops.object.transform_apply(scale=True)
                    gl.rotation_euler.x = math.pi / 2
                    gl.location = (vol_cx, 0.02, wz)
                    assign_material(gl, create_glass_material())
                    all_objs.append(gl)
                log_volume_feature(f"Tower level {li + 1} windows", win_start)

                clock_start = len(all_objs)
                # Clock face
                clock = ld.get("clock_face", {})
                if isinstance(clock, dict) and clock:
                    diam = clock.get("diameter_m", 1.5)
                    clock_z = z_acc - lh / 2
                    bpy.ops.mesh.primitive_circle_add(
                        radius=diam / 2, vertices=32, fill_type='NGON')
                    cf = bpy.context.active_object
                    cf.name = f"clock_face_{bldg_id}"
                    cf.rotation_euler.x = math.pi / 2
                    cf.location = (vol_cx, 0.16, clock_z)
                    clock_mat = get_or_create_material("mat_clock_face",
                                                        colour_hex="#F0F0F0", roughness=0.3)
                    assign_material(cf, clock_mat)
                    all_objs.append(cf)

                    surround_text = str(clock.get("surround", "")).lower()
                    if "frame" in surround_text or "stone" in surround_text or "brick" in surround_text:
                        bpy.ops.mesh.primitive_torus_add(
                            major_radius=diam / 2 + 0.12,
                            minor_radius=0.06,
                            major_segments=32,
                            minor_segments=10,
                        )
                        ring = bpy.context.active_object
                        ring.name = f"clock_surround_{li}_{bldg_id}"
                        ring.rotation_euler.x = math.pi / 2
                        ring.location = (vol_cx, 0.17, clock_z)
                        surround_hex = get_stone_hex(clock.get("surround", ""), default="#C8C0B0")
                        surround_mat = create_stone_material("mat_clock_surround", surround_hex)
                        assign_material(ring, surround_mat)
                        all_objs.append(ring)

                    # Clock hands (hour + minute)
                    hand_mat = get_or_create_material("mat_clock_hands",
                                                       colour_hex="#1A1A1A", roughness=0.5)
                    for hname, hlen, hangle in [("hour", diam * 0.25, 60), ("min", diam * 0.35, 160)]:
                        bpy.ops.mesh.primitive_cube_add(size=1)
                        hand = bpy.context.active_object
                        hand.name = f"clock_{hname}_{bldg_id}"
                        hand.scale = (0.02, 0.01, hlen)
                        bpy.ops.object.transform_apply(scale=True)
                        hand.location = (vol_cx, 0.18, clock_z)
                        hand.rotation_euler.y = math.radians(hangle)
                        assign_material(hand, hand_mat)
                        all_objs.append(hand)
                log_volume_feature(f"Tower level {li + 1} clock detail", clock_start)

                corbel_start = len(all_objs)
                # Decorative corbel band below parapet or upper tower stages
                parapet_info = ld.get("parapet", {})
                ld_text = json.dumps(ld).lower()
                if ("corbel" in ld_text or "corbelling" in ld_text or
                        (isinstance(parapet_info, dict) and "corbel" in json.dumps(parapet_info).lower())):
                    course_count = 3
                    if "5" in ld_text:
                        course_count = 5
                    elif "4" in ld_text:
                        course_count = 4
                    all_objs.extend(_create_corbel_band(
                        f"tower_corbel_{li}_{bldg_id}",
                        vol_cx,
                        0.02,
                        z_acc - 0.32,
                        vol_w,
                        course_count=course_count,
                        colour_hex=vol_hex,
                    ))
                log_volume_feature(f"Tower level {li + 1} corbelling", corbel_start)

            if tower_string_course_count:
                print(f"    Tower string courses: {tower_string_course_count} elements")

            # Tower parapet
            parapet_start = len(all_objs)
            top_level = level_details[-1] if level_details else {}
            parapet = top_level.get("parapet", {})
            if isinstance(parapet, dict) and parapet:
                ph = parapet.get("height_m", 0.8)
                for side, sc, loc in [
                    ("f", (vol_w, 0.15, ph), (vol_cx, 0, vol_total_h + ph / 2)),
                    ("b", (vol_w, 0.15, ph), (vol_cx, -vol_d, vol_total_h + ph / 2)),
                    ("l", (0.15, vol_d, ph), (vol_cx - vol_w / 2, -vol_d / 2, vol_total_h + ph / 2)),
                    ("r", (0.15, vol_d, ph), (vol_cx + vol_w / 2, -vol_d / 2, vol_total_h + ph / 2)),
                ]:
                    bpy.ops.mesh.primitive_cube_add(size=1)
                    pw = bpy.context.active_object
                    pw.name = f"tower_parapet_{side}_{bldg_id}"
                    pw.scale = sc
                    bpy.ops.object.transform_apply(scale=True)
                    pw.location = loc
                    assign_material(pw, tower_mat)
                    all_objs.append(pw)

                # Coping cap
                bpy.ops.mesh.primitive_cube_add(size=1)
                cap = bpy.context.active_object
                cap.name = f"tower_coping_{bldg_id}"
                cap.scale = (vol_w + 0.1, vol_d + 0.1, 0.06)
                bpy.ops.object.transform_apply(scale=True)
                cap.location = (vol_cx, -vol_d / 2, vol_total_h + ph + 0.03)
                coping_mat = get_or_create_material("mat_coping", colour_hex="#8A8A8A", roughness=0.3)
                assign_material(cap, coping_mat)
                all_objs.append(cap)
            log_volume_feature("Tower parapet/coping", parapet_start)

            # Optional open belfry + spire cap
            spire_start = len(all_objs)
            spire = vol.get("spire", {})
            if isinstance(spire, dict) and spire:
                spire_h = float(spire.get("height_m", 4.0))
                spire_w = float(spire.get("base_width_m", vol_w * 0.9))
                spire_d = float(spire.get("base_depth_m", vol_d * 0.9))
                spire_style = str(spire.get("style", "pyramid")).lower()

                if "open" in spire_style or spire.get("open_belfry", False):
                    # Four slender corner posts at top stage
                    post_w = max(0.08, min(0.16, spire_w * 0.08))
                    post_d = post_w
                    post_h = max(0.8, spire_h * 0.45)
                    for sx in (-1, 1):
                        for sy in (-1, 1):
                            bpy.ops.mesh.primitive_cube_add(size=1)
                            post = bpy.context.active_object
                            post.name = f"tower_belfry_post_{sx}_{sy}_{bldg_id}"
                            post.scale = (post_w, post_d, post_h)
                            bpy.ops.object.transform_apply(scale=True)
                            post.location = (
                                vol_cx + sx * (spire_w / 2 - post_w / 2),
                                -vol_d / 2 + sy * (spire_d / 2 - post_d / 2),
                                vol_total_h + post_h / 2,
                            )
                            assign_material(post, tower_mat)
                            all_objs.append(post)

                # Spire body
                bm = bmesh.new()
                hw = spire_w / 2
                hd = spire_d / 2
                z0 = vol_total_h + 0.02
                apex = bm.verts.new((vol_cx, -vol_d / 2, z0 + spire_h))
                v0 = bm.verts.new((vol_cx - hw, -vol_d / 2 - hd, z0))
                v1 = bm.verts.new((vol_cx + hw, -vol_d / 2 - hd, z0))
                v2 = bm.verts.new((vol_cx + hw, -vol_d / 2 + hd, z0))
                v3 = bm.verts.new((vol_cx - hw, -vol_d / 2 + hd, z0))
                bm.faces.new([v0, v1, apex])
                bm.faces.new([v1, v2, apex])
                bm.faces.new([v2, v3, apex])
                bm.faces.new([v3, v0, apex])
                bm.faces.new([v0, v3, v2, v1])
                smesh = bpy.data.meshes.new(f"tower_spire_{bldg_id}")
                bm.to_mesh(smesh)
                bm.free()
                sobj = bpy.data.objects.new(f"tower_spire_{bldg_id}", smesh)
                bpy.context.collection.objects.link(sobj)
                spire_hex = str(spire.get("colour_hex", "#2E3138"))
                if not spire_hex.startswith("#"):
                    spire_hex = colour_name_to_hex(spire_hex)
                spire_mat = get_or_create_material(f"mat_tower_spire_{spire_hex.lstrip('#')}", colour_hex=spire_hex, roughness=0.65)
                assign_material(sobj, spire_mat)
                all_objs.append(sobj)

                if spire.get("cross", False):
                    bpy.ops.mesh.primitive_cube_add(size=1)
                    cross_v = bpy.context.active_object
                    cross_v.name = f"tower_cross_v_{bldg_id}"
                    cross_v.scale = (0.04, 0.04, 0.45)
                    bpy.ops.object.transform_apply(scale=True)
                    cross_v.location = (vol_cx, -vol_d / 2, z0 + spire_h + 0.25)
                    assign_material(cross_v, get_or_create_material("mat_tower_cross", colour_hex="#8A8A8A", roughness=0.4))
                    all_objs.append(cross_v)
                    bpy.ops.mesh.primitive_cube_add(size=1)
                    cross_h = bpy.context.active_object
                    cross_h.name = f"tower_cross_h_{bldg_id}"
                    cross_h.scale = (0.18, 0.04, 0.04)
                    bpy.ops.object.transform_apply(scale=True)
                    cross_h.location = (vol_cx, -vol_d / 2, z0 + spire_h + 0.25)
                    assign_material(cross_h, get_or_create_material("mat_tower_cross", colour_hex="#8A8A8A", roughness=0.4))
                    all_objs.append(cross_h)
            log_volume_feature("Tower spire", spire_start)

            vegetation_start = len(all_objs)
            vegetation = top_level.get("vegetation", {})
            if isinstance(vegetation, dict) and vegetation:
                coverage = vegetation.get("coverage_percent", 10)
                tuft_count = max(2, min(8, int(coverage / 2)))
                veg_mat = get_or_create_material("mat_tower_vegetation", colour_hex="#5D6F3A", roughness=0.95)
                for ti in range(tuft_count):
                    fx = ((ti % 3) - 1) * (vol_w * 0.18)
                    fy = ((ti // 3) - 0.5) * (vol_d * 0.18)
                    bpy.ops.mesh.primitive_uv_sphere_add(radius=0.10 + (ti % 2) * 0.03, segments=8, ring_count=6)
                    tuft = bpy.context.active_object
                    tuft.name = f"tower_veg_{ti}_{bldg_id}"
                    tuft.scale.z = 0.6
                    tuft.location = (vol_cx + fx, -vol_d / 2 + fy, vol_total_h + ph + 0.08)
                    assign_material(tuft, veg_mat)
                    all_objs.append(tuft)
            log_volume_feature("Tower vegetation", vegetation_start)

        elif vol_id == "modern_addition":
            # Glass curtain wall building
            outer = create_box(f"modern_walls_{bldg_id}", vol_w, vol_d, vol_h,
                               location=(vol_cx, 0, 0))
            inner = create_box(f"modern_inner_{bldg_id}",
                               vol_w - 0.4, vol_d - 0.4, vol_h + 0.02,
                               location=(vol_cx, 0, -0.01))
            boolean_cut(outer, inner)
            outer.name = f"modern_{bldg_id}"

            # Brick base
            base = vol.get("base", {})
            base_h = base.get("height_m", 1.0) if isinstance(base, dict) else 1.0
            base_mat = create_brick_material(f"mat_modern_base_{vol_hex.lstrip('#')}",
                                              "#B85A3A", mortar_hex,
                                              bond_pattern=mv_bond)
            assign_material(outer, base_mat)
            all_objs.append(outer)

            # Curtain wall bays
            curtain_start = len(all_objs)
            cw = vol.get("curtain_wall", {})
            if isinstance(cw, dict):
                bay_count = cw.get("bay_count", 4)
                bay_w = cw.get("bay_width_m", 2.2)
                bay_h = cw.get("bay_height_m", 5.5)
                mullion_w = cw.get("mullion_width_mm", 80) / 1000.0
                band_count = max(1, int(cw.get("band_count", 1) or 1))
                band_gap = float(cw.get("band_gap_m", 0.35) or 0.35)
                z_base = float(cw.get("z_base_m", base_h) or base_h)
                add_mid_mullion = bool(cw.get("mid_mullion", True))

                glass_mat = create_glass_material("mat_curtain_glass", glass_type="storefront")
                mullion_hex = cw.get("mullion_colour", "#2A2A2A")
                if not mullion_hex.startswith("#"):
                    mullion_hex = "#2A2A2A"
                mullion_mat = get_or_create_material("mat_mullion", colour_hex=mullion_hex, roughness=0.4)

                cw_start_x = vol_cx - (bay_count * bay_w) / 2 + bay_w / 2
                for ri in range(band_count):
                    cw_z = z_base + bay_h / 2 + ri * (bay_h + band_gap)
                    for bi in range(bay_count):
                        bx = cw_start_x + bi * bay_w

                        # Glass panel
                        bpy.ops.mesh.primitive_plane_add(size=1)
                        gp = bpy.context.active_object
                        gp.name = f"curtain_glass_{ri}_{bi}_{bldg_id}"
                        gp.scale = (bay_w - mullion_w, 1, bay_h)
                        bpy.ops.object.transform_apply(scale=True)
                        gp.rotation_euler.x = math.pi / 2
                        gp.location = (bx, 0.16, cw_z)
                        assign_material(gp, glass_mat)
                        all_objs.append(gp)

                        # Vertical mullion (right side of each bay)
                        bpy.ops.mesh.primitive_cube_add(size=1)
                        mul = bpy.context.active_object
                        mul.name = f"mullion_{ri}_{bi}_{bldg_id}"
                        mul.scale = (mullion_w, 0.08, bay_h)
                        bpy.ops.object.transform_apply(scale=True)
                        mul.location = (bx + bay_w / 2, 0.14, cw_z)
                        assign_material(mul, mullion_mat)
                        all_objs.append(mul)

                    # Horizontal mullion at mid height (optional)
                    if add_mid_mullion:
                        bpy.ops.mesh.primitive_cube_add(size=1)
                        hmul = bpy.context.active_object
                        hmul.name = f"mullion_h_{ri}_{bldg_id}"
                        hmul.scale = (bay_count * bay_w, 0.08, mullion_w)
                        bpy.ops.object.transform_apply(scale=True)
                        hmul.location = (vol_cx, 0.14, cw_z)
                        assign_material(hmul, mullion_mat)
                        all_objs.append(hmul)
            log_volume_feature("Curtain wall", curtain_start)

            # Explicit openings for modern blocks (optional, used for coarse facade cut-ins)
            modern_openings_start = len(all_objs)
            win_rows = vol.get("window_rows", [])
            if isinstance(win_rows, list):
                for ri, row in enumerate(win_rows):
                    if not isinstance(row, dict):
                        continue
                    count = int(row.get("count", 0) or 0)
                    if count <= 0:
                        continue
                    ww = float(row.get("width_m", 1.2))
                    wh = float(row.get("height_m", 1.0))
                    sill = float(row.get("sill_height_m", 1.0))
                    row_z_off = float(row.get("z_offset_m", 0.0) or 0.0)
                    row_x_off = float(row.get("x_offset_m", 0.0) or 0.0)
                    spacing = vol_w / (count + 1)
                    frame_hex = str(row.get("frame_colour", "#2F3A52"))
                    if not frame_hex.startswith("#"):
                        frame_hex = colour_name_to_hex(frame_hex)
                    frame_mat = get_or_create_material(f"mat_modern_frame_{frame_hex.lstrip('#')}", colour_hex=frame_hex, roughness=0.45)
                    add_frames = bool(row.get("add_frames", True))
                    positions = row.get("positions_m", [])
                    use_positions = isinstance(positions, list) and len(positions) > 0

                    iter_count = len(positions) if use_positions else count
                    for wi in range(iter_count):
                        if use_positions:
                            wx = vol_cx + float(positions[wi] or 0.0) + row_x_off
                        else:
                            wx = vol_cx - vol_w / 2 + spacing * (wi + 1) + row_x_off
                        cutter = create_rect_cutter(f"modern_win_cut_{ri}_{wi}_{bldg_id}", ww, wh, depth=0.8)
                        cutter.location.x = wx
                        cutter.location.y = 0.01
                        cutter.location.z = sill + row_z_off + wh / 2
                        boolean_cut(outer, cutter)

                        bpy.ops.mesh.primitive_plane_add(size=1)
                        gl = bpy.context.active_object
                        gl.name = f"modern_glass_{ri}_{wi}_{bldg_id}"
                        gl.scale = (ww * 0.88, 1, wh * 0.88)
                        bpy.ops.object.transform_apply(scale=True)
                        gl.rotation_euler.x = math.pi / 2
                        gl.location = (wx, 0.02, sill + row_z_off + wh / 2)
                        assign_material(gl, create_glass_material())
                        all_objs.append(gl)

                        if add_frames:
                            ft = 0.04
                            for fn, fs, fl in [
                                ("t", (ww + ft, 0.05, ft), (wx, 0.03, sill + row_z_off + wh)),
                                ("b", (ww + ft, 0.05, ft), (wx, 0.03, sill + row_z_off)),
                                ("l", (ft, 0.05, wh), (wx - ww / 2, 0.03, sill + row_z_off + wh / 2)),
                                ("r", (ft, 0.05, wh), (wx + ww / 2, 0.03, sill + row_z_off + wh / 2)),
                            ]:
                                bpy.ops.mesh.primitive_cube_add(size=1)
                                fr = bpy.context.active_object
                                fr.name = f"modern_frame_{fn}_{ri}_{wi}_{bldg_id}"
                                fr.scale = fs
                                bpy.ops.object.transform_apply(scale=True)
                                fr.location = fl
                                assign_material(fr, frame_mat)
                                all_objs.append(fr)
                        if row.get("add_horizontal_mullion", False):
                            bpy.ops.mesh.primitive_cube_add(size=1)
                            hbar = bpy.context.active_object
                            hbar.name = f"modern_hmullion_{ri}_{bldg_id}"
                            hbar.scale = (vol_w / 2, 0.03, 0.015)
                            bpy.ops.object.transform_apply(scale=True)
                            hbar.location = (vol_cx, 0.14, sill + row_z_off + wh / 2)
                            assign_material(hbar, frame_mat)
                            all_objs.append(hbar)

            vol_doors = vol.get("doors_detail", [])
            if isinstance(vol_doors, list):
                door_hex = str(vol.get("door_colour_hex", "#2F3A52"))
                if not door_hex.startswith("#"):
                    door_hex = colour_name_to_hex(door_hex)
                door_roughness = float(vol.get("door_roughness", 0.45) or 0.45)
                door_mat = get_or_create_material(
                    f"mat_modern_door_{door_hex.lstrip('#')}",
                    colour_hex=door_hex,
                    roughness=door_roughness,
                )
                for di, ds in enumerate(vol_doors):
                    if not isinstance(ds, dict):
                        continue
                    dw = float(ds.get("width_m", 1.2))
                    dh = float(ds.get("height_m", 2.2))
                    dpos = str(ds.get("position", "center")).lower()
                    if "left" in dpos:
                        dx = vol_cx - vol_w * 0.28
                    elif "right" in dpos:
                        dx = vol_cx + vol_w * 0.28
                    else:
                        dx = vol_cx
                    dx += float(ds.get("x_offset_m", 0.0) or 0.0)

                    cutter = create_rect_cutter(f"modern_door_cut_{di}_{bldg_id}", dw, dh, depth=0.8)
                    cutter.location.x = dx
                    cutter.location.y = 0.01
                    cutter.location.z = dh / 2
                    boolean_cut(outer, cutter)

                    bpy.ops.mesh.primitive_cube_add(size=1)
                    dmesh = bpy.context.active_object
                    dmesh.name = f"modern_door_{di}_{bldg_id}"
                    dmesh.scale = (dw * 0.92, 0.03, dh * 0.96)
                    bpy.ops.object.transform_apply(scale=True)
                    dmesh.location = (dx, 0.03, dh / 2)
                    assign_material(dmesh, door_mat)
                    all_objs.append(dmesh)
                    frame_depth = float(ds.get("frame_depth_m", 0.04) or 0.04)
                    frame_mat = get_or_create_material(f"mat_modern_doorframe_{door_hex.lstrip('#')}", colour_hex=door_hex, roughness=door_roughness)
                    for fn, fl_offset in (("left", -dw / 2), ("right", dw / 2)):
                        bpy.ops.mesh.primitive_cube_add(size=1)
                        df = bpy.context.active_object
                        df.name = f"door_frame_{fn}_{di}_{bldg_id}"
                        df.scale = (0.02, frame_depth / 2, dh)
                        bpy.ops.object.transform_apply(scale=True)
                        x_off = dx + fl_offset
                        df.location = (x_off, 0.02, dh / 2)
                        assign_material(df, frame_mat)
                        all_objs.append(df)
            log_volume_feature("Modern explicit openings", modern_openings_start)

            # Flat roof
            modern_roof_start = len(all_objs)
            if not bool(vol.get("skip_flat_roof", False)):
                bpy.ops.mesh.primitive_plane_add(size=1)
                mroof = bpy.context.active_object
                mroof.name = f"modern_roof_{bldg_id}"
                mroof.scale = (vol_w + 0.1, vol_d + 0.1, 1)
                bpy.ops.object.transform_apply(scale=True)
                mroof.location = (vol_cx, -vol_d / 2, vol_h + 0.01)
                roof_mat = get_or_create_material("mat_roof_flat_modern", colour_hex="#4A4A4A", roughness=0.9)
                assign_material(mroof, roof_mat)
                all_objs.append(mroof)

            # Optional roofline proxy details (parapet/fascia/canopy posts)
            roofline_start = len(all_objs)
            parapet_h = float(vol.get("parapet_height_m", 0.0) or 0.0)
            parapet_t = float(vol.get("parapet_thickness_m", 0.18) or 0.18)
            fascia_d = float(vol.get("fascia_depth_m", 0.0) or 0.0)
            fascia_h = float(vol.get("fascia_height_m", 0.35) or 0.35)
            trim_hex = str(vol.get("trim_colour_hex", get_trim_hex(params)))
            if not trim_hex.startswith("#"):
                trim_hex = colour_name_to_hex(trim_hex)
            trim_roughness = float(vol.get("trim_roughness", 0.55) or 0.55)
            trim_mat = get_or_create_material(
                f"mat_modern_trim_{trim_hex.lstrip('#')}",
                colour_hex=trim_hex,
                roughness=trim_roughness,
            )

            if parapet_h > 0.01:
                # Front
                bpy.ops.mesh.primitive_cube_add(size=1)
                pf = bpy.context.active_object
                pf.name = f"modern_parapet_f_{bldg_id}"
                pf.scale = (vol_w / 2, parapet_t / 2, parapet_h / 2)
                bpy.ops.object.transform_apply(scale=True)
                pf.location = (vol_cx, parapet_t / 2, vol_h + parapet_h / 2)
                assign_material(pf, trim_mat)
                all_objs.append(pf)
                # Back
                bpy.ops.mesh.primitive_cube_add(size=1)
                pb = bpy.context.active_object
                pb.name = f"modern_parapet_b_{bldg_id}"
                pb.scale = (vol_w / 2, parapet_t / 2, parapet_h / 2)
                bpy.ops.object.transform_apply(scale=True)
                pb.location = (vol_cx, -vol_d - parapet_t / 2, vol_h + parapet_h / 2)
                assign_material(pb, trim_mat)
                all_objs.append(pb)
                # Left
                bpy.ops.mesh.primitive_cube_add(size=1)
                pl = bpy.context.active_object
                pl.name = f"modern_parapet_l_{bldg_id}"
                pl.scale = (parapet_t / 2, vol_d / 2 + parapet_t, parapet_h / 2)
                bpy.ops.object.transform_apply(scale=True)
                pl.location = (vol_cx - vol_w / 2 - parapet_t / 2, -vol_d / 2, vol_h + parapet_h / 2)
                assign_material(pl, trim_mat)
                all_objs.append(pl)
                # Right
                bpy.ops.mesh.primitive_cube_add(size=1)
                pr = bpy.context.active_object
                pr.name = f"modern_parapet_r_{bldg_id}"
                pr.scale = (parapet_t / 2, vol_d / 2 + parapet_t, parapet_h / 2)
                bpy.ops.object.transform_apply(scale=True)
                pr.location = (vol_cx + vol_w / 2 + parapet_t / 2, -vol_d / 2, vol_h + parapet_h / 2)
                assign_material(pr, trim_mat)
                all_objs.append(pr)

            if fascia_d > 0.01:
                bpy.ops.mesh.primitive_cube_add(size=1)
                fb = bpy.context.active_object
                fb.name = f"modern_fascia_{bldg_id}"
                fb.scale = (vol_w / 2, fascia_d / 2, fascia_h / 2)
                bpy.ops.object.transform_apply(scale=True)
                fb.location = (vol_cx, fascia_d / 2, vol_h - fascia_h / 2)
                assign_material(fb, trim_mat)
                all_objs.append(fb)

            post_count = int(vol.get("canopy_post_count", 0) or 0)
            if post_count > 0:
                post_w = float(vol.get("canopy_post_width_m", 0.25) or 0.25)
                post_d = float(vol.get("canopy_post_depth_m", 0.25) or 0.25)
                post_h = float(vol.get("canopy_post_height_m", max(2.4, vol_h - 0.08)) or max(2.4, vol_h - 0.08))
                post_inset = float(vol.get("canopy_post_inset_m", 0.4) or 0.4)
                door_hex = str(vol.get("door_colour_hex", "#2F3A52"))
                if not door_hex.startswith("#"):
                    door_hex = colour_name_to_hex(door_hex)
                post_roughness = float(vol.get("post_roughness", 0.6) or 0.6)
                post_mat = get_or_create_material(
                    f"mat_canopy_post_{door_hex.lstrip('#')}",
                    colour_hex=door_hex,
                    roughness=post_roughness,
                )
                denom = post_count + 1
                for pi in range(post_count):
                    px = vol_cx - vol_w / 2 + (pi + 1) * (vol_w / denom)
                    bpy.ops.mesh.primitive_cube_add(size=1)
                    post = bpy.context.active_object
                    post.name = f"canopy_post_{pi}_{bldg_id}"
                    post.scale = (post_w / 2, post_d / 2, post_h / 2)
                    bpy.ops.object.transform_apply(scale=True)
                    post.location = (px, post_inset, post_h / 2)
                    assign_material(post, post_mat)
                    all_objs.append(post)

                beam_h = float(vol.get("canopy_beam_height_m", 0.0) or 0.0)
                if beam_h > 0.01:
                    beam_d = float(vol.get("canopy_beam_depth_m", 0.2) or 0.2)
                    beam_z = float(vol.get("canopy_beam_z_m", post_h) or post_h)
                    beam_w = max(0.4, vol_w - 2 * post_inset)
                    bpy.ops.mesh.primitive_cube_add(size=1)
                    beam = bpy.context.active_object
                    beam.name = f"canopy_beam_{bldg_id}"
                    beam.scale = (beam_w / 2, beam_d / 2, beam_h / 2)
                    bpy.ops.object.transform_apply(scale=True)
                    beam.location = (vol_cx, post_inset, beam_z - beam_h / 2)
                    assign_material(beam, post_mat)
                    all_objs.append(beam)

            roof_units = vol.get("roof_units", [])
            if isinstance(roof_units, list):
                for ui, unit in enumerate(roof_units):
                    if not isinstance(unit, dict):
                        continue
                    uw = float(unit.get("width_m", 1.2) or 1.2)
                    ud = float(unit.get("depth_m", 1.0) or 1.0)
                    uh = float(unit.get("height_m", 0.8) or 0.8)
                    ux = float(unit.get("x_offset_m", 0.0) or 0.0)
                    uy = float(unit.get("y_offset_m", -vol_d * 0.5) or -vol_d * 0.5)
                    uz = float(unit.get("z_offset_m", vol_h + 0.05) or (vol_h + 0.05))
                    bpy.ops.mesh.primitive_cube_add(size=1)
                    ru = bpy.context.active_object
                    ru.name = f"roof_unit_{ui}_{bldg_id}"
                    ru.scale = (uw / 2, ud / 2, uh / 2)
                    bpy.ops.object.transform_apply(scale=True)
                    ru.location = (vol_cx + ux, uy, uz + uh / 2)
                    unit_roughness = float(unit.get("roughness", 0.7) or 0.7)
                    unit_mat = get_or_create_material(
                        f"mat_roof_unit_{ui}_{bldg_id}",
                        colour_hex="#6A7078",
                        roughness=unit_roughness,
                    )
                    assign_material(ru, unit_mat)
                    all_objs.append(ru)

            pickets = vol.get("fence_pickets", {})
            if isinstance(pickets, dict) and pickets:
                count = max(2, int(pickets.get("count", 24) or 24))
                pw = float(pickets.get("width_m", 0.07) or 0.07)
                pd = float(pickets.get("depth_m", 0.05) or 0.05)
                ph = float(pickets.get("height_m", max(1.2, vol_h - 0.2)) or max(1.2, vol_h - 0.2))
                inset = float(pickets.get("inset_m", 0.02) or 0.02)
                lift = float(pickets.get("lift_m", 0.0) or 0.0)
                phex = str(pickets.get("colour_hex", "#B99661"))
                if not phex.startswith("#"):
                    phex = colour_name_to_hex(phex)
                pmat = get_or_create_material(f"mat_fence_picket_{phex.lstrip('#')}", colour_hex=phex, roughness=0.85)
                for pi in range(count):
                    px = vol_cx - vol_w / 2 + (pi + 0.5) * (vol_w / count)
                    bpy.ops.mesh.primitive_cube_add(size=1)
                    pk = bpy.context.active_object
                    pk.name = f"fence_picket_{pi}_{bldg_id}"
                    pk.scale = (pw / 2, pd / 2, ph / 2)
                    bpy.ops.object.transform_apply(scale=True)
                    pk.location = (px, inset, lift + ph / 2)
                    assign_material(pk, pmat)
                    all_objs.append(pk)
            lights = vol.get("sidewalk_lights", [])
            if isinstance(lights, list) and lights:
                light_color = str(lights[0].get("colour_hex", "#F7E85C"))
                if not light_color.startswith("#"):
                    light_color = colour_name_to_hex(light_color)
                light_mat = get_or_create_material("mat_sidewalk_light", colour_hex=light_color, roughness=0.15)
                pole_mat = get_or_create_material("mat_sidewalk_pole", colour_hex="#0E0E0E", roughness=0.35)
                _bsdf = pole_mat.node_tree.nodes.get("Principled BSDF")
                if _bsdf and "Metallic" in _bsdf.inputs:
                    _bsdf.inputs["Metallic"].default_value = 0.75
                spacing = vol_w / (len(lights) + 1)
                for li, light in enumerate(lights):
                    lx = vol_cx - vol_w / 2 + spacing * (li + 1)
                    pole_h = float(light.get("height_m", 2.8) or 2.8)
                    pole_d = float(light.get("diameter_m", 0.08) or 0.08)
                    lamp_d = float(light.get("lamp_diameter_m", 0.28) or 0.28)
                    bpy.ops.mesh.primitive_cylinder_add(radius=pole_d / 2, depth=pole_h)
                    pole = bpy.context.active_object
                    pole.name = f"sidewalk_pole_{li}_{bldg_id}"
                    pole.location = (lx, inset, pole_h / 2)
                    assign_material(pole, pole_mat)
                    all_objs.append(pole)

                    bpy.ops.mesh.primitive_uv_sphere_add(radius=lamp_d / 2)
                    lamp = bpy.context.active_object
                    lamp.name = f"sidewalk_lamp_{li}_{bldg_id}"
                    lamp.location = (lx, inset, pole_h + lamp_d / 2)
                    assign_material(lamp, light_mat)
                    all_objs.append(lamp)

            log_volume_feature("Modern roofline proxies", roofline_start)
            log_volume_feature("Modern roof", modern_roof_start)

        else:
            # Heritage hall or generic volume
            outer = create_box(f"hall_walls_{bldg_id}", vol_w, vol_d, vol_h,
                               location=(vol_cx, 0, 0))
            inner = create_box(f"hall_inner_{bldg_id}",
                               vol_w - 0.5, vol_d - 0.5, vol_h + 0.02,
                               location=(vol_cx, 0, -0.01))
            boolean_cut(outer, inner)
            outer.name = f"hall_{bldg_id}"

            hall_mat = create_brick_material(f"mat_hall_{vol_hex.lstrip('#')}",
                                              vol_hex, mortar_hex,
                                              bond_pattern=mv_bond,
                                              polychrome_hex=mv_polychrome)
            assign_material(outer, hall_mat)
            all_objs.append(outer)

            # Volume-specific openings (for detailed multi-volume churches)
            # If volume has no windows, infer from top-level params or create defaults
            detail_openings_start = len(all_objs)
            win_rows = vol.get("windows_detail", vol.get("window_rows", []))
            if not win_rows or not isinstance(win_rows, list) or len(win_rows) == 0:
                # Generate default windows: one row per floor above ground
                num_floors = len(vol_floors)
                wpf = params.get("windows_per_floor", [])
                default_ww = params.get("window_width_m", 0.9)
                default_wh = params.get("window_height_m", 1.4)
                z_acc = 0.0
                default_rows = []
                for fi in range(num_floors):
                    fh = vol_floors[fi] if fi < len(vol_floors) else 3.0
                    sill = z_acc + fh * 0.25
                    wcount = wpf[fi] if fi < len(wpf) else max(1, int(vol_w / 2.0))
                    if fi == 0 and params.get("has_storefront"):
                        z_acc += fh
                        continue
                    default_rows.append({
                        "count": wcount,
                        "width_m": default_ww,
                        "height_m": default_wh,
                        "sill_height_m": sill,
                    })
                    z_acc += fh
                win_rows = default_rows
            if isinstance(win_rows, list):
                for ri, row in enumerate(win_rows):
                    if not isinstance(row, dict):
                        continue
                    count = int(row.get("count", 0) or 0)
                    if count <= 0:
                        continue
                    ww = float(row.get("width_m", 0.9))
                    wh = float(row.get("height_m", 1.8))
                    sill = float(row.get("sill_height_m", 0.9))
                    row_type = str(row.get("type", ""))
                    arch_type = str(row.get("arch_type", ""))
                    if not arch_type:
                        arch_type = "pointed" if "lancet" in row_type.lower() or "pointed" in row_type.lower() else "segmental"
                    spacing = vol_w / (count + 1)
                    frame_hex = str(row.get("frame_colour", "#3A3A3A"))
                    if not frame_hex.startswith("#"):
                        frame_hex = colour_name_to_hex(frame_hex)
                    frame_mat = get_or_create_material(f"mat_volframe_{frame_hex.lstrip('#')}", colour_hex=frame_hex, roughness=0.5)

                    for wi in range(count):
                        wx = vol_cx - vol_w / 2 + spacing * (wi + 1)
                        if arch_type in ("pointed", "segmental", "semicircular"):
                            spring_h = wh * 0.72
                            cutter = create_arch_cutter(
                                f"vol_win_cut_{ri}_{wi}_{bldg_id}",
                                ww,
                                wh,
                                spring_h,
                                arch_type=arch_type,
                                depth=0.8,
                            )
                        else:
                            cutter = create_rect_cutter(f"vol_win_cut_{ri}_{wi}_{bldg_id}", ww, wh, depth=0.8)
                            cutter.location.z = wh / 2

                        cutter.location.x = wx
                        cutter.location.y = 0.01
                        cutter.location.z += sill
                        boolean_cut(outer, cutter)

                        # Glass
                        bpy.ops.mesh.primitive_plane_add(size=1)
                        gl = bpy.context.active_object
                        gl.name = f"vol_glass_{ri}_{wi}_{bldg_id}"
                        gl.scale = (ww * 0.85, 1, wh * 0.85)
                        bpy.ops.object.transform_apply(scale=True)
                        gl.rotation_euler.x = math.pi / 2
                        gl.location = (wx, 0.02, sill + wh / 2)
                        assign_material(gl, create_glass_material())
                        all_objs.append(gl)

                        # Simple frame
                        ft = 0.04
                        for fn, fs, fl in [
                            ("t", (ww + ft, 0.05, ft), (wx, 0.03, sill + wh)),
                            ("b", (ww + ft * 2, 0.06, ft), (wx, 0.03, sill)),
                            ("l", (ft, 0.05, wh), (wx - ww / 2, 0.03, sill + wh / 2)),
                            ("r", (ft, 0.05, wh), (wx + ww / 2, 0.03, sill + wh / 2)),
                        ]:
                            bpy.ops.mesh.primitive_cube_add(size=1)
                            fr = bpy.context.active_object
                            fr.name = f"vol_frame_{fn}_{ri}_{wi}_{bldg_id}"
                            fr.scale = fs
                            bpy.ops.object.transform_apply(scale=True)
                            fr.location = fl
                            assign_material(fr, frame_mat)
                            all_objs.append(fr)

            vol_doors = vol.get("doors_detail", [])
            # Add default door for first volume if none specified
            if (not vol_doors or not isinstance(vol_doors, list) or len(vol_doors) == 0) and vi == 0:
                vol_doors = [{"width_m": 1.0, "height_m": 2.2, "position": "center"}]
            if isinstance(vol_doors, list):
                door_mat = get_or_create_material("mat_vol_door", colour_hex="#7B2132", roughness=0.45)
                for di, ds in enumerate(vol_doors):
                    if not isinstance(ds, dict):
                        continue
                    dw = float(ds.get("width_m", 1.0))
                    dh = float(ds.get("height_m", 2.2))
                    dpos = str(ds.get("position", "center")).lower()
                    if "left" in dpos:
                        dx = vol_cx - vol_w * 0.25
                    elif "right" in dpos:
                        dx = vol_cx + vol_w * 0.25
                    else:
                        dx = vol_cx

                    dtype = str(ds.get("type", "")).lower()
                    is_arched = "arch" in dtype or "pointed" in dtype or "gothic" in dtype
                    if is_arched:
                        cutter = create_arch_cutter(
                            f"vol_door_cut_{di}_{bldg_id}",
                            dw,
                            dh,
                            dh * 0.72,
                            arch_type="pointed" if ("pointed" in dtype or "gothic" in dtype) else "segmental",
                            depth=0.8,
                        )
                    else:
                        cutter = create_rect_cutter(f"vol_door_cut_{di}_{bldg_id}", dw, dh, depth=0.8)
                        cutter.location.z = dh / 2
                    cutter.location.x = dx
                    cutter.location.y = 0.01
                    boolean_cut(outer, cutter)

                    bpy.ops.mesh.primitive_cube_add(size=1)
                    d_obj = bpy.context.active_object
                    d_obj.name = f"vol_door_{di}_{bldg_id}"
                    d_obj.scale = (dw * 0.92, 0.06, dh * 0.95)
                    bpy.ops.object.transform_apply(scale=True)
                    d_obj.location = (dx, 0.04, dh * 0.48)
                    assign_material(d_obj, door_mat)
                    all_objs.append(d_obj)

            buttress_count = int(vol.get("buttress_count", 0) or 0)
            if buttress_count > 0:
                buttress_mat = create_stone_material("mat_vol_buttress", "#4E4A43")
                b_w = float(vol.get("buttress_width_m", 0.34))
                b_d = float(vol.get("buttress_depth_m", 0.45))
                b_h = float(vol.get("buttress_height_m", max(2.2, vol_h * 0.85)))
                stepped = bool(vol.get("buttress_stepped", False))
                spacing = vol_w / (buttress_count + 1)
                for bi in range(buttress_count):
                    bx = vol_cx - vol_w / 2 + spacing * (bi + 1)
                    bpy.ops.mesh.primitive_cube_add(size=1)
                    bt = bpy.context.active_object
                    bt.name = f"vol_buttress_{bi}_{bldg_id}"
                    bt.scale = (b_w, b_d, b_h)
                    bpy.ops.object.transform_apply(scale=True)
                    bt.location = (bx, b_d / 2, b_h / 2)
                    assign_material(bt, buttress_mat)
                    all_objs.append(bt)
                    if stepped:
                        bpy.ops.mesh.primitive_cube_add(size=1)
                        bt2 = bpy.context.active_object
                        bt2.name = f"vol_buttress_step_{bi}_{bldg_id}"
                        bt2.scale = (b_w * 0.72, b_d * 0.72, b_h * 0.45)
                        bpy.ops.object.transform_apply(scale=True)
                        bt2.location = (bx, b_d * 0.65, b_h * 0.72)
                        assign_material(bt2, buttress_mat)
                        all_objs.append(bt2)

            # Optional repeated chapel gables along front face
            chapel_gable_count = int(vol.get("chapel_gable_count", 0) or 0)
            if chapel_gable_count > 0:
                cg_start = len(all_objs)
                cg_w = float(vol.get("chapel_gable_width_m", 2.6))
                cg_d = float(vol.get("chapel_gable_depth_m", 1.8))
                cg_h = float(vol.get("chapel_gable_height_m", 3.2))
                cg_y = float(vol.get("chapel_gable_y_m", cg_d / 2))
                spacing = vol_w / (chapel_gable_count + 1)
                for ci in range(chapel_gable_count):
                    cx = vol_cx - vol_w / 2 + spacing * (ci + 1)
                    # Small gable wall
                    gbm = bmesh.new()
                    v0 = gbm.verts.new((cx - cg_w / 2, cg_y, vol_h))
                    v1 = gbm.verts.new((cx + cg_w / 2, cg_y, vol_h))
                    v2 = gbm.verts.new((cx, cg_y, vol_h + cg_h))
                    gbm.faces.new([v0, v1, v2])
                    gmesh = bpy.data.meshes.new(f"chapel_gable_{ci}_{bldg_id}")
                    gbm.to_mesh(gmesh)
                    gbm.free()
                    gobj = bpy.data.objects.new(f"chapel_gable_{ci}_{bldg_id}", gmesh)
                    bpy.context.collection.objects.link(gobj)
                    mod = gobj.modifiers.new("Solidify", 'SOLIDIFY')
                    mod.thickness = 0.24
                    mod.offset = 0
                    bpy.context.view_layer.objects.active = gobj
                    bpy.ops.object.modifier_apply(modifier=mod.name)
                    assign_material(gobj, hall_mat)
                    all_objs.append(gobj)

                    # Small roof for this chapel gable
                    rbm = bmesh.new()
                    ov = 0.12
                    vv0 = rbm.verts.new((cx - cg_w / 2 - ov, cg_y + cg_d, vol_h))
                    vv1 = rbm.verts.new((cx + cg_w / 2 + ov, cg_y + cg_d, vol_h))
                    vv2 = rbm.verts.new((cx + cg_w / 2 + ov, cg_y - ov, vol_h))
                    vv3 = rbm.verts.new((cx - cg_w / 2 - ov, cg_y - ov, vol_h))
                    vv4 = rbm.verts.new((cx, cg_y + cg_d, vol_h + cg_h * 0.75))
                    vv5 = rbm.verts.new((cx, cg_y - ov, vol_h + cg_h * 0.75))
                    rbm.faces.new([vv0, vv3, vv5, vv4])
                    rbm.faces.new([vv1, vv4, vv5, vv2])
                    rm = bpy.data.meshes.new(f"chapel_roof_{ci}_{bldg_id}")
                    rbm.to_mesh(rm)
                    rbm.free()
                    robj = bpy.data.objects.new(f"chapel_roof_{ci}_{bldg_id}", rm)
                    bpy.context.collection.objects.link(robj)
                    rmod = robj.modifiers.new("Solidify", 'SOLIDIFY')
                    rmod.thickness = 0.06
                    rmod.offset = -1
                    bpy.context.view_layer.objects.active = robj
                    bpy.ops.object.modifier_apply(modifier=rmod.name)
                    assign_material(robj, create_roof_material(f"mat_chapelroof_{bldg_id}", get_roof_hex(params)))
                    all_objs.append(robj)
                log_volume_feature("Chapel gables", cg_start)
            log_volume_feature("Volume-specific openings/details", detail_openings_start)

            # Engine bay arch (ground floor)
            ground_opening_start = len(all_objs)
            gf = vol.get("ground_floor", {})
            if isinstance(gf, dict):
                primary = gf.get("primary_opening", {})
                if isinstance(primary, dict) and primary:
                    pw = primary.get("width_m", 3.5)
                    ph = primary.get("height_to_crown_m", 4.0)
                    spring = primary.get("spring_line_height_m", 2.8)

                    cutter = create_arch_cutter(f"arch_cut_{bldg_id}", pw, ph, spring,
                                                arch_type="semicircular", depth=0.8)
                    cutter.location.x = vol_cx
                    cutter.location.y = 0.01
                    boolean_cut(outer, cutter)

                    # Red rolling door
                    infill = primary.get("infill", {})
                    door_hex = "#CC2020"  # fire engine red
                    if isinstance(infill, dict):
                        dc = str(infill.get("colour", "")).lower()
                        if "red" in dc:
                            door_hex = "#CC2020"

                    bpy.ops.mesh.primitive_cube_add(size=1)
                    door = bpy.context.active_object
                    door.name = f"engine_door_{bldg_id}"
                    door.scale = (pw * 0.95, 0.06, spring * 0.95)
                    bpy.ops.object.transform_apply(scale=True)
                    door.location = (vol_cx, 0.04, spring * 0.48)
                    door_mat = get_or_create_material("mat_fire_door", colour_hex=door_hex, roughness=0.4)
                    assign_material(door, door_mat)
                    all_objs.append(door)

                    # Fanlight glass above door
                    bpy.ops.mesh.primitive_circle_add(radius=pw / 2 * 0.9, vertices=16,
                                                       fill_type='NGON')
                    fan = bpy.context.active_object
                    fan.name = f"fanlight_{bldg_id}"
                    fan.rotation_euler.x = math.pi / 2
                    fan.location = (vol_cx, 0.04, spring)
                    # Clip bottom half by scaling
                    fan.scale.z = 0.5
                    assign_material(fan, create_glass_material())
                    all_objs.append(fan)

                    vous_start = len(all_objs)
                    vous = primary.get("voussoirs", {})
                    if isinstance(vous, dict) and vous:
                        stone_hex = get_stone_hex(vous.get("material", ""), vous.get("profile", ""), default="#C8C0B0")
                        all_objs.extend(_create_arch_voussoirs(
                            f"engine_voussoir_{bldg_id}",
                            vol_cx,
                            0.02,
                            0.0,
                            pw,
                            ph,
                            spring,
                            count=vous.get("count_approx", 15),
                            colour_hex=stone_hex,
                        ))
                    log_volume_feature("Engine-bay voussoirs", vous_start)

                # Personnel door
                sec = gf.get("secondary_opening", {})
                if isinstance(sec, dict) and sec:
                    sw = sec.get("width_m", 0.9)
                    sh = sec.get("height_m", 2.2)
                    cutter = create_rect_cutter(f"pers_door_cut_{bldg_id}", sw, sh, depth=0.8)
                    cutter.location.z = sh / 2
                    cutter.location.x = vol_cx + pw / 2 + 1.0
                    cutter.location.y = 0.01
                    boolean_cut(outer, cutter)

                    bpy.ops.mesh.primitive_cube_add(size=1)
                    pd = bpy.context.active_object
                    pd.name = f"pers_door_{bldg_id}"
                    pd.scale = (sw * 0.9, 0.06, sh * 0.95)
                    bpy.ops.object.transform_apply(scale=True)
                    pd.location = (vol_cx + pw / 2 + 1.0, 0.04, sh * 0.48)
                    assign_material(pd, door_mat)
                    all_objs.append(pd)
            log_volume_feature("Ground openings", ground_opening_start)

            # Second floor windows
            second_floor_start = len(all_objs)
            sf = vol.get("second_floor", {})
            if isinstance(sf, dict):
                sf_wins = sf.get("windows", [])
                for wi, ws in enumerate(sf_wins):
                    if not isinstance(ws, dict):
                        continue
                    wcount = ws.get("count", 2)
                    ww = ws.get("width_m", 0.9)
                    wh = ws.get("height_m", 1.6)
                    z2 = vol_floors[0] if vol_floors else 4.2
                    sill_z = z2 + (vol_floors[1] if len(vol_floors) > 1 else 3.5) * 0.2

                    spacing = vol_w / (wcount + 1)
                    for wci in range(wcount):
                        wx = vol_cx - vol_w / 2 + spacing * (wci + 1)
                        # Cut opening
                        cutter = create_arch_cutter(f"sf_win_cut_{wci}_{bldg_id}",
                                                     ww, wh, wh * 0.7,
                                                     arch_type="segmental", depth=0.8)
                        cutter.location.x = wx
                        cutter.location.z += sill_z
                        cutter.location.y = 0.01
                        boolean_cut(outer, cutter)

                        # Glass
                        bpy.ops.mesh.primitive_plane_add(size=1)
                        gl = bpy.context.active_object
                        gl.name = f"hall_glass_{wci}_{bldg_id}"
                        gl.scale = (ww * 0.85, 1, wh * 0.85)
                        bpy.ops.object.transform_apply(scale=True)
                        gl.rotation_euler.x = math.pi / 2
                        gl.location = (wx, 0.02, sill_z + wh / 2)
                        assign_material(gl, create_glass_material())
                        all_objs.append(gl)

                        # Frame
                        trim_hex = get_trim_hex(params)
                        fr_mat = get_or_create_material(f"mat_hallframe_{trim_hex.lstrip('#')}",
                                                         colour_hex=trim_hex, roughness=0.5)
                        ft = 0.04
                        for fn, fs, fl in [
                            ("t", (ww + ft, 0.05, ft), (wx, 0.03, sill_z + wh)),
                            ("b", (ww + ft * 2, 0.07, ft), (wx, 0.04, sill_z)),
                            ("l", (ft, 0.05, wh), (wx - ww / 2, 0.03, sill_z + wh / 2)),
                            ("r", (ft, 0.05, wh), (wx + ww / 2, 0.03, sill_z + wh / 2)),
                        ]:
                            bpy.ops.mesh.primitive_cube_add(size=1)
                            f_obj = bpy.context.active_object
                            f_obj.name = f"hall_frame_{fn}_{wci}_{bldg_id}"
                            f_obj.scale = fs
                            bpy.ops.object.transform_apply(scale=True)
                            f_obj.location = fl
                            assign_material(f_obj, fr_mat)
                            all_objs.append(f_obj)
            log_volume_feature("Upper windows", second_floor_start)

            # Gable roof for heritage hall
            roof_type = str(vol.get("roof_type", "gable")).lower()
            if "gable" in roof_type:
                roof_start = len(all_objs)
                pitch = vol.get("roof_pitch_deg", 35)
                ridge_h = (vol_w / 2) * _safe_tan(pitch)

                bm = bmesh.new()
                hw = vol_w / 2 + 0.15
                ov = 0.3
                y_f = ov
                y_b = -vol_d - ov

                v0 = bm.verts.new((vol_cx - hw, y_b, vol_h))
                v1 = bm.verts.new((vol_cx + hw, y_b, vol_h))
                v2 = bm.verts.new((vol_cx + hw, y_f, vol_h))
                v3 = bm.verts.new((vol_cx - hw, y_f, vol_h))
                v4 = bm.verts.new((vol_cx, y_b, vol_h + ridge_h))
                v5 = bm.verts.new((vol_cx, y_f, vol_h + ridge_h))

                bm.faces.new([v0, v3, v5, v4])
                bm.faces.new([v1, v4, v5, v2])
                bm.faces.new([v2, v5, v3])
                bm.faces.new([v0, v4, v1])

                rmesh = bpy.data.meshes.new(f"hall_roof_{bldg_id}")
                bm.to_mesh(rmesh)
                bm.free()

                robj = bpy.data.objects.new(f"hall_roof_{bldg_id}", rmesh)
                bpy.context.collection.objects.link(robj)
                mod = robj.modifiers.new("Solidify", 'SOLIDIFY')
                mod.thickness = 0.08
                mod.offset = -1
                bpy.context.view_layer.objects.active = robj
                bpy.ops.object.modifier_apply(modifier=mod.name)

                roof_hex = get_roof_hex(params)
                r_mat = create_roof_material(f"mat_hallroof_{roof_hex.lstrip('#')}", roof_hex)
                assign_material(robj, r_mat)
                all_objs.append(robj)
                log_volume_feature("Gable roof", roof_start)

                # Gable walls
                gable_start = len(all_objs)
                for y_pos in [0, -vol_d]:
                    gbm = bmesh.new()
                    gv0 = gbm.verts.new((vol_cx - vol_w / 2, 0, vol_h))
                    gv1 = gbm.verts.new((vol_cx + vol_w / 2, 0, vol_h))
                    gv2 = gbm.verts.new((vol_cx, 0, vol_h + ridge_h))
                    gbm.faces.new([gv0, gv1, gv2])

                    gm = bpy.data.meshes.new(f"hall_gable_{bldg_id}")
                    gbm.to_mesh(gm)
                    gbm.free()

                    gobj = bpy.data.objects.new(f"hall_gable_{bldg_id}", gm)
                    bpy.context.collection.objects.link(gobj)
                    gobj.location.y = y_pos
                    mod = gobj.modifiers.new("Solidify", 'SOLIDIFY')
                    mod.thickness = 0.3
                    mod.offset = 0
                    bpy.context.view_layer.objects.active = gobj
                    bpy.ops.object.modifier_apply(modifier=mod.name)
                    assign_material(gobj, hall_mat)
                    all_objs.append(gobj)
                log_volume_feature("Gable walls", gable_start)

                # Heritage-hall corbel table at eave line if described in volume details
                hall_corbel_start = len(all_objs)
                vol_dec = vol.get("second_floor", {}).get("decorative_elements", {})
                if isinstance(vol_dec, dict):
                    corbel_data = vol_dec.get("corbelling", {})
                    if corbel_data:
                        hall_course_count = 4 if "4" in json.dumps(corbel_data).lower() else 3
                        all_objs.extend(_create_corbel_band(
                            f"hall_corbel_{bldg_id}",
                            vol_cx,
                            0.02,
                            vol_h - 0.30,
                            vol_w,
                            course_count=hall_course_count,
                            colour_hex=vol_hex,
                        ))
                log_volume_feature("Hall corbelling", hall_corbel_start)

                # Oculus window in front gable
                oculus_start = len(all_objs)
                rf = vol.get("roof_features", [])
                for feat in rf:
                    if isinstance(feat, dict) and "oculus" in str(feat.get("type", "")).lower():
                        oc_diam = feat.get("diameter_m", 0.6)
                        oc_z = vol_h + ridge_h * 0.55
                        bpy.ops.mesh.primitive_circle_add(
                            radius=oc_diam / 2, vertices=24, fill_type='NGON')
                        oc = bpy.context.active_object
                        oc.name = f"oculus_{bldg_id}"
                        oc.rotation_euler.x = math.pi / 2
                        oc.location = (vol_cx, 0.16, oc_z)
                        assign_material(oc, create_glass_material())
                        all_objs.append(oc)

                        # Stone surround
                        bpy.ops.mesh.primitive_torus_add(
                            major_radius=oc_diam / 2 + 0.05,
                            minor_radius=0.05, major_segments=24, minor_segments=8)
                        ring = bpy.context.active_object
                        ring.name = f"oculus_surround_{bldg_id}"
                        ring.rotation_euler.x = math.pi / 2
                        ring.location = (vol_cx, 0.16, oc_z)
                        stone_mat = create_stone_material("mat_stone_oculus", "#C8C0B0")
                        assign_material(ring, stone_mat)
                        all_objs.append(ring)
                log_volume_feature("Oculus", oculus_start)

        # Offset this volume after geometry creation (supports side chapel strips / annex shifts)
        if vol_y_off != 0.0 or vol_z_off != 0.0:
            for obj in all_objs[vol_start_idx:]:
                if obj:
                    obj.location.y += vol_y_off
                    obj.location.z += vol_z_off

        # --- Seam filler between adjacent volumes ---
        # When two volumes sit side by side (not stacked), add a thin strip of
        # wall material at the junction to prevent light leaks at the seam.
        if vi > 0 and not stack_with_previous:
            prev_vol = volumes[vi - 1] if isinstance(volumes[vi - 1], dict) else {}
            prev_h = sum(max(0.5, float(fh)) for fh in (prev_vol.get("floor_heights_m") or [3.5]))
            seam_h = min(vol_h, prev_h)  # height of shared wall = shorter of the two
            seam_x = vol_cx - vol_w / 2  # left edge of current volume
            seam_depth = max(vol_d, prev_vol.get("depth_m", 10.0))
            if seam_h > 0.5:
                bpy.ops.mesh.primitive_cube_add(size=1)
                seam = bpy.context.active_object
                seam.name = f"seam_filler_{vi}_{bldg_id}"
                seam.scale = (0.02, seam_depth / 2, seam_h / 2)
                bpy.ops.object.transform_apply(scale=True)
                seam.location = (seam_x, -seam_depth / 2, seam_h / 2)
                seam_mat = create_brick_material(
                    f"mat_seam_{vol_hex.lstrip('#')}", vol_hex, mortar_hex,
                    bond_pattern=mv_bond)
                assign_material(seam, seam_mat)
                all_objs.append(seam)

            # Log eave height mismatch for QA
            if abs(vol_h - prev_h) > 0.5:
                print(f"    [WARN] Eave height mismatch at seam {vi}: "
                      f"prev={prev_h:.1f}m vs current={vol_h:.1f}m (delta={abs(vol_h - prev_h):.1f}m)")

        if not stack_with_previous:
            x_cursor += vol_w
            prev_cx = vol_cx

    all_objs = [o for o in all_objs if _obj_valid(o)]
    pre_join_count = len(all_objs)

    all_objs = join_by_prefix("hall_frame_", all_objs)
    all_objs = join_by_prefix("hall_glass_", all_objs)
    all_objs = join_by_prefix("curtain_glass_", all_objs)
    all_objs = join_by_prefix("mullion_", all_objs)
    all_objs = join_by_prefix("tower_glass_", all_objs)
    all_objs = join_by_prefix("tower_corner_", all_objs)
    all_objs = join_by_prefix("tower_veg_", all_objs)
    all_objs = join_by_prefix("tower_corbel_", all_objs)
    all_objs = join_by_prefix("tower_sc_", all_objs)
    all_objs = join_by_prefix("engine_voussoir_", all_objs)
    all_objs = join_by_prefix("clock_", all_objs)
    all_objs = join_by_prefix("clock_surround_", all_objs)

    post_join_count = len(all_objs)
    if post_join_count < pre_join_count:
        print(f"  Joined objects: {pre_join_count} -> {post_join_count}")

    # Move all to collection with offset
    col = bpy.data.collections.new(f"building_{bldg_id}")
    bpy.context.scene.collection.children.link(col)

    ox, oy, oz = offset
    for obj in all_objs:
        if _obj_valid(obj):
            obj.location.x += ox
            obj.location.y += oy
            obj.location.z += oz
            for c in obj.users_collection:
                c.objects.unlink(obj)
            col.objects.link(obj)

    # Store HCD metadata as custom properties on the collection
    if 'hcd_data' in params:
        hcd = params.get('hcd_data', {})
        col['hcd_reference'] = hcd.get('hcd_reference_number', 0)
        col['hcd_typology'] = hcd.get('typology', '')
        col['hcd_construction_date'] = hcd.get('construction_date', '')

    print(f"  [OK] Total objects: {len(all_objs)}")
    return col


def generate_st_stephens_custom(params, offset=(0, 0, 0)):
    """Custom one-off generator for St. Stephen-in-the-Fields Church.

    This bypasses generic house-form assumptions and builds a church-like
    massing directly (nave, chapel bay run, tower/spire, and rear annexes).
    """
    address = "103 Bellevue Ave"
    meta = params.get("_meta", {})
    if isinstance(meta, dict):
        address = meta.get("address", address)
    bldg_id = address.replace(" ", "_").replace(",", "").replace(".", "")
    print(f"[GENERATE CUSTOM] {address} (St. Stephen)")

    facade_hex = get_facade_hex(params)
    roof_hex = get_roof_hex(params)
    trim_hex = get_trim_hex(params)

    brick_mat = create_brick_material(f"mat_custom_brick_{facade_hex.lstrip('#')}", facade_hex, "#8A8A8A")
    roof_mat = create_roof_material(f"mat_custom_roof_{roof_hex.lstrip('#')}", roof_hex)
    stone_mat = create_stone_material(f"mat_custom_stone_{trim_hex.lstrip('#')}", trim_hex)
    glass_mat = create_glass_material(f"mat_custom_glass_{bldg_id}")
    stucco_mat = create_painted_material(f"mat_custom_stucco_{bldg_id}", "#B8826B")
    door_mat = get_or_create_material(f"mat_custom_door_{bldg_id}", colour_hex="#7B2132", roughness=0.45)

    all_objs = []

    def _obj_valid(o):
        try:
            return o is not None and o.name is not None
        except ReferenceError:
            return False

    def _gable_roof(name, width, depth, eave_z, ridge_z, cx=0.0, cy=0.0, overhang=0.25):
        bm = bmesh.new()
        hw = width / 2 + overhang
        hd = depth / 2 + overhang
        # Build in local object coordinates; position with object.location.
        v0 = bm.verts.new((-hw, -hd, eave_z))
        v1 = bm.verts.new((hw, -hd, eave_z))
        v2 = bm.verts.new((hw, hd, eave_z))
        v3 = bm.verts.new((-hw, hd, eave_z))
        v4 = bm.verts.new((0.0, -hd, ridge_z))
        v5 = bm.verts.new((0.0, hd, ridge_z))
        bm.faces.new([v0, v3, v5, v4])
        bm.faces.new([v1, v4, v5, v2])
        bm.faces.new([v2, v5, v3])
        bm.faces.new([v0, v4, v1])
        rmesh = bpy.data.meshes.new(name)
        bm.to_mesh(rmesh)
        bm.free()
        robj = bpy.data.objects.new(name, rmesh)
        bpy.context.collection.objects.link(robj)
        mod = robj.modifiers.new("Solidify", 'SOLIDIFY')
        mod.thickness = 0.08
        mod.offset = -1
        bpy.context.view_layer.objects.active = robj
        bpy.ops.object.modifier_apply(modifier=mod.name)
        robj.location.x = cx
        robj.location.y = cy
        assign_material(robj, roof_mat)
        return robj

    def _gable_end_wall(name, width, eave_z, ridge_z, cy, thickness=0.18):
        bm = bmesh.new()
        hw = width / 2
        ht = thickness / 2
        # Build in local coordinates; place at cy using object.location.
        v0 = bm.verts.new((-hw, -ht, 0.0))
        v1 = bm.verts.new((hw, -ht, 0.0))
        v2 = bm.verts.new((hw, ht, 0.0))
        v3 = bm.verts.new((-hw, ht, 0.0))
        v4 = bm.verts.new((-hw, -ht, eave_z))
        v5 = bm.verts.new((hw, -ht, eave_z))
        v6 = bm.verts.new((hw, ht, eave_z))
        v7 = bm.verts.new((-hw, ht, eave_z))
        va = bm.verts.new((0.0, -ht, ridge_z))
        vb = bm.verts.new((0.0, ht, ridge_z))

        bm.faces.new([v0, v1, v2, v3])      # bottom
        bm.faces.new([v0, v4, v5, v1])      # side
        bm.faces.new([v1, v5, v6, v2])      # side
        bm.faces.new([v2, v6, v7, v3])      # side
        bm.faces.new([v3, v7, v4, v0])      # side
        bm.faces.new([v4, va, v5])          # front triangle
        bm.faces.new([v7, v6, vb])          # back triangle
        bm.faces.new([v4, v7, vb, va])      # top left slope
        bm.faces.new([v5, va, vb, v6])      # top right slope

        m = bpy.data.meshes.new(name)
        bm.to_mesh(m)
        bm.free()
        obj = bpy.data.objects.new(name, m)
        bpy.context.collection.objects.link(obj)
        obj.location.y = cy
        assign_material(obj, brick_mat)
        return obj

    def _box_center(name, width, depth, height, cx, cy, bz=0.0):
        """Create box using center-XY and bottom-Z coordinates."""
        return create_box(name, width, depth, height, location=(cx, cy + depth / 2, bz))

    def _polygon_prism(name, points_xy, z0, z1, material):
        """Create vertical prism from 2D footprint points."""
        bm = bmesh.new()
        bottom = [bm.verts.new((x, y, z0)) for x, y in points_xy]
        top = [bm.verts.new((x, y, z1)) for x, y in points_xy]
        bm.faces.new(bottom)
        bm.faces.new(list(reversed(top)))
        n = len(points_xy)
        for i in range(n):
            j = (i + 1) % n
            bm.faces.new([bottom[i], bottom[j], top[j], top[i]])
        m = bpy.data.meshes.new(name)
        bm.to_mesh(m)
        bm.free()
        obj = bpy.data.objects.new(name, m)
        bpy.context.collection.objects.link(obj)
        assign_material(obj, material)
        return obj

    # Main nave (GIS-calibrated envelope)
    use_footprint_base = False
    if use_footprint_base:
        # GID 411057 footprint (SRID 2952) recentered to centroid, in metres.
        footprint_pts = [
            (1.844, 10.083), (1.414, 11.709), (5.143, 12.696), (5.284, 12.162),
            (12.532, 14.081), (14.067, 8.281), (16.762, 8.995), (19.025, 0.446),
            (20.424, -4.589), (17.742, -5.349), (10.466, -7.276), (10.339, -6.796),
            (7.121, -7.668), (7.156, -7.800), (-14.591, -13.556), (-15.321, -10.797),
            (-15.942, -10.961), (-16.757, -7.882), (-17.624, -8.112), (-19.174, -2.255),
            (-18.382, -2.046), (-19.223, 1.136), (-18.838, 1.238), (-19.671, 4.389),
        ]
        base = _polygon_prism(f"custom_footprint_base_{bldg_id}", footprint_pts, 0.0, 8.7, brick_mat)
        all_objs.append(base)

    nave_w = 13.6
    nave_d = 31.0
    nave_eave = 8.0
    nave_ridge = 13.4
    nave = _box_center(f"custom_nave_{bldg_id}", nave_w, nave_d, nave_eave, 0, 0, 0)
    assign_material(nave, brick_mat)
    all_objs.append(nave)
    nave_roof = _gable_roof(f"custom_nave_roof_{bldg_id}", nave_w, nave_d, nave_eave, nave_ridge, 0, 0, overhang=0.18)
    all_objs.append(nave_roof)
    nave_front_gable = _gable_end_wall(
        f"custom_nave_front_gable_{bldg_id}",
        nave_w - 0.25,
        nave_eave,
        nave_ridge - 0.15,
        nave_d / 2 - 0.12,
        thickness=0.22,
    )
    all_objs.append(nave_front_gable)
    nave_rear_gable = _gable_end_wall(
        f"custom_nave_rear_gable_{bldg_id}",
        nave_w - 0.25,
        nave_eave,
        nave_ridge - 0.15,
        -nave_d / 2 + 0.12,
        thickness=0.22,
    )
    all_objs.append(nave_rear_gable)




def generate_building(params, offset=(0, 0, 0), rotation=0.0):
    """Generate a complete 3D building from JSON parameters."""
    ok, validation_errors = _validate_params(params)
    for err in validation_errors:
        print(f"[VALIDATION] {err}")
    if not ok:
        print(f"[VALIDATION] SKIPPING {params.get('building_name')} - critical errors")
        return []

    params = apply_hcd_guide_defaults(params)

    # Normalize array lengths to match floor count
    floors = params.get("floors", 1)
    for arr_key, default_val in [("floor_heights_m", 3.0), ("windows_per_floor", 3)]:
        arr = params.get(arr_key, [])
        if arr and len(arr) != floors:
            if len(arr) < floors:
                fill = arr[-1] if arr else default_val
                arr = list(arr) + [fill] * (floors - len(arr))
            else:
                arr = arr[:floors]
            params[arr_key] = arr

    # Dedicated custom profile for St. Stephen church accuracy work
    meta = params.get("_meta", {})
    if isinstance(meta, dict) and meta.get("custom_model") == "st_stephens_custom":
        return generate_st_stephens_custom(params, offset)

    # Check for multi-volume buildings
    volumes = params.get("volumes", [])
    if len(volumes) >= 2:
        return generate_multi_volume(params, offset)

    address = "unknown"
    meta = params.get("_meta", {})
    if isinstance(meta, dict):
        address = meta.get("address", "unknown")

    bldg_id = address.replace(" ", "_").replace(",", "").replace(".", "")
    print(f"[GENERATE] {address}")

    # HCD-derived defaults (used as fallbacks when params don't specify)
    era_defaults = get_era_defaults(params)
    typology_hints = get_typology_hints(params)

    depth = params.get("facade_depth_m", DEFAULT_DEPTH)

    # 1. Create walls
    wall_obj, wall_h, width, depth = create_walls(params, depth)
    print(f"  Walls: {width:.1f}m x {depth:.1f}m x {wall_h:.1f}m")

    # 2. Cut window openings
    windows = cut_windows(wall_obj, params, wall_h, width, bldg_id)
    print(f"  Windows: {len(windows)} elements")

    # 3. Cut door openings
    doors = cut_doors(wall_obj, params, width)
    if doors:
        print(f"  Doors: {len(doors)} elements")

    # 4. Create roof
    roof_type = str(params.get("roof_type", "gable")).lower()
    ridge_height = 0
    gable_objs = []

    if "flat" in roof_type:
        roof_obj, parapet_h = create_flat_roof(params, wall_h, width, depth)
        print(f"  Roof: flat with {parapet_h:.1f}m parapet")
    elif "hip" in roof_type:
        roof_obj, ridge_height = create_hip_roof(params, wall_h, width, depth)
        print(f"  Roof: hip, peak +{ridge_height:.1f}m")
    elif "cross" in roof_type or "bay-and-gable" in roof_type or "bay_and_gable" in roof_type:
        roof_obj, ridge_height = create_cross_gable_roof(params, wall_h, width, depth)
        gable_objs = create_gable_walls(params, wall_h, width, depth, bldg_id)
        print(f"  Roof: cross-gable, ridge +{ridge_height:.1f}m, +{len(gable_objs)} gable walls")
    elif "gable" in roof_type:
        roof_obj, ridge_height = create_gable_roof(params, wall_h, width, depth)
        gable_objs = create_gable_walls(params, wall_h, width, depth, bldg_id)
        print(f"  Roof: gable, ridge +{ridge_height:.1f}m, +{len(gable_objs)} gable walls")
    else:
        roof_obj, ridge_height = create_gable_roof(params, wall_h, width, depth)
        gable_objs = create_gable_walls(params, wall_h, width, depth, bldg_id)

    # 5. Porch
    porch_objs = create_porch(params, width)
    if porch_objs:
        print(f"  Porch: {len(porch_objs)} elements")

    # 6. Bay windows
    bay_objs = create_bay_window(params, wall_h, width)
    if bay_objs:
        print(f"  Bay window: {len(bay_objs)} elements")

    # 7. Chimneys
    chimney_objs = create_chimney(params, wall_h, ridge_height, width)
    if chimney_objs:
        print(f"  Chimneys: {len(chimney_objs)}")

    # 8. Storefront
    sf_objs = create_storefront(params, wall_obj, width)
    if sf_objs:
        print(f"  Storefront: {len(sf_objs)} elements")

    # 9. String courses
    sc_objs = create_string_courses(params, wall_h, width, depth, bldg_id)
    if sc_objs:
        print(f"  String courses: {len(sc_objs)}")

    # 10. Quoins
    quoin_objs = create_quoins(params, wall_h, width, depth, bldg_id)
    if quoin_objs:
        print(f"  Quoins: {len(quoin_objs)}")

    # 11. Tower (for fire station etc)
    tower_objs = create_tower(params, bldg_id)
    if tower_objs:
        print(f"  Tower: {len(tower_objs)} elements")

    # 12. Bargeboard (decorative rake boards on gable)
    bb_objs = []
    if "gable" in roof_type:
        bb_objs = create_bargeboard(params, wall_h, width, depth, bldg_id)
        if bb_objs:
            print(f"  Bargeboard: {len(bb_objs)} elements")

    # 13. Cornice band
    cornice_objs = create_cornice_band(params, wall_h, width, depth, bldg_id)
    if cornice_objs:
        print(f"  Cornice: {len(cornice_objs)} elements")

    # 13b. Corbel table / stepped brickwork
    corbel_objs = create_corbelling(params, wall_h, width, depth, bldg_id)
    if corbel_objs:
        print(f"  Corbelling: {len(corbel_objs)} elements")

    # 14. Window lintels and sills
    lintel_objs = create_window_lintels(params, wall_h, width, bldg_id)
    if lintel_objs:
        print(f"  Lintels/sills: {len(lintel_objs)} elements")

    # 14b. Stained-glass transoms
    transom_objs = create_stained_glass_transoms(params, width, bldg_id)
    if transom_objs:
        print(f"  Transoms: {len(transom_objs)} elements")

    # 15. Brackets (gable and porch)
    bracket_objs = create_brackets(params, wall_h, width, depth, bldg_id)
    if bracket_objs:
        print(f"  Brackets: {len(bracket_objs)} elements")

    # 16. Ridge finial
    finial_objs = []
    if "gable" in roof_type:
        finial_objs = create_ridge_finial(params, wall_h, width, depth, bldg_id)
        if finial_objs:
            print(f"  Finial: {len(finial_objs)} elements")

    # 17. Voussoirs (arch stones)
    voussoir_objs = create_voussoirs(params, wall_h, width, bldg_id)
    if voussoir_objs:
        print(f"  Voussoirs: {len(voussoir_objs)} elements")

    # 18. Gable fish-scale shingles
    shingle_objs = []
    if "gable" in roof_type:
        shingle_objs = create_gable_shingles(params, wall_h, width, depth, bldg_id)
        if shingle_objs:
            print(f"  Gable shingles: {len(shingle_objs)} elements")

    # 19. Dormer
    dormer_objs = create_dormer(params, wall_h, width, depth, bldg_id)
    if dormer_objs:
        print(f"  Dormer: {len(dormer_objs)} elements")

    # 20. Fascia and soffit boards
    fascia_objs = create_fascia_boards(params, wall_h, width, depth, bldg_id)
    if fascia_objs:
        print(f"  Fascia/soffit: {len(fascia_objs)} elements")

    # 21. Parapet coping (flat roofs)
    parapet_objs = create_parapet_coping(params, wall_h, width, depth, bldg_id)
    if parapet_objs:
        print(f"  Parapet/coping: {len(parapet_objs)} elements")

    # 21a. Small rooftop hip element / penthouse cap
    hip_rooflet_objs = create_hip_rooflet(params, wall_h, width, depth, bldg_id)
    if hip_rooflet_objs:
        print(f"  Hip rooflet: {len(hip_rooflet_objs)} elements")

    # 21b. Gabled parapet
    gp_objs = create_gabled_parapet(params, wall_h, width, depth, bldg_id)
    if gp_objs:
        print(f"  Gabled parapet: {len(gp_objs)} elements")

    # 22. Turned porch posts (replace cylinders with Victorian turned posts)
    porch_objs = create_turned_posts(porch_objs, params, width)

    # 23. Storefront awning and signage
    awning_objs = create_storefront_awning(params, width, bldg_id)
    if awning_objs:
        print(f"  Awning/sign: {len(awning_objs)} elements")

    # 24. Foundation/water table
    found_objs = create_foundation(params, width, depth, bldg_id)
    if found_objs:
        print(f"  Foundation: {len(found_objs)} elements")

    # 25. Gutters and downspouts
    gutter_objs = create_gutters(params, wall_h, width, depth, bldg_id)
    if gutter_objs:
        print(f"  Gutters: {len(gutter_objs)} elements")

    # 26. Chimney caps
    chimney_cap_objs = create_chimney_caps(params, wall_h, ridge_height, width, bldg_id)
    if chimney_cap_objs:
        print(f"  Chimney caps: {len(chimney_cap_objs)} elements")

    # 27. Porch lattice skirt
    lattice_objs = create_porch_lattice(params, width, bldg_id)
    if lattice_objs:
        print(f"  Lattice skirt: {len(lattice_objs)} elements")

    # 28. Step handrails
    handrail_objs = create_step_handrails(params, width, bldg_id)
    if handrail_objs:
        print(f"  Handrails: {len(handrail_objs)} elements")

    # Collect all objects
    all_objs = [wall_obj, roof_obj] + gable_objs + windows + doors + porch_objs + bay_objs + \
               chimney_objs + sf_objs + sc_objs + quoin_objs + tower_objs + corbel_objs + \
               bb_objs + cornice_objs + lintel_objs + transom_objs + bracket_objs + finial_objs + \
               voussoir_objs + shingle_objs + dormer_objs + fascia_objs + parapet_objs + \
               hip_rooflet_objs + awning_objs + found_objs + gutter_objs + chimney_cap_objs + \
               lattice_objs + handrail_objs + gp_objs

    # Join small objects by type to reduce clutter
    def _obj_valid(o):
        try:
            return o is not None and o.name is not None
        except ReferenceError:
            return False

    def join_by_prefix(prefix, objs_list):
        """Join all objects whose name starts with prefix into a single mesh."""
        targets = []
        for o in objs_list:
            try:
                if o and o.name.startswith(prefix):
                    targets.append(o)
            except ReferenceError:
                continue
        if len(targets) < 2:
            return objs_list
        bpy.ops.object.select_all(action='DESELECT')
        for o in targets:
            o.select_set(True)
        bpy.context.view_layer.objects.active = targets[0]
        bpy.ops.object.join()
        joined = bpy.context.active_object
        joined.name = f"{prefix}{bldg_id}"
        # Replace in list: keep joined, remove others
        new_list = [o for o in objs_list if _obj_valid(o) and o not in targets]
        new_list.append(joined)
        return new_list

    all_objs = [o for o in all_objs if _obj_valid(o)]
    pre_join_count = len(all_objs)

    all_objs = join_by_prefix("frame_", all_objs)
    all_objs = join_by_prefix("muntin_", all_objs)
    all_objs = join_by_prefix("glass_", all_objs)
    all_objs = join_by_prefix("baluster_", all_objs)
    all_objs = join_by_prefix("bay_glass_", all_objs)
    all_objs = join_by_prefix("step_", all_objs)
    all_objs = join_by_prefix("lintel_", all_objs)
    all_objs = join_by_prefix("sill_", all_objs)
    all_objs = join_by_prefix("bracket_", all_objs)
    all_objs = join_by_prefix("porch_bracket_", all_objs)
    all_objs = join_by_prefix("bargeboard_", all_objs)
    all_objs = join_by_prefix("voussoir_", all_objs)
    all_objs = join_by_prefix("shingle_", all_objs)
    all_objs = join_by_prefix("dormer_frame_", all_objs)
    all_objs = join_by_prefix("dormer_cheek_", all_objs)
    all_objs = join_by_prefix("fascia_", all_objs)
    all_objs = join_by_prefix("soffit_", all_objs)
    all_objs = join_by_prefix("parapet_", all_objs)
    all_objs = join_by_prefix("coping_", all_objs)
    all_objs = join_by_prefix("turned_seg_", all_objs)
    all_objs = join_by_prefix("lattice_", all_objs)
    all_objs = join_by_prefix("foundation_", all_objs)
    all_objs = join_by_prefix("gutter_", all_objs)
    all_objs = join_by_prefix("downspout_", all_objs)
    all_objs = join_by_prefix("chimcap_", all_objs)
    all_objs = join_by_prefix("handrail_", all_objs)
    all_objs = join_by_prefix("rail_post_", all_objs)
    all_objs = join_by_prefix("hall_frame_", all_objs)
    all_objs = join_by_prefix("hall_glass_", all_objs)
    all_objs = join_by_prefix("curtain_glass_", all_objs)
    all_objs = join_by_prefix("mullion_", all_objs)
    all_objs = join_by_prefix("tower_glass_", all_objs)
    all_objs = join_by_prefix("tower_corner_", all_objs)
    all_objs = join_by_prefix("tower_veg_", all_objs)
    all_objs = join_by_prefix("tower_corbel_", all_objs)
    all_objs = join_by_prefix("engine_voussoir_", all_objs)
    all_objs = join_by_prefix("transom_", all_objs)
    all_objs = join_by_prefix("quoin_", all_objs)
    all_objs = join_by_prefix("string_course_", all_objs)
    all_objs = join_by_prefix("cornice_", all_objs)

    post_join_count = len(all_objs)
    if post_join_count < pre_join_count:
        print(f"  Joined objects: {pre_join_count} -> {post_join_count}")

    # Move to building collection and apply offset directly (no parent empty = no clutter)
    col = bpy.data.collections.new(f"building_{bldg_id}")
    bpy.context.scene.collection.children.link(col)

    ox, oy, oz = offset
    for obj in all_objs:
        if _obj_valid(obj):
            # Apply rotation around origin (Z-axis) before offset
            if rotation != 0.0:
                cos_r = math.cos(rotation)
                sin_r = math.sin(rotation)
                x, y = obj.location.x, obj.location.y
                obj.location.x = x * cos_r - y * sin_r
                obj.location.y = x * sin_r + y * cos_r
                obj.rotation_euler.z += rotation
            obj.location.x += ox
            obj.location.y += oy
            obj.location.z += oz
            # Move to building collection
            for c in obj.users_collection:
                c.objects.unlink(obj)
            col.objects.link(obj)

    # Store HCD metadata as custom properties on the collection
    if 'hcd_data' in params:
        hcd = params.get('hcd_data', {})
        col['hcd_reference'] = hcd.get('hcd_reference_number', 0)
        col['hcd_typology'] = hcd.get('typology', '')
        col['hcd_construction_date'] = hcd.get('construction_date', '')
        col['hcd_character_sub_area'] = hcd.get('character_sub_area', '')
        col['hcd_statement'] = hcd.get('statement_of_contribution', '')

    print(f"  [OK] Total objects: {len([o for o in all_objs if o])}")
    return col


# ---------------------------------------------------------------------------
# Multi-building loader
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Multi-building loader
# ---------------------------------------------------------------------------

def load_and_generate(params_path, spacing=15.0, match=None, limit=None):
    """Load one or more JSON param files and generate buildings."""
    clear_scene()

    path = Path(params_path)

    # Load site coordinates from GIS export (SRID 2952, local metres)
    site_coords_path = Path(__file__).parent / "params" / "_site_coordinates.json"
    site_coords = None
    if site_coords_path.exists():
        with open(site_coords_path, encoding="utf-8") as gf:
            site_coords = json.load(gf)
        print(f"Loaded site coordinates: {len(site_coords)} buildings (from PostGIS)")

    # Legacy geocode fallback
    geocode_path = Path(__file__).parent / "archive" / "geocode.json"
    geocode = None
    if geocode_path.exists():
        with open(geocode_path) as gf:
            geocode = json.load(gf)
        print(f"Loaded geocode.json: {len(geocode)} entries (legacy fallback)")

    if path.is_file():
        files = [path]
    elif path.is_dir():
        files = sorted(path.glob("*.json"))
        files = [f for f in files if not f.name.startswith("_")]
        if match:
            needle = str(match).lower()
            files = [f for f in files if needle in f.stem.lower()]
        if isinstance(limit, int) and limit > 0:
            files = files[:limit]
    else:
        print(f"[ERROR] Path not found: {params_path}")
        return

    print(f"=== Parametric Building Generator ===")
    print(f"Files: {len(files)}")

    buildings = []
    manifest_buildings = []
    for i, f in enumerate(files):
        print(f"\n--- [{i+1}/{len(files)}] {f.name} ---")
        with open(f) as fp:
            params = json.load(fp)

        if 'hcd_data' in params:
            hcd = params.get('hcd_data', {})
            print(f"  HCD #{hcd.get('hcd_reference_number', '?')}: {hcd.get('typology', 'Unknown')}, {hcd.get('construction_date', 'Unknown')}")
            if hcd.get('discrepancies'):
                print(f"  Discrepancies: {'; '.join(hcd['discrepancies'])}")

        # Determine building position:
        # 1. Site coordinates from PostGIS GIS export (preferred)
        # 2. Legacy geocode.json fallback
        # 3. Linear spacing as last resort
        address = params.get("building_name") or params.get("_meta", {}).get("address", "")
        geo_key = f.stem

        if site_coords and address and address in site_coords:
            sc = site_coords[address]
            rotation = math.radians(sc.get("rotation_deg", 0))
            offset = (sc["x"], sc["y"], 0)
        elif site_coords:
            # Try matching by filename stem (address with underscores)
            stem_addr = geo_key.replace("_", " ")
            if stem_addr in site_coords:
                sc = site_coords[stem_addr]
                offset = (sc["x"], sc["y"], 0)
                rotation = math.radians(sc.get("rotation_deg", 0))
            elif geocode and geo_key in geocode:
                gc = geocode[geo_key]
                offset = (gc["blender_x"], gc["blender_y"], 0)
                rotation = math.radians(gc.get("rotation_deg", 0))
            else:
                offset = (i * spacing, 0, 0)
                rotation = 0.0
        elif geocode and geo_key in geocode:
            gc = geocode[geo_key]
            offset = (gc["blender_x"], gc["blender_y"], 0)
            rotation = math.radians(gc.get("rotation_deg", 0))
        else:
            offset = (i * spacing, 0, 0)
            rotation = 0.0
        bldg = generate_building(params, offset=offset, rotation=rotation)
        buildings.append(bldg)
        hcd = params.get("hcd_data", {}) if isinstance(params.get("hcd_data"), dict) else {}
        manifest_buildings.append({
            "param_file": str(f.resolve()),
            "building_name": params.get("building_name") or params.get("_meta", {}).get("address", f.stem),
            "collection_name": bldg.name if bldg else None,
            "hcd_reference_number": hcd.get("hcd_reference_number"),
            "typology": hcd.get("typology"),
            "construction_date": hcd.get("construction_date"),
        })

    # Setup camera and lighting
    setup_scene(buildings, spacing)

    print(f"\n=== Done: {len(buildings)} buildings generated ===")
    return {
        "collections": buildings,
        "files": files,
        "buildings": manifest_buildings,
    }


def setup_scene(buildings, spacing):
    """Set up camera, sun, and render settings."""
    # Flush transforms so matrix_world is up-to-date
    bpy.context.view_layer.update()

    # Compute scene bounds from actual mesh bounding boxes (not just obj.location)
    bbox_min = [float('inf')] * 3
    bbox_max = [float('-inf')] * 3
    for col in buildings:
        if not col:
            continue
        for obj in col.objects:
            if obj.type != 'MESH':
                continue
            for corner in obj.bound_box:
                world = obj.matrix_world @ Vector(corner)
                for i in range(3):
                    bbox_min[i] = min(bbox_min[i], world[i])
                    bbox_max[i] = max(bbox_max[i], world[i])

    if bbox_min[0] == float('inf'):
        n = len(buildings)
        center_x = (n - 1) * spacing / 2
        center_y = 0
        facade_y = 0  # front face Y position
        scene_width = n * spacing
        scene_depth = 15.0
        scene_height = 10.0
    else:
        center_x = (bbox_min[0] + bbox_max[0]) / 2
        center_y = (bbox_min[1] + bbox_max[1]) / 2
        facade_y = bbox_max[1]  # front face = max Y (facade faces -Y, front is at max Y)
        scene_width = bbox_max[0] - bbox_min[0]
        scene_depth = bbox_max[1] - bbox_min[1]
        scene_height = bbox_max[2] - bbox_min[2]
        print(f"  [CAMERA] bbox: ({bbox_min[0]:.1f},{bbox_min[1]:.1f},{bbox_min[2]:.1f}) to ({bbox_max[0]:.1f},{bbox_max[1]:.1f},{bbox_max[2]:.1f})")
        print(f"  [CAMERA] center: ({center_x:.1f},{center_y:.1f}), dims: {scene_width:.1f}x{scene_depth:.1f}x{scene_height:.1f}m")

    # Sun light — warm afternoon from south-west
    bpy.ops.object.light_add(type='SUN', location=(center_x, center_y + 50, 50))
    sun = bpy.context.active_object
    sun.name = "Sun"
    sun.data.energy = 3.0
    sun.rotation_euler = (math.radians(50), math.radians(15), math.radians(210))

    # Camera — framed to actual building dimensions
    n_buildings = len([c for c in buildings if c])
    # Use facade-facing dimensions for framing (width + height), not depth
    facade_dim = max(scene_width, scene_height, 5.0)
    max_dim = max(scene_width, scene_depth, scene_height, 5.0)

    if n_buildings <= 3:
        orbit_radius = scene_height * 2.5 + 5.0
        cam_height = scene_height * 0.45 + 1.6

        # Find facade by averaging positions of window/door/bay objects
        facade_locs = []
        for col in buildings:
            if not col:
                continue
            for obj in col.objects:
                if obj.type == 'MESH' and any(kw in obj.name.lower() for kw in
                        ["frame_", "glass_", "door_", "bay_window", "bay_glass",
                         "storefront", "transom", "muntin"]):
                    facade_locs.append(obj.location.copy())

        if facade_locs:
            avg = sum(facade_locs, Vector()) / len(facade_locs)
            # Direction from building center to window cluster = toward facade
            facade_dir = Vector((avg.x - center_x, avg.y - center_y, 0))
            if facade_dir.length > 0.01:
                facade_dir.normalize()
            else:
                facade_dir = Vector((1, 0, 0))
            # Camera in front of facade, slight offset for 3/4 view
            perp = Vector((-facade_dir.y, facade_dir.x, 0))
            cam_x = center_x + facade_dir.x * orbit_radius + perp.x * orbit_radius * 0.15
            cam_y = center_y + facade_dir.y * orbit_radius + perp.y * orbit_radius * 0.15
            print(f"  [CAMERA] facade from {len(facade_locs)} objects, dir=({facade_dir.x:.2f},{facade_dir.y:.2f})")
        else:
            # Fallback: use bbox min on wider axis
            if scene_width >= scene_depth:
                cam_x = bbox_min[0] - orbit_radius * 0.9
                cam_y = center_y - orbit_radius * 0.2
            else:
                cam_x = center_x - orbit_radius * 0.2
                cam_y = bbox_min[1] - orbit_radius * 0.9
            print(f"  [CAMERA] no facade objects, using bbox fallback")

        target = Vector((center_x, center_y, scene_height * 0.4))
        cam_loc = Vector((cam_x, cam_y, cam_height))
        direction = target - cam_loc
        rot_quat = direction.to_track_quat('-Z', 'Y')
        print(f"  [CAMERA] orbit r={orbit_radius:.1f}, cam=({cam_x:.1f},{cam_y:.1f},{cam_height:.1f})")
        bpy.ops.object.camera_add(location=cam_loc)
        cam = bpy.context.active_object
        cam.name = "Camera"
        cam.rotation_euler = rot_quat.to_euler()
    else:
        # Wide neighbourhood view — look from south (positive direction)
        cam_dist = max_dim * 1.2
        cam_height = max_dim * 0.8
        cam_loc = Vector((center_x + cam_dist * 0.3, center_y - cam_dist * 0.4, cam_height))
        target = Vector((center_x, center_y, scene_height * 0.3))
        direction = target - cam_loc
        rot_quat = direction.to_track_quat('-Z', 'Y')
        bpy.ops.object.camera_add(location=cam_loc)
        cam = bpy.context.active_object
        cam.name = "Camera"
        cam.rotation_euler = rot_quat.to_euler()

    cam.data.lens = 35  # 35mm — slightly wide, shows context without distortion
    bpy.context.scene.camera = cam

    # Render settings — ensure material/rendered mode, not solid/wireframe
    scene = bpy.context.scene

    # --- Render Engine Setup ---
    # Cycles (GPU) for hero/QA renders, EEVEE for batch speed
    # Default: EEVEE for batch. Override with --cycles flag.

    use_cycles = "--cycles" in sys.argv

    if use_cycles:
        scene.render.engine = 'CYCLES'
        scene.cycles.device = 'GPU'
        scene.cycles.samples = 128
        scene.cycles.use_denoising = True
        scene.cycles.denoiser = 'OPENIMAGEDENOISE'
        scene.cycles.use_adaptive_sampling = True
        scene.cycles.adaptive_threshold = 0.01

        # Enable CUDA for RTX 2080S
        prefs = bpy.context.preferences.addons.get("cycles")
        if prefs:
            cprefs = prefs.preferences
            cprefs.compute_device_type = 'CUDA'
            cprefs.get_devices()
            for dev in cprefs.devices:
                dev.use = True  # enable all available GPUs + CPU
    else:
        # EEVEE — fast, good enough for batch verification
        for engine in ['BLENDER_EEVEE', 'BLENDER_EEVEE_NEXT']:
            try:
                scene.render.engine = engine
                break
            except:
                continue

        # EEVEE quality settings
        try:
            scene.eevee.use_shadows = True
            scene.eevee.shadow_cube_size = '1024'
            scene.eevee.shadow_cascade_size = '2048'
            scene.eevee.use_ssr = True
            scene.eevee.use_ssr_refraction = True
            scene.eevee.taa_render_samples = 64
            scene.eevee.use_gtao = True           # ambient occlusion
            scene.eevee.gtao_distance = 2.0
            scene.eevee.use_bloom = False          # no bloom for architectural
        except AttributeError:
            pass  # Blender version differences

    # --- Common render settings ---
    scene.render.resolution_x = 1920
    scene.render.resolution_y = 1080
    scene.render.film_transparent = False
    scene.render.image_settings.file_format = 'PNG'
    scene.render.image_settings.color_mode = 'RGB'
    scene.render.image_settings.compression = 15

    # Color management — filmic for realistic look
    scene.view_settings.view_transform = 'Filmic'
    scene.view_settings.look = 'Medium High Contrast'
    scene.view_settings.exposure = 0.0

    # World background — sky blue gradient instead of black
    world = bpy.data.worlds.get("World") or bpy.data.worlds.new("World")
    scene.world = world
    world.use_nodes = True
    nodes = world.node_tree.nodes
    links = world.node_tree.links
    nodes.clear()
    bg = nodes.new('ShaderNodeBackground')
    output = nodes.new('ShaderNodeOutputWorld')
    bg.inputs['Color'].default_value = (0.6, 0.7, 0.85, 1.0)  # light sky blue
    bg.inputs['Strength'].default_value = 1.0
    links.new(bg.outputs['Background'], output.inputs['Surface'])

    # Ground plane
    ground_size = max(max_dim * 4, 200)
    bpy.ops.mesh.primitive_plane_add(size=ground_size, location=(center_x, center_y, 0))
    ground = bpy.context.active_object
    ground.name = "ground"
    ground_mat = get_or_create_material("mat_ground", colour_hex="#505050", roughness=0.95)
    assign_material(ground, ground_mat)


def default_output_paths(params_path, output_blend=None, output_dir=None, render_path=None):
    """Compute default .blend and optional render output paths."""
    path = Path(params_path)
    if output_dir:
        out_dir = Path(output_dir)
    elif path.is_file():
        out_dir = path.parent.parent / "outputs"
    else:
        out_dir = path.parent / "outputs"

    if path.is_file():
        stem = path.stem
        blend_default = out_dir / f"{stem}.blend"
        render_default = out_dir / f"{stem}.png"
    else:
        blend_default = out_dir / "kensington_pilot.blend"
        render_default = out_dir / "kensington_pilot.png"

    blend_path = Path(output_blend) if output_blend else blend_default
    render_out = Path(render_path) if render_path else None
    return blend_path.resolve(), (render_out.resolve() if render_out else render_default.resolve())


def default_manifest_path(blend_path):
    """Place the run manifest next to the output .blend file."""
    return blend_path.with_suffix(".manifest.json")


def write_manifest(manifest_path, params_path, blend_path, render_path, do_render, run_data):
    """Write a machine-readable summary of the generation run."""
    run_data = run_data or {}
    payload = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "params_path": str(Path(params_path).resolve()),
        "blend_path": str(blend_path),
        "render_path": str(render_path) if do_render else None,
        "building_count": len(run_data.get("buildings", [])),
        "buildings": run_data.get("buildings", []),
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
        f.write("\n")
    print(f"Manifest: {manifest_path}")


def purge_orphans_safe():
    """Purge Blender orphan data with operator fallback for headless/context issues."""
    try:
        bpy.ops.outliner.orphans_purge(do_local_ids=True, do_linked_ids=True, do_recursive=True)
    except Exception:
        # Fallback: manually purge orphan meshes and materials
        for block in list(bpy.data.meshes):
            if block.users == 0:
                bpy.data.meshes.remove(block)
        for block in list(bpy.data.materials):
            if block.users == 0:
                bpy.data.materials.remove(block)


def resolve_batch_files(params_dir, output_dir=None, do_render=False,
                        skip_existing=False, match=None, limit=None):
    """Resolve which batch files would be processed and where outputs would go."""
    params_dir = Path(params_dir)
    files = sorted(f for f in params_dir.glob("*.json") if not f.name.startswith("_"))
    if match:
        needle = match.lower()
        files = [f for f in files if needle in f.stem.lower()]
    if isinstance(limit, int) and limit > 0:
        files = files[:limit]

    out_dir = Path(output_dir) if output_dir else params_dir.parent / "outputs"
    plans = []
    for f in files:
        # Skip param files marked as skipped (non-buildings, duplicates)
        try:
            with open(f, encoding="utf-8") as fh:
                pdata = json.load(fh)
            if pdata.get("skipped"):
                continue
        except Exception:
            pass
        blend_path, render_path = default_output_paths(str(f), output_dir=str(out_dir))
        manifest_path = default_manifest_path(blend_path)
        skipped = bool(skip_existing and blend_path.exists())
        plans.append({
            "param_file": str(f.resolve()),
            "blend_path": str(blend_path),
            "render_path": str(render_path) if do_render else None,
            "manifest_path": str(manifest_path),
            "skipped": skipped,
        })
    return plans


def generate_batch_individual(params_dir, output_dir=None, do_render=False,
                              skip_existing=False, match=None, limit=None):
    """Generate one .blend per param file plus a batch manifest."""
    params_dir = Path(params_dir)
    plans = resolve_batch_files(
        params_dir,
        output_dir=output_dir,
        do_render=do_render,
        skip_existing=skip_existing,
        match=match,
        limit=limit,
    )
    if not plans:
        print(f"[ERROR] No param files found in: {params_dir}")
        return None

    out_dir = Path(output_dir) if output_dir else params_dir.parent / "outputs"
    out_dir.mkdir(parents=True, exist_ok=True)

    batch_manifest = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "params_path": str(params_dir.resolve()),
        "mode": "batch_individual",
        "building_count": len(plans),
        "filters": {
            "match": match,
            "limit": limit,
            "skip_existing": skip_existing,
        },
        "counts": {
            "completed": 0,
            "skipped": 0,
            "failed": 0,
        },
        "buildings": [],
    }

    print(f"=== Parametric Building Generator ===")
    print(f"Files: {len(plans)}")
    print("Mode: batch individual")

    for i, plan in enumerate(plans, start=1):
        f = Path(plan["param_file"])
        blend_path = Path(plan["blend_path"])
        render_path = Path(plan["render_path"]) if plan["render_path"] else None
        manifest_path = Path(plan["manifest_path"])
        print(f"\n--- [{i}/{len(plans)}] {f.name} ---")

        if plan["skipped"]:
            print(f"  [SKIP] Existing output: {blend_path.name}")
            batch_manifest["counts"]["skipped"] += 1
            batch_manifest["buildings"].append({
                "param_file": str(f.resolve()),
                "blend_path": str(blend_path),
                "render_path": str(render_path) if do_render and render_path and render_path.exists() else None,
                "manifest_path": str(manifest_path) if manifest_path.exists() else None,
                "skipped": True,
                "status": "skipped",
            })
            continue

        try:
            run_data = load_and_generate(str(f), spacing=15.0)

            purge_orphans_safe()
            bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))
            print(f"Saved: {blend_path}")

            rendered = None
            if do_render:
                bpy.context.scene.render.filepath = str(render_path)
                bpy.ops.render.render(write_still=True)
                rendered = str(render_path)
                print(f"Rendered: {render_path}")

            write_manifest(manifest_path, str(f), blend_path, render_path, do_render, run_data)
            batch_manifest["counts"]["completed"] += 1
            batch_manifest["buildings"].append({
                "param_file": str(f.resolve()),
                "blend_path": str(blend_path),
                "render_path": rendered,
                "manifest_path": str(manifest_path),
                "summary": run_data.get("buildings", [{}])[0] if run_data else {},
                "skipped": False,
                "status": "completed",
            })
        except Exception as e:
            print(f"  [FAIL] {f.name}: {e}")
            batch_manifest["counts"]["failed"] += 1
            batch_manifest["buildings"].append({
                "param_file": str(f.resolve()),
                "blend_path": str(blend_path),
                "render_path": None,
                "manifest_path": None,
                "skipped": False,
                "status": "failed",
                "error": str(e),
            })

    batch_manifest_path = out_dir / "batch.manifest.json"
    with open(batch_manifest_path, "w") as f:
        json.dump(batch_manifest, f, indent=2)
        f.write("\n")
    print(f"\nBatch manifest: {batch_manifest_path}")
    return batch_manifest


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def _validate_params(params):
    """Pre-generation validation. Returns (ok, errors) tuple."""
    errors = []
    name = params.get("building_name", "unknown")

    if not params.get("facade_width_m") or params["facade_width_m"] <= 0:
        errors.append(f"{name}: facade_width_m is missing or <= 0")
    if not params.get("total_height_m") or params["total_height_m"] <= 0:
        errors.append(f"{name}: total_height_m is missing or <= 0")
    if not params.get("floors") or params["floors"] <= 0:
        errors.append(f"{name}: floors is missing or <= 0")

    if not params.get("floor_heights_m"):
        errors.append(f"{name}: WARNING - floor_heights_m missing, will use defaults")
    if not params.get("roof_type"):
        errors.append(f"{name}: WARNING - roof_type missing, will default to flat")
    if not params.get("facade_material"):
        errors.append(f"{name}: WARNING - facade_material missing, will default to brick")

    critical = [e for e in errors if "WARNING" not in e]
    return len(critical) == 0, errors

if __name__ == "__main__":
    import argparse

    argv = sys.argv
    cli_args = argv[argv.index("--") + 1:] if "--" in argv else argv[1:]

    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--validate", action="store_true", help="Validate params without generating")
    parser.add_argument("--params-dir", default="params", help="Params directory")
    parser.add_argument("--match", help="Only process buildings matching this string")
    parsed, _ = parser.parse_known_args(cli_args)

    if parsed.validate:
        params_dir = Path(parsed.params_dir)
        ok = 0
        fail = 0
        errors = []
        for f in sorted(params_dir.glob("*.json")):
            try:
                p = json.loads(f.read_text(encoding="utf-8"))
                if p.get("skipped"):
                    continue
                if parsed.match and parsed.match.lower() not in f.stem.lower():
                    continue
                valid, errs = _validate_params(p)
                if valid:
                    ok += 1
                else:
                    fail += 1
                    errors.extend(errs)
            except Exception as e:
                fail += 1
                errors.append(f"{f.name}: {e}")
        print(f"Validated: {ok} OK, {fail} FAIL")
        for err in errors:
            print(f"  {err}")
        sys.exit(0 if fail == 0 else 1)

    params_path = str(PARAMS_DIR)
    output_blend = None
    output_dir = None
    render_output = None
    manifest_output = None
    do_render = False
    batch_individual = False
    skip_existing = False
    match_filter = None
    limit = None
    dry_run = False

    if cli_args:
        args = cli_args

        def _get_value(idx):
            nxt = idx + 1
            if nxt >= len(args):
                return None
            value = args[nxt]
            if isinstance(value, str) and value.startswith("--"):
                return None
            return value

        i = 0
        while i < len(args):
            arg = args[i]
            if arg in ("--params", "--single"):
                value = _get_value(i)
                if value is None:
                    print(f"[WARN] Missing value for {arg}; keeping default params path")
                else:
                    params_path = value
                    i += 1
            elif arg == "--output-blend":
                value = _get_value(i)
                if value is None:
                    print("[WARN] Missing value for --output-blend; ignoring")
                else:
                    output_blend = value
                    i += 1
            elif arg == "--output-dir":
                value = _get_value(i)
                if value is None:
                    print("[WARN] Missing value for --output-dir; ignoring")
                else:
                    output_dir = value
                    i += 1
            elif arg == "--render":
                do_render = True
            elif arg == "--batch-individual":
                batch_individual = True
            elif arg == "--skip-existing":
                skip_existing = True
            elif arg == "--dry-run":
                dry_run = True
            elif arg == "--match":
                value = _get_value(i)
                if value is None:
                    print("[WARN] Missing value for --match; ignoring")
                else:
                    match_filter = value
                    i += 1
            elif arg == "--limit":
                value = _get_value(i)
                if value is None:
                    print("[WARN] Missing value for --limit; ignoring")
                else:
                    try:
                        limit = int(value)
                    except ValueError:
                        print(f"[WARN] Invalid --limit '{value}'; ignoring")
                        limit = None
                    i += 1
            elif arg == "--render-output":
                value = _get_value(i)
                if value is None:
                    print("[WARN] Missing value for --render-output; ignoring")
                else:
                    render_output = value
                    i += 1
            elif arg == "--manifest-output":
                value = _get_value(i)
                if value is None:
                    print("[WARN] Missing value for --manifest-output; ignoring")
                else:
                    manifest_output = value
                    i += 1
            elif isinstance(arg, str) and arg.startswith("--"):
                print(f"[WARN] Unknown option: {arg}")
            i += 1

    if dry_run:
        path = Path(params_path)
        if path.is_dir() and batch_individual:
            plans = resolve_batch_files(
                path,
                output_dir=output_dir,
                do_render=do_render,
                skip_existing=skip_existing,
                match=match_filter,
                limit=limit,
            )
            print("=== Dry Run ===")
            print(f"Mode: batch individual")
            print(f"Files: {len(plans)}")
            for plan in plans:
                status = "SKIP" if plan["skipped"] else "RUN"
                print(f"[{status}] {Path(plan['param_file']).name} -> {Path(plan['blend_path']).name}")
                if plan["render_path"]:
                    print(f"       render: {Path(plan['render_path']).name}")
                print(f"       manifest: {Path(plan['manifest_path']).name}")
        else:
            blend_path, render_path = default_output_paths(
                params_path,
                output_blend=output_blend,
                output_dir=output_dir,
                render_path=render_output,
            )
            manifest_path = Path(manifest_output).resolve() if manifest_output else default_manifest_path(blend_path)
            print("=== Dry Run ===")
            print(f"Params: {Path(params_path).resolve()}")
            print(f"Blend: {blend_path}")
            if do_render:
                print(f"Render: {render_path}")
            print(f"Manifest: {manifest_path}")
        sys.exit(0)

    if Path(params_path).is_dir() and batch_individual:
        try:
            generate_batch_individual(
                params_path,
                output_dir=output_dir,
                do_render=do_render,
                skip_existing=skip_existing,
                match=match_filter,
                limit=limit,
            )
        except Exception as e:
            print(f"Batch generation failed: {e}")
        sys.exit(0)

    # Generate buildings
    run_data = load_and_generate(params_path, match=match_filter, limit=limit)
    if run_data is None:
        print("[ERROR] Generation aborted due to invalid input path.")
        sys.exit(1)

    blend_path, render_path = default_output_paths(
        params_path,
        output_blend=output_blend,
        output_dir=output_dir,
        render_path=render_output,
    )
    manifest_path = Path(manifest_output).resolve() if manifest_output else default_manifest_path(blend_path)
    blend_path.parent.mkdir(parents=True, exist_ok=True)

    # Purge orphan data to reduce file size
    purge_orphans_safe()
    try:
        bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))
        print(f"Saved: {blend_path}")
    except Exception as e:
        print(f"Could not save .blend file: {e}")

    if do_render:
        render_path.parent.mkdir(parents=True, exist_ok=True)
        bpy.context.scene.render.filepath = str(render_path)
        try:
            bpy.ops.render.render(write_still=True)
            print(f"Rendered: {render_path}")
        except Exception as e:
            print(f"Could not render snapshot: {e}")

    try:
        write_manifest(manifest_path, params_path, blend_path, render_path, do_render, run_data)
    except Exception as e:
        print(f"Could not write manifest: {e}")
