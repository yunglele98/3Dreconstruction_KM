"""Window cutting for the Kensington building generator.

cut_windows, bay windows, transoms, window helpers.
Requires bpy and imports from materials, geometry, colours.

Extracted from generate_building.py.
"""

import bpy
import bmesh
import math
from mathutils import Vector

from generator_modules.colours import get_trim_hex, get_facade_hex
from generator_modules.materials import (
    assign_material, get_or_create_material,
    create_glass_material, create_wood_material, create_stone_material,
)
from generator_modules.geometry import (
    boolean_cut, create_arch_cutter, create_rect_cutter, _safe_tan,
)


def _normalize_floor_index(floor_idx_raw, floor_heights):
    """Normalize mixed floor labels into numeric indices."""
    if isinstance(floor_idx_raw, (int, float)):
        return float(floor_idx_raw)
    if isinstance(floor_idx_raw, str):
        fl = floor_idx_raw.lower()
        if "ground" in fl or fl == "1":
            return 1.0
        if "second" in fl or fl == "2":
            return 2.0
        if "third" in fl or fl == "3":
            return 3.0
        if "fourth" in fl or fl == "4":
            return 4.0
        if "attic" in fl or "gable" in fl:
            return len(floor_heights) + 0.5
        try:
            return float(fl)
        except ValueError:
            return 1.0
    return 1.0


def _floor_has_window_spec(floor_data):
    """Return whether a floor entry contains enough data to place windows."""
    if not isinstance(floor_data, dict):
        return False
    if floor_data.get("windows"):
        return True
    if any(key in floor_data for key in ("count", "estimated_count")):
        return True
    for bay_key in ["left_bay", "center_bay", "right_bay"]:
        bay = floor_data.get(bay_key)
        if isinstance(bay, dict) and bay.get("count", 0) > 0:
            return True
    return False


def get_effective_windows_detail(params):
    """Return window detail entries with fallback counts from windows_per_floor."""
    floor_heights = params.get("floor_heights_m", [3.0])
    raw_detail = params.get("windows_detail", [])
    effective = []
    all_upper_templates = []

    for floor_data in raw_detail:
        if not isinstance(floor_data, dict):
            continue
        floor_copy = dict(floor_data)
        floor_label = str(floor_data.get("floor", "")).lower()
        if floor_label in {"all_upper", "upper", "upper_floors"}:
            all_upper_templates.append(floor_copy)
            continue
        effective.append(floor_copy)

    by_floor = {}
    for floor_data in effective:
        floor_idx = int(_normalize_floor_index(floor_data.get("floor", 1), floor_heights))
        by_floor[floor_idx] = floor_data

    windows_per_floor = params.get("windows_per_floor", [])
    default_width = params.get("window_width_m", 0.85)
    default_height = params.get("window_height_m", 1.3)
    window_type = str(params.get("window_type", "double_hung")).lower()
    arch_type = ""
    if "segment" in window_type:
        arch_type = "segmental"
    elif "arched" in window_type or "arch" in window_type:
        arch_type = "semicircular"

    for floor_num, count in enumerate(windows_per_floor, start=1):
        if not isinstance(count, int) or count <= 0:
            continue

        if floor_num in by_floor:
            floor_data = by_floor[floor_num]
            if not _floor_has_window_spec(floor_data):
                floor_data["count"] = count
                floor_data.setdefault("width_m", default_width)
                floor_data.setdefault("height_m", default_height)
                if arch_type:
                    floor_data.setdefault("head_shape", f"{arch_type}_arch")
            continue

        template = None
        if floor_num >= 2 and all_upper_templates:
            template = dict(all_upper_templates[0])

        if template is None:
            template = {"floor": floor_num}
        else:
            template["floor"] = floor_num

        template["count"] = count
        template.setdefault("width_m", default_width)
        template.setdefault("height_m", default_height)
        if arch_type:
            template.setdefault("head_shape", f"{arch_type}_arch")
        effective.append(template)
        by_floor[floor_num] = template

    return effective


def cut_windows(wall_obj, params, wall_h, facade_width, bldg_id=""):
    """Cut window openings from the front wall and add glass panes + frames."""
    windows_detail = get_effective_windows_detail(params)
    floor_heights = params.get("floor_heights_m", [3.0])
    trim_hex = get_trim_hex(params)

    # Pre-compute door x positions so we can skip overlapping ground floor windows
    # Lazy import to avoid circular dependency (doors imports from geometry, windows)
    from generator_modules.doors import _resolve_doors
    door_specs = _resolve_doors(params, facade_width)
    door_x_positions = []
    for ds in door_specs:
        dpos = str(ds.get("position", "center")).lower()
        if "left" in dpos:
            door_x_positions.append(-facade_width / 4)
        elif "right" in dpos:
            door_x_positions.append(facade_width / 4)
        else:
            door_x_positions.append(0)

    has_storefront = params.get("has_storefront", False)

    window_objects = []

    for floor_data in windows_detail:
        if isinstance(floor_data, str):
            continue

        floor_idx = _normalize_floor_index(floor_data.get("floor", 1), floor_heights)

        # Skip ground floor windows for storefront buildings (storefront replaces them)
        if int(floor_idx) == 1 and has_storefront:
            continue

        # Skip ground floor windows that are described as non-window (entrance descriptions etc.)
        if int(floor_idx) == 1:
            desc = str(floor_data.get("description", "")).lower()
            if "entrance" in desc or "storefront" in desc or "glazing" in desc:
                continue

        # Calculate floor z offset — for half-floors (1.5, 2.5), use the floor below
        floor_int = int(floor_idx)
        if floor_idx != floor_int:  # half-floor (e.g. 1.5 → sum first 1 floor)
            z_base = sum(floor_heights[:floor_int])
        else:
            z_base = sum(floor_heights[:max(0, floor_int - 1)])

        # Extract windows from various formats
        windows = floor_data.get("windows", [])
        if not windows and ("count" in floor_data or "estimated_count" in floor_data):
            # Simple format — also handle estimated_* fields
            count = floor_data.get("count", floor_data.get("estimated_count", 0))
            w = floor_data.get("width_m", floor_data.get("estimated_width_m", 0.8))
            h = floor_data.get("height_m", floor_data.get("estimated_height_m", 1.3))
            windows = [{"count": count, "width_m": w, "height_m": h}]

        # Resolve gable/attic window from roof_detail if floor entry is just a note
        if not windows and floor_idx >= 2.5:
            gw = params.get("roof_detail", {}).get("gable_window", {})
            if isinstance(gw, dict) and gw.get("width_m"):
                windows = [{"count": 1, "width_m": gw["width_m"],
                           "height_m": gw.get("height_m", 0.8),
                           "type": gw.get("type", "arched"),
                           "arch_type": gw.get("arch_type", "segmental"),
                           "frame_colour": gw.get("frame_colour", "white")}]

        # Also check bay-based layouts (like 1A Leonard)
        for bay_key in ["left_bay", "center_bay", "right_bay"]:
            bay = floor_data.get(bay_key)
            if bay and isinstance(bay, dict) and bay.get("count", 0) > 0:
                windows.append(bay)

        # Check if individual window specs have position hints (e.g. "left_of_entrance")
        # If so, compute explicit x positions from those hints
        has_position_hints = any(
            isinstance(ws, dict) and ws.get("position") and
            any(kw in str(ws.get("position", "")).lower() for kw in ("left", "right", "center"))
            for ws in windows if isinstance(ws, dict)
        )

        for win_spec in windows:
            if isinstance(win_spec, str):
                continue
            if not isinstance(win_spec, dict):
                continue

            count = win_spec.get("count", 1)
            if count == 0:
                continue

            w = win_spec.get("width_m", win_spec.get("width_each_m", 0.8))
            h = win_spec.get("height_m", 1.3)

            # Window sill height — use param if provided, otherwise center in floor
            fi = max(0, int(floor_idx) - 1)
            fi = min(fi, len(floor_heights) - 1)
            floor_h_here = floor_heights[fi] if floor_heights else 3.0

            # Special case: gable/attic window — center in gable triangle
            if floor_idx >= 2.5 and "gable" in str(params.get("roof_type", "")).lower():
                pitch = params.get("roof_pitch_deg", 35)
                ridge_h = (facade_width / 2) * _safe_tan(pitch)
                gable_center_z = wall_h + ridge_h * 0.45  # slightly below center
                sill_h = gable_center_z - h / 2
            else:
                # Resolve sill height — above_grade is absolute, sill_height_m is
                # relative to this floor's base
                sill_above_grade = (
                    win_spec.get("sill_height_above_grade_m")
                    or floor_data.get("sill_height_above_grade_m")
                )
                sill_relative = win_spec.get("sill_height_m")
                if sill_above_grade is not None:
                    # Absolute from ground level — do NOT add z_base
                    sill_h = float(sill_above_grade)
                elif sill_relative is not None:
                    # Relative to this floor's base
                    sill_h = z_base + float(sill_relative)
                else:
                    sill_h = z_base + max(0.8, (floor_h_here - h) / 2)

            # Determine arch type — check multiple fields
            win_type = str(win_spec.get("type", "double_hung")).lower()
            arch_spec = str(win_spec.get("arch_type", "")).lower()
            is_arched = any(kw in win_type for kw in ("arch", "gothic", "roman", "segmental")) or \
                        any(kw in arch_spec for kw in ("arch", "gothic", "semicircular", "pointed", "segmental"))

            arch_type = "semicircular"
            if "pointed" in win_type or "gothic" in win_type or "pointed" in arch_spec:
                arch_type = "pointed"
            elif "segmental" in win_type or "segmental" in arch_spec:
                arch_type = "segmental"

            # Compute x positions for this window spec
            # If individual spec has position hint, use it relative to door/facade
            win_pos = str(win_spec.get("position", "")).lower()
            c2c = floor_data.get("spacing_center_to_center_m")
            if has_position_hints and count == 1 and win_pos:
                # Use center-to-center spacing from floor data if available
                offset_x = float(c2c) if c2c else facade_width / 4
                if "left" in win_pos:
                    explicit_x = -offset_x
                elif "right" in win_pos:
                    explicit_x = offset_x
                else:
                    explicit_x = 0
                x_positions = [explicit_x]
            elif has_position_hints and count == 1 and not win_pos:
                x_positions = [0]
            else:
                # Generic even spacing
                total_win_width = count * w + (count - 1) * max(0.3, (facade_width - count * w) / (count + 1))
                # Clamp total window span to facade width so windows stay inside the wall
                if total_win_width > facade_width:
                    total_win_width = facade_width
                start_x = -total_win_width / 2 + w / 2
                spacing = (total_win_width - w) / max(1, count - 1) if count > 1 else 0
                x_positions = [start_x + i * spacing if count > 1 else 0 for i in range(count)]

            # Clamp all window x-positions to stay within facade bounds
            hw_limit = facade_width / 2 - w / 2 - 0.05
            x_positions = [max(-hw_limit, min(hw_limit, xp)) for xp in x_positions]

            for i, x in enumerate(x_positions):

                # Skip ground floor windows that overlap with door positions
                if int(floor_idx) == 1 and door_x_positions:
                    overlap = False
                    for dx in door_x_positions:
                        if abs(x - dx) < (w / 2 + 0.3):
                            overlap = True
                            break
                    if overlap:
                        continue

                # Create cutter
                if is_arched:
                    spring_h = h * 0.7
                    cutter = create_arch_cutter(
                        f"win_cut_{floor_idx}_{i}",
                        w, h, spring_h, arch_type=arch_type, depth=0.8
                    )
                else:
                    cutter = create_rect_cutter(f"win_cut_{floor_idx}_{i}", w, h, depth=0.8)
                    cutter.location.z = h / 2

                cutter.location.x = x
                cutter.location.z += sill_h
                cutter.location.y = 0.01  # nudge past front face to avoid coplanar boolean

                boolean_cut(wall_obj, cutter)

                # Add window frame (4 thin boxes forming a rectangle)
                frame_t = 0.04  # frame thickness
                frame_d = 0.06  # frame depth (projection)
                # Per-building frame colour from JSON (some have dark bronze, others white)
                frame_hex = trim_hex
                frame_is_metal = False
                wf_colour = win_spec.get("frame_colour", win_spec.get("frame_colour_hex", ""))
                if isinstance(wf_colour, str) and wf_colour.startswith("#"):
                    frame_hex = wf_colour
                elif isinstance(wf_colour, str) and "bronze" in wf_colour.lower():
                    frame_hex = "#4A3A2A"
                    frame_is_metal = True
                elif isinstance(wf_colour, str) and "dark" in wf_colour.lower():
                    frame_hex = "#3A3A3A"
                elif isinstance(wf_colour, str) and any(
                    kw in wf_colour.lower() for kw in ("metal", "aluminum", "steel")
                ):
                    frame_is_metal = True
                if frame_is_metal:
                    frame_mat = get_or_create_material(
                        f"mat_frame_metal_{frame_hex.lstrip('#')}",
                        colour_hex=frame_hex, roughness=0.3, metallic=0.7)
                else:
                    frame_mat = create_wood_material(
                        f"mat_frame_wood_{frame_hex.lstrip('#')}", frame_hex)

                # Top frame
                bpy.ops.mesh.primitive_cube_add(size=1)
                ft = bpy.context.active_object
                ft.name = f"frame_t_{floor_idx}_{i}"
                ft.scale = (w + frame_t, frame_d, frame_t)
                bpy.ops.object.transform_apply(scale=True)
                ft.location = (x, frame_d / 2, sill_h + h)
                assign_material(ft, frame_mat)
                window_objects.append(ft)

                # Bottom frame (sill)
                bpy.ops.mesh.primitive_cube_add(size=1)
                fb = bpy.context.active_object
                fb.name = f"frame_b_{floor_idx}_{i}"
                fb.scale = (w + frame_t * 2, frame_d * 1.5, frame_t)
                bpy.ops.object.transform_apply(scale=True)
                fb.location = (x, frame_d * 0.75, sill_h)
                assign_material(fb, frame_mat)
                window_objects.append(fb)

                # Left frame
                bpy.ops.mesh.primitive_cube_add(size=1)
                fl = bpy.context.active_object
                fl.name = f"frame_l_{floor_idx}_{i}"
                fl.scale = (frame_t, frame_d, h)
                bpy.ops.object.transform_apply(scale=True)
                fl.location = (x - w / 2, frame_d / 2, sill_h + h / 2)
                assign_material(fl, frame_mat)
                window_objects.append(fl)

                # Right frame
                bpy.ops.mesh.primitive_cube_add(size=1)
                fr = bpy.context.active_object
                fr.name = f"frame_r_{floor_idx}_{i}"
                fr.scale = (frame_t, frame_d, h)
                bpy.ops.object.transform_apply(scale=True)
                fr.location = (x + w / 2, frame_d / 2, sill_h + h / 2)
                assign_material(fr, frame_mat)
                window_objects.append(fr)

                # Middle horizontal mullion (for double-hung look)
                bpy.ops.mesh.primitive_cube_add(size=1)
                fm = bpy.context.active_object
                fm.name = f"frame_m_{floor_idx}_{i}"
                fm.scale = (w, frame_d, frame_t * 0.7)
                bpy.ops.object.transform_apply(scale=True)
                fm.location = (x, frame_d / 2, sill_h + h / 2)
                assign_material(fm, frame_mat)
                window_objects.append(fm)

                # Vertical muntin (creates 2-over-2 pane look)
                bpy.ops.mesh.primitive_cube_add(size=1)
                mv = bpy.context.active_object
                mv.name = f"muntin_v_{floor_idx}_{i}"
                mv.scale = (frame_t * 0.5, frame_d, h * 0.92)
                bpy.ops.object.transform_apply(scale=True)
                mv.location = (x, frame_d / 2, sill_h + h / 2)
                assign_material(mv, frame_mat)
                window_objects.append(mv)

                # For wider windows, add a second vertical muntin (3-pane width)
                if w > 1.0:
                    third = w / 3
                    for mi, mx in enumerate([x - third / 2, x + third / 2]):
                        bpy.ops.mesh.primitive_cube_add(size=1)
                        mv2 = bpy.context.active_object
                        mv2.name = f"muntin_v2_{floor_idx}_{i}_{mi}"
                        mv2.scale = (frame_t * 0.5, frame_d, h * 0.92)
                        bpy.ops.object.transform_apply(scale=True)
                        mv2.location = (mx, frame_d / 2, sill_h + h / 2)
                        assign_material(mv2, frame_mat)
                        window_objects.append(mv2)

                # Add glass pane
                bpy.ops.mesh.primitive_plane_add(size=1)
                glass = bpy.context.active_object
                glass.name = f"glass_{floor_idx}_{i}"
                glass.scale = (w * 0.9, 1, h * 0.9)
                bpy.ops.object.transform_apply(scale=True)
                glass.rotation_euler.x = math.pi / 2
                glass.location = (x, 0.02, sill_h + h / 2)

                glass_mat = create_glass_material("mat_glass")
                assign_material(glass, glass_mat)

                window_objects.append(glass)

    return window_objects




def create_bay_window(params, wall_h, facade_width):
    """Create bay window projection if specified.

    Supports top-level bay_window key, canted (3-sided) geometry,
    double-height bays via floors_spanned, and position offsets.
    """
    floor_heights = params.get("floor_heights_m", [3.0, 3.0])
    objects = []

    # --- Collect bay specs from two sources ---
    bay_specs = []  # list of (bay_dict, floor_idx)

    # Source 1: top-level bay_window key
    top_bay = params.get("bay_window", {})
    if isinstance(top_bay, dict) and top_bay.get("present", False):
        floor_idx = top_bay.get("floor", 1)
        bay_specs.append((top_bay, floor_idx))

    # Source 2: windows_detail entries (existing behavior)
    windows_detail = params.get("windows_detail", [])
    for floor_data in windows_detail:
        if not isinstance(floor_data, dict):
            continue
        bay = floor_data.get("bay_window", {})
        if not isinstance(bay, dict) or not bay.get("type"):
            continue
        floor_idx = floor_data.get("floor", 2)
        bay_specs.append((bay, floor_idx))

    if not bay_specs:
        return objects

    facade_hex = get_facade_hex(params)
    hex_id = facade_hex.lstrip('#')
    facade_mat = get_or_create_material(f"mat_facade_{hex_id}", colour_hex=facade_hex, roughness=0.85)
    glass_mat = create_glass_material("mat_glass")
    trim_mat = get_or_create_material("mat_trim_white", colour_hex="#F0F0F0", roughness=0.5)

    facade_depth = params.get("facade_depth_m", 10.0)
    for bay, floor_idx in bay_specs:
        proj = bay.get("projection_m", 0.4)
        # Clamp projection to 20% of facade depth (prevents geometry beyond footprint)
        proj = min(proj, facade_depth * 0.2, 1.5)
        bay_w = min(bay.get("width_m", 2.5), facade_width - 0.2)  # leave 0.1m each side
        bay_h = bay.get("height_m", 2.0)
        sill_offset = bay.get("sill_height_m", 0.5)

        # --- Double-height: floors_spanned overrides bay_h ---
        floors_spanned = bay.get("floors_spanned", None)
        if floors_spanned and isinstance(floors_spanned, list) and len(floors_spanned) >= 2:
            span_indices = []
            for fs in floors_spanned:
                if isinstance(fs, (int, float)):
                    span_indices.append(int(fs))
                elif isinstance(fs, str):
                    name_map = {"ground": 1, "first": 1, "second": 2, "third": 3, "fourth": 4}
                    span_indices.append(name_map.get(fs.lower(), 1))
            if span_indices:
                first_floor = min(span_indices)
                last_floor = max(span_indices)
                floor_idx = first_floor
                z_start = sum(floor_heights[:max(0, first_floor - 1)])
                z_end = sum(floor_heights[:min(last_floor, len(floor_heights))])
                bay_h = (z_end - z_start) - sill_offset * 0.5

        # --- Z base ---
        z_base = sum(floor_heights[:max(0, int(floor_idx) - 1)]) if isinstance(floor_idx, (int, float)) else 3.0

        # Cap bay height so it doesn't extend above wall_h (into gable zone)
        max_bay_h = wall_h - z_base - sill_offset
        if max_bay_h > 0 and bay_h > max_bay_h:
            bay_h = max_bay_h

        # --- X offset from position field ---
        x_offset = 0.0
        position = bay.get("position", "")
        if isinstance(position, str):
            pos_lower = position.lower()
            if "left" in pos_lower:
                x_offset = -facade_width / 4
            elif "right" in pos_lower:
                x_offset = facade_width / 4
            elif "center" in pos_lower or "centre" in pos_lower:
                x_offset = 0.0

        # --- Determine bay type: canted (3-sided), oriel, or box ---
        bay_type = bay.get("type", "")
        sides = bay.get("sides", 0)
        bay_type_lower = str(bay_type).lower()
        is_canted = (
            sides == 3
            or "three_sided" in bay_type_lower
            or "canted" in bay_type_lower
        )
        is_oriel = "oriel" in bay_type_lower

        if is_canted:
            objects.extend(_create_canted_bay(
                bay, proj, bay_w, bay_h, z_base, sill_offset, x_offset,
                facade_mat, glass_mat, trim_mat
            ))
        else:
            objects.extend(_create_box_bay(
                bay, proj, bay_w, bay_h, z_base, sill_offset, x_offset,
                facade_mat, glass_mat, trim_mat
            ))

        # Oriel bays: add corbel brackets underneath (cantilevered, not ground-supported)
        if is_oriel:
            corbel_z = z_base + sill_offset
            corbel_depth = proj * 0.9
            corbel_h = min(0.4, sill_offset * 0.6) if sill_offset > 0.3 else 0.25
            stone_hex = get_trim_hex(params)
            corbel_mat = create_stone_material(
                f"mat_corbel_{stone_hex.lstrip('#')}", stone_hex)
            # Two corbels — left and right thirds of bay width
            for ci, cx in enumerate([x_offset - bay_w / 3, x_offset + bay_w / 3]):
                bpy.ops.mesh.primitive_cube_add(size=1)
                corbel = bpy.context.active_object
                corbel.name = f"bay_corbel_{ci}"
                corbel.scale = (0.15, corbel_depth * 0.5, corbel_h)
                bpy.ops.object.transform_apply(scale=True)
                corbel.location = (cx, corbel_depth * 0.25, corbel_z - corbel_h / 2)
                assign_material(corbel, corbel_mat)
                objects.append(corbel)
            # Decorative angled bracket faces (triangular profile)
            for ci, cx in enumerate([x_offset - bay_w / 3, x_offset + bay_w / 3]):
                bm = bmesh.new()
                v0 = bm.verts.new((cx - 0.06, 0.01, corbel_z))
                v1 = bm.verts.new((cx + 0.06, 0.01, corbel_z))
                v2 = bm.verts.new((cx + 0.06, corbel_depth * 0.4, corbel_z))
                v3 = bm.verts.new((cx - 0.06, corbel_depth * 0.4, corbel_z))
                v4 = bm.verts.new((cx - 0.06, 0.01, corbel_z - corbel_h))
                v5 = bm.verts.new((cx + 0.06, 0.01, corbel_z - corbel_h))
                bm.faces.new([v0, v1, v2, v3])  # top
                bm.faces.new([v4, v5, v1, v0])  # front
                bm.faces.new([v0, v3, v4])       # left triangle
                bm.faces.new([v1, v5, v2])       # right triangle
                bracket_mesh = bpy.data.meshes.new(f"bay_bracket_{ci}")
                bm.to_mesh(bracket_mesh)
                bm.free()
                bracket_obj = bpy.data.objects.new(f"bay_bracket_{ci}", bracket_mesh)
                bpy.context.collection.objects.link(bracket_obj)
                assign_material(bracket_obj, corbel_mat)
                objects.append(bracket_obj)

    return objects



def _create_box_bay(bay, proj, bay_w, bay_h, z_base, sill_offset, x_offset,
                    facade_mat, glass_mat, trim_mat):
    """Create a rectangular (flat-front) box bay window with sill, frames, and side windows."""
    objects = []
    z_bot = z_base + sill_offset
    z_top = z_bot + bay_h

    # Main bay box
    bpy.ops.mesh.primitive_cube_add(size=1)
    bay_obj = bpy.context.active_object
    bay_obj.name = "bay_window"
    bay_obj.scale = (bay_w, proj, bay_h)
    bpy.ops.object.transform_apply(scale=True)
    bay_obj.location = (x_offset, proj / 2, z_bot + bay_h / 2)
    assign_material(bay_obj, facade_mat)
    objects.append(bay_obj)

    # Glass panes on front face
    win_count = bay.get("window_count_in_bay", 3)
    win_w = bay.get("individual_window_width_m", bay_w / win_count * 0.8)
    win_h = bay.get("individual_window_height_m", bay_h * 0.7)

    frame_mat = get_or_create_material("mat_frame_2A2A2A", colour_hex="#2A2A2A", roughness=0.4)

    for i in range(win_count):
        x = x_offset - bay_w / 2 + bay_w / win_count * (i + 0.5)
        # Glass pane
        bpy.ops.mesh.primitive_plane_add(size=1)
        g = bpy.context.active_object
        g.name = f"bay_glass_{i}"
        g.scale = (win_w * 0.85, 1, win_h * 0.85)
        bpy.ops.object.transform_apply(scale=True)
        g.rotation_euler.x = math.pi / 2
        g.location = (x, proj + 0.01, z_bot + bay_h / 2)
        assign_material(g, glass_mat)
        objects.append(g)

        # Window frame surround
        for fx, fw, fh, fn in [
            (x, win_w + 0.04, 0.03, "frame_top"),       # top
            (x, win_w + 0.04, 0.03, "frame_bot"),       # bottom
            (x - win_w / 2 - 0.015, 0.03, win_h, "frame_left"),  # left
            (x + win_w / 2 + 0.015, 0.03, win_h, "frame_right"), # right
        ]:
            bpy.ops.mesh.primitive_cube_add(size=1)
            fr = bpy.context.active_object
            fr.name = f"bay_{fn}_{i}"
            if "top" in fn or "bot" in fn:
                fr.scale = (fw, 0.03, fh)
                z_fr = z_bot + bay_h / 2 + (win_h / 2 + 0.015 if "top" in fn else -win_h / 2 - 0.015)
                fr.location = (fx, proj + 0.02, z_fr)
            else:
                fr.scale = (fw, 0.03, fh)
                fr.location = (fx, proj + 0.02, z_bot + bay_h / 2)
            bpy.ops.object.transform_apply(scale=True)
            assign_material(fr, frame_mat)
            objects.append(fr)

    # Side windows (one on each side of the bay)
    side_win_h = win_h * 0.8
    side_win_w = proj * 0.6
    for side, sx in [("L", x_offset - bay_w / 2), ("R", x_offset + bay_w / 2)]:
        bpy.ops.mesh.primitive_plane_add(size=1)
        sg = bpy.context.active_object
        sg.name = f"bay_side_glass_{side}"
        sg.scale = (1, side_win_w, side_win_h)
        bpy.ops.object.transform_apply(scale=True)
        sg.rotation_euler.z = math.pi / 2
        sg.location = (sx + (0.01 if side == "R" else -0.01), proj / 2, z_bot + bay_h / 2)
        assign_material(sg, glass_mat)
        objects.append(sg)

    # Sill — projecting stone ledge at bottom
    bpy.ops.mesh.primitive_cube_add(size=1)
    bay_sill = bpy.context.active_object
    bay_sill.name = "bay_sill"
    bay_sill.scale = (bay_w + 0.08, proj + 0.1, 0.05)
    bpy.ops.object.transform_apply(scale=True)
    bay_sill.location = (x_offset, proj / 2, z_bot - 0.025)
    assign_material(bay_sill, trim_mat)
    objects.append(bay_sill)

    # Cornice cap
    bpy.ops.mesh.primitive_cube_add(size=1)
    bay_cap = bpy.context.active_object
    bay_cap.name = "bay_cornice"
    bay_cap.scale = (bay_w + 0.1, proj + 0.15, 0.08)
    bpy.ops.object.transform_apply(scale=True)
    bay_cap.location = (x_offset, proj / 2, z_top + 0.04)
    assign_material(bay_cap, trim_mat)
    objects.append(bay_cap)

    return objects



def _create_canted_bay(bay, proj, bay_w, bay_h, z_base, sill_offset, x_offset,
                       facade_mat, glass_mat, trim_mat):
    """Create a canted (3-sided) bay window using bmesh.

    Geometry (top-down view, facade along X axis at y=0):

        v0 (-bay_w/2, 0) ---- v3 (bay_w/2, 0)       <- facade plane
            \\                    /
         v1  \\                /  v2
              front panel                             <- at y=proj

    Front panel (v1-v2) is bay_w*0.5 wide, parallel to facade.
    Side panels connect facade corners to front panel corners.
    """
    objects = []
    angle_deg = bay.get("angle_deg", 45)

    front_w = bay_w * 0.5
    half_front = front_w / 2
    half_total = bay_w / 2

    z_bot = z_base + sill_offset
    z_top = z_bot + bay_h

    # 4 vertices at bottom, 4 at top
    verts_bot = [
        (-half_total + x_offset, 0, z_bot),        # v0: left at facade
        (-half_front + x_offset, proj, z_bot),      # v1: left-front
        (half_front + x_offset, proj, z_bot),       # v2: right-front
        (half_total + x_offset, 0, z_bot),          # v3: right at facade
    ]
    verts_top = [
        (-half_total + x_offset, 0, z_top),        # v4
        (-half_front + x_offset, proj, z_top),     # v5
        (half_front + x_offset, proj, z_top),      # v6
        (half_total + x_offset, 0, z_top),         # v7
    ]

    all_verts = verts_bot + verts_top  # indices 0-3 bottom, 4-7 top

    faces = [
        (0, 1, 2, 3),      # bottom (floor)
        (7, 6, 5, 4),      # top (ceiling)
        (0, 4, 5, 1),      # left side panel
        (1, 5, 6, 2),      # front panel
        (2, 6, 7, 3),      # right side panel
    ]

    mesh = bpy.data.meshes.new("canted_bay_mesh")
    bm = bmesh.new()

    bm_verts = [bm.verts.new(v) for v in all_verts]
    bm.verts.ensure_lookup_table()

    for face_indices in faces:
        bm.faces.new([bm_verts[i] for i in face_indices])

    bm.to_mesh(mesh)
    bm.free()
    mesh.update()

    bay_obj = bpy.data.objects.new("bay_window_canted", mesh)
    bpy.context.collection.objects.link(bay_obj)
    assign_material(bay_obj, facade_mat)
    objects.append(bay_obj)

    # --- Glass windows ---
    z_glass_center = z_bot + bay_h / 2
    win_h = bay.get("individual_window_height_m", bay_h * 0.7)

    # Front face glass (center panel)
    front_win_count = bay.get("window_count_in_bay", 3)
    front_pane_count = max(1, front_win_count - 2)
    front_pane_w = front_w / front_pane_count * 0.75

    for i in range(front_pane_count):
        fx = x_offset - half_front + front_w / front_pane_count * (i + 0.5)
        bpy.ops.mesh.primitive_plane_add(size=1)
        g = bpy.context.active_object
        g.name = f"bay_canted_front_glass_{i}"
        g.scale = (front_pane_w, 1, win_h * 0.9)
        bpy.ops.object.transform_apply(scale=True)
        g.rotation_euler.x = math.pi / 2
        g.location = (fx, proj + 0.01, z_glass_center)
        assign_material(g, glass_mat)
        objects.append(g)

    # Side panel glass (one pane per side)
    side_dx = half_total - half_front
    side_dy = proj
    side_len = math.sqrt(side_dx ** 2 + side_dy ** 2)
    side_angle = math.atan2(side_dy, side_dx)
    side_pane_w = side_len * 0.6

    # Left side panel glass
    lx_mid = x_offset + (-half_total + -half_front) / 2
    ly_mid = proj / 2
    bpy.ops.mesh.primitive_plane_add(size=1)
    gl = bpy.context.active_object
    gl.name = "bay_canted_left_glass"
    gl.scale = (side_pane_w, 1, win_h * 0.9)
    bpy.ops.object.transform_apply(scale=True)
    gl.rotation_euler.x = math.pi / 2
    gl.rotation_euler.z = -(math.pi / 2 - side_angle)
    gl.location = (lx_mid, ly_mid + 0.01, z_glass_center)
    assign_material(gl, glass_mat)
    objects.append(gl)

    # Right side panel glass
    rx_mid = x_offset + (half_total + half_front) / 2
    ry_mid = proj / 2
    bpy.ops.mesh.primitive_plane_add(size=1)
    gr = bpy.context.active_object
    gr.name = "bay_canted_right_glass"
    gr.scale = (side_pane_w, 1, win_h * 0.9)
    bpy.ops.object.transform_apply(scale=True)
    gr.rotation_euler.x = math.pi / 2
    gr.rotation_euler.z = (math.pi / 2 - side_angle)
    gr.location = (rx_mid, ry_mid + 0.01, z_glass_center)
    assign_material(gr, glass_mat)
    objects.append(gr)

    # --- Cornice (follows canted footprint) ---
    cornice_h = 0.08
    c_overhang = 0.05
    c_verts_bot = [
        (-half_total - c_overhang + x_offset, -c_overhang, z_top),
        (-half_front - c_overhang + x_offset, proj + c_overhang, z_top),
        (half_front + c_overhang + x_offset, proj + c_overhang, z_top),
        (half_total + c_overhang + x_offset, -c_overhang, z_top),
    ]
    c_verts_top = [
        (v[0], v[1], v[2] + cornice_h) for v in c_verts_bot
    ]
    c_all = c_verts_bot + c_verts_top
    c_faces = [
        (0, 1, 2, 3),
        (7, 6, 5, 4),
        (0, 4, 5, 1),
        (1, 5, 6, 2),
        (2, 6, 7, 3),
        (0, 3, 7, 4),
    ]

    c_mesh = bpy.data.meshes.new("canted_bay_cornice_mesh")
    c_bm = bmesh.new()
    c_bm_verts = [c_bm.verts.new(v) for v in c_all]
    c_bm.verts.ensure_lookup_table()
    for fi in c_faces:
        c_bm.faces.new([c_bm_verts[i] for i in fi])
    c_bm.to_mesh(c_mesh)
    c_bm.free()
    c_mesh.update()

    cornice_obj = bpy.data.objects.new("bay_canted_cornice", c_mesh)
    bpy.context.collection.objects.link(cornice_obj)
    assign_material(cornice_obj, trim_mat)
    objects.append(cornice_obj)

    return objects


