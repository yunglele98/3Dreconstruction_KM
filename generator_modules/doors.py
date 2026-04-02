"""Door cutting for the Kensington building generator.

_resolve_doors, cut_doors.
Requires bpy and imports from materials, geometry, colours.

Extracted from generate_building.py.
"""

import bpy
import bmesh
import math
from mathutils import Vector

from generator_modules.colours import colour_name_to_hex
from generator_modules.materials import (
    assign_material, get_or_create_material,
    create_canvas_material,
)
from generator_modules.geometry import (
    boolean_cut, create_arch_cutter, create_rect_cutter,
)


def _resolve_doors(params, facade_width):
    """Collect all door specs from params, resolving indirect references."""
    resolved = []

    # 1) Direct doors_detail entries with dimensions
    for door in params.get("doors_detail", []):
        if not isinstance(door, dict):
            continue
        if "width_m" in door:
            # Normalize: some params use height_to_crown_m instead of height_m
            d = dict(door)
            if "height_m" not in d and "height_to_crown_m" in d:
                d["height_m"] = d["height_to_crown_m"]
            # Detect glass from material field
            mat_str = str(d.get("material", "")).lower()
            dtype = str(d.get("type", "")).lower()
            if "glass" in dtype or "alumin" in mat_str or "glass" in mat_str:
                d["is_glass"] = True
            resolved.append(d)

    # 2) Resolve from ground_floor_arches (e.g. 20 Denison Sq)
    arches = params.get("ground_floor_arches", {})
    if isinstance(arches, dict):
        for arch_key in ["left_arch", "right_arch", "centre_arch", "center_arch"]:
            arch = arches.get(arch_key, {})
            if not isinstance(arch, dict):
                continue
            func = str(arch.get("function", "")).lower()
            if func == "entrance" or "door" in str(arch.get("door", {})):
                door_in_arch = arch.get("door", {})
                w = arch.get("total_width_m", 1.0)
                h = arch.get("total_height_m", 2.2)
                # Position: left_arch → left side, right_arch → right side
                if "left" in arch_key:
                    pos = "left"
                elif "right" in arch_key:
                    pos = "right"
                else:
                    pos = "center"
                colour = "dark_brown_stained"
                colour_hex = ""
                if isinstance(door_in_arch, dict):
                    colour = door_in_arch.get("colour", colour)
                    colour_hex = door_in_arch.get("colour_hex", "")
                    w = door_in_arch.get("width_m", w)
                    h = door_in_arch.get("height_m", h)
                resolved.append({
                    "width_m": w,
                    "height_m": h,
                    "position": pos,
                    "type": arch.get("type", "arched"),
                    "colour": colour,
                    "colour_hex": colour_hex,
                    "material": door_in_arch.get("material", "wood") if isinstance(door_in_arch, dict) else "wood",
                    "_source": "ground_floor_arches",
                })

    # 3) Resolve from windows_detail[].entrance (e.g. 21 Nassau St)
    for wd in params.get("windows_detail", []):
        if not isinstance(wd, dict):
            continue
        entrance = wd.get("entrance", {})
        if not isinstance(entrance, dict) or not entrance:
            continue
        w = entrance.get("width_m", 1.0)
        h = entrance.get("height_m", 2.2)
        pos = str(entrance.get("position", "center")).lower()
        etype = str(entrance.get("type", "")).lower()
        frame_col = entrance.get("frame_colour", "")
        frame_hex = entrance.get("frame_colour_hex", "")
        is_glass = "glass" in etype or "aluminum" in str(entrance.get("frame_material", "")).lower()
        d = {
            "width_m": w,
            "height_m": h,
            "position": pos,
            "type": etype,
            "colour": entrance.get("colour", frame_col),
            "colour_hex": frame_hex,
            "frame_colour": frame_col,
            "frame_colour_hex": frame_hex,
            "material": entrance.get("frame_material", "wood"),
            "glazing": entrance.get("glazing", ""),
            "is_glass": is_glass,
            "_source": "windows_detail_entrance",
        }
        # Carry awning data if present
        aw = entrance.get("awning", {})
        if isinstance(aw, dict) and aw.get("present", aw.get("type")):
            d["awning"] = aw
        resolved.append(d)

    # 4) Resolve from storefront entrance (backup for commercial buildings)
    sf = params.get("storefront", {})
    if isinstance(sf, dict):
        sf_ent = sf.get("entrance", {})
        if isinstance(sf_ent, dict) and sf_ent.get("width_m"):
            # Only add if not already captured
            already = any(d.get("_source") == "windows_detail_entrance" for d in resolved)
            if not already:
                resolved.append({
                    "width_m": sf_ent.get("width_m", 0.9),
                    "height_m": sf_ent.get("height_m", 2.1),
                    "position": str(sf_ent.get("position", "left")).lower(),
                    "type": sf_ent.get("type", "commercial_glass"),
                    "colour": sf_ent.get("colour", ""),
                    "colour_hex": sf_ent.get("colour_hex", ""),
                    "material": sf_ent.get("material", "aluminum"),
                    "is_glass": True,
                    "_source": "storefront_entrance",
                })

    # If still no doors resolved, don't fabricate one
    return resolved


def cut_doors(wall_obj, params, facade_width):
    """Cut door openings from the front wall, resolving from all param sources."""
    doors = _resolve_doors(params, facade_width)
    door_objects = []

    for i, door in enumerate(doors):
        w = door.get("width_m", 0.9)
        h = door.get("height_m", 2.2)

        # Determine x position
        pos = str(door.get("position", "center")).lower()
        if "left" in pos:
            x = -facade_width / 4
        elif "right" in pos:
            x = facade_width / 4
        else:
            x = 0

        # Check if arched — check type and arch_head fields
        door_type = str(door.get("type", "")).lower()
        arch_head = str(door.get("arch_head", "")).lower()
        is_arched = "arch" in door_type or "semicircular" in door_type or \
                    "arch" in arch_head or "segmental" in arch_head or "pointed" in arch_head
        is_glass = door.get("is_glass", False) or "glass" in door_type or "aluminum" in str(door.get("material", "")).lower()
        is_rolling = "rolling" in door_type or "shutter" in door_type
        is_double = "double" in door_type

        # Cut opening
        if is_arched:
            cutter = create_arch_cutter(f"door_cut_{i}", w, h, h * 0.7, depth=0.8)
        else:
            cutter = create_rect_cutter(f"door_cut_{i}", w, h, depth=0.8)
            cutter.location.z = h / 2

        cutter.location.x = x
        cutter.location.y = 0.01
        boolean_cut(wall_obj, cutter)

        # Determine door colour
        door_hex = door.get("colour_hex", "")
        if not door_hex or not door_hex.startswith("#"):
            col_name = str(door.get("colour", "")).lower().replace(" ", "_")
            if col_name:
                door_hex = colour_name_to_hex(col_name)
            else:
                door_hex = "#5A3A2A"

        # Frame colour
        frame_hex = door.get("frame_colour_hex", "")
        if not frame_hex or not frame_hex.startswith("#"):
            fc = str(door.get("frame_colour", "")).lower().replace(" ", "_")
            if fc and "bronze" in fc:
                frame_hex = "#4A3A2A"
            elif fc and "white" in fc:
                frame_hex = "#F0F0F0"
            elif fc:
                frame_hex = colour_name_to_hex(fc)
            elif is_glass:
                frame_hex = "#3A3A3A"
            else:
                frame_hex = "#F0F0F0"

        # --- Create door panel ---
        if is_glass:
            # Glass door — translucent panel
            glass_mat_name = f"mat_glass_door_{i}"
            if glass_mat_name not in bpy.data.materials:
                gm = bpy.data.materials.new(name=glass_mat_name)
                gm.blend_method = 'BLEND' if hasattr(gm, 'blend_method') else None
                gbsdf = gm.node_tree.nodes.get("Principled BSDF")
                if gbsdf:
                    gbsdf.inputs["Base Color"].default_value = (0.7, 0.8, 0.85, 1.0)
                    gbsdf.inputs["Roughness"].default_value = 0.05
                    if "Alpha" in gbsdf.inputs:
                        gbsdf.inputs["Alpha"].default_value = 0.3
                    if "Transmission Weight" in gbsdf.inputs:
                        gbsdf.inputs["Transmission Weight"].default_value = 0.8
                    elif "Transmission" in gbsdf.inputs:
                        gbsdf.inputs["Transmission"].default_value = 0.8
            else:
                gm = bpy.data.materials[glass_mat_name]

            bpy.ops.mesh.primitive_cube_add(size=1)
            dp = bpy.context.active_object
            dp.name = f"door_glass_{i}"
            dp.scale = (w * 0.92, 0.03, h * 0.92)
            bpy.ops.object.transform_apply(scale=True)
            dp.location = (x, 0.02, h * 0.92 / 2 + 0.05)
            assign_material(dp, gm)
            door_objects.append(dp)

            # Aluminum/metal frame bars
            frame_mat = get_or_create_material(f"mat_door_frame_{i}", colour_hex=frame_hex, roughness=0.3)
            # Centre mullion for double doors
            if is_double:
                bpy.ops.mesh.primitive_cube_add(size=1)
                cm = bpy.context.active_object
                cm.name = f"door_mullion_{i}"
                cm.scale = (0.04, 0.05, h * 0.92)
                bpy.ops.object.transform_apply(scale=True)
                cm.location = (x, 0.01, h * 0.92 / 2 + 0.05)
                assign_material(cm, frame_mat)
                door_objects.append(cm)

            # Side frames
            for side_x, fname in [(x - w / 2, "left"), (x + w / 2, "right")]:
                bpy.ops.mesh.primitive_cube_add(size=1)
                df = bpy.context.active_object
                df.name = f"door_frame_{fname}_{i}"
                df.scale = (0.04, 0.06, h)
                bpy.ops.object.transform_apply(scale=True)
                df.location = (side_x, 0.02, h / 2)
                assign_material(df, frame_mat)
                door_objects.append(df)

            # Top frame
            bpy.ops.mesh.primitive_cube_add(size=1)
            dh = bpy.context.active_object
            dh.name = f"door_header_{i}"
            dh.scale = (w + 0.08, 0.06, 0.04)
            bpy.ops.object.transform_apply(scale=True)
            dh.location = (x, 0.02, h + 0.02)
            assign_material(dh, frame_mat)
            door_objects.append(dh)

        elif is_rolling:
            # Rolling shutter door (fire station style)
            door_mat = get_or_create_material(f"mat_door_{i}", colour_hex=door_hex, roughness=0.4)
            # Horizontal slat pattern — stack thin panels
            slat_h = 0.08
            slat_count = int(h / slat_h)
            for si in range(slat_count):
                bpy.ops.mesh.primitive_cube_add(size=1)
                slat = bpy.context.active_object
                slat.name = f"door_slat_{i}_{si}"
                slat.scale = (w * 0.95, 0.04, slat_h * 0.85)
                bpy.ops.object.transform_apply(scale=True)
                slat.location = (x, 0.02, slat_h * si + slat_h / 2 + 0.05)
                assign_material(slat, door_mat)
                door_objects.append(slat)

        else:
            # Solid wood/painted door panel
            door_mat = get_or_create_material(f"mat_door_{i}", colour_hex=door_hex, roughness=0.6)
            panel_w = w * 0.9
            panel_h = h * 0.95
            bpy.ops.mesh.primitive_cube_add(size=1)
            dp = bpy.context.active_object
            dp.name = f"door_panel_{i}"
            dp.scale = (panel_w, 0.06, panel_h)
            bpy.ops.object.transform_apply(scale=True)
            dp.location = (x, 0.02, panel_h / 2)
            assign_material(dp, door_mat)
            door_objects.append(dp)

            # Raised panels — two stacked rectangular raised panels on door face
            panel_trim_mat = get_or_create_material(f"mat_door_trim_{i}", colour_hex=frame_hex, roughness=0.5)
            rpw = panel_w * 0.7  # raised panel width
            rp_gap = 0.08  # gap between panels
            # Bottom panel (taller)
            rp_bot_h = panel_h * 0.45
            bpy.ops.mesh.primitive_cube_add(size=1)
            rp1 = bpy.context.active_object
            rp1.name = f"door_rpanel_bot_{i}"
            rp1.scale = (rpw, 0.015, rp_bot_h)
            bpy.ops.object.transform_apply(scale=True)
            rp1.location = (x, 0.05, 0.1 + rp_bot_h / 2)
            assign_material(rp1, door_mat)
            door_objects.append(rp1)
            # Top panel (shorter)
            rp_top_h = panel_h * 0.35
            rp_top_z = 0.1 + rp_bot_h + rp_gap + rp_top_h / 2
            bpy.ops.mesh.primitive_cube_add(size=1)
            rp2 = bpy.context.active_object
            rp2.name = f"door_rpanel_top_{i}"
            rp2.scale = (rpw, 0.015, rp_top_h)
            bpy.ops.object.transform_apply(scale=True)
            rp2.location = (x, 0.05, rp_top_z)
            assign_material(rp2, door_mat)
            door_objects.append(rp2)

            # Door handle/knob
            handle_side = 1 if not is_double else 0
            hx = x + (panel_w / 2 - 0.08) * (1 if handle_side else -1)
            bpy.ops.mesh.primitive_cylinder_add(radius=0.02, depth=0.03, vertices=12)
            knob = bpy.context.active_object
            knob.name = f"door_knob_{i}"
            knob.rotation_euler.x = math.pi / 2
            knob.location = (hx, 0.06, h * 0.45)
            knob_mat = get_or_create_material("mat_door_knob", colour_hex="#C0A060", roughness=0.3)
            assign_material(knob, knob_mat)
            door_objects.append(knob)

            # Centre mullion for double doors
            if is_double or w > 1.2:
                bpy.ops.mesh.primitive_cube_add(size=1)
                sp = bpy.context.active_object
                sp.name = f"door_split_{i}"
                sp.scale = (0.02, 0.065, h * 0.9)
                bpy.ops.object.transform_apply(scale=True)
                sp.location = (x, 0.025, h * 0.9 / 2 + 0.02)
                assign_material(sp, panel_trim_mat)
                door_objects.append(sp)

            # Frame surround
            frame_mat = get_or_create_material(f"mat_door_frame_{i}", colour_hex=frame_hex, roughness=0.5)
            for side_x, fname in [(x - w / 2, "left"), (x + w / 2, "right")]:
                bpy.ops.mesh.primitive_cube_add(size=1)
                df = bpy.context.active_object
                df.name = f"door_frame_{fname}_{i}"
                df.scale = (0.05, 0.08, h)
                bpy.ops.object.transform_apply(scale=True)
                df.location = (side_x, 0.04, h / 2)
                assign_material(df, frame_mat)
                door_objects.append(df)

            # Door header / lintel
            bpy.ops.mesh.primitive_cube_add(size=1)
            dh = bpy.context.active_object
            dh.name = f"door_header_{i}"
            dh.scale = (w + 0.1, 0.08, 0.06)
            bpy.ops.object.transform_apply(scale=True)
            dh.location = (x, 0.04, h + 0.03)
            assign_material(dh, frame_mat)
            door_objects.append(dh)

            # Threshold / sill
            bpy.ops.mesh.primitive_cube_add(size=1)
            thr = bpy.context.active_object
            thr.name = f"door_threshold_{i}"
            thr.scale = (w, 0.12, 0.03)
            bpy.ops.object.transform_apply(scale=True)
            thr.location = (x, 0.04, 0.015)
            assign_material(thr, frame_mat)
            door_objects.append(thr)

        # Awning / canopy over door (from any door type)
        aw = door.get("awning", {})
        if isinstance(aw, dict) and aw.get("present", aw.get("type")):
            aw_w = aw.get("width_m", w + 0.5)
            aw_proj = aw.get("projection_m", 1.2)
            aw_z = aw.get("height_above_grade_m", h + 0.3)
            aw_hex = aw.get("colour_hex", "")
            if not aw_hex or not aw_hex.startswith("#"):
                aw_hex = colour_name_to_hex(str(aw.get("colour", "dark_grey")))
            aw_mat = create_canvas_material(f"mat_awning_{aw_hex.lstrip('#')}", aw_hex)
            bpy.ops.mesh.primitive_cube_add(size=1)
            canopy = bpy.context.active_object
            canopy.name = f"door_awning_{i}"
            canopy.scale = (aw_w, aw_proj, 0.05)
            bpy.ops.object.transform_apply(scale=True)
            canopy.location = (x, aw_proj / 2, aw_z)
            assign_material(canopy, aw_mat)
            door_objects.append(canopy)

    return door_objects


