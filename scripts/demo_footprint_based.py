"""Bellevue demo: footprint-based building generation.

Instead of parametric boxes placed at point coordinates, this script:
1. Takes each building footprint polygon from GIS
2. Matches it to the nearest building_assessment record
3. Extrudes the footprint to the massing height
4. Applies facade material, windows, doors, roof from params
5. Adds roads, park, trees from GIS

All geometry comes from the SAME GIS source — no coordinate mismatch possible.

Run: blender --python scripts/demo_footprint_based.py
"""

import bpy
import bmesh
import json
import math
import os
import random
import re
from pathlib import Path

random.seed(42)

SCRIPT_DIR = Path(os.path.dirname(os.path.abspath(__file__))).parent
GIS = json.load(open(SCRIPT_DIR / "outputs" / "gis_scene.json"))
SITE = json.load(open(SCRIPT_DIR / "params" / "_site_coordinates.json", encoding="utf-8"))

# Load params for material/window data
PARAMS = {}
for f in (SCRIPT_DIR / "params").glob("*.json"):
    if f.name.startswith("_"):
        continue
    try:
        d = json.load(open(f, encoding="utf-8"))
        if not d.get("skipped"):
            addr = d.get("building_name") or d.get("_meta", {}).get("address", "")
            if addr:
                PARAMS[addr] = d
    except:
        pass

# Full Kensington Market
# Dundas (north) to College (south), Bathurst (east) to Spadina (west)
X_MIN, X_MAX = -350, 200
Y_MIN, Y_MAX = -400, 350

# Scene transform: rotate so Bellevue Ave aligns with Y axis, center on origin.
# Bellevue runs at ~98 degrees from +X. Rotate by -98 degrees.
# Center of west row: (-119, 21) in original coords.
_SCENE_CX, _SCENE_CY = -50.0, -100.0  # center of expanded demo area
_SCENE_ROT = math.radians(-17.5)  # rotate scene to align Bellevue Ave with Y axis
_COS_SR = math.cos(_SCENE_ROT)
_SIN_SR = math.sin(_SCENE_ROT)


def scene_transform(x, y):
    """Transform GIS coords to scene coords (rotated + centered)."""
    # Translate to center, then rotate
    dx, dy = x - _SCENE_CX, y - _SCENE_CY
    return (dx * _COS_SR - dy * _SIN_SR,
            dx * _SIN_SR + dy * _COS_SR)


def scene_transform_ring(ring):
    """Transform a polygon ring."""
    return [scene_transform(x, y) for x, y in ring]


def scene_transform_angle(angle_rad):
    """Add scene rotation to an angle."""
    return angle_rad + _SCENE_ROT

_mats = {}


def mat(name, hex_c, rough=0.8):
    if name in _mats:
        return _mats[name]
    m = bpy.data.materials.new(name=name)
    m.use_nodes = True
    b = m.node_tree.nodes.get("Principled BSDF")
    if b:
        h = hex_c.lstrip("#")
        r, g, bl = (int(h[i:i+2], 16) / 255 for i in (0, 2, 4))
        b.inputs["Base Color"].default_value = (r, g, bl, 1)
        b.inputs["Roughness"].default_value = rough
    _mats[name] = m
    return m


def col(name):
    c = bpy.data.collections.new(name)
    bpy.context.scene.collection.children.link(c)
    return c


def link(obj, collection):
    for c in obj.users_collection:
        c.objects.unlink(obj)
    collection.objects.link(obj)


def in_bounds(ring, margin=0):
    if not ring or len(ring) < 3:
        return False
    cx = sum(c[0] for c in ring) / len(ring)
    cy = sum(c[1] for c in ring) / len(ring)
    return (X_MIN - margin) <= cx <= (X_MAX + margin) and \
           (Y_MIN - margin) <= cy <= (Y_MAX + margin)


def road_mesh(coords, width, name):
    if len(coords) < 2:
        return None
    bm = bmesh.new()
    hw = width / 2
    L, R = [], []
    for i, (x, y) in enumerate(coords):
        if i < len(coords) - 1:
            dx, dy = coords[i+1][0] - x, coords[i+1][1] - y
        else:
            dx, dy = x - coords[i-1][0], y - coords[i-1][1]
        l = max((dx*dx + dy*dy)**0.5, 0.01)
        nx, ny = -dy/l*hw, dx/l*hw
        L.append(bm.verts.new((x + nx, y + ny, 0.02)))
        R.append(bm.verts.new((x - nx, y - ny, 0.02)))
    for i in range(len(coords) - 1):
        try:
            bm.faces.new([L[i], L[i+1], R[i+1], R[i]])
        except:
            pass
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()
    return mesh


def poly_mesh(ring, z, name):
    """Create a filled polygon mesh from a ring of 2D coordinates."""
    if len(ring) < 3:
        return None
    bm = bmesh.new()
    verts = [bm.verts.new((x, y, z)) for x, y in ring]
    try:
        bm.faces.new(verts)
    except:
        bm.free()
        return None
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()
    return mesh


MATERIAL_COLOURS = {
    "brick": "#B8654A", "stone": "#A09880", "stucco": "#D8D0C0",
    "clapboard": "#E8DCC8", "paint": "#C8D0C8", "siding": "#C0C8C0",
    "wood": "#8A7050", "concrete": "#A0A0A0", "glass": "#6090B0",
}


def find_massing_height(cx, cy):
    """Find the massing height for a footprint centroid."""
    best_dist = 999
    best_h = 7.0
    for m in GIS.get("massing", []):
        rings = m.get("rings", [[]])
        if not rings or not rings[0]:
            continue
        ring = rings[0]
        mx = sum(c[0] for c in ring) / len(ring)
        my = sum(c[1] for c in ring) / len(ring)
        dist = math.sqrt((cx - mx)**2 + (cy - my)**2)
        if dist < best_dist:
            best_dist = dist
            h = m.get("h", 0)
            if h > 0:
                best_h = h
                best_dist = dist
    return best_h if best_dist < 20 else 7.0


def find_params(cx, cy):
    """Find nearest building params by position."""
    best_dist = 999
    best = None
    for addr, pos in SITE.items():
        dist = math.sqrt((cx - pos['x'])**2 + (cy - pos['y'])**2)
        if dist < best_dist:
            best_dist = dist
            best = addr
    if best and best_dist < 15:
        return PARAMS.get(best, {})
    return {}


def outward_normal(x1, y1, x2, y2, cx, cy):
    """Compute outward-facing normal for an edge."""
    dx, dy = x2 - x1, y2 - y1
    el = max(math.sqrt(dx*dx + dy*dy), 0.01)
    nx, ny = -dy / el, dx / el
    # Check if normal points away from center
    mid_x, mid_y = (x1 + x2) / 2, (y1 + y2) / 2
    to_cx = cx - mid_x
    to_cy = cy - mid_y
    if nx * to_cx + ny * to_cy > 0:
        nx, ny = -nx, -ny  # flip to outward
    return nx, ny, el


def create_building_from_footprint(ring, collection, override_h=None):
    """Create a detailed building from a footprint/massing polygon."""
    if len(ring) < 3:
        return

    xs = [c[0] for c in ring]
    ys = [c[1] for c in ring]
    cx = sum(xs) / len(xs)
    cy = sum(ys) / len(ys)

    # Use override height (from massing) or find from massing data
    if override_h and override_h > 0:
        h = override_h
    else:
        h = find_massing_height(cx, cy)
        if h <= 0:
            h = 7.0

    # Get params for material, windows, etc.
    params = find_params(cx, cy)
    facade_mat_name = (params.get("facade_material") or "brick").lower()

    # Per-building colour from colour_palette or facade_detail
    cp = params.get("colour_palette", {})
    fd = params.get("facade_detail", {})
    hex_col = (cp.get("facade_hex") or fd.get("brick_colour_hex") or
               MATERIAL_COLOURS.get(facade_mat_name, "#B8654A"))
    facade_mat = mat(f"Facade_{hex_col}", hex_col, 0.7)

    # Trim colour
    trim_hex = cp.get("trim_hex") or fd.get("trim_colour_hex") or "#E8E0D0"
    m_trim = mat(f"Trim_{trim_hex}", trim_hex, 0.6)

    floors = params.get("floors") or max(1, int(h / 3.0))
    has_storefront = params.get("has_storefront", False)
    roof_type = (params.get("roof_type") or "flat").lower()

    # 1. Extrude footprint to height (the building walls)
    bm = bmesh.new()
    bottom_verts = [bm.verts.new((x, y, 0)) for x, y in ring]
    try:
        bottom_face = bm.faces.new(bottom_verts)
    except:
        bm.free()
        return

    result = bmesh.ops.extrude_face_region(bm, geom=[bottom_face])
    for v in (v for v in result["geom"] if isinstance(v, bmesh.types.BMVert)):
        v.co.z = h

    bm.normal_update()
    mesh = bpy.data.meshes.new(f"Bldg_{cx:.0f}_{cy:.0f}")
    bm.to_mesh(mesh)
    bm.free()

    obj = bpy.data.objects.new(f"Bldg_{cx:.0f}_{cy:.0f}", mesh)
    obj.data.materials.append(facade_mat)
    link(obj, collection)

    # Foundation strip (darker, slightly wider at base)
    m_foundation = mat("Foundation", "#4A4A4A", 0.9)
    foundation_h = 0.4
    bm_f = bmesh.new()
    # Use the same ring but offset outward slightly
    f_ring = []
    for i_r in range(len(ring)):
        rx, ry = ring[i_r]
        f_ring.append((rx + (rx - cx) * 0.02, ry + (ry - cy) * 0.02))
    f_verts = [bm_f.verts.new((x, y, 0)) for x, y in f_ring]
    try:
        f_face = bm_f.faces.new(f_verts)
        result = bmesh.ops.extrude_face_region(bm_f, geom=[f_face])
        for v in (v for v in result["geom"] if isinstance(v, bmesh.types.BMVert)):
            v.co.z = foundation_h
        bm_f.normal_update()
        f_mesh = bpy.data.meshes.new(f"Found_{cx:.0f}")
        bm_f.to_mesh(f_mesh)
        bm_f.free()
        f_obj = bpy.data.objects.new(f"Found_{cx:.0f}", f_mesh)
        f_obj.data.materials.append(m_foundation)
        link(f_obj, collection)
    except:
        bm_f.free()

    # 2. Add windows on exterior edges
    m_glass = mat("Glass", "#3A5A7A", 0.2)
    m_door = mat("Door", "#4A2A10", 0.75)
    m_store = mat("Storefront", "#2A4A5A", 0.25)

    # Sort edges by length to find facade edges
    edges = []
    for i in range(len(ring)):
        x1, y1 = ring[i]
        x2, y2 = ring[(i + 1) % len(ring)]
        nx, ny, el = outward_normal(x1, y1, x2, y2, cx, cy)
        edges.append((el, x1, y1, x2, y2, nx, ny))
    edges.sort(reverse=True)

    floor_h = h / max(floors, 1)

    # Add windows to top 4 longest edges (or all edges > 3m)
    for ei, (length, x1, y1, x2, y2, nx, ny) in enumerate(edges):
        if length < 3.0:
            continue
        if ei >= 2:
            break

        dx, dy = x2 - x1, y2 - y1
        angle = math.atan2(dy, dx)

        # Build per-floor window specs from windows_detail if available
        wd = params.get("windows_detail")
        floor_win_specs = {}  # fi -> list of {count, width, height, sill}
        if wd and isinstance(wd, list):
            for fd_entry in wd:
                if not isinstance(fd_entry, dict):
                    continue
                floor_label = (fd_entry.get("floor") or "").lower()
                # Map floor label to index
                if "ground" in floor_label or "first" in floor_label:
                    fi_idx = 0
                elif "second" in floor_label:
                    fi_idx = 1
                elif "third" in floor_label:
                    fi_idx = 2
                elif "fourth" in floor_label:
                    fi_idx = 3
                elif "attic" in floor_label:
                    fi_idx = int(floors) - 1 if floors > 1 else 0
                else:
                    fi_idx = None
                if fi_idx is not None:
                    wins = fd_entry.get("windows", [])
                    if isinstance(wins, list):
                        floor_win_specs[fi_idx] = wins

        for fi in range(int(floors)):
            if fi == 0 and has_storefront and ei == 0:
                continue

            if fi in floor_win_specs:
                # Use per-floor window detail
                wi_counter = 0
                for wspec in floor_win_specs[fi]:
                    if not isinstance(wspec, dict):
                        continue
                    w_count = wspec.get("count", 1)
                    win_w = wspec.get("width_m", 1.0)
                    win_h = wspec.get("height_m", 1.4)
                    sill_h = wspec.get("sill_height_m", fi * floor_h + floor_h * 0.3)
                    for wi in range(w_count):
                        t = (wi_counter + 1) / (sum(ws.get("count", 1) for ws in floor_win_specs[fi] if isinstance(ws, dict)) + 1)
                        wx = x1 + dx * t + nx * 0.05
                        wy = y1 + dy * t + ny * 0.05
                        wz = sill_h + win_h / 2

                        bpy.ops.mesh.primitive_cube_add(size=1, location=(wx, wy, wz))
                        w = bpy.context.active_object
                        w.name = f"W_{ei}_{fi}_{wi_counter}"
                        w.scale = (win_w / 2, 0.08, win_h / 2)
                        w.rotation_euler = (0, 0, angle)
                        w.data.materials.append(m_glass)
                        link(w, collection)

                        # Window frame (trim colour, slightly larger behind the glass)
                        bpy.ops.mesh.primitive_cube_add(size=1, location=(wx + nx * 0.01, wy + ny * 0.01, wz))
                        wf = bpy.context.active_object
                        wf.name = f"WF_{ei}_{fi}_{wi_counter}"
                        wf.scale = (win_w / 2 + 0.05, 0.04, win_h / 2 + 0.05)
                        wf.rotation_euler = (0, 0, angle)
                        wf.data.materials.append(m_trim)
                        link(wf, collection)

                        # Window sill
                        bpy.ops.mesh.primitive_cube_add(size=1, location=(wx + nx * 0.08, wy + ny * 0.08, wz - win_h/2))
                        ws = bpy.context.active_object
                        ws.name = f"WS_{ei}_{fi}_{wi_counter}"
                        ws.scale = (win_w / 2 + 0.08, 0.06, 0.03)
                        ws.rotation_euler = (0, 0, angle)
                        ws.data.materials.append(m_trim)
                        link(ws, collection)

                        # Window lintel (header above window)
                        bpy.ops.mesh.primitive_cube_add(size=1,
                            location=(wx + nx * 0.07, wy + ny * 0.07, wz + win_h/2 + 0.04))
                        wl = bpy.context.active_object
                        wl.name = f"WL_{ei}_{fi}_{wi_counter}"
                        wl.scale = (win_w / 2 + 0.06, 0.05, 0.06)
                        wl.rotation_euler = (0, 0, angle)
                        wl.data.materials.append(m_trim)
                        link(wl, collection)

                        wi_counter += 1
            else:
                # Fallback: evenly-spaced windows
                n_win = max(1, int(length / 2.5))
                win_w, win_h = 1.0, 1.4
                sill_z = fi * floor_h + floor_h * 0.3
                for wi in range(n_win):
                    t = (wi + 1) / (n_win + 1)
                    wx = x1 + dx * t + nx * 0.05
                    wy = y1 + dy * t + ny * 0.05
                    wz = sill_z + win_h / 2

                    bpy.ops.mesh.primitive_cube_add(size=1, location=(wx, wy, wz))
                    w = bpy.context.active_object
                    w.name = f"W_{ei}_{fi}_{wi}"
                    w.scale = (win_w / 2, 0.08, win_h / 2)
                    w.rotation_euler = (0, 0, angle)
                    w.data.materials.append(m_glass)
                    link(w, collection)

                    # Window frame (trim colour, slightly larger behind the glass)
                    bpy.ops.mesh.primitive_cube_add(size=1, location=(wx + nx * 0.01, wy + ny * 0.01, wz))
                    wf = bpy.context.active_object
                    wf.name = f"WF_{ei}_{fi}_{wi}"
                    wf.scale = (win_w / 2 + 0.05, 0.04, win_h / 2 + 0.05)
                    wf.rotation_euler = (0, 0, angle)
                    wf.data.materials.append(m_trim)
                    link(wf, collection)

                    # Window sill
                    bpy.ops.mesh.primitive_cube_add(size=1, location=(wx + nx * 0.08, wy + ny * 0.08, wz - win_h/2))
                    ws = bpy.context.active_object
                    ws.name = f"WS_{ei}_{fi}_{wi}"
                    ws.scale = (win_w / 2 + 0.08, 0.06, 0.03)
                    ws.rotation_euler = (0, 0, angle)
                    ws.data.materials.append(m_trim)
                    link(ws, collection)

                    # Window lintel (header above window)
                    bpy.ops.mesh.primitive_cube_add(size=1,
                        location=(wx + nx * 0.07, wy + ny * 0.07, wz + win_h/2 + 0.04))
                    wl = bpy.context.active_object
                    wl.name = f"WL_{ei}_{fi}_{wi}"
                    wl.scale = (win_w / 2 + 0.06, 0.05, 0.06)
                    wl.rotation_euler = (0, 0, angle)
                    wl.data.materials.append(m_trim)
                    link(wl, collection)

        # Door on ground floor (first edge only)
        if ei == 0:
            # Use doors_detail from params if available
            doors = params.get("doors_detail", [])
            if doors and isinstance(doors, list):
                for di, door_data in enumerate(doors):
                    if not isinstance(door_data, dict):
                        continue
                    dw = door_data.get("width_m", 1.1)
                    dh = door_data.get("height_m", 2.3)
                    dpos = door_data.get("position", "center")
                    dt = 0.3 if dpos == "left" else 0.7 if dpos == "right" else 0.5
                    dox = x1 + dx * dt + nx * 0.05
                    doy = y1 + dy * dt + ny * 0.05
                    door_hex = door_data.get("colour_hex", "#4A2A10")
                    m_this_door = mat(f"Door_{door_hex}", door_hex, 0.75)
                    bpy.ops.mesh.primitive_cube_add(size=1, location=(dox, doy, dh / 2))
                    dd = bpy.context.active_object
                    dd.name = f"Door_{di}"
                    dd.scale = (dw / 2, 0.1, dh / 2)
                    dd.rotation_euler = (0, 0, angle)
                    dd.data.materials.append(m_this_door)
                    link(dd, collection)
            else:
                door_w, door_h = 1.1, 2.3
                dt = 0.5
                dox = x1 + dx * dt + nx * 0.05
                doy = y1 + dy * dt + ny * 0.05
                bpy.ops.mesh.primitive_cube_add(size=1, location=(dox, doy, door_h / 2))
                dd = bpy.context.active_object
                dd.name = "Door"
                dd.scale = (door_w / 2, 0.1, door_h / 2)
                dd.rotation_euler = (0, 0, angle)
                dd.data.materials.append(m_door)
                link(dd, collection)

        # Ground floor arches
        if ei == 0:
            gfa = params.get("ground_floor_arches", {})
            if isinstance(gfa, dict) and gfa.get("present", True) and gfa.get("arch_type"):
                arch_count = gfa.get("count", 1)
                for ai in range(arch_count):
                    at = (ai + 1) / (arch_count + 1)
                    arch_w = 1.5
                    arch_h = 2.5
                    ax = x1 + dx * at + nx * 0.06
                    ay = y1 + dy * at + ny * 0.06
                    # Arch as a tall dark opening
                    bpy.ops.mesh.primitive_cube_add(size=1, location=(ax, ay, arch_h / 2))
                    ao = bpy.context.active_object
                    ao.name = f"Arch_{ai}"
                    ao.scale = (arch_w / 2, 0.12, arch_h / 2)
                    ao.rotation_euler = (0, 0, angle)
                    ao.data.materials.append(mat("ArchOpening", "#1A1A2A", 0.9))
                    link(ao, collection)

        # Storefront on ground floor
        if ei == 0 and has_storefront:
            sf_data = params.get("storefront", {})
            sf_h = min(sf_data.get("height_m", floor_h * 0.7), 2.8)
            sf_w = sf_data.get("width_m", length * 0.7)
            sf_x = x1 + dx * 0.5 + nx * 0.05
            sf_y = y1 + dy * 0.5 + ny * 0.05
            bpy.ops.mesh.primitive_cube_add(size=1, location=(sf_x, sf_y, sf_h / 2 + 0.3))
            sf = bpy.context.active_object
            sf.name = "Storefront"
            sf.scale = (sf_w / 2, 0.1, sf_h / 2)
            sf.rotation_euler = (0, 0, angle)
            sf.data.materials.append(m_store)
            link(sf, collection)

            # Awning over storefront
            aw_x = sf_x + nx * 0.5
            aw_y = sf_y + ny * 0.5
            aw_z = sf_h + 0.5
            bpy.ops.mesh.primitive_cube_add(size=1, location=(aw_x, aw_y, aw_z))
            aw = bpy.context.active_object
            aw.name = "Awning"
            aw.scale = (sf_w / 2 + 0.2, 0.6, 0.05)
            aw.rotation_euler = (0, 0, angle)
            # Random awning colour
            aw_colours = ["#8B2020", "#1A4A1A", "#1A1A4A", "#4A1A4A", "#B85A2A"]
            aw_hex = random.choice(aw_colours)
            aw.data.materials.append(mat(f"Awning_{aw_hex}", aw_hex, 0.7))
            link(aw, collection)

        # String courses (decorative horizontal bands)
        deco = params.get("decorative_elements", {})
        if isinstance(deco, dict) and ei < 2:
            sc = deco.get("string_courses", {})
            if isinstance(sc, dict) and sc.get("present"):
                sc_h = sc.get("width_mm", 100) / 1000
                sc_proj = sc.get("projection_mm", 30) / 1000
                sc_hex = sc.get("colour_hex", "#A09080")
                m_sc = mat(f"StringCourse_{sc_hex}", sc_hex, 0.7)
                for fi in range(1, int(floors)):
                    sc_z = fi * floor_h
                    sc_x = x1 + dx * 0.5 + nx * (0.16 + sc_proj/2)
                    sc_y = y1 + dy * 0.5 + ny * (0.16 + sc_proj/2)
                    bpy.ops.mesh.primitive_cube_add(size=1, location=(sc_x, sc_y, sc_z))
                    sco = bpy.context.active_object
                    sco.name = f"StringCourse_{fi}"
                    sco.scale = (length / 2, sc_proj / 2, sc_h / 2)
                    sco.rotation_euler = (0, 0, angle)
                    sco.data.materials.append(m_sc)
                    link(sco, collection)

            # Cornice at roofline
            cornice = deco.get("cornice", {})
            if isinstance(cornice, dict) and cornice.get("present"):
                co_h = cornice.get("height_mm", 200) / 1000
                co_proj = cornice.get("projection_mm", 100) / 1000
                co_hex = cornice.get("colour_hex", "#A09080")
                m_co = mat(f"Cornice_{co_hex}", co_hex, 0.65)
                co_x = x1 + dx * 0.5 + nx * (0.16 + co_proj/2)
                co_y = y1 + dy * 0.5 + ny * (0.16 + co_proj/2)
                bpy.ops.mesh.primitive_cube_add(size=1, location=(co_x, co_y, h - co_h/2))
                coo = bpy.context.active_object
                coo.name = "Cornice"
                coo.scale = (length / 2, co_proj / 2, co_h / 2)
                coo.rotation_euler = (0, 0, angle)
                coo.data.materials.append(m_co)
                link(coo, collection)

            # Quoins (corner stones)
            quoins = deco.get("quoins", {})
            if isinstance(quoins, dict) and quoins.get("present"):
                q_w = quoins.get("strip_width_mm", 150) / 1000
                q_proj = quoins.get("projection_mm", 20) / 1000
                q_hex = quoins.get("colour_hex", "#C0B8A0")
                m_q = mat(f"Quoin_{q_hex}", q_hex, 0.7)
                for qx, qy in [(x1, y1), (x2, y2)]:
                    bpy.ops.mesh.primitive_cube_add(size=1, location=(qx + nx * 0.16, qy + ny * 0.16, h / 2))
                    qo = bpy.context.active_object
                    qo.name = "Quoin"
                    qo.scale = (q_w / 2, q_proj / 2, h / 2)
                    qo.rotation_euler = (0, 0, angle)
                    qo.data.materials.append(m_q)
                    link(qo, collection)

    # Bay windows (on longest street-facing edge)
    bw = params.get("bay_window", {})
    if isinstance(bw, dict) and bw.get("present") and len(edges) > 0:
        bw_w = bw.get("width_m", 2.0)
        bw_proj = bw.get("projection_m", 0.6)
        bw_floors = bw.get("floors", [0, 1])
        if not isinstance(bw_floors, list):
            bw_floors = [0, 1]

        # Place on longest edge
        length0, x1, y1, x2, y2, nx0, ny0 = edges[0]
        dx0, dy0 = x2 - x1, y2 - y1
        angle0 = math.atan2(dy0, dx0)

        # Bay window position: 30% along the edge
        bt = 0.3
        for bfi in bw_floors:
            if bfi >= floors:
                continue
            bz_base = bfi * floor_h + 0.3
            bz_h = floor_h * 0.7

            bwx = x1 + dx0 * bt + nx0 * (0.05 + bw_proj / 2)
            bwy = y1 + dy0 * bt + ny0 * (0.05 + bw_proj / 2)
            bwz = bz_base + bz_h / 2

            # Bay window as a box projecting from the wall
            bpy.ops.mesh.primitive_cube_add(size=1, location=(bwx, bwy, bwz))
            bwo = bpy.context.active_object
            bwo.name = f"BayWin_{bfi}"
            bwo.scale = (bw_w / 2, bw_proj / 2, bz_h / 2)
            bwo.rotation_euler = (0, 0, angle0)
            bwo.data.materials.append(m_trim)
            link(bwo, collection)

            # Glass front on bay window
            bgx = bwx + nx0 * bw_proj / 2
            bgy = bwy + ny0 * bw_proj / 2
            bpy.ops.mesh.primitive_cube_add(size=1, location=(bgx, bgy, bwz))
            bgo = bpy.context.active_object
            bgo.name = f"BayGlass_{bfi}"
            bgo.scale = (bw_w * 0.8 / 2, 0.05, bz_h * 0.7 / 2)
            bgo.rotation_euler = (0, 0, angle0)
            bgo.data.materials.append(m_glass)
            link(bgo, collection)

    # Balconies (from photo_observations)
    po = params.get("photo_observations", {})
    if isinstance(po, dict):
        bt = po.get("balcony_type") or po.get("balcony_details")
        if bt and bt not in ("none", "None", None) and len(edges) > 0:
            length0, x1, y1, x2, y2, nx0, ny0 = edges[0]
            dx0, dy0 = x2 - x1, y2 - y1
            angle0 = math.atan2(dy0, dx0)

            # Balcony on second floor, center of facade
            if floors >= 2:
                bal_w = min(length0 * 0.4, 2.5)
                bal_d = 1.0
                bal_z = floor_h + 0.1  # second floor level

                bx_pos = x1 + dx0 * 0.5 + nx0 * (0.05 + bal_d / 2)
                by_pos = y1 + dy0 * 0.5 + ny0 * (0.05 + bal_d / 2)

                # Balcony floor slab
                bpy.ops.mesh.primitive_cube_add(size=1, location=(bx_pos, by_pos, bal_z))
                bf = bpy.context.active_object
                bf.name = "BalconyFloor"
                bf.scale = (bal_w / 2, bal_d / 2, 0.05)
                bf.rotation_euler = (0, 0, angle0)
                bf.data.materials.append(mat("BalconyConcrete", "#A0A0A0", 0.8))
                link(bf, collection)

                # Railing (3 sides)
                m_rail = mat("Railing", "#2A2A2A", 0.4)
                rail_h = 0.9
                # Front rail
                rfx = bx_pos + nx0 * bal_d / 2
                rfy = by_pos + ny0 * bal_d / 2
                bpy.ops.mesh.primitive_cube_add(size=1, location=(rfx, rfy, bal_z + rail_h / 2))
                rf = bpy.context.active_object
                rf.name = "RailFront"
                rf.scale = (bal_w / 2, 0.02, rail_h / 2)
                rf.rotation_euler = (0, 0, angle0)
                rf.data.materials.append(m_rail)
                link(rf, collection)

    # Porch (on street-facing edge)
    if params.get("porch_present") and len(edges) > 0:
        length0, x1, y1, x2, y2, nx0, ny0 = edges[0]
        dx0, dy0 = x2 - x1, y2 - y1
        angle0 = math.atan2(dy0, dx0)

        porch_w = min(length0 * 0.6, 3.0)
        porch_d = 1.5
        porch_h = 2.8

        px = x1 + dx0 * 0.5 + nx0 * (0.05 + porch_d / 2)
        py = y1 + dy0 * 0.5 + ny0 * (0.05 + porch_d / 2)

        # Porch floor
        bpy.ops.mesh.primitive_cube_add(size=1, location=(px, py, 0.3))
        pf = bpy.context.active_object
        pf.name = "PorchFloor"
        pf.scale = (porch_w / 2, porch_d / 2, 0.05)
        pf.rotation_euler = (0, 0, angle0)
        pf.data.materials.append(mat("PorchWood", "#8A7050", 0.8))
        link(pf, collection)

        # Porch roof
        bpy.ops.mesh.primitive_cube_add(size=1, location=(px, py, porch_h))
        pr = bpy.context.active_object
        pr.name = "PorchRoof"
        pr.scale = (porch_w / 2 + 0.1, porch_d / 2 + 0.1, 0.05)
        pr.rotation_euler = (0, 0, angle0)
        pr.data.materials.append(mat("Roof", "#4A4A4A", 0.85))
        link(pr, collection)

        # Porch columns (2)
        m_col = mat("PorchColumn", "#E0D8C8", 0.7)
        for side in [-0.4, 0.4]:
            col_x = px + math.cos(angle0) * porch_w * side + nx0 * porch_d * 0.4
            col_y = py + math.sin(angle0) * porch_w * side + ny0 * porch_d * 0.4
            bpy.ops.mesh.primitive_cylinder_add(radius=0.06, depth=porch_h - 0.35,
                                                 location=(col_x, col_y, (porch_h + 0.35) / 2), vertices=8)
            co = bpy.context.active_object
            co.name = "PorchCol"
            co.data.materials.append(m_col)
            link(co, collection)

    # 3. Roof
    roof_hex = (params.get("colour_palette", {}).get("roof_hex") or
                params.get("roof_colour") or "#4A4A4A")
    m_roof = mat(f"Roof_{roof_hex}", roof_hex, 0.85)

    # Large massing blocks (rowhouse groups) get flat roofs
    # Only individual buildings (<10m wide) get gable/hip
    footprint_width = max(xs) - min(xs)
    footprint_depth = max(ys) - min(ys)
    min_dim = min(footprint_width, footprint_depth)
    max_dim = max(footprint_width, footprint_depth)

    if max_dim > 15:
        roof_type = "flat"  # block-level massing = flat roof

    if "gable" in roof_type and len(ring) >= 3:
        # Oriented bounding box for gable direction
        best_len, best_dx, best_dy = 0, 1, 0
        for i in range(len(ring)):
            x1, y1 = ring[i]
            x2, y2 = ring[(i + 1) % len(ring)]
            el = math.sqrt((x2-x1)**2 + (y2-y1)**2)
            if el > best_len:
                best_len = el
                best_dx = (x2-x1) / max(el, 0.01)
                best_dy = (y2-y1) / max(el, 0.01)

        perp_dx, perp_dy = -best_dy, best_dx
        ridge_projs = []
        perp_projs = []
        for x, y in ring:
            ridge_projs.append((x - cx) * best_dx + (y - cy) * best_dy)
            perp_projs.append((x - cx) * perp_dx + (y - cy) * perp_dy)

        ridge_min, ridge_max = min(ridge_projs), max(ridge_projs)
        perp_min, perp_max = min(perp_projs), max(perp_projs)
        bw = perp_max - perp_min
        ridge_h = min(bw * 0.35, 2.5)
        if ridge_h < 0.5:
            ridge_h = 1.0

        r1x = cx + best_dx * ridge_min
        r1y = cy + best_dy * ridge_min
        r2x = cx + best_dx * ridge_max
        r2y = cy + best_dy * ridge_max

        bm = bmesh.new()
        c1 = bm.verts.new((r1x + perp_dx * perp_min, r1y + perp_dy * perp_min, h))
        c2 = bm.verts.new((r1x + perp_dx * perp_max, r1y + perp_dy * perp_max, h))
        c3 = bm.verts.new((r2x + perp_dx * perp_max, r2y + perp_dy * perp_max, h))
        c4 = bm.verts.new((r2x + perp_dx * perp_min, r2y + perp_dy * perp_min, h))
        ridge1 = bm.verts.new((r1x, r1y, h + ridge_h))
        ridge2 = bm.verts.new((r2x, r2y, h + ridge_h))
        try:
            bm.faces.new([c1, c4, ridge2, ridge1])
            bm.faces.new([c2, ridge1, ridge2, c3])
            bm.faces.new([c1, c2, ridge1])
            bm.faces.new([c4, ridge2, c3])
        except:
            pass
        mesh = bpy.data.meshes.new("GableRoof")
        bm.to_mesh(mesh)
        bm.free()
        roof = bpy.data.objects.new("GableRoof", mesh)
        roof.data.materials.append(m_roof)
        link(roof, collection)

    elif "hip" in roof_type:
        ridge_h = min((max(xs) - min(xs)) * 0.25, (max(ys) - min(ys)) * 0.25, 2.5)
        bm = bmesh.new()
        bottom = [bm.verts.new((x, y, h)) for x, y in ring]
        top = bm.verts.new((cx, cy, h + ridge_h))
        for i in range(len(bottom)):
            j = (i + 1) % len(bottom)
            try:
                bm.faces.new([bottom[i], bottom[j], top])
            except:
                pass
        mesh = bpy.data.meshes.new("HipRoof")
        bm.to_mesh(mesh)
        bm.free()
        roof = bpy.data.objects.new("HipRoof", mesh)
        roof.data.materials.append(m_roof)
        link(roof, collection)

    # Chimneys
    rf = params.get("roof_features", [])
    if isinstance(rf, list):
        for feat in rf:
            if isinstance(feat, str) and "chimney" in feat.lower():
                # Place chimney on the ridge/back edge
                ch_w, ch_d, ch_h = 0.4, 0.4, 1.2
                # Position at back-right corner of the building
                if len(edges) >= 2:
                    _, bx1, by1, bx2, by2, bnx, bny = edges[1]  # second longest edge (back)
                    ch_x = (bx1 + bx2) / 2 + bnx * 0.3
                    ch_y = (by1 + by2) / 2 + bny * 0.3
                    bpy.ops.mesh.primitive_cube_add(size=1, location=(ch_x, ch_y, h + ch_h/2))
                    ch = bpy.context.active_object
                    ch.name = "Chimney"
                    ch.scale = (ch_w/2, ch_d/2, ch_h/2)
                    ch.data.materials.append(mat("Chimney", "#6A5A4A", 0.8))
                    link(ch, collection)
                break  # only one chimney per building

    # Bargeboards (decorative woodwork on gable edges)
    deco = params.get("decorative_elements", {})
    if isinstance(deco, dict):
        bb = deco.get("bargeboard", {})
        if isinstance(bb, dict) and (bb.get("present") or bb.get("colour_hex")):
            bb_hex = bb.get("colour_hex") or trim_hex
            m_bb = mat(f"Bargeboard_{bb_hex}", bb_hex, 0.7)
            if "gable" in roof_type and len(edges) >= 1:
                length0, bx1, by1, bx2, by2, bnx0, bny0 = edges[0]
                # Two bargeboard strips along the gable slope
                for side in [-1, 1]:
                    # Diagonal from eave to ridge
                    ridge_h_bb = min((max(xs)-min(xs)) * 0.35, 2.5)
                    mid_x = (bx1 + bx2) / 2
                    mid_y = (by1 + by2) / 2
                    start_x = mid_x + bnx0 * (max(ys)-min(ys))/2 * side * 0.4
                    start_y = mid_y + bny0 * (max(ys)-min(ys))/2 * side * 0.4

                    bpy.ops.mesh.primitive_cube_add(size=1,
                        location=(start_x, start_y, h + ridge_h_bb * 0.4))
                    bbo = bpy.context.active_object
                    bbo.name = f"Bargeboard_{side}"
                    slope_len = math.sqrt(ridge_h_bb**2 + ((max(ys)-min(ys))/2)**2)
                    bbo.scale = (0.04, slope_len / 2, 0.12)
                    bbo.rotation_euler = (0, 0, math.atan2(bny0, bnx0))
                    bbo.data.materials.append(m_bb)
                    link(bbo, collection)

    # Dormers (from roof_detail or roof_features)
    rd = params.get("roof_detail", {})
    gable_win = rd.get("gable_window", {}) if isinstance(rd, dict) else {}
    if isinstance(gable_win, dict) and gable_win.get("present"):
        dw = gable_win.get("width_m", 0.8)
        dh = gable_win.get("height_m", 0.9)
        if "gable" in roof_type and len(edges) >= 1:
            length0, dx1, dy1, dx2, dy2, dnx, dny = edges[0]
            dmx = (dx1 + dx2) / 2 + dnx * 0.3
            dmy = (dy1 + dy2) / 2 + dny * 0.3
            dmz = h + 0.8
            bpy.ops.mesh.primitive_cube_add(size=1, location=(dmx, dmy, dmz))
            dorm = bpy.context.active_object
            dorm.name = "Dormer"
            dorm.scale = (dw / 2, 0.4, dh / 2)
            dorm.rotation_euler = (0, 0, math.atan2(dny, dnx))
            dorm.data.materials.append(facade_mat)
            link(dorm, collection)
            # Dormer window
            bpy.ops.mesh.primitive_cube_add(size=1, location=(dmx + dnx * 0.05, dmy + dny * 0.05, dmz))
            dwn = bpy.context.active_object
            dwn.name = "DormerWin"
            dwn.scale = (dw * 0.6 / 2, 0.06, dh * 0.6 / 2)
            dwn.rotation_euler = (0, 0, math.atan2(dny, dnx))
            dwn.data.materials.append(m_glass)
            link(dwn, collection)

    # Gutters (along the top of walls, both long edges)
    for gi in range(min(2, len(edges))):
        gl, gx1, gy1, gx2, gy2, gnx, gny = edges[gi]
        if gl < 3:
            continue
        gmx = (gx1 + gx2) / 2 + gnx * 0.15
        gmy = (gy1 + gy2) / 2 + gny * 0.15
        bpy.ops.mesh.primitive_cube_add(size=1, location=(gmx, gmy, h - 0.05))
        gut = bpy.context.active_object
        gut.name = f"Gutter_{gi}"
        gut.scale = (gl / 2, 0.04, 0.04)
        gut.rotation_euler = (0, 0, math.atan2(gy2-gy1, gx2-gx1))
        gut.data.materials.append(m_trim)
        link(gut, collection)

    # Parapet coping (on flat roofs)
    if roof_type == "flat" and len(edges) >= 2:
        m_coping = mat("Coping", "#C0B8A8", 0.7)
        for pi in range(min(2, len(edges))):
            pl, px1, py1, px2, py2, pnx, pny = edges[pi]
            if pl < 3:
                continue
            pmx = (px1 + px2) / 2 + pnx * 0.08
            pmy = (py1 + py2) / 2 + pny * 0.08
            bpy.ops.mesh.primitive_cube_add(size=1, location=(pmx, pmy, h + 0.06))
            cop = bpy.context.active_object
            cop.name = f"Coping_{pi}"
            cop.scale = (pl / 2, 0.08, 0.06)
            cop.rotation_euler = (0, 0, math.atan2(py2-py1, px2-px1))
            cop.data.materials.append(m_coping)
            link(cop, collection)

    # Step handrails (for buildings with stoops)
    po_data = params.get("photo_observations", {})
    porch_t = (po_data.get("porch_type") if isinstance(po_data, dict) else None) or params.get("porch_type")
    if porch_t and porch_t in ("stoop", "steps", "stoop_with_railing") and len(edges) > 0:
        length0, sx1, sy1, sx2, sy2, snx, sny = edges[0]
        sdx, sdy = sx2 - sx1, sy2 - sy1
        sangle = math.atan2(sdy, sdx)

        m_handrail = mat("Handrail", "#2A2A2A", 0.4)
        # Two handrails beside the door
        for side_offset in [-0.6, 0.6]:
            hx = sx1 + sdx * 0.5 + math.cos(sangle) * side_offset + snx * 0.5
            hy = sy1 + sdy * 0.5 + math.sin(sangle) * side_offset + sny * 0.5
            bpy.ops.mesh.primitive_cylinder_add(radius=0.02, depth=1.0,
                location=(hx, hy, 0.5), vertices=6)
            hr = bpy.context.active_object
            hr.name = "Handrail"
            hr.data.materials.append(m_handrail)
            link(hr, collection)

    # Fire escape (from photo_observations)
    po_data2 = params.get("photo_observations", {})
    if isinstance(po_data2, dict) and po_data2.get("fire_escape"):
        if len(edges) >= 2:
            # Place on second longest edge (side wall)
            fe_l, fe_x1, fe_y1, fe_x2, fe_y2, fe_nx, fe_ny = edges[1]
            fe_angle = math.atan2(fe_y2 - fe_y1, fe_x2 - fe_x1)
            m_fe = mat("FireEscape", "#3A3A3A", 0.4)

            # Ladder + platforms for each floor
            fe_cx = (fe_x1 + fe_x2) / 2 + fe_nx * 0.3
            fe_cy = (fe_y1 + fe_y2) / 2 + fe_ny * 0.3
            for fi_fe in range(int(floors)):
                fe_z = (fi_fe + 1) * floor_h
                # Platform
                bpy.ops.mesh.primitive_cube_add(size=1, location=(fe_cx, fe_cy, fe_z))
                fep = bpy.context.active_object
                fep.name = f"FE_Platform_{fi_fe}"
                fep.scale = (0.8, 0.5, 0.03)
                fep.rotation_euler = (0, 0, fe_angle)
                fep.data.materials.append(m_fe)
                link(fep, collection)

                # Railing
                bpy.ops.mesh.primitive_cube_add(size=1, location=(fe_cx + fe_nx * 0.5, fe_cy + fe_ny * 0.5, fe_z + 0.45))
                fer = bpy.context.active_object
                fer.name = f"FE_Rail_{fi_fe}"
                fer.scale = (0.8, 0.02, 0.45)
                fer.rotation_euler = (0, 0, fe_angle)
                fer.data.materials.append(m_fe)
                link(fer, collection)

            # Ladder between platforms
            bpy.ops.mesh.primitive_cube_add(size=1, location=(fe_cx, fe_cy, h / 2))
            fel = bpy.context.active_object
            fel.name = "FE_Ladder"
            fel.scale = (0.03, 0.3, h / 2)
            fel.rotation_euler = (0, 0, fe_angle)
            fel.data.materials.append(m_fe)
            link(fel, collection)

    # Signage band above storefront
    if has_storefront and len(edges) > 0:
        length0, sg_x1, sg_y1, sg_x2, sg_y2, sg_nx, sg_ny = edges[0]
        sg_dx, sg_dy = sg_x2 - sg_x1, sg_y2 - sg_y1
        sg_angle = math.atan2(sg_dy, sg_dx)

        sign_w = min(length0 * 0.5, 3.0)
        sign_h = 0.4
        sign_z = floor_h - 0.1
        sgx = sg_x1 + sg_dx * 0.5 + sg_nx * 0.08
        sgy = sg_y1 + sg_dy * 0.5 + sg_ny * 0.08

        sign_colours = ["#1A3A1A", "#3A1A1A", "#1A1A3A", "#4A3A1A", "#E8E0D0"]
        sign_hex = random.choice(sign_colours)
        bpy.ops.mesh.primitive_cube_add(size=1, location=(sgx, sgy, sign_z))
        sgo = bpy.context.active_object
        sgo.name = "Signage"
        sgo.scale = (sign_w / 2, 0.06, sign_h / 2)
        sgo.rotation_euler = (0, 0, sg_angle)
        sgo.data.materials.append(mat(f"Sign_{sign_hex}", sign_hex, 0.6))
        link(sgo, collection)

    # Front steps (most houses have 2-3 steps up to the door)
    if len(edges) > 0 and not has_storefront:
        length0, st_x1, st_y1, st_x2, st_y2, st_nx, st_ny = edges[0]
        st_dx, st_dy = st_x2 - st_x1, st_y2 - st_y1
        st_angle = math.atan2(st_dy, st_dx)

        m_steps = mat("ConcreteSteps", "#A0A098", 0.85)
        step_w = 1.2
        for si in range(3):
            step_d = 0.3
            step_h = 0.15
            step_z = si * step_h + step_h / 2
            step_offset = 0.05 + si * step_d
            sx = st_x1 + st_dx * 0.5 + st_nx * step_offset
            sy = st_y1 + st_dy * 0.5 + st_ny * step_offset

            bpy.ops.mesh.primitive_cube_add(size=1, location=(sx, sy, step_z))
            sto = bpy.context.active_object
            sto.name = f"Step_{si}"
            sto.scale = (step_w / 2, step_d / 2, step_h / 2)
            sto.rotation_euler = (0, 0, st_angle)
            sto.data.materials.append(m_steps)
            link(sto, collection)

    # Downspouts (drain pipes on building corners)
    m_downspout = mat("Downspout", "#4A4A4A", 0.5)
    if len(edges) >= 2:
        length0, dp_x1, dp_y1, dp_x2, dp_y2, dp_nx, dp_ny = edges[0]
        for dp_corner in [(dp_x1, dp_y1), (dp_x2, dp_y2)]:
            dpx = dp_corner[0] + dp_nx * 0.08
            dpy = dp_corner[1] + dp_ny * 0.08
            bpy.ops.mesh.primitive_cylinder_add(radius=0.03, depth=h,
                location=(dpx, dpy, h / 2), vertices=6)
            dp = bpy.context.active_object
            dp.name = "Downspout"
            dp.data.materials.append(m_downspout)
            link(dp, collection)

    # =========================================================================
    # REFINED ARCHITECTURAL DETAILS (from params deep dive)
    # =========================================================================

    # Window glazing bars (muntins) — subdivide each window into panes
    # Based on window_type: "1-over-1", "2-over-2", "6-over-6" etc.
    window_type = params.get("window_type", "")
    if isinstance(window_type, str) and "over" in window_type:
        try:
            parts = window_type.lower().replace("-over-", "x").split("x")
            panes_top = int(parts[0])
            panes_bot = int(parts[1]) if len(parts) > 1 else panes_top
        except:
            panes_top, panes_bot = 1, 1
    else:
        panes_top, panes_bot = 1, 1

    m_muntin = mat("Muntin", trim_hex, 0.6)
    if (panes_top > 1 or panes_bot > 1) and len(edges) > 0:
        length0, mx1, my1, mx2, my2, mnx, mny = edges[0]
        mdx, mdy = mx2 - mx1, my2 - my1
        m_angle = math.atan2(mdy, mdx)
        win_w_m = params.get("window_width_m", 0.9) or 0.9
        win_h_m = params.get("window_height_m", 1.4) or 1.4

        for fi_m in range(int(floors)):
            sill_z_m = fi_m * floor_h + floor_h * 0.3
            n_win_m = (params.get("windows_per_floor", [2]) or [2])
            n_w = n_win_m[fi_m] if fi_m < len(n_win_m) else 2
            if not isinstance(n_w, (int, float)):
                n_w = 2
            n_w = int(n_w)
            for wi_m in range(n_w):
                t_m = (wi_m + 1) / (n_w + 1)
                mwx = mx1 + mdx * t_m + mnx * 0.07
                mwy = my1 + mdy * t_m + mny * 0.07
                mwz = sill_z_m + win_h_m / 2

                # Horizontal muntin (center bar)
                if panes_top > 0 and panes_bot > 0:
                    bpy.ops.mesh.primitive_cube_add(size=1, location=(mwx, mwy, mwz))
                    mh = bpy.context.active_object
                    mh.name = f"Muntin_H_{fi_m}_{wi_m}"
                    mh.scale = (win_w_m / 2, 0.01, 0.015)
                    mh.rotation_euler = (0, 0, m_angle)
                    mh.data.materials.append(m_muntin)
                    link(mh, collection)

                # Vertical muntins
                total_panes = max(panes_top, panes_bot)
                if total_panes > 1:
                    for vi in range(1, total_panes):
                        v_offset = -win_w_m/2 + (win_w_m * vi / total_panes)
                        vx = mwx + math.cos(m_angle) * v_offset
                        vy = mwy + math.sin(m_angle) * v_offset
                        bpy.ops.mesh.primitive_cube_add(size=1, location=(vx, vy, mwz))
                        mv = bpy.context.active_object
                        mv.name = f"Muntin_V_{fi_m}_{wi_m}_{vi}"
                        mv.scale = (0.015, 0.01, win_h_m / 2)
                        mv.rotation_euler = (0, 0, m_angle)
                        mv.data.materials.append(m_muntin)
                        link(mv, collection)

    # Eave overhang (roof extends past wall)
    eave_mm = 300
    rd_eo = params.get("roof_detail", {})
    if isinstance(rd_eo, dict):
        eave_mm = rd_eo.get("eave_overhang_mm", 300) or 300
    eave_m = eave_mm / 1000.0
    if eave_m > 0.1 and "gable" in roof_type and len(edges) >= 2:
        m_eave = mat("Eave", "#5A5A5A", 0.85)
        for ei_e in range(min(2, len(edges))):
            el, ex1, ey1, ex2, ey2, enx, eny = edges[ei_e]
            if el < 2:
                continue
            e_angle = math.atan2(ey2 - ey1, ex2 - ex1)
            emx = (ex1 + ex2) / 2 + enx * eave_m
            emy = (ey1 + ey2) / 2 + eny * eave_m
            bpy.ops.mesh.primitive_cube_add(size=1, location=(emx, emy, h - 0.03))
            eo = bpy.context.active_object
            eo.name = f"Eave_{ei_e}"
            eo.scale = (el / 2 + 0.1, eave_m / 2, 0.03)
            eo.rotation_euler = (0, 0, e_angle)
            eo.data.materials.append(m_eave)
            link(eo, collection)

    # Mortar colour accent (thin lines on brick facade to suggest bond pattern)
    mortar_hex_m = "#C8C0B0"
    fd_m = params.get("facade_detail", {})
    if isinstance(fd_m, dict):
        mc = fd_m.get("mortar_colour", "")
        if mc and "dark" in str(mc).lower():
            mortar_hex_m = "#8A8A80"
        elif mc and "light" in str(mc).lower():
            mortar_hex_m = "#D0C8B8"

    # Decorative brickwork indicator (raised band on facade)
    deco_bw = params.get("decorative_elements", {})
    if isinstance(deco_bw, dict) and isinstance(deco_bw.get("decorative_brickwork"), dict):
        if deco_bw["decorative_brickwork"].get("present"):
            if len(edges) > 0:
                el0, dbx1, dby1, dbx2, dby2, dbnx, dbny = edges[0]
                db_angle = math.atan2(dby2 - dby1, dbx2 - dbx1)
                # Decorative band at 2/3 height
                db_z = h * 0.67
                dbmx = (dbx1 + dbx2) / 2 + dbnx * 0.06
                dbmy = (dby1 + dby2) / 2 + dbny * 0.06
                m_deco_brick = mat(f"DecoBrick_{hex_col}", hex_col, 0.65)
                bpy.ops.mesh.primitive_cube_add(size=1, location=(dbmx, dbmy, db_z))
                dbo = bpy.context.active_object
                dbo.name = "DecoBrickBand"
                dbo.scale = (el0 * 0.8 / 2, 0.04, 0.08)
                dbo.rotation_euler = (0, 0, db_angle)
                dbo.data.materials.append(m_deco_brick)
                link(dbo, collection)

    # Bay window canted sides (add angled side panels to existing bay windows)
    bw_shape = ""
    if isinstance(deco_bw, dict):
        bw_shape = deco_bw.get("bay_window_shape", "") or ""
    bw_data = params.get("bay_window", {})
    if isinstance(bw_data, dict) and bw_data.get("present") and bw_shape == "canted" and len(edges) > 0:
        bw_w = bw_data.get("width_m", 2.0)
        bw_proj = bw_data.get("projection_m", 0.6)
        bw_floors_c = bw_data.get("floors", [0, 1])
        if not isinstance(bw_floors_c, list):
            bw_floors_c = [0, 1]
        el0, cx1, cy1, cx2, cy2, cnx, cny = edges[0]
        c_angle = math.atan2(cy2 - cy1, cx2 - cx1)
        bt_c = 0.3
        m_bay_side = mat("BaySide", trim_hex, 0.6)

        for bfi_c in bw_floors_c:
            if bfi_c >= floors:
                continue
            bz_c = bfi_c * floor_h + 0.3
            bh_c = floor_h * 0.7
            for side_c in [-1, 1]:
                # Angled side panel
                side_x = cx1 + (cx2-cx1) * bt_c + math.cos(c_angle) * bw_w/2 * side_c * 0.8
                side_y = cy1 + (cy2-cy1) * bt_c + math.sin(c_angle) * bw_w/2 * side_c * 0.8
                side_x += cnx * bw_proj * 0.3
                side_y += cny * bw_proj * 0.3
                bpy.ops.mesh.primitive_cube_add(size=1,
                    location=(side_x, side_y, bz_c + bh_c/2))
                bs = bpy.context.active_object
                bs.name = f"BaySide_{bfi_c}_{side_c}"
                bs.scale = (0.04, bw_proj * 0.5, bh_c / 2)
                bs.rotation_euler = (0, 0, c_angle + side_c * 0.5)
                bs.data.materials.append(m_bay_side)
                link(bs, collection)

    # Roof ridge cap (decorative ridge on gable roofs)
    if "gable" in roof_type and len(edges) >= 1:
        el0, rx1, ry1, rx2, ry2, rnx, rny = edges[0]
        r_angle = math.atan2(ry2 - ry1, rx2 - rx1)
        ridge_h_cap = min((max(xs)-min(xs)) * 0.35, 2.5)
        rmx = (rx1 + rx2) / 2
        rmy = (ry1 + ry2) / 2
        m_ridge = mat("RidgeCap", "#5A5A5A", 0.8)
        bpy.ops.mesh.primitive_cube_add(size=1, location=(rmx, rmy, h + ridge_h_cap - 0.02))
        rc = bpy.context.active_object
        rc.name = "RidgeCap"
        rc.scale = (el0 / 2, 0.05, 0.04)
        rc.rotation_euler = (0, 0, r_angle)
        rc.data.materials.append(m_ridge)
        link(rc, collection)

    # Address number plate (small coloured rectangle near door)
    if len(edges) > 0 and params.get("building_name"):
        el0, ax1, ay1, ax2, ay2, anx, any_a = edges[0]
        a_angle = math.atan2(ay2 - ay1, ax2 - ax1)
        # Position near the door (40% along front edge, at 1.5m height)
        at = 0.4
        anx_pos = ax1 + (ax2-ax1) * at + anx * 0.07
        any_pos = ay1 + (ay2-ay1) * at + any_a * 0.07
        m_addr = mat("AddrPlate", "#E8E0D0", 0.6)
        bpy.ops.mesh.primitive_cube_add(size=1, location=(anx_pos, any_pos, 1.5))
        ap = bpy.context.active_object
        ap.name = "AddrPlate"
        ap.scale = (0.12, 0.02, 0.08)
        ap.rotation_euler = (0, 0, a_angle)
        ap.data.materials.append(m_addr)
        link(ap, collection)

    # Transom window above door (common in Victorian houses)
    doors_d = params.get("doors_detail", [])
    if isinstance(doors_d, list):
        for dd_t in doors_d:
            if not isinstance(dd_t, dict):
                continue
            transom = dd_t.get("transom", {})
            if isinstance(transom, dict) and transom.get("present"):
                t_h = transom.get("height_m", 0.3)
                dw_t = dd_t.get("width_m", 1.0)
                dh_t = dd_t.get("height_m", 2.1)
                dpos_t = dd_t.get("position", "center")
                dt_t = 0.3 if dpos_t == "left" else 0.7 if dpos_t == "right" else 0.5
                if len(edges) > 0:
                    el0, tx1, ty1, tx2, ty2, tnx, tny = edges[0]
                    tdx, tdy = tx2 - tx1, ty2 - ty1
                    t_angle = math.atan2(tdy, tdx)
                    trx = tx1 + tdx * dt_t + tnx * 0.06
                    try_ = ty1 + tdy * dt_t + tny * 0.06
                    m_transom = mat("Transom", "#5A7A8A", 0.3)
                    bpy.ops.mesh.primitive_cube_add(size=1,
                        location=(trx, try_, dh_t + t_h/2))
                    tro = bpy.context.active_object
                    tro.name = "Transom"
                    tro.scale = (dw_t * 0.9 / 2, 0.06, t_h / 2)
                    tro.rotation_euler = (0, 0, t_angle)
                    tro.data.materials.append(m_transom)
                    link(tro, collection)
                break

    # Voussoirs (arch stones above windows — from decorative_elements)
    voussoirs = deco_bw.get("stone_voussoirs", {}) if isinstance(deco_bw, dict) else {}
    if isinstance(voussoirs, dict) and voussoirs.get("present") and len(edges) > 0:
        v_hex = voussoirs.get("colour_hex", "#C0B8A0")
        m_vous = mat(f"Voussoir_{v_hex}", v_hex, 0.7)
        el0, vx1, vy1, vx2, vy2, vnx, vny = edges[0]
        vdx, vdy = vx2 - vx1, vy2 - vy1
        v_angle = math.atan2(vdy, vdx)
        win_w_v = params.get("window_width_m", 0.9) or 0.9
        win_h_v = params.get("window_height_m", 1.4) or 1.4

        for fi_v in range(int(floors)):
            sill_v = fi_v * floor_h + floor_h * 0.3
            wz_v = sill_v + win_h_v
            n_wv = 2
            wpf_v = params.get("windows_per_floor", [2])
            if isinstance(wpf_v, list) and fi_v < len(wpf_v):
                n_wv = int(wpf_v[fi_v]) if isinstance(wpf_v[fi_v], (int, float)) else 2
            for wi_v in range(n_wv):
                tv = (wi_v + 1) / (n_wv + 1)
                vwx = vx1 + vdx * tv + vnx * 0.06
                vwy = vy1 + vdy * tv + vny * 0.06
                # Voussoir keystone (wider at center)
                bpy.ops.mesh.primitive_cube_add(size=1, location=(vwx, vwy, wz_v + 0.06))
                vo = bpy.context.active_object
                vo.name = f"Voussoir_{fi_v}_{wi_v}"
                vo.scale = (win_w_v * 0.6 / 2, 0.04, 0.06)
                vo.rotation_euler = (0, 0, v_angle)
                vo.data.materials.append(m_vous)
                link(vo, collection)

    # Stone lintels (flat header stones above windows)
    lintels = deco_bw.get("stone_lintels", {}) if isinstance(deco_bw, dict) else {}
    if isinstance(lintels, dict) and lintels.get("present") and len(edges) > 0:
        l_hex = lintels.get("colour_hex", "#B0A890")
        m_lintel_s = mat(f"StoneLint_{l_hex}", l_hex, 0.7)
        el0, lx1, ly1, lx2, ly2, lnx, lny = edges[0]
        ldx, ldy = lx2 - lx1, ly2 - ly1
        l_angle = math.atan2(ldy, ldx)
        win_w_l = params.get("window_width_m", 0.9) or 0.9
        win_h_l = params.get("window_height_m", 1.4) or 1.4

        for fi_l in range(int(floors)):
            sill_l = fi_l * floor_h + floor_h * 0.3
            wz_l = sill_l + win_h_l
            n_wl = 2
            wpf_l = params.get("windows_per_floor", [2])
            if isinstance(wpf_l, list) and fi_l < len(wpf_l):
                n_wl = int(wpf_l[fi_l]) if isinstance(wpf_l[fi_l], (int, float)) else 2
            for wi_l in range(n_wl):
                tl = (wi_l + 1) / (n_wl + 1)
                lwx = lx1 + ldx * tl + lnx * 0.06
                lwy = ly1 + ldy * tl + lny * 0.06
                bpy.ops.mesh.primitive_cube_add(size=1, location=(lwx, lwy, wz_l + 0.04))
                lo = bpy.context.active_object
                lo.name = f"StoneLintel_{fi_l}_{wi_l}"
                lo.scale = (win_w_l / 2 + 0.1, 0.05, 0.05)
                lo.rotation_euler = (0, 0, l_angle)
                lo.data.materials.append(m_lintel_s)
                link(lo, collection)

    # Roof flashing (metal strip where roof meets wall on gable end)
    if "gable" in roof_type and len(edges) >= 2:
        m_flash = mat("Flashing", "#707070", 0.4)
        el1, fx1, fy1, fx2, fy2, fnx, fny = edges[1]
        f_angle = math.atan2(fy2 - fy1, fx2 - fx1)
        fmx = (fx1 + fx2) / 2
        fmy = (fy1 + fy2) / 2
        bpy.ops.mesh.primitive_cube_add(size=1, location=(fmx, fmy, h))
        fl = bpy.context.active_object
        fl.name = "Flashing"
        fl.scale = (0.04, el1 / 2, 0.08)
        fl.rotation_euler = (0, 0, f_angle)
        fl.data.materials.append(m_flash)
        link(fl, collection)

    # Soffit (underside of eave overhang — visible trim board)
    if eave_m > 0.1 and len(edges) >= 2:
        m_soffit = mat("Soffit", "#E0D8C8", 0.7)
        for si_s in range(min(2, len(edges))):
            sel, sx1, sy1, sx2, sy2, snx_s, sny_s = edges[si_s]
            if sel < 2:
                continue
            s_angle = math.atan2(sy2 - sy1, sx2 - sx1)
            smx = (sx1 + sx2) / 2 + snx_s * (eave_m * 0.5)
            smy = (sy1 + sy2) / 2 + sny_s * (eave_m * 0.5)
            bpy.ops.mesh.primitive_cube_add(size=1, location=(smx, smy, h - 0.08))
            so = bpy.context.active_object
            so.name = f"Soffit_{si_s}"
            so.scale = (sel / 2 + 0.05, eave_m * 0.4, 0.02)
            so.rotation_euler = (0, 0, s_angle)
            so.data.materials.append(m_soffit)
            link(so, collection)

    # Door frame (trim around door opening)
    if len(edges) > 0:
        el0, dfx1, dfy1, dfx2, dfy2, dfnx, dfny = edges[0]
        df_angle = math.atan2(dfy2 - dfy1, dfx2 - dfx1)
        df_t = 0.5
        dfx = dfx1 + (dfx2-dfx1) * df_t + dfnx * 0.04
        dfy_p = dfy1 + (dfy2-dfy1) * df_t + dfny * 0.04
        door_h_df = 2.3
        door_w_df = 1.1
        m_doorframe = mat("DoorFrame", trim_hex, 0.6)
        # Left jamb
        bpy.ops.mesh.primitive_cube_add(size=1,
            location=(dfx - math.cos(df_angle) * door_w_df/2, dfy_p - math.sin(df_angle) * door_w_df/2, door_h_df/2))
        dfl = bpy.context.active_object
        dfl.name = "DoorFrame_L"
        dfl.scale = (0.04, 0.06, door_h_df / 2)
        dfl.rotation_euler = (0, 0, df_angle)
        dfl.data.materials.append(m_doorframe)
        link(dfl, collection)
        # Right jamb
        bpy.ops.mesh.primitive_cube_add(size=1,
            location=(dfx + math.cos(df_angle) * door_w_df/2, dfy_p + math.sin(df_angle) * door_w_df/2, door_h_df/2))
        dfr = bpy.context.active_object
        dfr.name = "DoorFrame_R"
        dfr.scale = (0.04, 0.06, door_h_df / 2)
        dfr.rotation_euler = (0, 0, df_angle)
        dfr.data.materials.append(m_doorframe)
        link(dfr, collection)
        # Header
        bpy.ops.mesh.primitive_cube_add(size=1,
            location=(dfx, dfy_p, door_h_df + 0.04))
        dfh = bpy.context.active_object
        dfh.name = "DoorFrame_H"
        dfh.scale = (door_w_df / 2 + 0.05, 0.06, 0.05)
        dfh.rotation_euler = (0, 0, df_angle)
        dfh.data.materials.append(m_doorframe)
        link(dfh, collection)

    # Basement window (small window at ground level)
    if h > 5 and len(edges) > 0:
        el0, bwx1, bwy1, bwx2, bwy2, bwnx, bwny = edges[0]
        bw_angle = math.atan2(bwy2 - bwy1, bwx2 - bwx1)
        bw_dx, bw_dy = bwx2 - bwx1, bwy2 - bwy1
        n_bw = max(1, int(el0 / 4))
        for bwi in range(n_bw):
            t_bw = (bwi + 1) / (n_bw + 1)
            bwx_p = bwx1 + bw_dx * t_bw + bwnx * 0.06
            bwy_p = bwy1 + bw_dy * t_bw + bwny * 0.06
            bpy.ops.mesh.primitive_cube_add(size=1, location=(bwx_p, bwy_p, 0.25))
            bw_o = bpy.context.active_object
            bw_o.name = f"BasementWin_{bwi}"
            bw_o.scale = (0.4, 0.06, 0.2)
            bw_o.rotation_euler = (0, 0, bw_angle)
            bw_o.data.materials.append(m_glass)
            link(bw_o, collection)

    # Wall cap / coping on party walls
    pw_left = params.get("party_wall_left", False)
    pw_right = params.get("party_wall_right", False)
    if (pw_left or pw_right) and len(edges) >= 2:
        m_pw_cap = mat("PartyWallCap", "#B0A898", 0.7)
        for ei_pw in range(2, min(4, len(edges))):
            el_pw, pwx1, pwy1, pwx2, pwy2, pwnx, pwny = edges[ei_pw]
            if el_pw > 8:
                continue
            pw_angle = math.atan2(pwy2 - pwy1, pwx2 - pwx1)
            pwmx = (pwx1 + pwx2) / 2
            pwmy = (pwy1 + pwy2) / 2
            bpy.ops.mesh.primitive_cube_add(size=1, location=(pwmx, pwmy, h + 0.04))
            pw_o = bpy.context.active_object
            pw_o.name = f"PWCap_{ei_pw}"
            pw_o.scale = (el_pw / 2, 0.12, 0.04)
            pw_o.rotation_euler = (0, 0, pw_angle)
            pw_o.data.materials.append(m_pw_cap)
            link(pw_o, collection)

    # Porch railing (horizontal rail between porch columns)
    if params.get("porch_present") and len(edges) > 0:
        el0_pr, prx1, pry1, prx2, pry2, prnx, prny = edges[0]
        pr_angle = math.atan2(pry2 - pry1, prx2 - pry1) if abs(pry2 - pry1) > 0.01 else 0
        pr_angle = math.atan2(pry2 - pry1, prx2 - prx1)
        porch_w_r = min(el0_pr * 0.6, 3.0)
        porch_d_r = 1.5
        prx_c = prx1 + (prx2-prx1) * 0.5 + prnx * (0.05 + porch_d_r)
        pry_c = pry1 + (pry2-pry1) * 0.5 + prny * (0.05 + porch_d_r)
        m_porch_rail = mat("PorchRail", "#E0D8C8", 0.7)
        # Front rail
        bpy.ops.mesh.primitive_cube_add(size=1, location=(prx_c, pry_c, 0.75))
        prf = bpy.context.active_object
        prf.name = "PorchRailFront"
        prf.scale = (porch_w_r / 2, 0.02, 0.03)
        prf.rotation_euler = (0, 0, pr_angle)
        prf.data.materials.append(m_porch_rail)
        link(prf, collection)
        # Balusters (vertical spindles)
        m_baluster = mat("Baluster", "#E0D8C8", 0.7)
        n_bal = max(2, int(porch_w_r / 0.15))
        for bal_i in range(n_bal):
            bal_t = -porch_w_r/2 + porch_w_r * bal_i / max(n_bal-1, 1)
            bal_x = prx_c + math.cos(pr_angle) * bal_t
            bal_y = pry_c + math.sin(pr_angle) * bal_t
            bpy.ops.mesh.primitive_cylinder_add(radius=0.015, depth=0.45,
                location=(bal_x, bal_y, 0.52), vertices=6)
            bal = bpy.context.active_object
            bal.name = f"Baluster_{bal_i}"
            bal.data.materials.append(m_baluster)
            link(bal, collection)

    # Chimney cap (wider top on chimney)
    rf_ch = params.get("roof_features", [])
    if isinstance(rf_ch, list):
        for feat_ch in rf_ch:
            if isinstance(feat_ch, str) and "chimney" in feat_ch.lower():
                if len(edges) >= 2:
                    _, chx1, chy1, chx2, chy2, chnx, chny = edges[1]
                    ch_mx = (chx1 + chx2) / 2 + chnx * 0.3
                    ch_my = (chy1 + chy2) / 2 + chny * 0.3
                    m_ch_cap = mat("ChimneyCap", "#5A4A3A", 0.8)
                    bpy.ops.mesh.primitive_cube_add(size=1,
                        location=(ch_mx, ch_my, h + 1.2 + 0.06))
                    chc = bpy.context.active_object
                    chc.name = "ChimneyCap"
                    chc.scale = (0.25, 0.25, 0.06)
                    chc.data.materials.append(m_ch_cap)
                    link(chc, collection)
                    # Chimney pot (small cylinder on top)
                    bpy.ops.mesh.primitive_cylinder_add(radius=0.08, depth=0.2,
                        location=(ch_mx, ch_my, h + 1.2 + 0.22), vertices=8)
                    chp = bpy.context.active_object
                    chp.name = "ChimneyPot"
                    chp.data.materials.append(mat("ChimneyPot", "#6A5A4A", 0.8))
                    link(chp, collection)
                break

    # Corbelling (stepped brick projection below cornice)
    cornice_d = deco_bw.get("cornice", {}) if isinstance(deco_bw, dict) else {}
    if isinstance(cornice_d, dict) and cornice_d.get("present") and len(edges) > 0:
        el0_cb, cbx1, cby1, cbx2, cby2, cbnx, cbny = edges[0]
        cb_angle = math.atan2(cby2 - cby1, cbx2 - cbx1)
        co_h_mm = cornice_d.get("height_mm", 300) or 300
        m_corbel = mat(f"Corbel_{hex_col}", hex_col, 0.65)
        # 3 stepped layers below cornice
        for step_i in range(3):
            step_proj = 0.02 + step_i * 0.015
            step_z = h - (co_h_mm/1000) - (step_i + 1) * 0.06
            step_x = (cbx1 + cbx2) / 2 + cbnx * (0.06 + step_proj)
            step_y = (cby1 + cby2) / 2 + cbny * (0.06 + step_proj)
            bpy.ops.mesh.primitive_cube_add(size=1, location=(step_x, step_y, step_z))
            cbo = bpy.context.active_object
            cbo.name = f"Corbel_{step_i}"
            cbo.scale = (el0_cb * 0.9 / 2, step_proj, 0.03)
            cbo.rotation_euler = (0, 0, cb_angle)
            cbo.data.materials.append(m_corbel)
            link(cbo, collection)

    # Window shutters (decorative side panels — common on Victorian houses)
    if params.get("condition") in ("good", "fair") and len(edges) > 0:
        el0_sh, shx1, shy1, shx2, shy2, shnx, shny = edges[0]
        sh_dx, sh_dy = shx2 - shx1, shy2 - shy1
        sh_angle = math.atan2(sh_dy, sh_dx)
        win_w_sh = params.get("window_width_m", 0.9) or 0.9
        win_h_sh = params.get("window_height_m", 1.4) or 1.4
        # Shutter colour: dark green, dark blue, or dark red
        shutter_colours = ["#2A4A2A", "#2A2A4A", "#4A2A2A", "#3A3A3A"]
        sh_hex = random.choice(shutter_colours)
        m_shutter = mat(f"Shutter_{sh_hex}", sh_hex, 0.75)
        # Only add shutters if random says so (50%)
        if random.random() > 0.5:
            wpf_sh = params.get("windows_per_floor", [2]) or [2]
            for fi_sh in range(min(int(floors), 3)):
                sill_sh = fi_sh * floor_h + floor_h * 0.3
                n_w_sh = wpf_sh[fi_sh] if fi_sh < len(wpf_sh) and isinstance(wpf_sh[fi_sh], (int, float)) else 2
                n_w_sh = int(n_w_sh)
                for wi_sh in range(n_w_sh):
                    t_sh = (wi_sh + 1) / (n_w_sh + 1)
                    swx = shx1 + sh_dx * t_sh + shnx * 0.04
                    swy = shy1 + sh_dy * t_sh + shny * 0.04
                    swz = sill_sh + win_h_sh / 2
                    for side_sh in [-1, 1]:
                        sx_sh = swx + math.cos(sh_angle) * (win_w_sh/2 + 0.06) * side_sh
                        sy_sh = swy + math.sin(sh_angle) * (win_w_sh/2 + 0.06) * side_sh
                        bpy.ops.mesh.primitive_cube_add(size=1, location=(sx_sh, sy_sh, swz))
                        sho = bpy.context.active_object
                        sho.name = f"Shutter_{fi_sh}_{wi_sh}_{side_sh}"
                        sho.scale = (win_w_sh * 0.25, 0.02, win_h_sh / 2)
                        sho.rotation_euler = (0, 0, sh_angle)
                        sho.data.materials.append(m_shutter)
                        link(sho, collection)

    # Kick plate / base trim (thin strip above foundation)
    if len(edges) > 0:
        m_kick = mat("KickPlate", "#3A3A3A", 0.8)
        for ei_k in range(min(2, len(edges))):
            el_k, kx1, ky1, kx2, ky2, knx, kny = edges[ei_k]
            if el_k < 2:
                continue
            k_angle = math.atan2(ky2 - ky1, kx2 - kx1)
            kmx = (kx1 + kx2) / 2 + knx * 0.06
            kmy = (ky1 + ky2) / 2 + kny * 0.06
            bpy.ops.mesh.primitive_cube_add(size=1, location=(kmx, kmy, 0.5))
            ko = bpy.context.active_object
            ko.name = f"KickPlate_{ei_k}"
            ko.scale = (el_k / 2, 0.03, 0.06)
            ko.rotation_euler = (0, 0, k_angle)
            ko.data.materials.append(m_kick)
            link(ko, collection)

    # Windowbox planters (flower boxes below windows — seasonal but charming)
    if random.random() > 0.6 and len(edges) > 0:
        el0_wb, wbx1, wby1, wbx2, wby2, wbnx, wbny = edges[0]
        wb_dx, wb_dy = wbx2 - wbx1, wby2 - wby1
        wb_angle = math.atan2(wb_dy, wb_dx)
        m_planter = mat("WindowPlanter", "#6A4A2A", 0.8)
        m_soil_wb = mat("PlanterSoil", "#4A3A2A", 0.9)
        wpf_wb = params.get("windows_per_floor", [2]) or [2]
        # Only on ground or second floor
        for fi_wb in range(min(2, int(floors))):
            sill_wb = fi_wb * floor_h + floor_h * 0.3
            n_w_wb = wpf_wb[fi_wb] if fi_wb < len(wpf_wb) and isinstance(wpf_wb[fi_wb], (int, float)) else 2
            n_w_wb = int(n_w_wb)
            if random.random() > 0.5:
                continue
            for wi_wb in range(n_w_wb):
                if random.random() > 0.5:
                    continue
                t_wb = (wi_wb + 1) / (n_w_wb + 1)
                wbx_p = wbx1 + wb_dx * t_wb + wbnx * 0.12
                wby_p = wby1 + wb_dy * t_wb + wbny * 0.12
                win_w_wb = params.get("window_width_m", 0.9) or 0.9
                bpy.ops.mesh.primitive_cube_add(size=1,
                    location=(wbx_p, wby_p, sill_wb - 0.08))
                wbo = bpy.context.active_object
                wbo.name = f"Planter_{fi_wb}_{wi_wb}"
                wbo.scale = (win_w_wb * 0.8 / 2, 0.1, 0.08)
                wbo.rotation_euler = (0, 0, wb_angle)
                wbo.data.materials.append(m_planter)
                link(wbo, collection)

    # Satellite dish / antenna on some roofs
    if random.random() > 0.85:
        m_dish = mat("SatDish", "#D0D0D0", 0.4)
        dish_x = cx + random.uniform(-1, 1)
        dish_y = cy + random.uniform(-1, 1)
        bpy.ops.mesh.primitive_uv_sphere_add(radius=0.25,
            location=(dish_x, dish_y, h + 0.5), segments=8, ring_count=6)
        dish = bpy.context.active_object
        dish.name = "SatDish"
        dish.scale = (1, 0.3, 1)
        dish.rotation_euler = (0.5, 0, random.uniform(0, 6.28))
        dish.data.materials.append(m_dish)
        link(dish, collection)

    # AC unit (box on side wall or ground)
    if random.random() > 0.7 and len(edges) >= 2:
        _, acx1, acy1, acx2, acy2, acnx, acny = edges[1]
        ac_angle = math.atan2(acy2 - acy1, acx2 - acx1)
        acx = (acx1 + acx2) / 2 + acnx * 0.4
        acy_p = (acy1 + acy2) / 2 + acny * 0.4
        m_ac = mat("ACUnit", "#C8C8C8", 0.5)
        bpy.ops.mesh.primitive_cube_add(size=1, location=(acx, acy_p, 0.3))
        ac = bpy.context.active_object
        ac.name = "ACUnit"
        ac.scale = (0.35, 0.25, 0.3)
        ac.rotation_euler = (0, 0, ac_angle)
        ac.data.materials.append(m_ac)
        link(ac, collection)

    # Meter box (electrical/gas meter on wall)
    if len(edges) >= 2 and random.random() > 0.5:
        _, mtx1, mty1, mtx2, mty2, mtnx, mtny = edges[1]
        mt_angle = math.atan2(mty2 - mty1, mtx2 - mtx1)
        mtx_p = mtx1 + (mtx2-mtx1) * 0.3 + mtnx * 0.08
        mty_p = mty1 + (mty2-mty1) * 0.3 + mtny * 0.08
        m_meter = mat("MeterBox", "#8A8A8A", 0.6)
        bpy.ops.mesh.primitive_cube_add(size=1, location=(mtx_p, mty_p, 1.2))
        mt = bpy.context.active_object
        mt.name = "MeterBox"
        mt.scale = (0.2, 0.06, 0.25)
        mt.rotation_euler = (0, 0, mt_angle)
        mt.data.materials.append(m_meter)
        link(mt, collection)

    # Vent/exhaust on roof
    if random.random() > 0.6:
        m_vent = mat("RoofVent", "#6A6A6A", 0.6)
        vx = cx + random.uniform(-1.5, 1.5)
        vy = cy + random.uniform(-1.5, 1.5)
        bpy.ops.mesh.primitive_cylinder_add(radius=0.1, depth=0.3,
            location=(vx, vy, h + 0.15), vertices=8)
        vent = bpy.context.active_object
        vent.name = "RoofVent"
        vent.data.materials.append(m_vent)
        link(vent, collection)

    # Drip edge / fascia board detail (thin strip at roof edge)
    if len(edges) > 0:
        m_fascia = mat("Fascia", trim_hex, 0.65)
        for ei_f in range(min(2, len(edges))):
            el_f, fax1, fay1, fax2, fay2, fanx, fany = edges[ei_f]
            if el_f < 2:
                continue
            fa_angle = math.atan2(fay2 - fay1, fax2 - fax1)
            famx = (fax1 + fax2) / 2 + fanx * 0.03
            famy = (fay1 + fay2) / 2 + fany * 0.03
            bpy.ops.mesh.primitive_cube_add(size=1, location=(famx, famy, h + 0.02))
            fao = bpy.context.active_object
            fao.name = f"Fascia_{ei_f}"
            fao.scale = (el_f / 2 + 0.05, 0.03, 0.1)
            fao.rotation_euler = (0, 0, fa_angle)
            fao.data.materials.append(m_fascia)
            link(fao, collection)

    # Porch lattice (diamond lattice panel below raised porch)
    if params.get("porch_present") and len(edges) > 0:
        el0_lt, ltx1, lty1, ltx2, lty2, ltnx, ltny = edges[0]
        lt_angle = math.atan2(lty2 - lty1, ltx2 - ltx1)
        porch_w_lt = min(el0_lt * 0.6, 3.0)
        ltx_c = ltx1 + (ltx2-ltx1) * 0.5 + ltnx * 1.0
        lty_c = lty1 + (lty2-lty1) * 0.5 + ltny * 1.0
        m_lattice = mat("Lattice", "#E0D8C8", 0.7)
        # Lattice panel under porch floor (decorative screen)
        bpy.ops.mesh.primitive_cube_add(size=1, location=(ltx_c, lty_c, 0.15))
        lto = bpy.context.active_object
        lto.name = "Lattice"
        lto.scale = (porch_w_lt / 2, 0.02, 0.15)
        lto.rotation_euler = (0, 0, lt_angle)
        lto.data.materials.append(m_lattice)
        link(lto, collection)

    # Rain barrel (beside some houses)
    if random.random() > 0.8 and len(edges) >= 2:
        _, rbx1, rby1, rbx2, rby2, rbnx, rbny = edges[1]
        rb_mx = rbx1 + (rbx2-rbx1) * 0.8 + rbnx * 0.4
        rb_my = rby1 + (rby2-rby1) * 0.8 + rbny * 0.4
        m_barrel = mat("RainBarrel", "#2A4A2A", 0.7)
        bpy.ops.mesh.primitive_cylinder_add(radius=0.25, depth=0.8,
            location=(rb_mx, rb_my, 0.4), vertices=12)
        rb = bpy.context.active_object
        rb.name = "RainBarrel"
        rb.data.materials.append(m_barrel)
        link(rb, collection)

    # Outdoor light fixture (porch/entrance light)
    if len(edges) > 0:
        el0_ol, olx1, oly1, olx2, oly2, olnx, olny = edges[0]
        ol_angle = math.atan2(oly2 - oly1, olx2 - olx1)
        # Light beside door
        ol_t = 0.42
        olx_p = olx1 + (olx2-olx1) * ol_t + olnx * 0.08
        oly_p = oly1 + (oly2-oly1) * ol_t + olny * 0.08
        m_light_fix = mat("LightFixture", "#8A7A5A", 0.5)
        m_light_bulb = mat("LightBulb", "#F0E8C0", 0.3)
        # Bracket
        bpy.ops.mesh.primitive_cube_add(size=1, location=(olx_p, oly_p, 2.3))
        olb = bpy.context.active_object
        olb.name = "LightBracket"
        olb.scale = (0.04, 0.08, 0.04)
        olb.rotation_euler = (0, 0, ol_angle)
        olb.data.materials.append(m_light_fix)
        link(olb, collection)
        # Lantern
        bpy.ops.mesh.primitive_cube_add(size=1,
            location=(olx_p + olnx * 0.1, oly_p + olny * 0.1, 2.3))
        oll = bpy.context.active_object
        oll.name = "Lantern"
        oll.scale = (0.06, 0.06, 0.1)
        oll.data.materials.append(m_light_bulb)
        link(oll, collection)

    # House number plaque (on wall beside door — different from address plate)
    if len(edges) > 0 and params.get("building_name"):
        el0_hn, hnx1, hny1, hnx2, hny2, hnnx, hnny = edges[0]
        hn_angle = math.atan2(hny2 - hny1, hnx2 - hnx1)
        hn_t = 0.55
        hnx_p = hnx1 + (hnx2-hnx1) * hn_t + hnnx * 0.06
        hny_p = hny1 + (hny2-hny1) * hn_t + hnny * 0.06
        m_plaque = mat("HousePlaque", "#1A1A1A", 0.7)
        bpy.ops.mesh.primitive_cube_add(size=1, location=(hnx_p, hny_p, 1.8))
        hno = bpy.context.active_object
        hno.name = "HouseNumber"
        hno.scale = (0.08, 0.015, 0.06)
        hno.rotation_euler = (0, 0, hn_angle)
        hno.data.materials.append(m_plaque)
        link(hno, collection)

    # Brick soldier course (vertical bricks above windows — common in Victorian)
    era = ""
    hcd = params.get("hcd_data", {})
    if isinstance(hcd, dict):
        era = hcd.get("construction_date", "") or ""
    if "pre-1889" in era.lower() or "1890" in era or "1889" in era:
        if len(edges) > 0:
            el0_sc, scx1, scy1, scx2, scy2, scnx, scny = edges[0]
            sc_dx, sc_dy = scx2 - scx1, scy2 - scy1
            sc_angle = math.atan2(sc_dy, sc_dx)
            win_w_sc = params.get("window_width_m", 0.9) or 0.9
            win_h_sc = params.get("window_height_m", 1.4) or 1.4
            m_soldier = mat(f"Soldier_{hex_col}", hex_col, 0.6)
            wpf_sc = params.get("windows_per_floor", [2]) or [2]
            for fi_sc in range(min(int(floors), 3)):
                sill_sc = fi_sc * floor_h + floor_h * 0.3
                wz_sc = sill_sc + win_h_sc
                n_w_sc = wpf_sc[fi_sc] if fi_sc < len(wpf_sc) and isinstance(wpf_sc[fi_sc], (int, float)) else 2
                n_w_sc = int(n_w_sc)
                for wi_sc in range(n_w_sc):
                    t_sc = (wi_sc + 1) / (n_w_sc + 1)
                    swx = scx1 + sc_dx * t_sc + scnx * 0.05
                    swy = scy1 + sc_dy * t_sc + scny * 0.05
                    # Soldier course = slightly raised band above window
                    bpy.ops.mesh.primitive_cube_add(size=1,
                        location=(swx, swy, wz_sc + 0.08))
                    sco = bpy.context.active_object
                    sco.name = f"Soldier_{fi_sc}_{wi_sc}"
                    sco.scale = (win_w_sc / 2 + 0.05, 0.035, 0.04)
                    sco.rotation_euler = (0, 0, sc_angle)
                    sco.data.materials.append(m_soldier)
                    link(sco, collection)

    # Gable vent (triangular or round vent in gable wall)
    if "gable" in roof_type:
        m_gvent = mat("GableVent", "#6A6A6A", 0.6)
        gvx = cx
        gvy = cy
        ridge_h_gv = min((max(xs)-min(xs)) * 0.35, 2.5)
        bpy.ops.mesh.primitive_cylinder_add(radius=0.15, depth=0.05,
            location=(gvx, gvy, h + ridge_h_gv * 0.5), vertices=6)
        gv = bpy.context.active_object
        gv.name = "GableVent"
        # Rotate to face outward on the gable wall
        if len(edges) >= 2:
            _, gvx1, gvy1, gvx2, gvy2, _, _ = edges[1]
            gv_angle = math.atan2(gvy2 - gvy1, gvx2 - gvx1)
            gv.rotation_euler = (math.pi/2, 0, gv_angle)
        gv.data.materials.append(m_gvent)
        link(gv, collection)

    # Pilasters (flat columns on commercial facades)
    pilasters_d = deco_bw.get("pilasters", {}) if isinstance(deco_bw, dict) else {}
    if has_storefront and len(edges) > 0:
        el0_pi, pix1, piy1, pix2, piy2, pinx, piny = edges[0]
        pi_angle = math.atan2(piy2 - piy1, pix2 - pix1)
        m_pilaster = mat("Pilaster", trim_hex, 0.65)
        # Two pilasters at edges of storefront
        for side_pi in [0.15, 0.85]:
            pix_p = pix1 + (pix2-pix1) * side_pi + pinx * 0.08
            piy_p = piy1 + (piy2-piy1) * side_pi + piny * 0.08
            bpy.ops.mesh.primitive_cube_add(size=1,
                location=(pix_p, piy_p, floor_h / 2))
            pio = bpy.context.active_object
            pio.name = f"Pilaster_{side_pi}"
            pio.scale = (0.1, 0.06, floor_h / 2)
            pio.rotation_euler = (0, 0, pi_angle)
            pio.data.materials.append(m_pilaster)
            link(pio, collection)

    # Rear extension (many Kensington houses have lower rear additions)
    if random.random() > 0.6 and len(edges) >= 2:
        el1_re, rex1, rey1, rex2, rey2, renx, reny = edges[1]
        re_angle = math.atan2(rey2 - rey1, rex2 - rex1)
        re_w = random.uniform(3, 5)
        re_d = random.uniform(3, 5)
        re_h_val = h * 0.6  # lower than main building
        re_cx = (rex1 + rex2) / 2 - renx * re_d / 2  # extend behind
        re_cy = (rey1 + rey2) / 2 - reny * re_d / 2
        m_rear = mat(f"RearExt_{hex_col}", hex_col, 0.75)
        bpy.ops.mesh.primitive_cube_add(size=1, location=(re_cx, re_cy, re_h_val / 2))
        reo = bpy.context.active_object
        reo.name = "RearExtension"
        reo.scale = (re_w / 2, re_d / 2, re_h_val / 2)
        reo.rotation_euler = (0, 0, re_angle)
        reo.data.materials.append(m_rear)
        link(reo, collection)

    # Dormer on rear extension
    if random.random() > 0.7 and "gable" in roof_type:
        dm_x = cx + random.uniform(-1, 1)
        dm_y = cy + random.uniform(-2, 0)
        dm_z = h * 0.7
        m_dormer_wall = mat("DormerWall", hex_col, 0.7)
        bpy.ops.mesh.primitive_cube_add(size=1, location=(dm_x, dm_y, dm_z))
        dmo = bpy.context.active_object
        dmo.name = "RearDormer"
        dmo.scale = (0.8, 0.5, 0.6)
        dmo.data.materials.append(m_dormer_wall)
        link(dmo, collection)
        # Dormer roof
        bpy.ops.mesh.primitive_cube_add(size=1, location=(dm_x, dm_y, dm_z + 0.65))
        dmr = bpy.context.active_object
        dmr.name = "RearDormerRoof"
        dmr.scale = (0.9, 0.6, 0.05)
        dmr.rotation_euler = (0.15, 0, 0)
        dmr.data.materials.append(mat("Roof", "#4A4A4A", 0.85))
        link(dmr, collection)

    # Skylight on flat roofs
    if roof_type == "flat" and random.random() > 0.7:
        skx = cx + random.uniform(-1, 1)
        sky_p = cy + random.uniform(-1, 1)
        m_skylight = mat("Skylight", "#7090A0", 0.25)
        bpy.ops.mesh.primitive_cube_add(size=1, location=(skx, sky_p, h + 0.06))
        sk = bpy.context.active_object
        sk.name = "Skylight"
        sk.scale = (0.5, 0.5, 0.06)
        sk.data.materials.append(m_skylight)
        link(sk, collection)

    # Exterior staircase (for multi-unit buildings, metal stairs on side)
    if floors >= 3 and random.random() > 0.7 and len(edges) >= 2:
        _, esx1, esy1, esx2, esy2, esnx, esny = edges[1]
        es_angle = math.atan2(esy2 - esy1, esx2 - esx1)
        es_cx = (esx1 + esx2) / 2 + esnx * 1.0
        es_cy = (esy1 + esy2) / 2 + esny * 1.0
        m_ext_stair = mat("ExtStair", "#4A4A4A", 0.4)
        # Stringer (diagonal support)
        stair_h = h * 0.7
        stair_len = math.sqrt(stair_h**2 + 3**2)
        stair_pitch = math.atan2(stair_h, 3)
        bpy.ops.mesh.primitive_cube_add(size=1, location=(es_cx, es_cy, stair_h / 2))
        eso = bpy.context.active_object
        eso.name = "ExtStairStringer"
        eso.scale = (0.04, stair_len / 2, 0.15)
        eso.rotation_euler = (stair_pitch, 0, es_angle)
        eso.data.materials.append(m_ext_stair)
        link(eso, collection)
        # Landing platforms
        for lp_i in range(int(floors) - 1):
            lp_z = (lp_i + 1) * floor_h
            bpy.ops.mesh.primitive_cube_add(size=1,
                location=(es_cx + esnx * 0.3, es_cy + esny * 0.3, lp_z))
            lpo = bpy.context.active_object
            lpo.name = f"Landing_{lp_i}"
            lpo.scale = (0.6, 0.5, 0.03)
            lpo.rotation_euler = (0, 0, es_angle)
            lpo.data.materials.append(m_ext_stair)
            link(lpo, collection)

    # =========================================================================
    # ADVANCED FACADE DETAILS (from facade_detail, chimneys, photo_observations)
    # =========================================================================

    # Use precise chimney data when available (position, dimensions, colour)
    chimney_data = params.get("chimneys", {})
    if isinstance(chimney_data, dict) and chimney_data.get("count", 0) > 0:
        ch_count = chimney_data.get("count", 1)
        ch_w = chimney_data.get("width_m", 0.6)
        ch_d = chimney_data.get("depth_m", 0.4)
        ch_above = min(chimney_data.get("height_above_ridge_m", 0.8), 1.5)
        ch_hex = chimney_data.get("colour_hex", hex_col)
        ch_pos = chimney_data.get("position", "right_rear")
        m_chimney_detail = mat(f"ChimneyD_{ch_hex}", ch_hex, 0.75)

        for chi in range(ch_count):
            # Position based on chimney_data.position
            if "left" in ch_pos and len(edges) >= 2:
                _, chx1, chy1, chx2, chy2, chnx, chny = edges[min(2, len(edges)-1)]
                ch_t = 0.3 + chi * 0.4
            elif "right" in ch_pos and len(edges) >= 2:
                _, chx1, chy1, chx2, chy2, chnx, chny = edges[min(3, len(edges)-1)]
                ch_t = 0.3 + chi * 0.4
            elif len(edges) >= 2:
                _, chx1, chy1, chx2, chy2, chnx, chny = edges[1]
                ch_t = 0.5
            else:
                continue

            chx_p = chx1 + (chx2-chx1) * ch_t
            chy_p = chy1 + (chy2-chy1) * ch_t

            ridge_h_ch = min((max(xs)-min(xs)) * 0.35, 2.5) if "gable" in roof_type else 0
            ch_base_z = h + ridge_h_ch - 0.3
            ch_total_h = ch_above + 0.3 + ridge_h_ch * 0.3

            bpy.ops.mesh.primitive_cube_add(size=1,
                location=(chx_p, chy_p, ch_base_z + ch_total_h / 2))
            cho = bpy.context.active_object
            cho.name = f"ChimneyD_{chi}"
            cho.scale = (ch_w / 2, ch_d / 2, ch_total_h / 2)
            cho.data.materials.append(m_chimney_detail)
            link(cho, collection)

            # Chimney crown (wider cap)
            bpy.ops.mesh.primitive_cube_add(size=1,
                location=(chx_p, chy_p, ch_base_z + ch_total_h + 0.04))
            chcr = bpy.context.active_object
            chcr.name = f"ChimneyCrown_{chi}"
            chcr.scale = (ch_w / 2 + 0.05, ch_d / 2 + 0.05, 0.04)
            chcr.data.materials.append(m_chimney_detail)
            link(chcr, collection)

            # Chimney flue (small cylinder on top)
            bpy.ops.mesh.primitive_cylinder_add(radius=0.06, depth=0.15,
                location=(chx_p, chy_p, ch_base_z + ch_total_h + 0.15), vertices=8)
            chfl = bpy.context.active_object
            chfl.name = f"ChimneyFlue_{chi}"
            chfl.data.materials.append(mat("ChimneyFlue", "#5A5050", 0.7))
            link(chfl, collection)

    # Window frame colour from facade_detail (per-building frame colour)
    frame_hex = trim_hex
    wd_frames = params.get("windows_detail", [])
    if isinstance(wd_frames, list):
        for wdf in wd_frames:
            if isinstance(wdf, dict):
                wins = wdf.get("windows", [])
                if isinstance(wins, list):
                    for w_spec in wins:
                        if isinstance(w_spec, dict) and w_spec.get("frame_colour"):
                            frame_hex = w_spec["frame_colour"]
                            break
                    if frame_hex != trim_hex:
                        break

    # Recessed window reveals (shadow gap around windows for depth)
    m_reveal = mat(f"Reveal_{hex_col}", hex_col, 0.8)
    if len(edges) > 0:
        el0_rv, rvx1, rvy1, rvx2, rvy2, rvnx, rvny = edges[0]
        rv_dx, rv_dy = rvx2 - rvx1, rvy2 - rvy1
        rv_angle = math.atan2(rv_dy, rv_dx)
        win_w_rv = params.get("window_width_m", 0.9) or 0.9
        win_h_rv = params.get("window_height_m", 1.4) or 1.4
        wpf_rv = params.get("windows_per_floor", [2]) or [2]

        for fi_rv in range(min(int(floors), 4)):
            sill_rv = fi_rv * floor_h + floor_h * 0.3
            n_w_rv = wpf_rv[fi_rv] if fi_rv < len(wpf_rv) and isinstance(wpf_rv[fi_rv], (int, float)) else 2
            n_w_rv = int(n_w_rv)
            for wi_rv in range(n_w_rv):
                t_rv = (wi_rv + 1) / (n_w_rv + 1)
                rwx = rvx1 + rv_dx * t_rv + rvnx * 0.03
                rwy = rvy1 + rv_dy * t_rv + rvny * 0.02
                rwz = sill_rv + win_h_rv / 2
                # Reveal is a slightly recessed dark rectangle behind the window
                bpy.ops.mesh.primitive_cube_add(size=1, location=(rwx, rwy, rwz))
                rvo = bpy.context.active_object
                rvo.name = f"Reveal_{fi_rv}_{wi_rv}"
                rvo.scale = (win_w_rv / 2 + 0.08, 0.02, win_h_rv / 2 + 0.08)
                rvo.rotation_euler = (0, 0, rv_angle)
                rvo.data.materials.append(mat("RevealShadow", "#2A2A2A", 0.9))
                link(rvo, collection)

    # Brick quoin detail (alternating stone blocks at corners — refined)
    quoins_d = deco_bw.get("quoins", {}) if isinstance(deco_bw, dict) else {}
    if isinstance(quoins_d, dict) and quoins_d.get("present") and len(edges) > 0:
        q_hex = quoins_d.get("colour_hex", "#C0B8A0")
        q_w = (quoins_d.get("strip_width_mm", 150) or 150) / 1000
        q_proj = (quoins_d.get("projection_mm", 20) or 20) / 1000
        m_quoin_d = mat(f"QuoinD_{q_hex}", q_hex, 0.7)
        el0_q, qx1, qy1, qx2, qy2, qnx, qny = edges[0]
        q_angle = math.atan2(qy2 - qy1, qx2 - qx1)

        # Alternating quoin blocks at both corners of front facade
        for corner in [(qx1, qy1), (qx2, qy2)]:
            n_blocks = int(h / 0.35)
            for qi in range(n_blocks):
                qz = qi * 0.35 + 0.175
                block_w = q_w if qi % 2 == 0 else q_w * 0.7
                qcx = corner[0] + qnx * (0.06 + q_proj / 2)
                qcy = corner[1] + qny * (0.06 + q_proj / 2)
                bpy.ops.mesh.primitive_cube_add(size=1, location=(qcx, qcy, qz))
                qo = bpy.context.active_object
                qo.name = f"QuoinBlock_{qi}"
                qo.scale = (block_w / 2, q_proj / 2, 0.15)
                qo.rotation_euler = (0, 0, q_angle)
                qo.data.materials.append(m_quoin_d)
                link(qo, collection)

    # Storefront bulkhead (solid panel below storefront glass)
    if has_storefront and len(edges) > 0:
        el0_bh, bhx1, bhy1, bhx2, bhy2, bhnx, bhny = edges[0]
        bh_dx, bh_dy = bhx2 - bhx1, bhy2 - bhy1
        bh_angle = math.atan2(bh_dy, bh_dx)
        sf_data_bh = params.get("storefront", {})
        if isinstance(sf_data_bh, dict):
            sf_w_bh = sf_data_bh.get("width_m", el0_bh * 0.7)
        else:
            sf_w_bh = el0_bh * 0.7
        bulkhead_h = 0.5
        bhx_c = bhx1 + bh_dx * 0.5 + bhnx * 0.06
        bhy_c = bhy1 + bh_dy * 0.5 + bhny * 0.06
        m_bulkhead = mat("Bulkhead", "#3A3A3A", 0.8)
        bpy.ops.mesh.primitive_cube_add(size=1, location=(bhx_c, bhy_c, bulkhead_h / 2))
        bho = bpy.context.active_object
        bho.name = "Bulkhead"
        bho.scale = (sf_w_bh / 2, 0.08, bulkhead_h / 2)
        bho.rotation_euler = (0, 0, bh_angle)
        bho.data.materials.append(m_bulkhead)
        link(bho, collection)

    # Storefront recessed entry (indented doorway on commercial ground floor)
    if has_storefront and len(edges) > 0:
        el0_re, rex1, rey1, rex2, rey2, renx_e, reny_e = edges[0]
        re_dx, re_dy = rex2 - rex1, rey2 - rey1
        re_angle_e = math.atan2(re_dy, re_dx)
        # Dark recessed opening at center of storefront
        entry_w = 1.5
        entry_h = 2.5
        entry_d = 0.5
        rex_c = rex1 + re_dx * 0.5 + renx_e * (0.06 + entry_d / 2)
        rey_c = rey1 + re_dy * 0.5 + reny_e * (0.06 + entry_d / 2)
        m_recess = mat("RecessEntry", "#1A1A1A", 0.9)
        bpy.ops.mesh.primitive_cube_add(size=1, location=(rex_c, rey_c, entry_h / 2))
        reo_e = bpy.context.active_object
        reo_e.name = "RecessEntry"
        reo_e.scale = (entry_w / 2, entry_d / 2, entry_h / 2)
        reo_e.rotation_euler = (0, 0, re_angle_e)
        reo_e.data.materials.append(m_recess)
        link(reo_e, collection)

    # Dentil course (row of small tooth-like blocks below cornice)
    cornice_type = ""
    if isinstance(cornice_d, dict):
        cornice_type = cornice_d.get("type", "") or ""
    if ("decorative" in cornice_type or "dentil" in cornice_type) and len(edges) > 0:
        el0_dt, dtx1, dty1, dtx2, dty2, dtnx, dtny = edges[0]
        dt_dx, dt_dy = dtx2 - dtx1, dty2 - dty1
        dt_angle = math.atan2(dt_dy, dt_dx)
        co_h_dt = (cornice_d.get("height_mm", 300) or 300) / 1000
        m_dentil = mat("Dentil", trim_hex, 0.65)
        n_teeth = int(el0_dt / 0.12)
        for ti in range(n_teeth):
            t_dt = (ti + 0.5) / n_teeth
            dtx_p = dtx1 + dt_dx * t_dt + dtnx * 0.08
            dty_p = dty1 + dt_dy * t_dt + dtny * 0.08
            # Alternating teeth
            if ti % 2 == 0:
                bpy.ops.mesh.primitive_cube_add(size=1,
                    location=(dtx_p, dty_p, h - co_h_dt - 0.04))
                dto = bpy.context.active_object
                dto.name = f"Dentil_{ti}"
                dto.scale = (0.04, 0.03, 0.04)
                dto.rotation_euler = (0, 0, dt_angle)
                dto.data.materials.append(m_dentil)
                link(dto, collection)

    # Facade colour accent strip (between floors — based on bond_pattern/mortar)
    bond = ""
    if isinstance(fd_m, dict):
        bond = fd_m.get("bond_pattern", "") or ""
    if bond and len(edges) > 0 and floors >= 2:
        el0_bp, bpx1, bpy1, bpx2, bpy2, bpnx, bpny = edges[0]
        bp_angle = math.atan2(bpy2 - bpy1, bpx2 - bpx1)
        # Thin mortar-coloured line between each floor (suggests bond coursing)
        for fi_bp in range(1, int(floors)):
            bp_z = fi_bp * floor_h
            bpmx = (bpx1 + bpx2) / 2 + bpnx * 0.05
            bpmy = (bpy1 + bpy2) / 2 + bpny * 0.05
            bpy.ops.mesh.primitive_cube_add(size=1, location=(bpmx, bpmy, bp_z))
            bpo = bpy.context.active_object
            bpo.name = f"BondLine_{fi_bp}"
            bpo.scale = (el0_bp / 2, 0.015, 0.01)
            bpo.rotation_euler = (0, 0, bp_angle)
            bpo.data.materials.append(mat("MortarLine", mortar_hex_m, 0.8))
            link(bpo, collection)

    # Decorative brackets under cornice (from decorative_elements)
    brackets = deco_bw.get("gable_brackets", {}) if isinstance(deco_bw, dict) else {}
    if isinstance(brackets, dict) and brackets.get("type"):
        b_count = brackets.get("count", 4) or 4
        b_proj = (brackets.get("projection_mm", 80) or 80) / 1000
        b_h = (brackets.get("height_mm", 120) or 120) / 1000
        b_hex = brackets.get("colour_hex", trim_hex)
        m_bracket = mat(f"Bracket_{b_hex}", b_hex, 0.65)
        if len(edges) > 0:
            el0_br, brx1, bry1, brx2, bry2, brnx, brny = edges[0]
            br_angle = math.atan2(bry2 - bry1, brx2 - brx1)
            br_dx, br_dy = brx2 - brx1, bry2 - bry1
            for bi_br in range(b_count):
                t_br = (bi_br + 1) / (b_count + 1)
                brx_p = brx1 + br_dx * t_br + brnx * (0.06 + b_proj / 2)
                bry_p = bry1 + br_dy * t_br + brny * (0.06 + b_proj / 2)
                # L-shaped bracket (vertical + horizontal)
                # Vertical part
                bpy.ops.mesh.primitive_cube_add(size=1,
                    location=(brx_p, bry_p, h - b_h / 2))
                bv = bpy.context.active_object
                bv.name = f"BracketV_{bi_br}"
                bv.scale = (0.03, b_proj / 2, b_h / 2)
                bv.rotation_euler = (0, 0, br_angle)
                bv.data.materials.append(m_bracket)
                link(bv, collection)
                # Horizontal part
                bpy.ops.mesh.primitive_cube_add(size=1,
                    location=(brx_p, bry_p, h - 0.02))
                bh_o = bpy.context.active_object
                bh_o.name = f"BracketH_{bi_br}"
                bh_o.scale = (0.03, b_proj / 2, 0.02)
                bh_o.rotation_euler = (0, 0, br_angle)
                bh_o.data.materials.append(m_bracket)
                link(bh_o, collection)

    # Water table (horizontal band at top of foundation)
    if len(edges) > 0:
        m_water_table = mat("WaterTable", "#8A8A80", 0.8)
        for ei_wt in range(min(2, len(edges))):
            el_wt, wtx1, wty1, wtx2, wty2, wtnx, wtny = edges[ei_wt]
            if el_wt < 2:
                continue
            wt_angle = math.atan2(wty2 - wty1, wtx2 - wtx1)
            wtmx = (wtx1 + wtx2) / 2 + wtnx * 0.07
            wtmy = (wty1 + wty2) / 2 + wtny * 0.07
            bpy.ops.mesh.primitive_cube_add(size=1, location=(wtmx, wtmy, 0.42))
            wto = bpy.context.active_object
            wto.name = f"WaterTable_{ei_wt}"
            wto.scale = (el_wt / 2, 0.04, 0.03)
            wto.rotation_euler = (0, 0, wt_angle)
            wto.data.materials.append(m_water_table)
            link(wto, collection)

    # Ornamental shingles in gable (from decorative_elements)
    shingles = deco_bw.get("ornamental_shingles", {}) if isinstance(deco_bw, dict) else {}
    if isinstance(shingles, dict) and shingles.get("present") and "gable" in roof_type:
        sh_hex_o = shingles.get("colour_hex", "#8A6A4A")
        m_shingle = mat(f"OrnShingle_{sh_hex_o}", sh_hex_o, 0.8)
        ridge_h_sh = min((max(xs)-min(xs)) * 0.35, 2.5)
        if len(edges) >= 2:
            el1_sh, shx1, shy1, shx2, shy2, shnx_o, shny_o = edges[1]
            sh_mx = (shx1 + shx2) / 2 + shnx_o * 0.06
            sh_my = (shy1 + shy2) / 2 + shny_o * 0.06
            sh_angle_o = math.atan2(shy2 - shy1, shx2 - shx1)
            bpy.ops.mesh.primitive_cube_add(size=1,
                location=(sh_mx, sh_my, h + ridge_h_sh * 0.35))
            sho_o = bpy.context.active_object
            sho_o.name = "OrnShingle"
            sho_o.scale = (el1_sh * 0.3, 0.03, ridge_h_sh * 0.3)
            sho_o.rotation_euler = (0, 0, sh_angle_o)
            sho_o.data.materials.append(m_shingle)
            link(sho_o, collection)

    # =========================================================================
    # MICRO FACADE DETAILS
    # =========================================================================

    # Brick arched window headers (segmental arch above each window)
    arch_style = ""
    if isinstance(hcd, dict):
        era_arch = hcd.get("construction_date", "") or ""
        if "pre-1889" in era_arch.lower():
            arch_style = "segmental"
        elif "1890" in era_arch or "1904" in era_arch:
            arch_style = "flat"
    if arch_style == "segmental" and len(edges) > 0:
        el0_ar, arx1, ary1, arx2, ary2, arnx, arny = edges[0]
        ar_dx, ar_dy = arx2 - arx1, ary2 - ary1
        ar_angle = math.atan2(ar_dy, ar_dx)
        m_arch_header = mat(f"ArchHeader_{hex_col}", hex_col, 0.6)
        win_w_ar = params.get("window_width_m", 0.9) or 0.9
        win_h_ar = params.get("window_height_m", 1.4) or 1.4
        wpf_ar = params.get("windows_per_floor", [2]) or [2]
        for fi_ar in range(min(int(floors), 3)):
            sill_ar = fi_ar * floor_h + floor_h * 0.3
            wz_ar = sill_ar + win_h_ar
            n_w_ar = wpf_ar[fi_ar] if fi_ar < len(wpf_ar) and isinstance(wpf_ar[fi_ar], (int, float)) else 2
            for wi_ar in range(int(n_w_ar)):
                t_ar = (wi_ar + 1) / (int(n_w_ar) + 1)
                awx = arx1 + ar_dx * t_ar + arnx * 0.05
                awy = ary1 + ar_dy * t_ar + arny * 0.05
                # Segmental arch = shallow curved header
                bpy.ops.mesh.primitive_cylinder_add(radius=win_w_ar / 2 + 0.05,
                    depth=0.04, location=(awx, awy, wz_ar + 0.04), vertices=12)
                aro = bpy.context.active_object
                aro.name = f"ArchHead_{fi_ar}_{wi_ar}"
                aro.scale = (1, 0.3, 1)
                aro.rotation_euler = (math.pi/2, 0, ar_angle)
                aro.data.materials.append(m_arch_header)
                link(aro, collection)

    # Keystone accent (center stone in arch above windows/doors)
    if arch_style and len(edges) > 0:
        el0_ks, ksx1, ksy1, ksx2, ksy2, ksnx, ksny = edges[0]
        ks_dx, ks_dy = ksx2 - ksx1, ksy2 - ksy1
        ks_angle = math.atan2(ks_dy, ks_dx)
        m_keystone = mat("Keystone", "#C0B8A0", 0.7)
        win_h_ks = params.get("window_height_m", 1.4) or 1.4
        # Keystone above door
        kst = 0.5
        ksx_p = ksx1 + ks_dx * kst + ksnx * 0.07
        ksy_p = ksy1 + ks_dy * kst + ksny * 0.07
        door_h_ks = 2.3
        bpy.ops.mesh.primitive_cube_add(size=1, location=(ksx_p, ksy_p, door_h_ks + 0.08))
        kso = bpy.context.active_object
        kso.name = "Keystone"
        kso.scale = (0.08, 0.04, 0.1)
        kso.rotation_euler = (0, 0, ks_angle)
        kso.data.materials.append(m_keystone)
        link(kso, collection)

    # Drip moulding (projecting ledge above each window to shed rain)
    if len(edges) > 0 and floors >= 2:
        el0_dm, dmx1, dmy1, dmx2, dmy2, dmnx, dmny = edges[0]
        dm_dx, dm_dy = dmx2 - dmx1, dmy2 - dmy1
        dm_angle = math.atan2(dm_dy, dm_dx)
        m_drip = mat("DripMould", trim_hex, 0.65)
        win_w_dm = params.get("window_width_m", 0.9) or 0.9
        win_h_dm = params.get("window_height_m", 1.4) or 1.4
        wpf_dm = params.get("windows_per_floor", [2]) or [2]
        for fi_dm in range(1, min(int(floors), 3)):
            sill_dm = fi_dm * floor_h + floor_h * 0.3
            wz_dm = sill_dm + win_h_dm
            n_w_dm = wpf_dm[fi_dm] if fi_dm < len(wpf_dm) and isinstance(wpf_dm[fi_dm], (int, float)) else 2
            for wi_dm in range(int(n_w_dm)):
                t_dm = (wi_dm + 1) / (int(n_w_dm) + 1)
                dwx = dmx1 + dm_dx * t_dm + dmnx * 0.1
                dwy = dmy1 + dm_dy * t_dm + dmny * 0.1
                bpy.ops.mesh.primitive_cube_add(size=1,
                    location=(dwx, dwy, wz_dm + 0.06))
                dmo_o = bpy.context.active_object
                dmo_o.name = f"DripMould_{fi_dm}_{wi_dm}"
                dmo_o.scale = (win_w_dm / 2 + 0.1, 0.05, 0.02)
                dmo_o.rotation_euler = (0, 0, dm_angle)
                dmo_o.data.materials.append(m_drip)
                link(dmo_o, collection)

    # Pilaster capital (decorative top of pilaster on commercial buildings)
    if has_storefront and len(edges) > 0:
        el0_pc, pcx1, pcy1, pcx2, pcy2, pcnx, pcny = edges[0]
        pc_angle = math.atan2(pcy2 - pcy1, pcx2 - pcx1)
        m_capital = mat("Capital", trim_hex, 0.6)
        for side_pc in [0.15, 0.85]:
            pcx_p = pcx1 + (pcx2-pcx1) * side_pc + pcnx * 0.09
            pcy_p = pcy1 + (pcy2-pcy1) * side_pc + pcny * 0.09
            bpy.ops.mesh.primitive_cube_add(size=1,
                location=(pcx_p, pcy_p, floor_h - 0.06))
            pco = bpy.context.active_object
            pco.name = f"Capital_{side_pc}"
            pco.scale = (0.14, 0.08, 0.06)
            pco.rotation_euler = (0, 0, pc_angle)
            pco.data.materials.append(m_capital)
            link(pco, collection)

    # Continuous sill band (stone/trim band connecting all window sills on a floor)
    if floors >= 2 and len(edges) > 0:
        el0_sb, sbx1, sby1, sbx2, sby2, sbnx, sbny = edges[0]
        sb_angle = math.atan2(sby2 - sby1, sbx2 - sbx1)
        m_sill_band = mat("SillBand", trim_hex, 0.65)
        win_h_sb = params.get("window_height_m", 1.4) or 1.4
        for fi_sb in range(1, min(int(floors), 3)):
            sill_sb_z = fi_sb * floor_h + floor_h * 0.3
            sbmx = (sbx1 + sbx2) / 2 + sbnx * 0.08
            sbmy = (sby1 + sby2) / 2 + sbny * 0.08
            bpy.ops.mesh.primitive_cube_add(size=1,
                location=(sbmx, sbmy, sill_sb_z - 0.02))
            sbo = bpy.context.active_object
            sbo.name = f"SillBand_{fi_sb}"
            sbo.scale = (el0_sb * 0.85 / 2, 0.04, 0.025)
            sbo.rotation_euler = (0, 0, sb_angle)
            sbo.data.materials.append(m_sill_band)
            link(sbo, collection)

    # Wall texture panel (subtle colour variation on large flat walls)
    if not has_storefront and len(edges) > 0 and floors >= 2:
        el0_tp, tpx1, tpy1, tpx2, tpy2, tpnx, tpny = edges[0]
        tp_angle = math.atan2(tpy2 - tpy1, tpx2 - tpx1)
        # Slightly different shade panel on upper floors
        r_c, g_c, b_c = int(hex_col[1:3], 16), int(hex_col[3:5], 16), int(hex_col[5:7], 16)
        darker = f"#{max(0,r_c-15):02x}{max(0,g_c-15):02x}{max(0,b_c-15):02x}"
        m_panel = mat(f"WallPanel_{darker}", darker, 0.72)
        tpmx = (tpx1 + tpx2) / 2 + tpnx * 0.04
        tpmy = (tpy1 + tpy2) / 2 + tpny * 0.04
        panel_h = floor_h * (floors - 1)
        bpy.ops.mesh.primitive_cube_add(size=1,
            location=(tpmx, tpmy, floor_h + panel_h / 2))
        tpo = bpy.context.active_object
        tpo.name = "WallPanel"
        tpo.scale = (el0_tp * 0.92 / 2, 0.01, panel_h / 2)
        tpo.rotation_euler = (0, 0, tp_angle)
        tpo.data.materials.append(m_panel)
        link(tpo, collection)

    # Gable finial (decorative peak ornament on gable roof)
    if "gable" in roof_type:
        ridge_h_fn = min((max(xs)-min(xs)) * 0.35, 2.5)
        m_finial = mat("Finial", trim_hex, 0.6)
        fnx = cx
        fny = cy
        # Small decorative piece at the gable peak
        bpy.ops.mesh.primitive_cone_add(radius1=0.06, depth=0.2,
            location=(fnx, fny, h + ridge_h_fn + 0.1), vertices=6)
        fn = bpy.context.active_object
        fn.name = "GableFinial"
        fn.data.materials.append(m_finial)
        link(fn, collection)

    # Threshold (stone/concrete step at door base)
    if len(edges) > 0:
        el0_th, thx1, thy1, thx2, thy2, thnx, thny = edges[0]
        th_angle = math.atan2(thy2 - thy1, thx2 - thx1)
        th_t = 0.5
        thx_p = thx1 + (thx2-thx1) * th_t + thnx * 0.08
        thy_p = thy1 + (thy2-thy1) * th_t + thny * 0.08
        m_threshold = mat("Threshold", "#A0A098", 0.85)
        bpy.ops.mesh.primitive_cube_add(size=1, location=(thx_p, thy_p, 0.02))
        tho = bpy.context.active_object
        tho.name = "Threshold"
        tho.scale = (0.6, 0.2, 0.02)
        tho.rotation_euler = (0, 0, th_angle)
        tho.data.materials.append(m_threshold)
        link(tho, collection)

    # Spandrel panel (decorative panel between floors on commercial buildings)
    if has_storefront and floors >= 2 and len(edges) > 0:
        el0_sp, spx1, spy1, spx2, spy2, spnx, spny = edges[0]
        sp_angle = math.atan2(spy2 - spy1, spx2 - spx1)
        sp_z = floor_h
        spmx = (spx1 + spx2) / 2 + spnx * 0.07
        spmy = (spy1 + spy2) / 2 + spny * 0.07
        # Decorative panel between storefront and upper floor
        sp_hex = trim_hex
        m_spandrel = mat(f"Spandrel_{sp_hex}", sp_hex, 0.65)
        bpy.ops.mesh.primitive_cube_add(size=1, location=(spmx, spmy, sp_z))
        spo = bpy.context.active_object
        spo.name = "Spandrel"
        spo.scale = (el0_sp * 0.8 / 2, 0.04, 0.15)
        spo.rotation_euler = (0, 0, sp_angle)
        spo.data.materials.append(m_spandrel)
        link(spo, collection)

    # Corner board (vertical trim at building corners)
    if facade_mat_name in ("clapboard", "siding", "wood", "paint") and len(edges) > 0:
        m_corner_board = mat("CornerBoard", trim_hex, 0.65)
        el0_cb2, cbx1_2, cby1_2, cbx2_2, cby2_2, cbnx_2, cbny_2 = edges[0]
        for corner_pt in [(cbx1_2, cby1_2), (cbx2_2, cby2_2)]:
            cpx = corner_pt[0] + cbnx_2 * 0.06
            cpy_c = corner_pt[1] + cbny_2 * 0.06
            bpy.ops.mesh.primitive_cube_add(size=1, location=(cpx, cpy_c, h / 2))
            cbo2 = bpy.context.active_object
            cbo2.name = "CornerBoard"
            cbo2.scale = (0.04, 0.04, h / 2)
            cbo2.data.materials.append(m_corner_board)
            link(cbo2, collection)

    # Stucco scoring lines (horizontal grooves on stucco facades)
    if facade_mat_name in ("stucco", "paint") and len(edges) > 0 and h > 3:
        el0_ss, ssx1, ssy1, ssx2, ssy2, ssnx, ssny = edges[0]
        ss_angle = math.atan2(ssy2 - ssy1, ssx2 - ssx1)
        m_score = mat("StuccoScore", "#9A9A90", 0.85)
        n_lines = int(h / 0.6)
        for sli in range(n_lines):
            sl_z = 0.5 + sli * 0.6
            if sl_z > h - 0.5:
                break
            slmx = (ssx1 + ssx2) / 2 + ssnx * 0.05
            slmy = (ssy1 + ssy2) / 2 + ssny * 0.05
            bpy.ops.mesh.primitive_cube_add(size=1, location=(slmx, slmy, sl_z))
            slo = bpy.context.active_object
            slo.name = f"StuccoLine_{sli}"
            slo.scale = (el0_ss / 2, 0.008, 0.005)
            slo.rotation_euler = (0, 0, ss_angle)
            slo.data.materials.append(m_score)
            link(slo, collection)

    # Clapboard lap lines (horizontal lines suggesting wood siding)
    if facade_mat_name == "clapboard" and len(edges) > 0 and h > 3:
        el0_cl, clx1, cly1, clx2, cly2, clnx, clny = edges[0]
        cl_angle = math.atan2(cly2 - cly1, clx2 - clx1)
        m_lap = mat("ClapLap", "#D0C8B8", 0.8)
        n_laps = int(h / 0.15)
        for cli in range(0, n_laps, 3):  # every 3rd line for performance
            cl_z = 0.5 + cli * 0.15
            if cl_z > h - 0.3:
                break
            clmx = (clx1 + clx2) / 2 + clnx * 0.055
            clmy = (cly1 + cly2) / 2 + clny * 0.055
            bpy.ops.mesh.primitive_cube_add(size=1, location=(clmx, clmy, cl_z))
            clo = bpy.context.active_object
            clo.name = f"ClapLap_{cli}"
            clo.scale = (el0_cl / 2, 0.008, 0.003)
            clo.rotation_euler = (0, 0, cl_angle)
            clo.data.materials.append(m_lap)
            link(clo, collection)

    # =========================================================================
    # COMMERCIAL / KENSINGTON MARKET SPECIFIC DETAILS
    # =========================================================================

    # Business name sign (coloured box with business name from context)
    biz_name = params.get("context", {}).get("business_name") if isinstance(params.get("context"), dict) else None
    if biz_name and has_storefront and len(edges) > 0:
        el0_bn, bnx1, bny1, bnx2, bny2, bnnx, bnny = edges[0]
        bn_dx, bn_dy = bnx2 - bnx1, bny2 - bny1
        bn_angle = math.atan2(bn_dy, bn_dx)
        # Large sign above storefront
        sign_w = min(el0_bn * 0.7, 4.0)
        sign_h = 0.6
        sign_z = floor_h + 0.2
        bsx = bnx1 + bn_dx * 0.5 + bnnx * 0.1
        bsy = bny1 + bn_dy * 0.5 + bnny * 0.1
        biz_colours = ["#1A3A1A", "#3A1A1A", "#1A1A3A", "#4A3A1A", "#E8E0D0",
                       "#2A4A4A", "#4A2A4A", "#2A2A2A", "#C04040", "#4040C0"]
        biz_hex = biz_colours[hash(biz_name) % len(biz_colours)]
        m_biz = mat(f"BizSign_{biz_hex}", biz_hex, 0.6)
        bpy.ops.mesh.primitive_cube_add(size=1, location=(bsx, bsy, sign_z))
        bso = bpy.context.active_object
        bso.name = "BizSign"
        bso.scale = (sign_w / 2, 0.08, sign_h / 2)
        bso.rotation_euler = (0, 0, bn_angle)
        bso.data.materials.append(m_biz)
        link(bso, collection)
        # Sign bracket (small L-shaped support)
        for sb_side in [-sign_w/2 + 0.2, sign_w/2 - 0.2]:
            sbx = bsx + math.cos(bn_angle) * sb_side
            sby = bsy + math.sin(bn_angle) * sb_side
            bpy.ops.mesh.primitive_cube_add(size=1, location=(sbx, sby, sign_z - 0.1))
            sbo = bpy.context.active_object
            sbo.name = "SignBracket"
            sbo.scale = (0.02, 0.06, 0.04)
            sbo.rotation_euler = (0, 0, bn_angle)
            sbo.data.materials.append(mat("SignBracket", "#3A3A3A", 0.5))
            link(sbo, collection)

    # Projecting blade sign (perpendicular sign sticking out from facade)
    if biz_name and has_storefront and random.random() > 0.4 and len(edges) > 0:
        el0_bs, bsx1, bsy1, bsx2, bsy2, bsnx, bsny = edges[0]
        bs_angle = math.atan2(bsy2 - bsy1, bsx2 - bsx1)
        bs_t = random.uniform(0.3, 0.7)
        psx = bsx1 + (bsx2-bsx1) * bs_t + bsnx * 0.4
        psy = bsy1 + (bsy2-bsy1) * bs_t + bsny * 0.4
        blade_hex = biz_colours[hash(biz_name + "blade") % len(biz_colours)]
        m_blade = mat(f"Blade_{blade_hex}", blade_hex, 0.6)
        bpy.ops.mesh.primitive_cube_add(size=1, location=(psx, psy, floor_h + 0.5))
        blo = bpy.context.active_object
        blo.name = "BladSign"
        blo.scale = (0.03, 0.4, 0.3)
        blo.rotation_euler = (0, 0, bs_angle)
        blo.data.materials.append(m_blade)
        link(blo, collection)
        # Mounting arm
        bpy.ops.mesh.primitive_cube_add(size=1, location=(
            bsx1 + (bsx2-bsx1)*bs_t + bsnx*0.15, bsy1 + (bsy2-bsy1)*bs_t + bsny*0.15,
            floor_h + 0.8))
        arm = bpy.context.active_object
        arm.name = "BladeArm"
        arm.scale = (0.02, 0.2, 0.02)
        arm.rotation_euler = (0, 0, bs_angle)
        arm.data.materials.append(mat("BladeArm", "#3A3A3A", 0.5))
        link(arm, collection)

    # Display window (glass showcase box projecting from storefront)
    if has_storefront and random.random() > 0.6 and len(edges) > 0:
        el0_dw, dwx1, dwy1, dwx2, dwy2, dwnx, dwny = edges[0]
        dw_dx, dw_dy = dwx2 - dwx1, dwy2 - dwy1
        dw_angle = math.atan2(dw_dy, dw_dx)
        dw_t = random.uniform(0.2, 0.4)
        dwx_p = dwx1 + dw_dx * dw_t + dwnx * 0.3
        dwy_p = dwy1 + dw_dy * dw_t + dwny * 0.3
        m_display = mat("DisplayCase", "#6A8A9A", 0.2)
        bpy.ops.mesh.primitive_cube_add(size=1, location=(dwx_p, dwy_p, 0.7))
        dwo = bpy.context.active_object
        dwo.name = "DisplayWindow"
        dwo.scale = (0.6, 0.3, 0.5)
        dwo.rotation_euler = (0, 0, dw_angle)
        dwo.data.materials.append(m_display)
        link(dwo, collection)

    # Roll-up security gate (metal grid over storefront — some shops)
    if has_storefront and random.random() > 0.85 and len(edges) > 0:
        el0_sg, sgx1, sgy1, sgx2, sgy2, sgnx, sgny = edges[0]
        sg_dx, sg_dy = sgx2 - sgx1, sgy2 - sgy1
        sg_angle = math.atan2(sg_dy, sg_dx)
        sf_data_sg = params.get("storefront", {})
        sg_w = sf_data_sg.get("width_m", el0_sg * 0.7) if isinstance(sf_data_sg, dict) else el0_sg * 0.7
        sgx_c = sgx1 + sg_dx * 0.5 + sgnx * 0.04
        sgy_c = sgy1 + sg_dy * 0.5 + sgny * 0.04
        m_gate = mat("SecurityGate", "#6A6A6A", 0.4)
        # Gate housing (box above storefront)
        bpy.ops.mesh.primitive_cube_add(size=1, location=(sgx_c, sgy_c, floor_h + 0.1))
        gho = bpy.context.active_object
        gho.name = "GateHousing"
        gho.scale = (sg_w / 2, 0.08, 0.1)
        gho.rotation_euler = (0, 0, sg_angle)
        gho.data.materials.append(m_gate)
        link(gho, collection)

    # Outdoor merchandise display (racks/tables in front of shop)
    if has_storefront and random.random() > 0.5 and len(edges) > 0:
        el0_md, mdx1, mdy1, mdx2, mdy2, mdnx, mdny = edges[0]
        md_dx, md_dy = mdx2 - mdx1, mdy2 - mdy1
        md_angle = math.atan2(md_dy, md_dx)
        mdx_c = mdx1 + md_dx * random.uniform(0.3, 0.7) + mdnx * 2.0
        mdy_c = mdy1 + md_dy * random.uniform(0.3, 0.7) + mdny * 2.0
        m_rack = mat("DisplayRack", "#8A7050", 0.8)
        bpy.ops.mesh.primitive_cube_add(size=1, location=(mdx_c, mdy_c, 0.5))
        mdo = bpy.context.active_object
        mdo.name = "MerchDisplay"
        mdo.scale = (0.6, 0.3, 0.5)
        mdo.rotation_euler = (0, 0, md_angle + random.uniform(-0.2, 0.2))
        mdo.data.materials.append(m_rack)
        link(mdo, collection)

    # A-frame sandwich board (advertising sign on sidewalk)
    if has_storefront and random.random() > 0.4 and len(edges) > 0:
        el0_af, afx1, afy1, afx2, afy2, afnx, afny = edges[0]
        af_dx, af_dy = afx2 - afx1, afy2 - afy1
        af_angle = math.atan2(af_dy, af_dx)
        afx_c = afx1 + af_dx * 0.6 + afnx * 2.5
        afy_c = afy1 + af_dy * 0.6 + afny * 2.5
        board_colours = ["#E8E0D0", "#2A2A2A", "#4A2A1A", "#1A4A1A"]
        m_board = mat(f"AFrame_{random.choice(board_colours)}", random.choice(board_colours), 0.7)
        # Two angled panels
        for af_side in [-0.02, 0.02]:
            bpy.ops.mesh.primitive_cube_add(size=1,
                location=(afx_c + afnx * af_side * 10, afy_c + afny * af_side * 10, 0.35))
            afo = bpy.context.active_object
            afo.name = "AFrame"
            afo.scale = (0.3, 0.02, 0.35)
            tilt = 0.08 if af_side > 0 else -0.08
            afo.rotation_euler = (0, tilt, af_angle)
            afo.data.materials.append(m_board)
            link(afo, collection)

    # Fruit/produce crates (Kensington Market specialty — stacked boxes outside shops)
    biz_cat = params.get("context", {}).get("business_category", "") if isinstance(params.get("context"), dict) else ""
    if has_storefront and ("food" in str(biz_cat).lower() or "grocery" in str(biz_cat).lower() or
                           "produce" in str(biz_cat).lower() or "market" in str(biz_name or "").lower() or
                           random.random() > 0.8) and len(edges) > 0:
        el0_cr, crx1, cry1, crx2, cry2, crnx, crny = edges[0]
        cr_dx, cr_dy = crx2 - crx1, cry2 - cry1
        cr_angle = math.atan2(cr_dy, cr_dx)
        crx_c = crx1 + cr_dx * 0.3 + crnx * 1.5
        cry_c = cry1 + cr_dy * 0.3 + crny * 1.5
        crate_colours = ["#8A6A3A", "#6A5A2A", "#9A7A4A"]
        for ci_cr in range(random.randint(2, 5)):
            cx_cr = crx_c + math.cos(cr_angle) * ci_cr * 0.45
            cy_cr = cry_c + math.sin(cr_angle) * ci_cr * 0.45
            stack_h = random.randint(1, 3)
            for si_cr in range(stack_h):
                m_crate = mat(f"Crate_{random.choice(crate_colours)}",
                              random.choice(crate_colours), 0.85)
                bpy.ops.mesh.primitive_cube_add(size=1,
                    location=(cx_cr, cy_cr, 0.15 + si_cr * 0.3))
                cro = bpy.context.active_object
                cro.name = f"Crate_{ci_cr}_{si_cr}"
                cro.scale = (0.2, 0.15, 0.12)
                cro.rotation_euler = (0, 0, cr_angle + random.uniform(-0.1, 0.1))
                cro.data.materials.append(m_crate)
                link(cro, collection)

    # String lights (decorative lights between buildings — Kensington vibe)
    if has_storefront and random.random() > 0.6 and len(edges) > 0:
        el0_sl, slx1, sly1, slx2, sly2, slnx, slny = edges[0]
        sl_dx, sl_dy = slx2 - slx1, sly2 - sly1
        sl_angle = math.atan2(sl_dy, sl_dx)
        m_string_wire = mat("StringWire", "#2A2A2A", 0.5)
        m_string_bulb = mat("StringBulb", "#F0E8A0", 0.3)
        # Wire from one side of storefront to the other, with sag
        n_bulbs = max(3, int(el0_sl / 0.5))
        for sli in range(n_bulbs):
            t_sl = sli / max(n_bulbs - 1, 1)
            sag = -0.3 * math.sin(t_sl * math.pi)  # parabolic sag
            slx_p = slx1 + sl_dx * t_sl + slnx * 1.5
            sly_p = sly1 + sl_dy * t_sl + slny * 1.5
            slz = floor_h - 0.3 + sag
            # Small bulb
            bpy.ops.mesh.primitive_uv_sphere_add(radius=0.03,
                location=(slx_p, sly_p, slz), segments=4, ring_count=3)
            slo = bpy.context.active_object
            slo.name = f"Bulb_{sli}"
            slo.data.materials.append(m_string_bulb)
            link(slo, collection)

    # Plywood hoarding / construction barrier (on some vacant/under renovation)
    condition = params.get("condition", "")
    if condition in ("poor", "vacant") and len(edges) > 0:
        el0_hw, hwx1, hwy1, hwx2, hwy2, hwnx, hwny = edges[0]
        hw_angle = math.atan2(hwy2 - hwy1, hwx2 - hwx1)
        hmx = (hwx1 + hwx2) / 2 + hwnx * 0.5
        hmy = (hwy1 + hwy2) / 2 + hwny * 0.5
        m_plywood = mat("Plywood", "#C0A878", 0.9)
        bpy.ops.mesh.primitive_cube_add(size=1, location=(hmx, hmy, 1.2))
        hwo = bpy.context.active_object
        hwo.name = "Hoarding"
        hwo.scale = (el0_hw * 0.8 / 2, 0.03, 1.2)
        hwo.rotation_euler = (0, 0, hw_angle)
        hwo.data.materials.append(m_plywood)
        link(hwo, collection)

    # Graffiti tag (small coloured rectangle on side wall — common in Kensington)
    po_graf = params.get("photo_observations", {})
    if isinstance(po_graf, dict) and po_graf.get("graffiti") and len(edges) >= 2:
        _, grx1, gry1, grx2, gry2, grnx, grny = edges[1]
        gr_angle = math.atan2(gry2 - gry1, grx2 - grx1) if abs(grx2-grx1) > 0.01 else 0
        gr_angle = math.atan2(gry2 - gry1, grx2 - grx1)
        grx_c = (grx1 + grx2) / 2 + grnx * 0.05
        gry_c = (gry1 + gry2) / 2 + grny * 0.05
        graf_colours = ["#CC4466", "#44CC88", "#4488CC", "#CCAA44", "#AA44CC",
                        "#FF6644", "#44AAAA", "#CC8844"]
        for gi_gr in range(random.randint(1, 3)):
            g_hex = random.choice(graf_colours)
            gx = grx_c + random.uniform(-1.5, 1.5)
            gy = gry_c + random.uniform(-1.5, 1.5)
            gz = random.uniform(0.5, h * 0.6)
            m_graf = mat(f"Graf_{g_hex}", g_hex, 0.7)
            bpy.ops.mesh.primitive_cube_add(size=1, location=(gx, gy, gz))
            gro = bpy.context.active_object
            gro.name = f"Graffiti_{gi_gr}"
            gro.scale = (random.uniform(0.3, 1.0), 0.015, random.uniform(0.2, 0.6))
            gro.rotation_euler = (0, 0, gr_angle)
            gro.data.materials.append(m_graf)
            link(gro, collection)

    # Vintage/antique shop clutter (Kensington is full of vintage shops)
    if has_storefront and "vintage" in str(biz_name or "").lower() and len(edges) > 0:
        el0_vt, vtx1, vty1, vtx2, vty2, vtnx, vtny = edges[0]
        vt_angle = math.atan2(vty2 - vty1, vtx2 - vtx1)
        m_junk = mat("VintageJunk", "#8A6A4A", 0.8)
        for vi in range(random.randint(3, 7)):
            vx = vtx1 + (vtx2-vtx1) * random.uniform(0.1, 0.9) + vtnx * random.uniform(1, 3)
            vy = vty1 + (vty2-vty1) * random.uniform(0.1, 0.9) + vtny * random.uniform(1, 3)
            vz = random.uniform(0, 0.5)
            bpy.ops.mesh.primitive_cube_add(size=1, location=(vx, vy, vz + 0.1))
            vto = bpy.context.active_object
            vto.name = f"VintageItem_{vi}"
            vto.scale = (random.uniform(0.1, 0.3), random.uniform(0.1, 0.2), random.uniform(0.1, 0.3))
            vto.rotation_euler = (random.uniform(-0.2, 0.2), random.uniform(-0.2, 0.2), random.uniform(0, 6.28))
            vto.data.materials.append(m_junk)
            link(vto, collection)

    # Hanging baskets / planters (on commercial facade brackets)
    if has_storefront and random.random() > 0.5 and len(edges) > 0:
        el0_hb, hbx1, hby1, hbx2, hby2, hbnx, hbny = edges[0]
        hb_dx, hb_dy = hbx2 - hbx1, hby2 - hby1
        hb_angle = math.atan2(hb_dy, hb_dx)
        m_basket = mat("HangBasket", "#6A5A3A", 0.8)
        m_plant_hb = mat("BasketPlant", "#3A5A2A", 0.8)
        n_baskets = random.randint(1, 3)
        for hbi in range(n_baskets):
            hb_t = (hbi + 1) / (n_baskets + 1)
            hbx_p = hbx1 + hb_dx * hb_t + hbnx * 0.2
            hby_p = hby1 + hb_dy * hb_t + hbny * 0.2
            # Bracket
            bpy.ops.mesh.primitive_cube_add(size=1, location=(hbx_p, hby_p, floor_h + 0.3))
            hbo = bpy.context.active_object
            hbo.name = f"BasketBracket_{hbi}"
            hbo.scale = (0.02, 0.15, 0.02)
            hbo.rotation_euler = (0, 0, hb_angle)
            hbo.data.materials.append(mat("BasketBracketM", "#3A3A3A", 0.5))
            link(hbo, collection)
            # Basket
            bpy.ops.mesh.primitive_uv_sphere_add(radius=0.15,
                location=(hbx_p + hbnx * 0.15, hby_p + hbny * 0.15, floor_h + 0.1),
                segments=6, ring_count=4)
            hbp = bpy.context.active_object
            hbp.name = f"Basket_{hbi}"
            hbp.data.materials.append(m_basket)
            link(hbp, collection)
            # Plant in basket
            bpy.ops.mesh.primitive_uv_sphere_add(radius=0.18,
                location=(hbx_p + hbnx * 0.15, hby_p + hbny * 0.15, floor_h + 0.2),
                segments=4, ring_count=3)
            hbpl = bpy.context.active_object
            hbpl.name = f"BasketPlant_{hbi}"
            hbpl.scale = (1, 1, 0.6)
            hbpl.data.materials.append(m_plant_hb)
            link(hbpl, collection)

    # Canopy / retractable awning frame (metal frame over storefront)
    if has_storefront and random.random() > 0.5 and len(edges) > 0:
        el0_cf, cfx1, cfy1, cfx2, cfy2, cfnx, cfny = edges[0]
        cf_dx, cf_dy = cfx2 - cfx1, cfy2 - cfy1
        cf_angle = math.atan2(cf_dy, cf_dx)
        sf_w_cf = min(el0_cf * 0.7, 4.0)
        cfx_c = cfx1 + cf_dx * 0.5 + cfnx * 0.8
        cfy_c = cfy1 + cf_dy * 0.5 + cfny * 0.8
        m_frame_aw = mat("AwningFrame", "#5A5A5A", 0.4)
        # Two side arms
        for arm_side in [-sf_w_cf/2, sf_w_cf/2]:
            ax_cf = cfx_c + math.cos(cf_angle) * arm_side
            ay_cf = cfy_c + math.sin(cf_angle) * arm_side
            bpy.ops.mesh.primitive_cube_add(size=1, location=(ax_cf, ay_cf, floor_h - 0.3))
            afo_cf = bpy.context.active_object
            afo_cf.name = "AwFrame"
            afo_cf.scale = (0.02, 0.5, 0.02)
            afo_cf.rotation_euler = (0.3, 0, cf_angle)
            afo_cf.data.materials.append(m_frame_aw)
            link(afo_cf, collection)

    # Rooftop antenna / cell tower equipment
    if random.random() > 0.9 and h > 8:
        m_antenna = mat("Antenna", "#8A8A8A", 0.4)
        ant_x = cx + random.uniform(-1, 1)
        ant_y = cy + random.uniform(-1, 1)
        bpy.ops.mesh.primitive_cylinder_add(radius=0.03, depth=2.0,
            location=(ant_x, ant_y, h + 1.0), vertices=6)
        ant = bpy.context.active_object
        ant.name = "Antenna"
        ant.data.materials.append(m_antenna)
        link(ant, collection)
        # Cross pieces
        for ant_h_off in [0.5, 1.0, 1.5]:
            bpy.ops.mesh.primitive_cube_add(size=1,
                location=(ant_x, ant_y, h + ant_h_off))
            antc = bpy.context.active_object
            antc.name = "AntennaCross"
            antc.scale = (0.3, 0.02, 0.02)
            antc.data.materials.append(m_antenna)
            link(antc, collection)

    # Exhaust fan / ventilation hood (on restaurant side walls)
    if has_storefront and "food" in str(biz_cat).lower() and len(edges) >= 2:
        _, vhx1, vhy1, vhx2, vhy2, vhnx, vhny = edges[1]
        vh_angle = math.atan2(vhy2 - vhy1, vhx2 - vhx1)
        vhx_c = (vhx1 + vhx2) / 2 + vhnx * 0.2
        vhy_c = (vhy1 + vhy2) / 2 + vhny * 0.2
        m_vent_hood = mat("VentHood", "#6A6A6A", 0.5)
        bpy.ops.mesh.primitive_cube_add(size=1, location=(vhx_c, vhy_c, h * 0.7))
        vho = bpy.context.active_object
        vho.name = "VentHood"
        vho.scale = (0.3, 0.2, 0.3)
        vho.rotation_euler = (0, 0, vh_angle)
        vho.data.materials.append(m_vent_hood)
        link(vho, collection)
        # Duct pipe going up
        bpy.ops.mesh.primitive_cylinder_add(radius=0.1, depth=h * 0.3,
            location=(vhx_c, vhy_c, h * 0.85), vertices=8)
        vhd = bpy.context.active_object
        vhd.name = "VentDuct"
        vhd.data.materials.append(m_vent_hood)
        link(vhd, collection)

    # Residential front patio furniture (tables/chairs)
    if not has_storefront and random.random() > 0.7 and params.get("porch_present") and len(edges) > 0:
        el0_pf, pfx1, pfy1, pfx2, pfy2, pfnx, pfny = edges[0]
        pf_angle = math.atan2(pfy2 - pfy1, pfx2 - pfx1)
        pfx_c = pfx1 + (pfx2-pfx1) * 0.5 + pfnx * 1.5
        pfy_c = pfy1 + (pfy2-pfy1) * 0.5 + pfny * 1.5
        m_patio_furn = mat("PatioFurn", "#E0D8C8", 0.7)
        # Small table
        bpy.ops.mesh.primitive_cylinder_add(radius=0.3, depth=0.03,
            location=(pfx_c, pfy_c, 0.55), vertices=8)
        pft = bpy.context.active_object
        pft.name = "PatioTable"
        pft.data.materials.append(m_patio_furn)
        link(pft, collection)
        # Table leg
        bpy.ops.mesh.primitive_cylinder_add(radius=0.03, depth=0.55,
            location=(pfx_c, pfy_c, 0.275), vertices=6)
        pfl = bpy.context.active_object
        pfl.name = "TableLeg"
        pfl.data.materials.append(m_patio_furn)
        link(pfl, collection)
        # Two chairs
        for ch_off in [-0.5, 0.5]:
            chx = pfx_c + math.cos(pf_angle) * ch_off
            chy = pfy_c + math.sin(pf_angle) * ch_off
            bpy.ops.mesh.primitive_cube_add(size=1, location=(chx, chy, 0.35))
            cho_pf = bpy.context.active_object
            cho_pf.name = "Chair"
            cho_pf.scale = (0.2, 0.2, 0.02)
            cho_pf.data.materials.append(m_patio_furn)
            link(cho_pf, collection)
            # Chair back
            bpy.ops.mesh.primitive_cube_add(size=1, location=(chx - pfnx*0.1, chy - pfny*0.1, 0.55))
            chb = bpy.context.active_object
            chb.name = "ChairBack"
            chb.scale = (0.2, 0.02, 0.12)
            chb.rotation_euler = (0, 0, pf_angle)
            chb.data.materials.append(m_patio_furn)
            link(chb, collection)

    # Security camera (on commercial buildings)
    if has_storefront and random.random() > 0.6 and len(edges) > 0:
        el0_cam, camx1, camy1, camx2, camy2, camnx, camny = edges[0]
        cam_angle = math.atan2(camy2 - camy1, camx2 - camx1)
        cam_t = random.choice([0.1, 0.9])
        camx_p = camx1 + (camx2-camx1) * cam_t + camnx * 0.12
        camy_p = camy1 + (camy2-camy1) * cam_t + camny * 0.12
        m_camera = mat("SecurityCam", "#2A2A2A", 0.5)
        # Mounting bracket
        bpy.ops.mesh.primitive_cube_add(size=1, location=(camx_p, camy_p, floor_h - 0.2))
        camb = bpy.context.active_object
        camb.name = "CamBracket"
        camb.scale = (0.03, 0.12, 0.03)
        camb.rotation_euler = (0, 0, cam_angle)
        camb.data.materials.append(m_camera)
        link(camb, collection)
        # Camera body
        bpy.ops.mesh.primitive_cube_add(size=1,
            location=(camx_p + camnx*0.12, camy_p + camny*0.12, floor_h - 0.2))
        camc = bpy.context.active_object
        camc.name = "CamBody"
        camc.scale = (0.04, 0.06, 0.04)
        camc.rotation_euler = (0, 0.3, cam_angle)
        camc.data.materials.append(m_camera)
        link(camc, collection)

    # Doorbell / intercom panel
    if len(edges) > 0:
        el0_db, dbx1_i, dby1_i, dbx2_i, dby2_i, dbnx_i, dbny_i = edges[0]
        db_angle_i = math.atan2(dby2_i - dby1_i, dbx2_i - dbx1_i)
        db_t_i = 0.43
        dbx_p = dbx1_i + (dbx2_i-dbx1_i) * db_t_i + dbnx_i * 0.06
        dby_p = dby1_i + (dby2_i-dby1_i) * db_t_i + dbny_i * 0.06
        m_intercom = mat("Intercom", "#C0C0C0", 0.5)
        bpy.ops.mesh.primitive_cube_add(size=1, location=(dbx_p, dby_p, 1.3))
        dbo_i = bpy.context.active_object
        dbo_i.name = "Intercom"
        dbo_i.scale = (0.05, 0.015, 0.08)
        dbo_i.rotation_euler = (0, 0, db_angle_i)
        dbo_i.data.materials.append(m_intercom)
        link(dbo_i, collection)

    # Storefront window decals / stickers (coloured bands on glass)
    if has_storefront and random.random() > 0.4 and len(edges) > 0:
        el0_dc, dcx1, dcy1, dcx2, dcy2, dcnx, dcny = edges[0]
        dc_dx, dc_dy = dcx2 - dcx1, dcy2 - dcy1
        dc_angle = math.atan2(dc_dy, dc_dx)
        sf_d = params.get("storefront", {})
        dc_w = sf_d.get("width_m", el0_dc * 0.5) if isinstance(sf_d, dict) else el0_dc * 0.5
        dcx_c = dcx1 + dc_dx * 0.5 + dcnx * 0.12
        dcy_c = dcy1 + dc_dy * 0.5 + dcny * 0.12
        decal_colours = ["#E8E0D0", "#FFD700", "#FF4444", "#44FF44", "#4444FF"]
        dc_hex = random.choice(decal_colours)
        m_decal = mat(f"Decal_{dc_hex}", dc_hex, 0.4)
        # Horizontal stripe on window
        bpy.ops.mesh.primitive_cube_add(size=1, location=(dcx_c, dcy_c, 1.0))
        dco = bpy.context.active_object
        dco.name = "WinDecal"
        dco.scale = (dc_w * 0.6 / 2, 0.005, 0.08)
        dco.rotation_euler = (0, 0, dc_angle)
        dco.data.materials.append(m_decal)
        link(dco, collection)

    # Visible interior light (warm glow visible through windows at night)
    if random.random() > 0.7 and len(edges) > 0:
        el0_il, ilx1, ily1, ilx2, ily2, ilnx, ilny = edges[0]
        il_angle = math.atan2(ily2 - ily1, ilx2 - ilx1)
        ilx_c = (ilx1 + ilx2) / 2
        ily_c = (ily1 + ily2) / 2
        m_interior = mat("InteriorGlow", "#F0E8C0", 0.3)
        # Warm panel behind window (simulates interior light)
        bpy.ops.mesh.primitive_cube_add(size=1, location=(ilx_c, ily_c, floor_h * 0.6))
        ilo = bpy.context.active_object
        ilo.name = "InteriorLight"
        ilo.scale = (el0_il * 0.6 / 2, 0.01, floor_h * 0.4)
        ilo.rotation_euler = (0, 0, il_angle)
        ilo.data.materials.append(m_interior)
        link(ilo, collection)

    # Window air conditioning drip tray / bracket
    if random.random() > 0.8 and floors >= 2 and len(edges) > 0:
        el0_at, atx1, aty1, atx2, aty2, atnx, atny = edges[0]
        at_angle = math.atan2(aty2 - aty1, atx2 - atx1)
        at_t = random.uniform(0.2, 0.8)
        atx_p = atx1 + (atx2-atx1) * at_t + atnx * 0.15
        aty_p = aty1 + (aty2-aty1) * at_t + atny * 0.15
        m_ac_bracket = mat("ACBracket", "#6A6A6A", 0.5)
        # L-shaped bracket under AC
        bpy.ops.mesh.primitive_cube_add(size=1,
            location=(atx_p, aty_p, floor_h + floor_h * 0.3))
        ato = bpy.context.active_object
        ato.name = "ACBracket"
        ato.scale = (0.3, 0.04, 0.03)
        ato.rotation_euler = (0, 0, at_angle)
        ato.data.materials.append(m_ac_bracket)
        link(ato, collection)

    # Newspaper box stand (at commercial doorways)
    if has_storefront and random.random() > 0.7 and len(edges) > 0:
        el0_nb, nbx1, nby1, nbx2, nby2, nbnx, nbny = edges[0]
        nb_angle = math.atan2(nby2 - nby1, nbx2 - nbx1)
        nbx_c = nbx1 + (nbx2-nbx1) * 0.85 + nbnx * 1.5
        nby_c = nby1 + (nby2-nby1) * 0.85 + nbny * 1.5
        nb_colours = ["#CC2222", "#2222CC", "#22CC22", "#CCCC22"]
        m_nb = mat(f"NewsStand_{random.choice(nb_colours)}", random.choice(nb_colours), 0.6)
        bpy.ops.mesh.primitive_cube_add(size=1, location=(nbx_c, nby_c, 0.5))
        nbo = bpy.context.active_object
        nbo.name = "NewsStand"
        nbo.scale = (0.2, 0.15, 0.5)
        nbo.rotation_euler = (0, 0, nb_angle)
        nbo.data.materials.append(m_nb)
        link(nbo, collection)

    # Gutter downspout elbow (bottom bend where downspout meets ground)
    if len(edges) >= 2:
        for dp_ei in range(min(2, len(edges))):
            el_dp2, dpx1_2, dpy1_2, dpx2_2, dpy2_2, dpnx2, dpny2 = edges[dp_ei]
            for dp_corner2 in [(dpx1_2, dpy1_2), (dpx2_2, dpy2_2)]:
                dpx_e = dp_corner2[0] + dpnx2 * 0.12
                dpy_e = dp_corner2[1] + dpny2 * 0.12
                m_elbow = mat("DownspoutElbow", "#4A4A4A", 0.5)
                bpy.ops.mesh.primitive_cube_add(size=1, location=(dpx_e, dpy_e, 0.15))
                elo = bpy.context.active_object
                elo.name = "DSElbow"
                elo.scale = (0.04, 0.06, 0.04)
                elo.data.materials.append(m_elbow)
                link(elo, collection)

    # Chimney flashing / base collar
    if isinstance(chimney_data, dict) and chimney_data.get("count", 0) > 0 and len(edges) >= 2:
        _, chfx1, chfy1, chfx2, chfy2, chfnx, chfny = edges[1]
        ch_t_f = 0.5
        chfx_p = chfx1 + (chfx2-chfx1) * ch_t_f
        chfy_p = chfy1 + (chfy2-chfy1) * ch_t_f
        ch_w_f = chimney_data.get("width_m", 0.6)
        ch_d_f = chimney_data.get("depth_m", 0.4)
        m_ch_flash = mat("ChimneyFlash", "#707070", 0.4)
        bpy.ops.mesh.primitive_cube_add(size=1, location=(chfx_p, chfy_p, h + 0.02))
        chfo = bpy.context.active_object
        chfo.name = "ChFlash"
        chfo.scale = (ch_w_f/2 + 0.08, ch_d_f/2 + 0.08, 0.03)
        chfo.data.materials.append(m_ch_flash)
        link(chfo, collection)

    # Window flower box with flowers (more detailed than window planter)
    if random.random() > 0.75 and len(edges) > 0:
        el0_fb2, fbx1_2, fby1_2, fbx2_2, fby2_2, fbnx_2, fbny_2 = edges[0]
        fb_dx2 = fbx2_2 - fbx1_2
        fb_dy2 = fby2_2 - fby1_2
        fb_angle2 = math.atan2(fb_dy2, fb_dx2)
        win_w_fb2 = params.get("window_width_m", 0.9) or 0.9
        # Pick a random 2nd floor window
        fb_t2 = random.uniform(0.2, 0.8)
        fbx_p2 = fbx1_2 + fb_dx2 * fb_t2 + fbnx_2 * 0.12
        fby_p2 = fby1_2 + fb_dy2 * fb_t2 + fbny_2 * 0.12
        sill_fb2 = floor_h + floor_h * 0.25 if floors >= 2 else floor_h * 0.25
        # Box
        m_fbox = mat("FlowerBox", "#5A4A2A", 0.8)
        bpy.ops.mesh.primitive_cube_add(size=1, location=(fbx_p2, fby_p2, sill_fb2 - 0.06))
        fbo2 = bpy.context.active_object
        fbo2.name = "FlowerBox2"
        fbo2.scale = (win_w_fb2 * 0.7 / 2, 0.08, 0.06)
        fbo2.rotation_euler = (0, 0, fb_angle2)
        fbo2.data.materials.append(m_fbox)
        link(fbo2, collection)
        # Flowers (3-5 small coloured spheres)
        flower_hex2 = ["#FF6688", "#FFAA22", "#FF4444", "#AA44FF", "#44AAFF"]
        for ffi in range(random.randint(3, 5)):
            ff_off = random.uniform(-win_w_fb2*0.3, win_w_fb2*0.3)
            ffx = fbx_p2 + math.cos(fb_angle2) * ff_off + fbnx_2 * 0.05
            ffy = fby_p2 + math.sin(fb_angle2) * ff_off + fbny_2 * 0.05
            bpy.ops.mesh.primitive_uv_sphere_add(radius=0.04,
                location=(ffx, ffy, sill_fb2 + 0.02), segments=4, ring_count=3)
            ffo = bpy.context.active_object
            ffo.name = f"Flower2_{ffi}"
            ffo.data.materials.append(mat(f"Fl2_{random.choice(flower_hex2)}", random.choice(flower_hex2), 0.7))
            link(ffo, collection)

    # Wall-mounted mailbox slot (on front wall near door)
    if not has_storefront and len(edges) > 0:
        el0_ms, msx1, msy1, msx2, msy2, msnx, msny = edges[0]
        ms_angle = math.atan2(msy2 - msy1, msx2 - msx1)
        ms_t = 0.45
        msx_p = msx1 + (msx2-msx1) * ms_t + msnx * 0.05
        msy_p = msy1 + (msy2-msy1) * ms_t + msny * 0.05
        m_mailslot = mat("MailSlot", "#8A7A5A", 0.6)
        bpy.ops.mesh.primitive_cube_add(size=1, location=(msx_p, msy_p, 1.1))
        mso = bpy.context.active_object
        mso.name = "MailSlot"
        mso.scale = (0.15, 0.03, 0.04)
        mso.rotation_euler = (0, 0, ms_angle)
        mso.data.materials.append(m_mailslot)
        link(mso, collection)

    # Garage door (on some houses — rear or side)
    if not has_storefront and random.random() > 0.8 and len(edges) >= 2:
        _, gdx1, gdy1, gdx2, gdy2, gdnx, gdny = edges[1]
        gd_angle = math.atan2(gdy2 - gdy1, gdx2 - gdx1)
        gdx_c = (gdx1 + gdx2) / 2 + gdnx * 0.06
        gdy_c = (gdy1 + gdy2) / 2 + gdny * 0.06
        m_garage = mat("GarageDoor", "#6A6A6A", 0.7)
        bpy.ops.mesh.primitive_cube_add(size=1, location=(gdx_c, gdy_c, 1.2))
        gdo = bpy.context.active_object
        gdo.name = "GarageDoor"
        gdo.scale = (1.3, 0.06, 1.2)
        gdo.rotation_euler = (0, 0, gd_angle)
        gdo.data.materials.append(m_garage)
        link(gdo, collection)
        # Horizontal panel lines on garage door
        for gl_i in range(4):
            gl_z = 0.3 + gl_i * 0.5
            bpy.ops.mesh.primitive_cube_add(size=1, location=(gdx_c, gdy_c, gl_z))
            glo = bpy.context.active_object
            glo.name = f"GarageLine_{gl_i}"
            glo.scale = (1.25, 0.065, 0.005)
            glo.rotation_euler = (0, 0, gd_angle)
            glo.data.materials.append(mat("GarageLine", "#5A5A5A", 0.7))
            link(glo, collection)

    # Garden hose reel (on side of residential buildings)
    if not has_storefront and random.random() > 0.85 and len(edges) >= 2:
        _, hrx1, hry1, hrx2, hry2, hrnx, hrny = edges[1]
        hrx_c = hrx1 + (hrx2-hrx1) * 0.6 + hrnx * 0.2
        hry_c = hry1 + (hry2-hry1) * 0.6 + hrny * 0.2
        m_hose = mat("HoseReel", "#2A6A2A", 0.7)
        bpy.ops.mesh.primitive_torus_add(major_radius=0.15, minor_radius=0.04,
            location=(hrx_c, hry_c, 0.4), major_segments=12, minor_segments=6)
        hro = bpy.context.active_object
        hro.name = "HoseReel"
        hro.data.materials.append(m_hose)
        link(hro, collection)

    # Window curtain/blind indicator (thin coloured strip inside window)
    if random.random() > 0.5 and len(edges) > 0:
        el0_cu, cux1, cuy1, cux2, cuy2, cunx, cuny = edges[0]
        cu_dx, cu_dy = cux2 - cux1, cuy2 - cuy1
        cu_angle = math.atan2(cu_dy, cu_dx)
        win_w_cu = params.get("window_width_m", 0.9) or 0.9
        win_h_cu = params.get("window_height_m", 1.4) or 1.4
        curtain_colours = ["#E8E0D0", "#A0A0C0", "#C0A080", "#8A2A2A", "#2A4A6A"]
        m_curtain = mat(f"Curtain_{random.choice(curtain_colours)}",
                        random.choice(curtain_colours), 0.8)
        wpf_cu = params.get("windows_per_floor", [2]) or [2]
        # Pick one random floor
        fi_cu = random.randint(0, min(int(floors)-1, 2))
        sill_cu = fi_cu * floor_h + floor_h * 0.3
        n_w_cu = wpf_cu[fi_cu] if fi_cu < len(wpf_cu) and isinstance(wpf_cu[fi_cu], (int,float)) else 2
        for wi_cu in range(int(n_w_cu)):
            if random.random() > 0.6:
                continue
            t_cu = (wi_cu + 1) / (int(n_w_cu) + 1)
            cwx = cux1 + cu_dx * t_cu + cunx * 0.03
            cwy = cuy1 + cu_dy * t_cu + cuny * 0.03
            cwz = sill_cu + win_h_cu * 0.7
            # Curtain as thin strip at top of window
            bpy.ops.mesh.primitive_cube_add(size=1, location=(cwx, cwy, cwz))
            cuo = bpy.context.active_object
            cuo.name = f"Curtain_{fi_cu}_{wi_cu}"
            cuo.scale = (win_w_cu * 0.4, 0.005, win_h_cu * 0.3)
            cuo.rotation_euler = (0, 0, cu_angle)
            cuo.data.materials.append(m_curtain)
            link(cuo, collection)

    # Clothesline (between buildings or on balcony — common in Kensington)
    if random.random() > 0.8 and len(edges) >= 2:
        _, clx1_l, cly1_l, clx2_l, cly2_l, clnx_l, clny_l = edges[1]
        cl_angle_l = math.atan2(cly2_l - cly1_l, clx2_l - clx1_l)
        clmx = (clx1_l + clx2_l) / 2 + clnx_l * 2
        clmy = (cly1_l + cly2_l) / 2 + clny_l * 2
        m_clothesline = mat("Clothesline", "#E8E0D0", 0.6)
        cl_len = min(edges[1][0] * 0.5, 4)
        bpy.ops.mesh.primitive_cylinder_add(radius=0.005, depth=cl_len,
            location=(clmx, clmy, floor_h + 1.0), vertices=4)
        cllo = bpy.context.active_object
        cllo.name = "Clothesline"
        cllo.rotation_euler = (math.pi/2, 0, cl_angle_l)
        cllo.data.materials.append(m_clothesline)
        link(cllo, collection)
        # A few hanging items (small rectangles)
        m_laundry = mat("Laundry", "#E0E0E0", 0.8)
        for li in range(random.randint(2, 5)):
            lt = random.uniform(0.1, 0.9)
            lx = clmx + math.cos(cl_angle_l + math.pi/2) * (cl_len * (lt - 0.5))
            ly = clmy + math.sin(cl_angle_l + math.pi/2) * (cl_len * (lt - 0.5))
            bpy.ops.mesh.primitive_cube_add(size=1, location=(lx, ly, floor_h + 0.6))
            ldo = bpy.context.active_object
            ldo.name = f"Laundry_{li}"
            ldo.scale = (0.15, 0.005, random.uniform(0.15, 0.35))
            ldo.rotation_euler = (0, 0, cl_angle_l + random.uniform(-0.3, 0.3))
            laundry_colours = ["#E0E0E0", "#A0C0E0", "#E0C0A0", "#C0E0A0"]
            ldo.data.materials.append(mat(f"Laundry_{random.choice(laundry_colours)}",
                                          random.choice(laundry_colours), 0.8))
            link(ldo, collection)

    # Building number on commercial facade (large, visible)
    if has_storefront and params.get("building_name") and len(edges) > 0:
        el0_num, numx1, numy1, numx2, numy2, numnx, numny = edges[0]
        num_angle = math.atan2(numy2 - numy1, numx2 - numx1)
        num_t = 0.08
        numx_p = numx1 + (numx2-numx1) * num_t + numnx * 0.07
        numy_p = numy1 + (numy2-numy1) * num_t + numny * 0.07
        m_bldg_num = mat("BldgNum", "#E8E0D0", 0.6)
        bpy.ops.mesh.primitive_cube_add(size=1, location=(numx_p, numy_p, floor_h + 0.3))
        numo = bpy.context.active_object
        numo.name = "BldgNumber"
        numo.scale = (0.15, 0.02, 0.12)
        numo.rotation_euler = (0, 0, num_angle)
        numo.data.materials.append(m_bldg_num)
        link(numo, collection)

    # Weeping mortar (rough texture band on old brick — aged appearance)
    if "pre-1889" in era.lower() and facade_mat_name == "brick" and len(edges) > 0:
        el0_wm, wmx1, wmy1, wmx2, wmy2, wmnx, wmny = edges[0]
        wm_angle = math.atan2(wmy2 - wmy1, wmx2 - wmx1)
        m_weep = mat("WeepMortar", "#B0A890", 0.95)
        # Rough horizontal band at random heights
        for wmi in range(random.randint(1, 3)):
            wm_z = random.uniform(1, h * 0.8)
            wmmx = (wmx1 + wmx2) / 2 + wmnx * 0.055
            wmmy = (wmy1 + wmy2) / 2 + wmny * 0.055
            bpy.ops.mesh.primitive_cube_add(size=1, location=(wmmx, wmmy, wm_z))
            wmo = bpy.context.active_object
            wmo.name = f"WeepMortar_{wmi}"
            wmo.scale = (el0_wm * random.uniform(0.3, 0.8) / 2, 0.008, 0.02)
            wmo.rotation_euler = (0, 0, wm_angle)
            wmo.data.materials.append(m_weep)
            link(wmo, collection)

    # Detached garage behind house (from back alley photo)
    if not has_storefront and random.random() > 0.7 and len(edges) >= 2:
        _, garx1, gary1, garx2, gary2, garnx, garny = edges[1]
        gar_angle = math.atan2(gary2 - gary1, garx2 - garx1)
        garmx = (garx1 + garx2) / 2 - garnx * 8
        garmy = (gary1 + gary2) / 2 - garny * 8
        gar_w = random.uniform(3, 4)
        gar_h = random.uniform(2.5, 3.5)
        m_garage_bldg = mat("GarageBldg", "#7A7A78", 0.8)
        bpy.ops.mesh.primitive_cube_add(size=1, location=(garmx, garmy, gar_h / 2))
        garo = bpy.context.active_object
        garo.name = "DetachedGarage"
        garo.scale = (gar_w / 2, 2.5, gar_h / 2)
        garo.rotation_euler = (0, 0, gar_angle)
        garo.data.materials.append(m_garage_bldg)
        link(garo, collection)
        # Garage door on front
        bpy.ops.mesh.primitive_cube_add(size=1, location=(
            garmx + garnx * 2.5, garmy + garny * 2.5, 1.0))
        gdo2 = bpy.context.active_object
        gdo2.name = "GarageDoor2"
        gdo2.scale = (gar_w * 0.8 / 2, 0.04, 1.0)
        gdo2.rotation_euler = (0, 0, gar_angle)
        gdo2.data.materials.append(mat("GarageDoor2", "#5A5A5A", 0.7))
        link(gdo2, collection)
        # Gravel pad
        bpy.ops.mesh.primitive_cube_add(size=1, location=(
            garmx + garnx * 4, garmy + garny * 4, 0.01))
        gpo = bpy.context.active_object
        gpo.name = "GravelPad"
        gpo.scale = (gar_w / 2 + 0.5, 2, 0.01)
        gpo.rotation_euler = (0, 0, gar_angle)
        gpo.data.materials.append(mat("GravelPad", "#8A8070", 0.9))
        link(gpo, collection)

    # Wooden privacy fence between properties (from alley photo)
    if not has_storefront and random.random() > 0.5 and len(edges) >= 2:
        el1_pf, pfx1_w, pfy1_w, pfx2_w, pfy2_w, pfnx_w, pfny_w = edges[1]
        pf_angle_w = math.atan2(pfy2_w - pfy1_w, pfx2_w - pfx1_w)
        m_wood_fence = mat("WoodFence", "#8A7050", 0.85)
        pfmx = (pfx1_w + pfx2_w) / 2
        pfmy = (pfy1_w + pfy2_w) / 2
        fence_h_w = random.uniform(1.5, 1.8)
        bpy.ops.mesh.primitive_cube_add(size=1, location=(pfmx, pfmy, fence_h_w / 2))
        pfo_w = bpy.context.active_object
        pfo_w.name = "WoodFence"
        pfo_w.scale = (0.03, el1_pf / 2, fence_h_w / 2)
        pfo_w.rotation_euler = (0, 0, pf_angle_w)
        pfo_w.data.materials.append(m_wood_fence)
        link(pfo_w, collection)

    # "For Lease" sign in vacant storefronts
    ctx = params.get("context", {})
    is_vacant = ctx.get("is_vacant", False) if isinstance(ctx, dict) else False
    if has_storefront and is_vacant and len(edges) > 0:
        el0_fl, flx1, fly1, flx2, fly2, flnx, flny = edges[0]
        fl_angle = math.atan2(fly2 - fly1, flx2 - flx1)
        flx_c = flx1 + (flx2-flx1) * 0.5 + flnx * 0.1
        fly_c = fly1 + (fly2-fly1) * 0.5 + flny * 0.1
        bpy.ops.mesh.primitive_cube_add(size=1, location=(flx_c, fly_c, 1.2))
        flo = bpy.context.active_object
        flo.name = "ForLease"
        flo.scale = (0.4, 0.01, 0.3)
        flo.rotation_euler = (0, 0, fl_angle)
        flo.data.materials.append(mat("ForLease", "#E8E0D0", 0.6))
        link(flo, collection)

    # Metal flat canopy (modern black, from commercial photos)
    if has_storefront and random.random() > 0.7 and len(edges) > 0:
        el0_mc, mcx1, mcy1, mcx2, mcy2, mcnx, mcny = edges[0]
        mc_angle = math.atan2(mcy2 - mcy1, mcx2 - mcx1)
        mc_w = min(el0_mc * 0.6, 3.5)
        mcx_c = mcx1 + (mcx2-mcx1) * 0.5 + mcnx * 0.6
        mcy_c = mcy1 + (mcy2-mcy1) * 0.5 + mcny * 0.6
        bpy.ops.mesh.primitive_cube_add(size=1, location=(mcx_c, mcy_c, floor_h - 0.1))
        mco = bpy.context.active_object
        mco.name = "MetalCanopy"
        mco.scale = (mc_w / 2, 0.6, 0.03)
        mco.rotation_euler = (0, 0, mc_angle)
        mco.data.materials.append(mat("MetalCanopy", "#2A2A2A", 0.4))
        link(mco, collection)

    # Metal balcony with vertical bar railing (from night Kensington photo)
    if floors >= 2 and random.random() > 0.6 and len(edges) > 0:
        el0_mr, mrx1, mry1, mrx2, mry2, mrnx, mrny = edges[0]
        mr_angle = math.atan2(mry2 - mry1, mrx2 - mrx1)
        mr_w = min(el0_mr * 0.5, 3.0)
        mrx_c = mrx1 + (mrx2-mrx1) * 0.5 + mrnx * 0.3
        mry_c = mry1 + (mry2-mry1) * 0.5 + mrny * 0.3
        m_metal_rail = mat("MetalRail", "#2A2A2A", 0.4)
        bpy.ops.mesh.primitive_cube_add(size=1, location=(mrx_c, mry_c, floor_h + 0.8))
        mro = bpy.context.active_object
        mro.name = "MetalRailTop"
        mro.scale = (mr_w / 2, 0.02, 0.02)
        mro.rotation_euler = (0, 0, mr_angle)
        mro.data.materials.append(m_metal_rail)
        link(mro, collection)
        # Vertical bars
        n_bars = max(3, int(mr_w / 0.12))
        for bi_mr in range(n_bars):
            br_t = bi_mr / max(n_bars - 1, 1)
            brx = mrx_c + math.cos(mr_angle) * mr_w * (br_t - 0.5)
            bry = mry_c + math.sin(mr_angle) * mr_w * (br_t - 0.5)
            bpy.ops.mesh.primitive_cylinder_add(radius=0.01, depth=0.7,
                location=(brx, bry, floor_h + 0.45), vertices=4)
            bro = bpy.context.active_object
            bro.name = f"RailBar_{bi_mr}"
            bro.data.materials.append(m_metal_rail)
            link(bro, collection)

    # Window curtains / venetian blinds (from night photo — yellow wooden blinds)
    if random.random() > 0.4 and len(edges) > 0:
        el0_vb, vbx1, vby1, vbx2, vby2, vbnx, vbny = edges[0]
        vb_dx, vb_dy = vbx2 - vbx1, vby2 - vby1
        vb_angle = math.atan2(vb_dy, vb_dx)
        win_w_vb = params.get("window_width_m", 0.9) or 0.9
        win_h_vb = params.get("window_height_m", 1.4) or 1.4
        blind_colours = ["#D0C080", "#E0D8C0", "#C0B080", "#A0A098"]
        m_blind = mat(f"Blind_{random.choice(blind_colours)}",
                      random.choice(blind_colours), 0.75)
        wpf_vb = params.get("windows_per_floor", [2]) or [2]
        # Pick random floor and window for blinds
        fi_vb = random.randint(0, min(int(floors)-1, 2))
        sill_vb = fi_vb * floor_h + floor_h * 0.3
        n_w_vb = wpf_vb[fi_vb] if fi_vb < len(wpf_vb) and isinstance(wpf_vb[fi_vb], (int,float)) else 2
        for wi_vb in range(int(n_w_vb)):
            if random.random() > 0.4:
                continue
            t_vb = (wi_vb + 1) / (int(n_w_vb) + 1)
            vbwx = vbx1 + vb_dx * t_vb + vbnx * 0.035
            vbwy = vby1 + vb_dy * t_vb + vbny * 0.035
            # Blind as horizontal strips inside window
            for bl_i in range(5):
                bl_z = sill_vb + win_h_vb * 0.15 + bl_i * (win_h_vb * 0.7 / 5)
                bpy.ops.mesh.primitive_cube_add(size=1, location=(vbwx, vbwy, bl_z))
                blo_vb = bpy.context.active_object
                blo_vb.name = f"Blind_{fi_vb}_{wi_vb}_{bl_i}"
                blo_vb.scale = (win_w_vb * 0.4, 0.003, 0.015)
                blo_vb.rotation_euler = (0, 0, vb_angle)
                blo_vb.data.materials.append(m_blind)
                link(blo_vb, collection)

    # Cross-gable roof (from roof_type — adds perpendicular gable on main gable)
    if "cross" in roof_type and "gable" in roof_type and len(edges) >= 2:
        ridge_h_cg = min((max(xs)-min(xs)) * 0.35, 2.5)
        # Secondary gable perpendicular to main
        el1_cg, cgx1, cgy1, cgx2, cgy2, cgnx, cgny = edges[1]
        cg_angle = math.atan2(cgy2 - cgy1, cgx2 - cgx1)
        cg_w = min(el1_cg * 0.5, 3.0)
        cg_mx = (cgx1 + cgx2) / 2
        cg_my = (cgy1 + cgy2) / 2
        cg_ridge_h = ridge_h_cg * 0.8
        m_cg_roof = mat(f"Roof_{roof_hex}" if 'roof_hex' in dir() else "Roof_cg",
                        params.get("colour_palette", {}).get("roof_hex", "#4A4A4A"), 0.85)
        bm_cg = bmesh.new()
        # Cross gable triangle
        v1_cg = bm_cg.verts.new((cg_mx - math.cos(cg_angle)*cg_w/2, cg_my - math.sin(cg_angle)*cg_w/2, h))
        v2_cg = bm_cg.verts.new((cg_mx + math.cos(cg_angle)*cg_w/2, cg_my + math.sin(cg_angle)*cg_w/2, h))
        v3_cg = bm_cg.verts.new((cg_mx + cgnx*0.3, cg_my + cgny*0.3, h + cg_ridge_h))
        try:
            bm_cg.faces.new([v1_cg, v2_cg, v3_cg])
        except: pass
        cg_mesh = bpy.data.meshes.new("CrossGable")
        bm_cg.to_mesh(cg_mesh)
        bm_cg.free()
        cg_obj = bpy.data.objects.new("CrossGable", cg_mesh)
        cg_obj.data.materials.append(m_cg_roof)
        link(cg_obj, collection)

    # Turret / tower (from photo_observations — very rare, usually churches)
    po_turret = params.get("photo_observations", {})
    if isinstance(po_turret, dict) and po_turret.get("turret_notes"):
        if len(edges) >= 2:
            # Place turret at a corner
            el0_tu, tux1, tuy1, tux2, tuy2, tunx, tuny = edges[0]
            tu_x = tux1 + tunx * 0.3
            tu_y = tuy1 + tuny * 0.3
            turret_h = h * 0.4
            m_turret = mat("Turret", hex_col, 0.7)
            bpy.ops.mesh.primitive_cylinder_add(radius=0.8, depth=turret_h,
                location=(tu_x, tu_y, h + turret_h/2), vertices=8)
            tuo = bpy.context.active_object
            tuo.name = "Turret"
            tuo.data.materials.append(m_turret)
            link(tuo, collection)
            # Conical roof on turret
            bpy.ops.mesh.primitive_cone_add(radius1=0.9, depth=1.2,
                location=(tu_x, tu_y, h + turret_h + 0.6), vertices=8)
            turo = bpy.context.active_object
            turo.name = "TurretRoof"
            turo.data.materials.append(mat("TurretRoof", "#2A4A2A", 0.8))
            link(turo, collection)

    # Stained glass transoms (coloured glass panels above windows — heritage buildings)
    hcd_feats = hcd.get("building_features", []) if isinstance(hcd, dict) else []
    if isinstance(hcd_feats, list) and any("stain" in str(f).lower() for f in hcd_feats):
        if len(edges) > 0:
            el0_sg2, sgx1_2, sgy1_2, sgx2_2, sgy2_2, sgnx_2, sgny_2 = edges[0]
            sg_dx2 = sgx2_2 - sgx1_2
            sg_dy2 = sgy2_2 - sgy1_2
            sg_angle2 = math.atan2(sg_dy2, sg_dx2)
            m_stained = mat("StainedGlass", "#8A3A5A", 0.25)
            win_h_sg = params.get("window_height_m", 1.4) or 1.4
            wpf_sg = params.get("windows_per_floor", [2]) or [2]
            for fi_sg in range(min(int(floors), 2)):
                sill_sg = fi_sg * floor_h + floor_h * 0.3
                n_w_sg = wpf_sg[fi_sg] if fi_sg < len(wpf_sg) and isinstance(wpf_sg[fi_sg], (int,float)) else 2
                for wi_sg in range(int(n_w_sg)):
                    t_sg = (wi_sg + 1) / (int(n_w_sg) + 1)
                    sgwx = sgx1_2 + sg_dx2 * t_sg + sgnx_2 * 0.06
                    sgwy = sgy1_2 + sg_dy2 * t_sg + sgny_2 * 0.06
                    # Small coloured panel above each window
                    bpy.ops.mesh.primitive_cube_add(size=1,
                        location=(sgwx, sgwy, sill_sg + win_h_sg + 0.12))
                    sgo2 = bpy.context.active_object
                    sgo2.name = f"StainGlass_{fi_sg}_{wi_sg}"
                    sgo2.scale = (0.3, 0.04, 0.08)
                    sgo2.rotation_euler = (0, 0, sg_angle2)
                    sgo2.data.materials.append(m_stained)
                    link(sgo2, collection)

    # Hip rooflet (small secondary hip roof over bay window or porch)
    if params.get("bay_window", {}).get("present") and "gable" not in roof_type:
        if len(edges) > 0:
            el0_hr, hrx1_2, hry1_2, hrx2_2, hry2_2, hrnx_2, hrny_2 = edges[0]
            hr_angle = math.atan2(hry2_2 - hry1_2, hrx2_2 - hrx1_2)
            bw_data_hr = params.get("bay_window", {})
            bw_w_hr = bw_data_hr.get("width_m", 2.0)
            bw_proj_hr = bw_data_hr.get("projection_m", 0.6)
            hr_t = 0.3
            hrx_p = hrx1_2 + (hrx2_2-hrx1_2) * hr_t + hrnx_2 * (bw_proj_hr + 0.2)
            hry_p = hry1_2 + (hry2_2-hry1_2) * hr_t + hrny_2 * (bw_proj_hr + 0.2)
            # Small hip roof over bay
            bpy.ops.mesh.primitive_cone_add(radius1=bw_w_hr * 0.6, depth=0.8,
                location=(hrx_p, hry_p, h - 0.5), vertices=4)
            hro2 = bpy.context.active_object
            hro2.name = "HipRooflet"
            hro2.rotation_euler = (0, 0, hr_angle)
            hro2.data.materials.append(mat("Roof_hip2", "#4A4A4A", 0.85))
            link(hro2, collection)

    # Gabled parapet (decorative stepped parapet on commercial flat roofs)
    if has_storefront and roof_type == "flat" and random.random() > 0.5 and len(edges) > 0:
        el0_gp, gpx1, gpy1, gpx2, gpy2, gpnx, gpny = edges[0]
        gp_angle = math.atan2(gpy2 - gpy1, gpx2 - gpx1) if abs(gpx2-gpx1) > 0.01 else 0
        gp_angle = math.atan2(gpy2 - gpy1, gpx2 - gpx1)
        gp_w = el0_gp * 0.6
        gpmx = (gpx1 + gpx2) / 2 + gpnx * 0.06
        gpmy = (gpy1 + gpy2) / 2 + gpny * 0.06
        m_parapet_gable = mat("GabledParapet", hex_col, 0.7)
        # Central raised section
        bpy.ops.mesh.primitive_cube_add(size=1, location=(gpmx, gpmy, h + 0.4))
        gpo = bpy.context.active_object
        gpo.name = "GabledParapet"
        gpo.scale = (gp_w * 0.3 / 2, 0.08, 0.4)
        gpo.rotation_euler = (0, 0, gp_angle)
        gpo.data.materials.append(m_parapet_gable)
        link(gpo, collection)
        # Side steps
        for gp_side in [-1, 1]:
            bpy.ops.mesh.primitive_cube_add(size=1,
                location=(gpmx + math.cos(gp_angle) * gp_w * 0.25 * gp_side,
                          gpmy + math.sin(gp_angle) * gp_w * 0.25 * gp_side, h + 0.2))
            gps = bpy.context.active_object
            gps.name = f"ParapetStep_{gp_side}"
            gps.scale = (gp_w * 0.15, 0.08, 0.2)
            gps.rotation_euler = (0, 0, gp_angle)
            gps.data.materials.append(m_parapet_gable)
            link(gps, collection)

    # Roof material variation (shingle vs slate vs metal from roof_material param)
    roof_mat_name = (params.get("roof_material") or "asphalt shingles").lower()
    if "metal" in roof_mat_name or "tin" in roof_mat_name:
        # Metal roofs are lighter, shinier
        pass  # Already handled by per-building roof colour
    elif "slate" in roof_mat_name:
        pass  # Darker, handled by colour

    # Street setback (offset building from street — from street_setback_m param)
    # This is already effectively handled by the building position from GIS data
    # but we note it here for documentation

    # Condition deterioration indicators (from condition_issues)
    cond_issues = params.get("assessment", {}).get("condition_issues") if isinstance(params.get("assessment"), dict) else None
    if cond_issues and isinstance(cond_issues, str):
        if "crack" in cond_issues.lower() and len(edges) > 0:
            # Add visible crack line on facade
            el0_ck, ckx1, cky1, ckx2, cky2, cknx, ckny = edges[0]
            ck_angle = math.atan2(cky2 - cky1, ckx2 - ckx1)
            ckx_c = ckx1 + (ckx2-ckx1) * random.uniform(0.2, 0.8) + cknx * 0.06
            cky_c = cky1 + (cky2-cky1) * random.uniform(0.2, 0.8) + ckny * 0.06
            m_crack = mat("Crack", "#3A3A3A", 0.9)
            bpy.ops.mesh.primitive_cube_add(size=1, location=(ckx_c, cky_c, h * 0.5))
            cko = bpy.context.active_object
            cko.name = "FacadeCrack"
            cko.scale = (0.01, 0.005, h * 0.3)
            cko.rotation_euler = (0, random.uniform(-0.2, 0.2), ck_angle)
            cko.data.materials.append(m_crack)
            link(cko, collection)

        if "peel" in cond_issues.lower() or "flak" in cond_issues.lower():
            # Peeling paint patch
            if len(edges) > 0:
                el0_pp, ppx1, ppy1, ppx2, ppy2, ppnx, ppny = edges[0]
                pp_angle = math.atan2(ppy2 - ppy1, ppx2 - ppx1)
                ppx_c = ppx1 + (ppx2-ppx1) * random.uniform(0.3, 0.7) + ppnx * 0.055
                ppy_c = ppy1 + (ppy2-ppy1) * random.uniform(0.3, 0.7) + ppny * 0.055
                m_peel = mat("PeelingPaint", "#C8C0B0", 0.9)
                bpy.ops.mesh.primitive_cube_add(size=1,
                    location=(ppx_c, ppy_c, random.uniform(1, h * 0.6)))
                ppo_c = bpy.context.active_object
                ppo_c.name = "PeelingPaint"
                ppo_c.scale = (random.uniform(0.2, 0.5), 0.01, random.uniform(0.2, 0.4))
                ppo_c.rotation_euler = (0, 0, pp_angle)
                ppo_c.data.materials.append(m_peel)
                link(ppo_c, collection)

    # Painted garage door mural (from "Radiant Child" photo — Kensington has these)
    if not has_storefront and random.random() > 0.92 and len(edges) >= 2:
        _, mgx1, mgy1, mgx2, mgy2, mgnx, mgny = edges[1]
        mg_angle = math.atan2(mgy2 - mgy1, mgx2 - mgx1)
        mgx_c = (mgx1 + mgx2) / 2 - mgnx * 7
        mgy_c = (mgy1 + mgy2) / 2 - mgny * 7
        mural_garage_colours = ["#CC2222", "#2222CC", "#CCCC22", "#22CC22", "#CC22CC"]
        mg_hex = random.choice(mural_garage_colours)
        m_garage_mural = mat(f"GarageMural_{mg_hex}", mg_hex, 0.7)
        bpy.ops.mesh.primitive_cube_add(size=1, location=(mgx_c, mgy_c, 1.0))
        mgo = bpy.context.active_object
        mgo.name = "GarageMural"
        mgo.scale = (1.5, 0.04, 1.0)
        mgo.rotation_euler = (0, 0, mg_angle)
        mgo.data.materials.append(m_garage_mural)
        link(mgo, collection)

    # Asymmetric window arrangement (from window_arrangement param)
    # When "asymmetric", shift windows off-center
    win_arr = params.get("window_arrangement") or ""
    po_arr = po_turret.get("window_arrangement", "") if isinstance(po_turret, dict) else ""
    if "asymm" in str(win_arr).lower() or "asymm" in str(po_arr).lower():
        # Already partially handled by per-floor window specs
        # But add a visible marker — offset the door slightly
        pass

    # Heritage plaque (bronze plaque on heritage buildings)
    if isinstance(hcd, dict) and hcd.get("contributing") == "Yes" and random.random() > 0.6:
        if len(edges) > 0:
            el0_hp, hpx1, hpy1, hpx2, hpy2, hpnx, hpny = edges[0]
            hp_angle = math.atan2(hpy2 - hpy1, hpx2 - hpx1)
            hpx_c = hpx1 + (hpx2-hpx1) * 0.6 + hpnx * 0.06
            hpy_c = hpy1 + (hpy2-hpy1) * 0.6 + hpny * 0.06
            m_plaque_h = mat("HeritagePlaque", "#8A6A2A", 0.5)
            bpy.ops.mesh.primitive_cube_add(size=1, location=(hpx_c, hpy_c, 1.5))
            hpo = bpy.context.active_object
            hpo.name = "HeritagePlaque"
            hpo.scale = (0.15, 0.02, 0.1)
            hpo.rotation_euler = (0, 0, hp_angle)
            hpo.data.materials.append(m_plaque_h)
            link(hpo, collection)

    # Arched window on heritage buildings (from photo_observations)
    if isinstance(po_turret, dict) and po_turret.get("arched_windows"):
        if len(edges) > 0:
            el0_aw, awx1, awy1, awx2, awy2, awnx, awny = edges[0]
            aw_dx, aw_dy = awx2 - awx1, awy2 - awy1
            aw_angle = math.atan2(aw_dy, aw_dx)
            m_arch_win = mat("ArchedWin", "#5A7A8A", 0.3)
            # Replace one upper floor window with arched version
            if floors >= 2:
                aw_t = 0.5
                awx_p = awx1 + aw_dx * aw_t + awnx * 0.06
                awy_p = awy1 + aw_dy * aw_t + awny * 0.06
                aw_z = floor_h + floor_h * 0.4
                # Arched top (half cylinder)
                bpy.ops.mesh.primitive_cylinder_add(radius=0.5, depth=0.06,
                    location=(awx_p, awy_p, aw_z + 0.7), vertices=12)
                awo = bpy.context.active_object
                awo.name = "ArchedWindow"
                awo.scale = (1, 0.8, 1)
                awo.rotation_euler = (math.pi/2, 0, aw_angle)
                awo.data.materials.append(m_arch_win)
                link(awo, collection)

    # Corner street lights at commercial buildings
    if has_storefront and len(edges) > 0:
        for tl_t in [0.05, 0.95]:
            if random.random() > 0.85:
                continue
            el0_tl, tlx1, tly1, tlx2, tly2, tlnx, tlny = edges[0]
            tlx_p = tlx1 + (tlx2-tlx1) * tl_t + tlnx * 2
            tly_p = tly1 + (tly2-tly1) * tl_t + tlny * 2
            bpy.ops.mesh.primitive_cylinder_add(radius=0.04, depth=3.5,
                location=(tlx_p, tly_p, 1.75), vertices=6)
            tlo = bpy.context.active_object
            tlo.name = "CornerLight"
            tlo.data.materials.append(mat("PostLight", "#3A3A3A", 0.5))
            link(tlo, collection)
            bpy.ops.mesh.primitive_cube_add(size=1, location=(tlx_p, tly_p, 3.6))
            tlh = bpy.context.active_object
            tlh.name = "CornerHead"
            tlh.scale = (0.2, 0.1, 0.04)
            tlh.data.materials.append(mat("LightHead3", "#E0E0D0", 0.3))
            link(tlh, collection)

    # Commercial patio / CafeTO deck (wooden outdoor patio — from Augusta photo)
    if has_storefront and random.random() > 0.6 and len(edges) > 0:
        el0_pt, ptx1, pty1, ptx2, pty2, ptnx, ptny = edges[0]
        pt_dx, pt_dy = ptx2 - ptx1, pty2 - pty1
        pt_angle_p = math.atan2(pt_dy, pt_dx)
        patio_w = min(el0_pt * 0.6, 4.0)
        patio_d = 2.5
        ptx_c = ptx1 + pt_dx * 0.5 + ptnx * (0.1 + patio_d / 2 + 1.5)
        pty_c = pty1 + pt_dy * 0.5 + ptny * (0.1 + patio_d / 2 + 1.5)
        m_patio_wood = mat("PatioWood", "#8A7050", 0.8)
        # Deck platform
        bpy.ops.mesh.primitive_cube_add(size=1, location=(ptx_c, pty_c, 0.15))
        pto = bpy.context.active_object
        pto.name = "PatioDeck"
        pto.scale = (patio_w / 2, patio_d / 2, 0.08)
        pto.rotation_euler = (0, 0, pt_angle_p)
        pto.data.materials.append(m_patio_wood)
        link(pto, collection)
        # Railing posts
        m_patio_rail = mat("PatioRail", "#8A7050", 0.75)
        for post_t in [0.1, 0.5, 0.9]:
            for post_side in [-1, 1]:
                ppx = ptx_c + math.cos(pt_angle_p) * patio_w * (post_t - 0.5) + ptnx * patio_d/2 * post_side * 0.8
                ppy = pty_c + math.sin(pt_angle_p) * patio_w * (post_t - 0.5) + ptny * patio_d/2 * post_side * 0.8
                bpy.ops.mesh.primitive_cylinder_add(radius=0.03, depth=0.8,
                    location=(ppx, ppy, 0.6), vertices=6)
                bpy.context.active_object.data.materials.append(m_patio_rail)
                link(bpy.context.active_object, collection)

    # Overhead power lines between buildings (from Kensington night photo)
    if random.random() > 0.7 and len(edges) > 0:
        el0_ow, owx1, owy1, owx2, owy2, ownx, owny = edges[0]
        m_overhead = mat("OverheadWire", "#1A1A1A", 0.3)
        ow_start_x = (owx1 + owx2) / 2
        ow_start_y = (owy1 + owy2) / 2
        ow_end_x = ow_start_x + ownx * 15
        ow_end_y = ow_start_y + owny * 15
        ow_len = math.sqrt((ow_end_x - ow_start_x)**2 + (ow_end_y - ow_start_y)**2)
        ow_angle = math.atan2(ow_end_y - ow_start_y, ow_end_x - ow_start_x)
        ow_mx = (ow_start_x + ow_end_x) / 2
        ow_my = (ow_start_y + ow_end_y) / 2
        bpy.ops.mesh.primitive_cylinder_add(radius=0.008, depth=ow_len,
            location=(ow_mx, ow_my, h - 0.5), vertices=4)
        owo = bpy.context.active_object
        owo.name = "OverheadWire"
        owo.rotation_euler = (math.pi/2, 0, ow_angle)
        owo.data.materials.append(m_overhead)
        link(owo, collection)

    # Painted wall mural (large coloured panel on side wall — from photos)
    if random.random() > 0.9 and len(edges) >= 2:
        _, mux1, muy1, mux2, muy2, munx, muny = edges[1]
        mu_angle = math.atan2(muy2 - muy1, mux2 - mux1)
        mumx = (mux1 + mux2) / 2 + munx * 0.06
        mumy = (muy1 + muy2) / 2 + muny * 0.06
        mural_colours = ["#CC4466", "#44AACC", "#CCAA44", "#66CC44", "#AA44CC"]
        mu_hex = random.choice(mural_colours)
        m_mural = mat(f"Mural_{mu_hex}", mu_hex, 0.7)
        mu_w = min(edges[1][0] * 0.6, 5)
        mu_h = h * 0.5
        bpy.ops.mesh.primitive_cube_add(size=1, location=(mumx, mumy, h * 0.4))
        muo = bpy.context.active_object
        muo.name = "Mural"
        muo.scale = (mu_w / 2, 0.02, mu_h / 2)
        muo.rotation_euler = (0, 0, mu_angle)
        muo.data.materials.append(m_mural)
        link(muo, collection)

    # Bicycle locked to rack/pole (near commercial buildings)
    if has_storefront and random.random() > 0.5 and len(edges) > 0:
        el0_bk, bkx1, bky1, bkx2, bky2, bknx, bkny = edges[0]
        bk_angle = math.atan2(bky2 - bky1, bkx2 - bkx1)
        bkx_p = bkx1 + (bkx2-bkx1) * random.uniform(0.2, 0.8) + bknx * 3
        bky_p = bky1 + (bky2-bky1) * random.uniform(0.2, 0.8) + bkny * 3
        m_bike_frame = mat("BikeFrame", random.choice(["#CC2222", "#2222CC", "#22CC22", "#222222"]), 0.4)
        for wh_off in [-0.4, 0.4]:
            bwx = bkx_p + math.cos(bk_angle) * wh_off
            bwy = bky_p + math.sin(bk_angle) * wh_off
            bpy.ops.mesh.primitive_torus_add(major_radius=0.3, minor_radius=0.015,
                location=(bwx, bwy, 0.3), major_segments=12, minor_segments=4)
            bwo_b = bpy.context.active_object
            bwo_b.name = "BikeWheel"
            bwo_b.rotation_euler = (0, 0, bk_angle)
            bwo_b.data.materials.append(mat("BikeWheel", "#2A2A2A", 0.5))
            link(bwo_b, collection)
        bpy.ops.mesh.primitive_cube_add(size=1, location=(bkx_p, bky_p, 0.45))
        bfo = bpy.context.active_object
        bfo.name = "BikeFrame"
        bfo.scale = (0.4, 0.02, 0.15)
        bfo.rotation_euler = (0, 0.2, bk_angle)
        bfo.data.materials.append(m_bike_frame)
        link(bfo, collection)

    # Traffic cone (occasional, near construction/parking)
    if random.random() > 0.92:
        tcx_c = cx + random.uniform(-5, 5)
        tcy_c = cy + random.uniform(-5, 5)
        m_cone = mat("TrafficCone", "#FF6600", 0.6)
        bpy.ops.mesh.primitive_cone_add(radius1=0.12, depth=0.5,
            location=(tcx_c, tcy_c, 0.25), vertices=8)
        tco = bpy.context.active_object
        tco.name = "TrafficCone"
        tco.data.materials.append(m_cone)
        link(tco, collection)
        bpy.ops.mesh.primitive_cylinder_add(radius=0.1, depth=0.02,
            location=(tcx_c, tcy_c, 0.35), vertices=8)
        tcs = bpy.context.active_object
        tcs.name = "ConeStripe"
        tcs.data.materials.append(mat("ConeWhite", "#E8E8E0", 0.7))
        link(tcs, collection)

    # Window AC units (box on window sill — from night Kensington photo)
    if random.random() > 0.7 and len(edges) > 0 and floors >= 2:
        el0_wac, wacx1, wacy1, wacx2, wacy2, wacnx, wacny = edges[0]
        wac_dx, wac_dy = wacx2 - wacx1, wacy2 - wacy1
        wac_angle = math.atan2(wac_dy, wac_dx)
        wac_t = random.uniform(0.2, 0.8)
        wac_x = wacx1 + wac_dx * wac_t + wacnx * 0.2
        wac_y = wacy1 + wac_dy * wac_t + wacny * 0.2
        wac_z = floor_h + floor_h * 0.4
        m_wac = mat("WindowAC", "#C8C8C8", 0.5)
        bpy.ops.mesh.primitive_cube_add(size=1, location=(wac_x, wac_y, wac_z))
        waco = bpy.context.active_object
        waco.name = "WindowAC"
        waco.scale = (0.35, 0.25, 0.2)
        waco.rotation_euler = (0, 0, wac_angle)
        waco.data.materials.append(m_wac)
        link(waco, collection)

    # Oculus / round windows in gables (from 77 Bellevue photo)
    if "gable" in roof_type and random.random() > 0.7 and len(edges) >= 2:
        ridge_h_oc = min((max(xs)-min(xs)) * 0.35, 2.5)
        _, ocx1, ocy1, ocx2, ocy2, ocnx, ocny = edges[1]
        oc_mx = (ocx1 + ocx2) / 2 + ocnx * 0.06
        oc_my = (ocy1 + ocy2) / 2 + ocny * 0.06
        oc_z = h + ridge_h_oc * 0.3
        m_oculus = mat("Oculus", "#5A7A8A", 0.3)
        bpy.ops.mesh.primitive_cylinder_add(radius=0.25, depth=0.04,
            location=(oc_mx, oc_my, oc_z), vertices=16)
        oco = bpy.context.active_object
        oco.name = "Oculus"
        oc_angle = math.atan2(ocy2 - ocy1, ocx2 - ocx1)
        oco.rotation_euler = (math.pi/2, 0, oc_angle)
        oco.data.materials.append(m_oculus)
        link(oco, collection)
        m_oc_surround = mat("OculusSurround", trim_hex, 0.65)
        bpy.ops.mesh.primitive_torus_add(major_radius=0.3, minor_radius=0.04,
            location=(oc_mx, oc_my, oc_z), major_segments=16, minor_segments=6)
        ocs = bpy.context.active_object
        ocs.name = "OculusSurround"
        ocs.rotation_euler = (math.pi/2, 0, oc_angle)
        ocs.data.materials.append(m_oc_surround)
        link(ocs, collection)

    # Arched doorway entrance (stone arch over heritage door)
    if isinstance(hcd, dict) and hcd.get("contributing") == "Yes" and len(edges) > 0:
        el0_ad, adx1, ady1, adx2, ady2, adnx, adny = edges[0]
        ad_angle = math.atan2(ady2 - ady1, adx2 - adx1)
        adx_p = adx1 + (adx2-adx1) * 0.5 + adnx * 0.07
        ady_p = ady1 + (ady2-ady1) * 0.5 + adny * 0.07
        bpy.ops.mesh.primitive_torus_add(major_radius=0.6, minor_radius=0.08,
            location=(adx_p, ady_p, 2.3), major_segments=8, minor_segments=6)
        ado = bpy.context.active_object
        ado.name = "DoorArch"
        ado.scale = (1, 0.3, 1)
        ado.rotation_euler = (0, 0, ad_angle)
        ado.data.materials.append(mat("ArchDoor", trim_hex, 0.65))
        link(ado, collection)

    # Varied parapet heights (stepped commercial skyline)
    if has_storefront and roof_type == "flat" and random.random() > 0.4 and len(edges) > 0:
        el0_vh, vhx1_p, vhy1_p, vhx2_p, vhy2_p, vhnx_p, vhny_p = edges[0]
        vh_angle_p = math.atan2(vhy2_p - vhy1_p, vhx2_p - vhx1_p)
        parapet_extra = random.uniform(0.3, 1.2)
        vhmx = (vhx1_p + vhx2_p) / 2 + vhnx_p * 0.06
        vhmy = (vhy1_p + vhy2_p) / 2 + vhny_p * 0.06
        bpy.ops.mesh.primitive_cube_add(size=1, location=(vhmx, vhmy, h + parapet_extra / 2))
        vho_p = bpy.context.active_object
        vho_p.name = "ParapetVar"
        vho_p.scale = (el0_vh * 0.9 / 2, 0.12, parapet_extra / 2)
        vho_p.rotation_euler = (0, 0, vh_angle_p)
        vho_p.data.materials.append(mat(f"ParV_{hex_col}", hex_col, 0.72))
        link(vho_p, collection)

    # Snow patches on ground (March photos show remaining snow)
    if random.random() > 0.7:
        for _ in range(random.randint(1, 3)):
            snow_x = cx + random.uniform(-4, 4)
            snow_y = cy + random.uniform(-4, 4)
            bpy.ops.mesh.primitive_cylinder_add(radius=random.uniform(0.3, 1.0),
                depth=0.03, location=(snow_x, snow_y, 0.015), vertices=8)
            sno = bpy.context.active_object
            sno.name = "SnowPatch"
            sno.scale = (1, random.uniform(0.5, 1.5), 1)
            sno.rotation_euler = (0, 0, random.uniform(0, 6.28))
            sno.data.materials.append(mat("Snow", "#E8E8F0", 0.85))
            link(sno, collection)

    # Utility box on side wall (green electrical panel)
    if random.random() > 0.6 and len(edges) >= 2:
        _, ubx1, uby1, ubx2, uby2, ubnx, ubny = edges[1]
        ub_angle = math.atan2(uby2 - uby1, ubx2 - ubx1)
        ubx_c = ubx1 + (ubx2-ubx1) * 0.4 + ubnx * 0.1
        uby_c = uby1 + (uby2-uby1) * 0.4 + ubny * 0.1
        bpy.ops.mesh.primitive_cube_add(size=1, location=(ubx_c, uby_c, 0.8))
        ubo = bpy.context.active_object
        ubo.name = "UtilBox"
        ubo.scale = (0.3, 0.08, 0.4)
        ubo.rotation_euler = (0, 0, ub_angle)
        ubo.data.materials.append(mat("UtilBox", "#3A6A3A", 0.6))
        link(ubo, collection)

    # Dryer vent on side wall
    if not has_storefront and random.random() > 0.5 and len(edges) >= 2:
        _, dvx1, dvy1, dvx2, dvy2, dvnx, dvny = edges[1]
        dv_angle = math.atan2(dvy2 - dvy1, dvx2 - dvx1)
        dvx_c = dvx1 + (dvx2-dvx1) * random.uniform(0.3, 0.7) + dvnx * 0.08
        dvy_c = dvy1 + (dvy2-dvy1) * random.uniform(0.3, 0.7) + dvny * 0.08
        bpy.ops.mesh.primitive_cylinder_add(radius=0.05, depth=0.04,
            location=(dvx_c, dvy_c, random.uniform(1, 2)), vertices=8)
        dvo = bpy.context.active_object
        dvo.name = "DryerVent"
        dvo.rotation_euler = (math.pi/2, 0, dv_angle)
        dvo.data.materials.append(mat("DryerVent", "#C0C0C0", 0.5))
        link(dvo, collection)

    # Party wall chimney (brick chimney on shared wall between semis)
    if (pw_left or pw_right) and len(edges) >= 3 and random.random() > 0.5:
        el2, pwcx1, pwcy1, pwcx2, pwcy2, _, _ = edges[2]
        if el2 < 8:
            pwc_mx = (pwcx1 + pwcx2) / 2
            pwc_my = (pwcy1 + pwcy2) / 2
            ridge_h_pw = min((max(xs)-min(xs)) * 0.35, 2.5) if "gable" in roof_type else 0
            bpy.ops.mesh.primitive_cube_add(size=1,
                location=(pwc_mx, pwc_my, h + ridge_h_pw + 0.5))
            pwco = bpy.context.active_object
            pwco.name = "PWChimney"
            pwco.scale = (0.3, 0.25, 0.5)
            pwco.data.materials.append(mat("PWChimney", hex_col, 0.75))
            link(pwco, collection)

    # Conduit/pipe run on exterior wall
    if random.random() > 0.5 and len(edges) > 0:
        el0_cd, cdx1, cdy1, cdx2, cdy2, cdnx, cdny = edges[0]
        cd_t = random.choice([0.1, 0.9])
        cdx_p = cdx1 + (cdx2-cdx1) * cd_t + cdnx * 0.06
        cdy_p = cdy1 + (cdy2-cdy1) * cd_t + cdny * 0.06
        bpy.ops.mesh.primitive_cylinder_add(radius=0.02, depth=h * 0.8,
            location=(cdx_p, cdy_p, h * 0.4), vertices=6)
        cdo = bpy.context.active_object
        cdo.name = "Conduit"
        cdo.data.materials.append(mat("Conduit", "#5A5A5A", 0.5))
        link(cdo, collection)

    # Upper porch / deck with lattice railing (from stucco house photo)
    if floors >= 2 and random.random() > 0.7 and len(edges) > 0:
        el0_up, upx1, upy1, upx2, upy2, upnx, upny = edges[0]
        up_angle = math.atan2(upy2 - upy1, upx2 - upx1)
        up_w = min(el0_up * 0.5, 3.0)
        up_d = 1.2
        upx_c = upx1 + (upx2-upx1) * 0.5 + upnx * (0.05 + up_d / 2)
        upy_c = upy1 + (upy2-upy1) * 0.5 + upny * (0.05 + up_d / 2)
        up_z = floor_h
        # Deck floor
        bpy.ops.mesh.primitive_cube_add(size=1, location=(upx_c, upy_c, up_z + 0.02))
        upf = bpy.context.active_object
        upf.name = "UpperDeck"
        upf.scale = (up_w / 2, up_d / 2, 0.03)
        upf.rotation_euler = (0, 0, up_angle)
        upf.data.materials.append(mat("DeckWood", "#8A7050", 0.8))
        link(upf, collection)
        # Lattice railing
        m_lattice_r = mat("LatticeRail", "#E0D8C8", 0.7)
        # Front rail
        bpy.ops.mesh.primitive_cube_add(size=1,
            location=(upx_c + upnx * up_d/2, upy_c + upny * up_d/2, up_z + 0.45))
        upr = bpy.context.active_object
        upr.name = "LatticeRailFront"
        upr.scale = (up_w / 2, 0.03, 0.45)
        upr.rotation_euler = (0, 0, up_angle)
        upr.data.materials.append(m_lattice_r)
        link(upr, collection)

    # Cedar/arborvitae hedge (tall evergreen privacy hedge — from photos)
    if not has_storefront and random.random() > 0.8 and len(edges) >= 2:
        _, hgx1, hgy1, hgx2, hgy2, hgnx, hgny = edges[1]
        hg_angle = math.atan2(hgy2 - hgy1, hgx2 - hgx1)
        hg_len = min(edges[1][0] * 0.6, 5)
        hgmx = (hgx1 + hgx2) / 2
        hgmy = (hgy1 + hgy2) / 2
        hg_h = random.uniform(2.0, 3.5)
        m_hedge = mat("Hedge", "#1A4A1A", 0.9)
        bpy.ops.mesh.primitive_cube_add(size=1, location=(hgmx, hgmy, hg_h / 2))
        hgo = bpy.context.active_object
        hgo.name = "CedarHedge"
        hgo.scale = (0.4, hg_len / 2, hg_h / 2)
        hgo.rotation_euler = (0, 0, hg_angle)
        hgo.data.materials.append(m_hedge)
        link(hgo, collection)

    # Rear addition at different height (from alley photo — lower extension)
    if random.random() > 0.5 and len(edges) >= 2:
        _, rax1, ray1, rax2, ray2, ranx, rany = edges[1]
        ra_angle = math.atan2(ray2 - ray1, rax2 - rax1)
        ra_h = h * random.uniform(0.4, 0.7)
        ra_w = random.uniform(3, 5)
        ra_d = random.uniform(2, 4)
        # Different material for rear addition
        rear_mats = [hex_col, "#C8C0B0", "#A0A098", "#D0C8B8"]
        ra_hex = random.choice(rear_mats)
        ramx = (rax1 + rax2) / 2 - ranx * (ra_d + 1)
        ramy = (ray1 + ray2) / 2 - rany * (ra_d + 1)
        bpy.ops.mesh.primitive_cube_add(size=1, location=(ramx, ramy, ra_h / 2))
        rao = bpy.context.active_object
        rao.name = "RearAdd"
        rao.scale = (ra_w / 2, ra_d / 2, ra_h / 2)
        rao.rotation_euler = (0, 0, ra_angle)
        rao.data.materials.append(mat(f"RearAdd_{ra_hex}", ra_hex, 0.75))
        link(rao, collection)
        # Flat roof on rear addition
        bpy.ops.mesh.primitive_cube_add(size=1, location=(ramx, ramy, ra_h + 0.03))
        rar = bpy.context.active_object
        rar.name = "RearRoof"
        rar.scale = (ra_w / 2 + 0.1, ra_d / 2 + 0.1, 0.03)
        rar.rotation_euler = (0, 0, ra_angle)
        rar.data.materials.append(mat("Roof_rear", "#4A4A4A", 0.85))
        link(rar, collection)

    # Wooden back deck / elevated platform (from alley photo)
    if not has_storefront and random.random() > 0.6 and len(edges) >= 2:
        _, bdx1, bdy1, bdx2, bdy2, bdnx, bdny = edges[1]
        bd_angle = math.atan2(bdy2 - bdy1, bdx2 - bdy1) if abs(bdx2-bdx1) > 0.01 else 0
        bd_angle = math.atan2(bdy2 - bdy1, bdx2 - bdx1)
        bdmx = (bdx1 + bdx2) / 2 - bdnx * 2
        bdmy = (bdy1 + bdy2) / 2 - bdny * 2
        bd_w = random.uniform(2, 4)
        bd_h_deck = random.uniform(0.5, 2.0)
        m_deck_wd = mat("BackDeck", "#8A7050", 0.8)
        # Deck platform
        bpy.ops.mesh.primitive_cube_add(size=1, location=(bdmx, bdmy, bd_h_deck))
        bdo = bpy.context.active_object
        bdo.name = "BackDeck"
        bdo.scale = (bd_w / 2, 1.5, 0.04)
        bdo.rotation_euler = (0, 0, bd_angle)
        bdo.data.materials.append(m_deck_wd)
        link(bdo, collection)
        # Support posts
        for sp_off in [-bd_w/2 + 0.2, bd_w/2 - 0.2]:
            spx = bdmx + math.cos(bd_angle) * sp_off
            spy = bdmy + math.sin(bd_angle) * sp_off
            bpy.ops.mesh.primitive_cylinder_add(radius=0.05, depth=bd_h_deck,
                location=(spx, spy, bd_h_deck / 2), vertices=6)
            bpy.context.active_object.data.materials.append(m_deck_wd)
            link(bpy.context.active_object, collection)

    # Recycling bins at rear (from alley photo — blue bins behind houses)
    if not has_storefront and random.random() > 0.5 and len(edges) >= 2:
        _, rbx1, rby1, rbx2, rby2, rbnx_r, rbny_r = edges[1]
        rb_mx = (rbx1 + rbx2) / 2 - rbnx_r * 5
        rb_my = (rby1 + rby2) / 2 - rbny_r * 5
        for rbi in range(random.randint(1, 3)):
            rb_offset = rbi * 0.4
            bpy.ops.mesh.primitive_cube_add(size=1,
                location=(rb_mx + rb_offset, rb_my, 0.35))
            rbo = bpy.context.active_object
            rbo.name = f"RearBin_{rbi}"
            rbo.scale = (0.2, 0.25, 0.35)
            bin_mats = [mat("BlueBin2", "#2A2A8A", 0.7),
                        mat("GreenBin2", "#2A6A2A", 0.7),
                        mat("GreyBin2", "#5A5A5A", 0.7)]
            rbo.data.materials.append(random.choice(bin_mats))
            link(rbo, collection)

    # Covered porch entrance (brick column portico — from school photo)
    if isinstance(hcd, dict) and hcd.get("typology") and "institutional" in str(hcd.get("typology")).lower():
        if len(edges) > 0:
            el0_cp, cpx1, cpy1, cpx2, cpy2, cpnx, cpny = edges[0]
            cp_angle = math.atan2(cpy2 - cpy1, cpx2 - cpx1)
            cp_w = min(el0_cp * 0.3, 4.0)
            cp_d = 2.5
            cpx_c = cpx1 + (cpx2-cpx1) * 0.5 + cpnx * (cp_d / 2 + 0.1)
            cpy_c = cpy1 + (cpy2-cpy1) * 0.5 + cpny * (cp_d / 2 + 0.1)
            m_portico = mat("Portico", "#8A7A6A", 0.8)
            # Roof slab
            bpy.ops.mesh.primitive_cube_add(size=1, location=(cpx_c, cpy_c, 3.0))
            cpro = bpy.context.active_object
            cpro.name = "PorticoRoof"
            cpro.scale = (cp_w / 2, cp_d / 2, 0.1)
            cpro.rotation_euler = (0, 0, cp_angle)
            cpro.data.materials.append(m_portico)
            link(cpro, collection)
            # Brick columns
            for col_off in [-cp_w/2 + 0.3, cp_w/2 - 0.3]:
                colx = cpx_c + math.cos(cp_angle) * col_off + cpnx * cp_d * 0.4
                coly = cpy_c + math.sin(cp_angle) * col_off + cpny * cp_d * 0.4
                bpy.ops.mesh.primitive_cube_add(size=1, location=(colx, coly, 1.5))
                colo = bpy.context.active_object
                colo.name = "PorticoCol"
                colo.scale = (0.2, 0.2, 1.5)
                colo.data.materials.append(mat("BrickCol", hex_col, 0.75))
                link(colo, collection)

    # Rooftop letters/signage (from Kensington school — "KENSINGTON" letters on roof)
    if isinstance(hcd, dict) and ("school" in str(hcd.get("typology", "")).lower() or
                                    "institutional" in str(hcd.get("typology", "")).lower()):
        if len(edges) > 0:
            el0_rl, rlx1, rly1, rlx2, rly2, rlnx, rlny = edges[0]
            rl_angle = math.atan2(rly2 - rly1, rlx2 - rlx1)
            rlmx = (rlx1 + rlx2) / 2 + rlnx * 0.2
            rlmy = (rly1 + rly2) / 2 + rlny * 0.2
            m_letters = mat("RoofLetters", "#E8E0D0", 0.6)
            # Row of letter blocks on roof
            n_letters = random.randint(6, 10)
            for li_rl in range(n_letters):
                lt = (li_rl + 0.5) / n_letters
                lx_rl = rlx1 + (rlx2-rlx1) * lt + rlnx * 0.2
                ly_rl = rly1 + (rly2-rly1) * lt + rlny * 0.2
                bpy.ops.mesh.primitive_cube_add(size=1, location=(lx_rl, ly_rl, h + 0.6))
                llo = bpy.context.active_object
                llo.name = f"RoofLetter_{li_rl}"
                llo.scale = (0.3, 0.04, 0.4)
                llo.rotation_euler = (0, 0, rl_angle)
                llo.data.materials.append(m_letters)
                link(llo, collection)

    # Natural playground elements (log structures — from school photo)
    if isinstance(hcd, dict) and "school" in str(hcd.get("typology", "")).lower():
        if len(edges) > 0:
            el0_np, npx1, npy1, npx2, npy2, npnx, npny = edges[0]
            np_x = npx1 + (npx2-npx1) * 0.3 + npnx * 8
            np_y = npy1 + (npy2-npy1) * 0.3 + npny * 8
            m_log = mat("Log", "#6A5030", 0.85)
            for npi in range(random.randint(3, 6)):
                log_x = np_x + random.uniform(-3, 3)
                log_y = np_y + random.uniform(-3, 3)
                log_len = random.uniform(1.5, 3.0)
                log_angle = random.uniform(0, math.pi)
                bpy.ops.mesh.primitive_cylinder_add(radius=0.08, depth=log_len,
                    location=(log_x, log_y, 0.5), vertices=6)
                logo = bpy.context.active_object
                logo.name = f"PlayLog_{npi}"
                logo.rotation_euler = (random.uniform(0.2, 0.8), 0, log_angle)
                logo.data.materials.append(m_log)
                link(logo, collection)

    # Covered bike parking (bike shelter structure)
    if random.random() > 0.92 and len(edges) > 0:
        el0_bp, bpx1_s, bpy1_s, bpx2_s, bpy2_s, bpnx_s, bpny_s = edges[0]
        bp_angle_s = math.atan2(bpy2_s - bpy1_s, bpx2_s - bpx1_s)
        bpx_cs = bpx1_s + (bpx2_s-bpx1_s) * 0.8 + bpnx_s * 3
        bpy_cs = bpy1_s + (bpy2_s-bpy1_s) * 0.8 + bpny_s * 3
        m_bike_shelter = mat("BikeShelter", "#6A6A6A", 0.4)
        # Roof
        bpy.ops.mesh.primitive_cube_add(size=1, location=(bpx_cs, bpy_cs, 2.2))
        bps_r = bpy.context.active_object
        bps_r.name = "BikeShelterRoof"
        bps_r.scale = (1.5, 1.0, 0.03)
        bps_r.rotation_euler = (0, 0, bp_angle_s)
        bps_r.data.materials.append(m_bike_shelter)
        link(bps_r, collection)
        # Posts
        for bp_post in [-1.2, 1.2]:
            bpx_p = bpx_cs + math.cos(bp_angle_s) * bp_post
            bpy_p = bpy_cs + math.sin(bp_angle_s) * bp_post
            bpy.ops.mesh.primitive_cylinder_add(radius=0.03, depth=2.2,
                location=(bpx_p, bpy_p, 1.1), vertices=6)
            bpy.context.active_object.data.materials.append(m_bike_shelter)
            link(bpy.context.active_object, collection)

    # Dumpster/recycling container in alley (large green metal box)
    if random.random() > 0.8 and len(edges) >= 2:
        _, dux1, duy1, dux2, duy2, dunx, duny = edges[1]
        du_angle = math.atan2(duy2 - duy1, dux2 - dux1)
        dumx = (dux1 + dux2) / 2 - dunx * 6
        dumy = (duy1 + duy2) / 2 - duny * 6
        m_dumpster = mat("Dumpster", "#2A5A2A", 0.7)
        bpy.ops.mesh.primitive_cube_add(size=1, location=(dumx, dumy, 0.6))
        duo = bpy.context.active_object
        duo.name = "Dumpster"
        duo.scale = (0.8, 0.5, 0.6)
        duo.rotation_euler = (0, 0, du_angle + random.uniform(-0.3, 0.3))
        duo.data.materials.append(m_dumpster)
        link(duo, collection)
        # Lid
        bpy.ops.mesh.primitive_cube_add(size=1, location=(dumx, dumy, 1.22))
        dul = bpy.context.active_object
        dul.name = "DumpsterLid"
        dul.scale = (0.85, 0.55, 0.03)
        dul.rotation_euler = (random.uniform(-0.1, 0.1), 0, du_angle + random.uniform(-0.3, 0.3))
        dul.data.materials.append(mat("DumpsterLid", "#1A4A1A", 0.7))
        link(dul, collection)

    # Electrical service mast (pipe from utility pole to building)
    if random.random() > 0.5 and len(edges) > 0:
        el0_em, emx1, emy1, emx2, emy2, emnx, emny = edges[0]
        em_t = random.choice([0.05, 0.95])
        emx_p = emx1 + (emx2-emx1) * em_t + emnx * 0.08
        emy_p = emy1 + (emy2-emy1) * em_t + emny * 0.08
        m_mast_e = mat("ServiceMast", "#4A4A4A", 0.5)
        # Vertical conduit up building side
        bpy.ops.mesh.primitive_cylinder_add(radius=0.025, depth=h * 0.4,
            location=(emx_p, emy_p, h * 0.8), vertices=6)
        emo = bpy.context.active_object
        emo.name = "ServiceMast"
        emo.data.materials.append(m_mast_e)
        link(emo, collection)
        # Weatherhead (curved top piece)
        bpy.ops.mesh.primitive_cube_add(size=1, location=(emx_p + emnx * 0.1, emy_p + emny * 0.1, h))
        emh = bpy.context.active_object
        emh.name = "Weatherhead"
        emh.scale = (0.04, 0.04, 0.06)
        emh.data.materials.append(m_mast_e)
        link(emh, collection)

    # TV antenna (rabbit ears on some roofs)
    if random.random() > 0.85:
        ant_x_tv = cx + random.uniform(-1, 1)
        ant_y_tv = cy + random.uniform(-1, 1)
        m_tv = mat("TVAnt", "#6A6A6A", 0.4)
        bpy.ops.mesh.primitive_cylinder_add(radius=0.02, depth=1.5,
            location=(ant_x_tv, ant_y_tv, h + 0.75), vertices=4)
        bpy.context.active_object.data.materials.append(m_tv)
        link(bpy.context.active_object, collection)
        for tv_off in [0.3, 0.6, 0.9]:
            bpy.ops.mesh.primitive_cube_add(size=1,
                location=(ant_x_tv, ant_y_tv, h + tv_off))
            tve = bpy.context.active_object
            tve.scale = (0.4 - tv_off * 0.2, 0.01, 0.01)
            tve.data.materials.append(m_tv)
            link(tve, collection)

    # Brick interlocking driveway (patterned brick driveway — from row house photo)
    if not has_storefront and random.random() > 0.7 and len(edges) > 0:
        el0_bid, bidx1, bidy1, bidx2, bidy2, bidnx, bidny = edges[0]
        bid_angle = math.atan2(bidy2 - bidy1, bidx2 - bidx1)
        bidx_c = bidx1 + (bidx2-bidx1) * 0.7 + bidnx * 4
        bidy_c = bidy1 + (bidy2-bidy1) * 0.7 + bidny * 4
        m_interlock = mat("Interlock", "#A08068", 0.85)
        bpy.ops.mesh.primitive_cube_add(size=1, location=(bidx_c, bidy_c, 0.015))
        bido = bpy.context.active_object
        bido.name = "InterlockDrive"
        bido.scale = (1.3, 2.5, 0.015)
        bido.rotation_euler = (0, 0, bid_angle)
        bido.data.materials.append(m_interlock)
        link(bido, collection)

    # Metal/vinyl siding on upper floors (different material from brick ground floor)
    if facade_mat_name == "brick" and random.random() > 0.7 and floors >= 2 and len(edges) > 0:
        el0_vs, vsx1, vsy1, vsx2, vsy2, vsnx, vsny = edges[0]
        vs_angle = math.atan2(vsy2 - vsy1, vsx2 - vsx1)
        vsmx = (vsx1 + vsx2) / 2 + vsnx * 0.05
        vsmy = (vsy1 + vsy2) / 2 + vsny * 0.05
        siding_colours = ["#C8C0B0", "#D8D0C0", "#A0A098", "#B0A890"]
        vs_hex = random.choice(siding_colours)
        m_siding = mat(f"Siding_{vs_hex}", vs_hex, 0.8)
        # Panel covering upper portion of facade
        panel_h = floor_h * (floors - 1)
        bpy.ops.mesh.primitive_cube_add(size=1,
            location=(vsmx, vsmy, floor_h + panel_h / 2))
        vso = bpy.context.active_object
        vso.name = "SidingPanel"
        vso.scale = (el0_vs * 0.45 / 2, 0.015, panel_h / 2)
        vso.rotation_euler = (0, 0, vs_angle)
        vso.data.materials.append(m_siding)
        link(vso, collection)

    # Construction hoarding / chain link fence (buildings under construction)
    if condition in ("poor",) and random.random() > 0.5 and len(edges) > 0:
        el0_ch, chx1_h, chy1_h, chx2_h, chy2_h, chnx_h, chny_h = edges[0]
        ch_angle_h = math.atan2(chy2_h - chy1_h, chx2_h - chx1_h)
        chx_c = chx1_h + (chx2_h-chx1_h) * 0.5 + chnx_h * 2
        chy_c = chy1_h + (chy2_h-chy1_h) * 0.5 + chny_h * 2
        # Chain link fence
        m_chainlink = mat("ChainLink", "#8A8A8A", 0.3)
        bpy.ops.mesh.primitive_cube_add(size=1, location=(chx_c, chy_c, 1.0))
        clf = bpy.context.active_object
        clf.name = "ChainLink"
        clf.scale = (el0_ch * 0.8 / 2, 0.02, 1.0)
        clf.rotation_euler = (0, 0, ch_angle_h)
        clf.data.materials.append(m_chainlink)
        link(clf, collection)
        # Construction sign (yellow)
        bpy.ops.mesh.primitive_cube_add(size=1,
            location=(chx_c + random.uniform(-1, 1), chy_c + random.uniform(-1, 1), 1.3))
        cso = bpy.context.active_object
        cso.name = "ConstructionSign"
        cso.scale = (0.3, 0.02, 0.2)
        cso.rotation_euler = (0, 0, ch_angle_h)
        cso.data.materials.append(mat("ConstSign", "#FFCC00", 0.6))
        link(cso, collection)

    # Flagpole (Canadian flag — from fire station photo)
    if isinstance(hcd, dict) and ("institutional" in str(hcd.get("typology", "")).lower() or
                                    "fire" in str(params.get("building_name", "")).lower()):
        if len(edges) > 0:
            el0_fp, fpx1, fpy1, fpx2, fpy2, fpnx, fpny = edges[0]
            fpx_c = fpx1 + (fpx2-fpx1) * 0.3 + fpnx * 2
            fpy_c = fpy1 + (fpy2-fpy1) * 0.3 + fpny * 2
            m_flagpole = mat("FlagPole", "#C0C0C0", 0.4)
            # Pole
            bpy.ops.mesh.primitive_cylinder_add(radius=0.03, depth=6,
                location=(fpx_c, fpy_c, 3), vertices=6)
            fpo = bpy.context.active_object
            fpo.name = "FlagPole"
            fpo.data.materials.append(m_flagpole)
            link(fpo, collection)
            # Flag (red rectangle)
            bpy.ops.mesh.primitive_cube_add(size=1, location=(fpx_c + 0.4, fpy_c, 5.5))
            flo = bpy.context.active_object
            flo.name = "Flag"
            flo.scale = (0.5, 0.005, 0.25)
            flo.data.materials.append(mat("FlagRed", "#CC2222", 0.7))
            link(flo, collection)

    # Large arched garage/fire doors (from fire station photo — red doors)
    if "fire" in str(params.get("building_name", "")).lower() or \
       "station" in str(params.get("building_name", "")).lower():
        if len(edges) > 0:
            el0_fd, fdx1, fdy1, fdx2, fdy2, fdnx, fdny = edges[0]
            fd_angle = math.atan2(fdy2 - fdy1, fdx2 - fdx1)
            fd_t = 0.5
            fdx_c = fdx1 + (fdx2-fdx1) * fd_t + fdnx * 0.06
            fdy_c = fdy1 + (fdy2-fdy1) * fd_t + fdny * 0.06
            m_fire_door = mat("FireDoor", "#CC2222", 0.7)
            bpy.ops.mesh.primitive_cube_add(size=1, location=(fdx_c, fdy_c, 1.8))
            fdo_f = bpy.context.active_object
            fdo_f.name = "FireDoor"
            fdo_f.scale = (1.5, 0.08, 1.8)
            fdo_f.rotation_euler = (0, 0, fd_angle)
            fdo_f.data.materials.append(m_fire_door)
            link(fdo_f, collection)
            # Arch above fire door
            bpy.ops.mesh.primitive_torus_add(major_radius=0.8, minor_radius=0.1,
                location=(fdx_c, fdy_c, 3.6), major_segments=8, minor_segments=6)
            fda = bpy.context.active_object
            fda.name = "FireDoorArch"
            fda.scale = (1, 0.3, 1)
            fda.rotation_euler = (0, 0, fd_angle)
            fda.data.materials.append(mat("FireDoorArch", trim_hex, 0.65))
            link(fda, collection)

    # Building name lettering on facade (from fire station "No 8 HOSE STATION")
    bldg_name = params.get("building_name", "")
    if ("station" in bldg_name.lower() or "church" in bldg_name.lower() or
        "school" in bldg_name.lower()) and len(edges) > 0:
        el0_lt, ltx1_f, lty1_f, ltx2_f, lty2_f, ltnx_f, ltny_f = edges[0]
        lt_angle_f = math.atan2(lty2_f - lty1_f, ltx2_f - ltx1_f)
        ltmx = (ltx1_f + ltx2_f) / 2 + ltnx_f * 0.08
        ltmy = (lty1_f + lty2_f) / 2 + ltny_f * 0.08
        m_facade_text = mat("FacadeText", "#E8E0D0", 0.6)
        # Text band across facade
        bpy.ops.mesh.primitive_cube_add(size=1, location=(ltmx, ltmy, h * 0.65))
        lto_f = bpy.context.active_object
        lto_f.name = "FacadeLettering"
        lto_f.scale = (el0_lt * 0.5 / 2, 0.02, 0.12)
        lto_f.rotation_euler = (0, 0, lt_angle_f)
        lto_f.data.materials.append(m_facade_text)
        link(lto_f, collection)

    # Copper/green roof accent (aged copper roof sections — from panorama photo)
    if random.random() > 0.9 and "gable" in roof_type:
        ridge_h_cu = min((max(xs)-min(xs)) * 0.35, 2.5)
        m_copper = mat("CopperRoof", "#4A8A6A", 0.6)
        bpy.ops.mesh.primitive_cube_add(size=1, location=(cx, cy, h + ridge_h_cu * 0.3))
        curo = bpy.context.active_object
        curo.name = "CopperAccent"
        curo.scale = (1.5, 0.5, 0.04)
        curo.data.materials.append(m_copper)
        link(curo, collection)

    # Green tarp / protective covering (common on porches/yards in March)
    if random.random() > 0.85 and len(edges) >= 2:
        _, tpx1, tpy1, tpx2, tpy2, tpnx_t, tpny_t = edges[1]
        tpx_c = (tpx1 + tpx2) / 2 - tpnx_t * 3
        tpy_c = (tpy1 + tpy2) / 2 - tpny_t * 3
        m_tarp = mat("Tarp", "#2A6A4A", 0.7)
        bpy.ops.mesh.primitive_cube_add(size=1, location=(tpx_c, tpy_c, 0.5))
        tpo = bpy.context.active_object
        tpo.name = "Tarp"
        tpo.scale = (random.uniform(0.5, 1.5), random.uniform(0.5, 1.0), 0.01)
        tpo.rotation_euler = (random.uniform(-0.1, 0.1), random.uniform(-0.1, 0.1), random.uniform(0, 6.28))
        tpo.data.materials.append(m_tarp)
        link(tpo, collection)

    # Green utility transformer box (street-level, from graffiti box photo)
    if random.random() > 0.9 and len(edges) > 0:
        el0_ub2, ubx1_2, uby1_2, ubx2_2, uby2_2, ubnx_2, ubny_2 = edges[0]
        ub_angle_2 = math.atan2(uby2_2 - uby1_2, ubx2_2 - ubx1_2)
        ubx_c2 = ubx1_2 + (ubx2_2-ubx1_2) * random.choice([0.1, 0.9]) + ubnx_2 * 3
        uby_c2 = uby1_2 + (uby2_2-uby1_2) * random.choice([0.1, 0.9]) + ubny_2 * 3
        m_transformer = mat("Transformer", "#5A7A5A", 0.7)
        bpy.ops.mesh.primitive_cube_add(size=1, location=(ubx_c2, uby_c2, 0.5))
        ubo2 = bpy.context.active_object
        ubo2.name = "TransformerBox"
        ubo2.scale = (0.5, 0.3, 0.5)
        ubo2.rotation_euler = (0, 0, ub_angle_2)
        ubo2.data.materials.append(m_transformer)
        link(ubo2, collection)
        # Vents on sides
        for vent_z in [0.3, 0.7]:
            bpy.ops.mesh.primitive_cube_add(size=1,
                location=(ubx_c2 + ubnx_2 * 0.16, uby_c2 + ubny_2 * 0.16, vent_z))
            vnt = bpy.context.active_object
            vnt.name = "TransVent"
            vnt.scale = (0.15, 0.01, 0.05)
            vnt.rotation_euler = (0, 0, ub_angle_2)
            vnt.data.materials.append(mat("TransVent", "#4A6A4A", 0.6))
            link(vnt, collection)

    # Coloured accent trim (different colour trim from main facade — from photos)
    if random.random() > 0.5 and len(edges) > 0:
        accent_colours = ["#CC4444", "#4444CC", "#44CC44", "#CCCC44", "#CC44CC", "#44CCCC"]
        ac_hex = random.choice(accent_colours)
        if ac_hex != hex_col and ac_hex != trim_hex:
            el0_ac, acx1_t, acy1_t, acx2_t, acy2_t, acnx_t, acny_t = edges[0]
            ac_angle_t = math.atan2(acy2_t - acy1_t, acx2_t - acx1_t)
            # Thin accent line at window sill level
            for fi_ac in range(min(int(floors), 3)):
                ac_z = fi_ac * floor_h + floor_h * 0.28
                acmx = (acx1_t + acx2_t) / 2 + acnx_t * 0.07
                acmy = (acy1_t + acy2_t) / 2 + acny_t * 0.07
                bpy.ops.mesh.primitive_cube_add(size=1, location=(acmx, acmy, ac_z))
                aco = bpy.context.active_object
                aco.name = f"AccentTrim_{fi_ac}"
                aco.scale = (el0_ac * 0.85 / 2, 0.015, 0.015)
                aco.rotation_euler = (0, 0, ac_angle_t)
                aco.data.materials.append(mat(f"Accent_{ac_hex}", ac_hex, 0.65))
                link(aco, collection)


def main():
    # Clear scene
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete()
    for c in list(bpy.data.collections):
        bpy.data.collections.remove(c)

    print("=== Bellevue Demo: Footprint-Based Generation ===")

    # Ground plane (centered on origin after transform)
    c_env = col("Ground")
    bpy.ops.mesh.primitive_plane_add(size=1, location=(0, 0, -0.05))
    g = bpy.context.active_object
    g.name = "Ground"
    g.scale = (400, 400, 1)
    g.data.materials.append(mat("Ground", "#5A6A4A", 0.95))
    link(g, c_env)

    # Buildings from gis_scene building_positions (SAME source as roads/footprints)
    c_bldg = col("Buildings")
    bldg_count = 0

    bp = GIS.get("building_positions", {})

    for addr, pos in sorted(bp.items()):
        bx, by = pos['x'], pos['y']
        if not (X_MIN <= bx <= X_MAX and Y_MIN <= by <= Y_MAX):
            continue

        # Determine facing direction from street name + position.
        # Bellevue/Wales/Leonard run NNW-SSE: west side (x<-70) faces ENE (73),
        #   east side faces WSW (253)
        # Augusta/Nassau/Denison/Oxford run roughly ENE-WSW: south side faces NNW (343),
        #   north side faces SSE (163)
        street = addr.split()
        street_name = ""
        for si, s in enumerate(street):
            if s in ("Ave", "St", "Pl", "Sq"):
                street_name = " ".join(street[max(0,si-1):si+1])
                break

        # N-S streets: run roughly NNW-SSE (verified from building_positions data)
        # x-cutoff: buildings west of cutoff face ENE (73), east face WSW (253)
        ns_streets = {
            "Augusta Ave": 32,       # x_mid=32
            "Bellevue Ave": -85,     # x_mid=-85
            "Spadina Ave": 241,      # x_mid=241 (east perimeter)
            "Kensington Ave": 171,   # x_mid=171
            "Lippincott St": -289,   # x_mid=-289 (far west)
            "Bathurst St": -326,     # x_mid=-326 (west perimeter)
            "Leonard Ave": -179,     # x_mid=-179
            "Kensington Pl": 112,    # x_mid=112 (N-S verified)
            "Baillie Pl": 254,       # x_mid=254 (Glen Baillie, N-S)
        }
        # E-W streets: run roughly ENE-WSW (verified from building_positions data)
        # y-cutoff: buildings south of cutoff face NNW (343), north face SSE (163)
        ew_streets = {
            "Oxford St": 151,        # y_mid=151
            "Nassau St": 41,         # y_mid=41
            "Wales Ave": -228,       # y_mid=-228 (E-W verified)
            "Dundas St": -266,       # y_mid=-266 (north perimeter)
            "Baldwin St": -3,        # y_mid=-3
            "College St": 227,       # y_mid=227 (south perimeter)
            "Hickory St": -280,      # y_mid=-280 (E-W verified)
            "Leonard Pl": -164,      # y_mid=-164 (E-W verified)
            "St Andrew St": -100,
            "Fitzroy Terr": -100,
            "Carlyle St": -100,
        }

        if street_name in ns_streets:
            x_cutoff = ns_streets[street_name]
            facing_bearing = 73 if bx < x_cutoff else 253
        elif street_name in ew_streets:
            y_cutoff = ew_streets[street_name]
            facing_bearing = 343 if by < y_cutoff else 163
        elif street_name in ("Denison Sq",):
            # Denison Sq: E-W, y_mid=-110
            facing_bearing = 163 if by > -110 else 343
        elif street_name in ("Denison Ave",):
            # Diagonal, runs NE-SW, x_mid=-11
            facing_bearing = 73 if bx < -11 else 253
        elif street_name in ("Casimir St",):
            # Diagonal, runs NE-SW, x_mid=-124
            facing_bearing = 73 if bx < -124 else 253
        else:
            # Fallback: use bearing data
            facing_bearing = pos.get('bearing_deg', 73)

        rot_deg = (360 - facing_bearing) % 360
        rot_rad = math.radians(rot_deg)
        # Apply scene rotation to building rotation
        rot_rad = scene_transform_angle(rot_rad)
        massing_h = pos.get('massing_height_m')

        # Get params
        p = PARAMS.get(addr, {})
        stories = p.get('floors', 2) or 2
        h = massing_h or p.get('total_height_m') or stories * 3.2
        if h <= 0:
            h = stories * 3.2
        width = p.get('facade_width_m', 5.2) or 5.2
        depth = 10.0  # front building portion only

        # Transform position to scene coords
        sbx, sby = scene_transform(bx, by)

        # Create box CENTERED on the transformed position
        hw, hd = width / 2, depth / 2

        # 4 corners centered on (0,0)
        corners = [(-hw, hd), (hw, hd), (hw, -hd), (-hw, -hd)]

        cos_r, sin_r = math.cos(rot_rad), math.sin(rot_rad)
        ring = [(lx*cos_r - ly*sin_r + sbx, lx*sin_r + ly*cos_r + sby) for lx, ly in corners]

        create_building_from_footprint(ring, c_bldg, override_h=h)
        bldg_count += 1

    print(f"  Buildings (from gis_scene positions): {bldg_count}")

    # Front fences
    c_fence = col("Fences")
    m_fence = mat("IronFence", "#2A2A2A", 0.4)
    fence_count = 0
    for addr, pos in sorted(bp.items()):
        bx, by = pos['x'], pos['y']
        if not (X_MIN <= bx <= X_MAX and Y_MIN <= by <= Y_MAX):
            continue
        # Determine facing from same logic
        parts = addr.split()
        sn = ""
        for si, s in enumerate(parts):
            if s in ("Ave", "St", "Pl", "Sq"):
                sn = " ".join(parts[max(0,si-1):si+1])
                break
        ns_cutoffs_f = {"Bellevue Ave": -85, "Augusta Ave": 32,
                        "Leonard Ave": -179, "Lippincott St": -289,
                        "Kensington Ave": 171, "Kensington Pl": 112}
        ew_cutoffs_f = {"Nassau St": 41, "Oxford St": 151, "Baldwin St": -3,
                        "Wales Ave": -228, "Hickory St": -280}
        if sn in ns_cutoffs_f:
            facing = 73 if bx < ns_cutoffs_f[sn] else 253
        elif sn in ew_cutoffs_f:
            facing = 343 if by < ew_cutoffs_f[sn] else 163
        else:
            continue
        rot = math.radians((360 - facing) % 360)
        rot = scene_transform_angle(rot)
        sbx, sby = scene_transform(bx, by)

        width = 5.2
        # Fence runs along the front, offset by depth/2 + 1m
        cos_r, sin_r = math.cos(rot), math.sin(rot)
        fence_offset = 6.0  # depth/2 + 1m gap
        fx = sbx + (-math.sin(rot)) * fence_offset  # perpendicular to facing
        fy = sby + math.cos(rot) * fence_offset

        # Actually simpler: fence at front of building
        front_nx = -math.sin(rot)  # facing direction x
        front_ny = math.cos(rot)   # facing direction y
        fx = sbx + front_nx * 6.0
        fy = sby + front_ny * 6.0

        bpy.ops.mesh.primitive_cube_add(size=1, location=(fx, fy, 0.45))
        fo = bpy.context.active_object
        fo.name = f"Fence_{fence_count}"
        fo.scale = (width / 2, 0.02, 0.45)
        fo.rotation_euler = (0, 0, rot)
        fo.data.materials.append(m_fence)
        link(fo, c_fence)
        fence_count += 1
    print(f"  Fences: {fence_count}")

    # Trash/recycling bins at front of some houses
    c_bins = col("StreetBins")
    m_bin_green = mat("GreenBin", "#2A6A2A", 0.7)
    m_bin_blue = mat("BlueBin", "#2A2A8A", 0.7)
    m_bin_grey = mat("GreyBin", "#5A5A5A", 0.7)
    bin_count = 0
    for addr, pos in sorted(bp.items()):
        bx, by = pos['x'], pos['y']
        if not (X_MIN <= bx <= X_MAX and Y_MIN <= by <= Y_MAX):
            continue
        # Only 30% of houses have visible bins
        if random.random() > 0.3:
            continue
        sbx, sby = scene_transform(bx, by)
        # Place bins offset from building front
        bin_offset = random.uniform(6, 8)
        # Use a random angle offset
        ba = random.uniform(0, 6.28)
        bin_x = sbx + math.cos(ba) * 2
        bin_y = sby + math.sin(ba) * 2

        for bi, bm in enumerate([m_bin_green, m_bin_blue, m_bin_grey]):
            if random.random() > 0.5:
                continue
            bpy.ops.mesh.primitive_cube_add(size=1,
                location=(bin_x + bi * 0.4, bin_y, 0.35))
            bo = bpy.context.active_object
            bo.name = f"Bin_{bin_count}"
            bo.scale = (0.2, 0.25, 0.35)
            bo.data.materials.append(bm)
            link(bo, c_bins)
            bin_count += 1
    print(f"  Bins: {bin_count}")

    # Parked cars along roads
    c_cars = col("ParkedCars")
    car_colours = ["#2A2A2A", "#8A8A8A", "#C0C0C0", "#1A3A6A", "#6A1A1A", "#E8E0D0", "#3A3A3A"]
    car_count = 0
    for r in GIS.get("roads", []):
        coords = r.get("coords", [])
        if len(coords) < 2:
            continue
        r_cx = sum(c[0] for c in coords) / len(coords)
        r_cy = sum(c[1] for c in coords) / len(coords)
        if not (X_MIN - 10 <= r_cx <= X_MAX + 10 and Y_MIN - 10 <= r_cy <= Y_MAX + 10):
            continue
        for ci in range(len(coords) - 1):
            x1c, y1c = coords[ci]
            x2c, y2c = coords[ci + 1]
            seg_len = math.sqrt((x2c-x1c)**2 + (y2c-y1c)**2)
            if seg_len < 10:
                continue
            sdx, sdy = (x2c-x1c)/seg_len, (y2c-y1c)/seg_len
            snx_c, sny_c = -sdy, sdx
            n_cars = int(seg_len / 15)
            for cari in range(n_cars):
                if random.random() > 0.6:
                    continue
                t_car = (cari + 0.5) / max(n_cars, 1)
                car_x = x1c + (x2c-x1c) * t_car + snx_c * 4.5
                car_y = y1c + (y2c-y1c) * t_car + sny_c * 4.5
                tcx_c, tcy_c = scene_transform(car_x, car_y)
                car_angle = math.atan2(sdy, sdx) + _SCENE_ROT
                car_hex = random.choice(car_colours)
                m_car = mat(f"Car_{car_hex}", car_hex, 0.4)
                bpy.ops.mesh.primitive_cube_add(size=1, location=(tcx_c, tcy_c, 0.6))
                cb = bpy.context.active_object
                cb.name = f"CarBody_{car_count}"
                cb.scale = (2.2, 0.9, 0.5)
                cb.rotation_euler = (0, 0, car_angle)
                cb.data.materials.append(m_car)
                link(cb, c_cars)
                bpy.ops.mesh.primitive_cube_add(size=1, location=(tcx_c, tcy_c, 1.15))
                cr = bpy.context.active_object
                cr.name = f"CarRoof_{car_count}"
                cr.scale = (1.2, 0.8, 0.35)
                cr.rotation_euler = (0, 0, car_angle)
                cr.data.materials.append(m_car)
                link(cr, c_cars)
                car_count += 1
    print(f"  Parked cars: {car_count}")

    # Mailboxes
    c_mail = col("Mailboxes")
    m_mailbox = mat("Mailbox", "#CC2222", 0.6)
    mail_count = 0
    for addr, pos in sorted(bp.items()):
        bx_m, by_m = pos['x'], pos['y']
        if not (X_MIN <= bx_m <= X_MAX and Y_MIN <= by_m <= Y_MAX):
            continue
        if random.random() > 0.4:
            continue
        sbx_m, sby_m = scene_transform(bx_m, by_m)
        mx_m = sbx_m + random.uniform(-2, 2)
        my_m = sby_m + random.uniform(-2, 2)
        bpy.ops.mesh.primitive_cylinder_add(radius=0.03, depth=1.0, location=(mx_m, my_m, 0.5), vertices=6)
        bpy.context.active_object.data.materials.append(mat("MailPost", "#4A4A4A", 0.5))
        link(bpy.context.active_object, c_mail)
        bpy.ops.mesh.primitive_cube_add(size=1, location=(mx_m, my_m, 1.05))
        mb = bpy.context.active_object
        mb.name = f"Mailbox_{mail_count}"
        mb.scale = (0.15, 0.1, 0.12)
        mb.data.materials.append(m_mailbox)
        link(mb, c_mail)
        mail_count += 1
    print(f"  Mailboxes: {mail_count}")

    # Sidewalk curbs along roads
    c_curbs = col("Curbs")
    m_curb = mat("Curb", "#B0B0A8", 0.85)
    curb_count = 0
    for r in GIS.get("roads", []):
        coords = r.get("coords", [])
        if len(coords) < 2:
            continue
        r_cx = sum(c[0] for c in coords) / len(coords)
        r_cy = sum(c[1] for c in coords) / len(coords)
        if not (X_MIN - 20 <= r_cx <= X_MAX + 20 and Y_MIN - 20 <= r_cy <= Y_MAX + 20):
            continue
        for side in [-1, 1]:
            curb_coords = []
            for ci_c in range(len(coords)):
                xc, yc = coords[ci_c]
                if ci_c < len(coords) - 1:
                    dxc, dyc = coords[ci_c+1][0] - xc, coords[ci_c+1][1] - yc
                else:
                    dxc, dyc = xc - coords[ci_c-1][0], yc - coords[ci_c-1][1]
                sl = max(math.sqrt(dxc*dxc + dyc*dyc), 0.01)
                nxc, nyc = -dyc/sl * 3.8 * side, dxc/sl * 3.8 * side
                curb_coords.append(scene_transform(xc + nxc, yc + nyc))
            if len(curb_coords) >= 2:
                cmesh = road_mesh(curb_coords, 0.2, f"Curb_{curb_count}")
                if cmesh:
                    cobj = bpy.data.objects.new(f"Curb_{curb_count}", cmesh)
                    cobj.location.z = 0.08
                    cobj.data.materials.append(m_curb)
                    link(cobj, c_curbs)
                    curb_count += 1
    print(f"  Curbs: {curb_count}")

    # Power lines between poles
    c_wires = col("PowerLines")
    m_wire_pl = mat("Wire", "#1A1A1A", 0.3)
    wire_count = 0
    pole_positions = []
    for pt in GIS.get("field", {}).get("poles", []):
        px_w, py_w = pt['x'], pt['y']
        if not (X_MIN - 10 <= px_w <= X_MAX + 10 and Y_MIN - 10 <= py_w <= Y_MAX + 10):
            continue
        pole_positions.append(scene_transform(px_w, py_w))
    used_pairs = set()
    for i_w, (px1_w, py1_w) in enumerate(pole_positions):
        best_d_w = 999
        best_j_w = -1
        for j_w, (px2_w, py2_w) in enumerate(pole_positions):
            if i_w == j_w:
                continue
            dw = math.sqrt((px2_w-px1_w)**2 + (py2_w-py1_w)**2)
            if dw < best_d_w and dw < 40:
                pair_w = (min(i_w, j_w), max(i_w, j_w))
                if pair_w not in used_pairs:
                    best_d_w = dw
                    best_j_w = j_w
        if best_j_w >= 0:
            px2_w, py2_w = pole_positions[best_j_w]
            used_pairs.add((min(i_w, best_j_w), max(i_w, best_j_w)))
            w_angle = math.atan2(py2_w - py1_w, px2_w - px1_w)
            w_len = math.sqrt((px2_w-px1_w)**2 + (py2_w-py1_w)**2)
            wmx, wmy = (px1_w + px2_w) / 2, (py1_w + py2_w) / 2
            bpy.ops.mesh.primitive_cylinder_add(radius=0.01, depth=w_len, location=(wmx, wmy, 7.0), vertices=4)
            wo = bpy.context.active_object
            wo.name = f"Wire_{wire_count}"
            wo.rotation_euler = (math.pi/2, 0, w_angle)
            wo.data.materials.append(m_wire_pl)
            link(wo, c_wires)
            wire_count += 1
    print(f"  Power lines: {wire_count}")

    # Street signs at intersections
    c_signs = col("StreetSigns")
    m_sign_green = mat("SignGreen", "#1A5A2A", 0.6)
    sign_count = 0
    for pt in GIS.get("field", {}).get("signs", []):
        xs_s, ys_s = pt['x'], pt['y']
        if not (X_MIN - 10 <= xs_s <= X_MAX + 10 and Y_MIN - 10 <= ys_s <= Y_MAX + 10):
            continue
        tsx, tsy = scene_transform(xs_s, ys_s)
        bpy.ops.mesh.primitive_cylinder_add(radius=0.04, depth=2.8, location=(tsx, tsy, 1.4), vertices=6)
        bpy.context.active_object.data.materials.append(mat("SignPole", "#4A4A4A", 0.5))
        link(bpy.context.active_object, c_signs)
        bpy.ops.mesh.primitive_cube_add(size=1, location=(tsx, tsy, 2.6))
        ss = bpy.context.active_object
        ss.name = f"Sign_{sign_count}"
        ss.scale = (0.5, 0.02, 0.15)
        ss.rotation_euler = (0, 0, random.uniform(0, math.pi))
        ss.data.materials.append(m_sign_green)
        link(ss, c_signs)
        sign_count += 1
    print(f"  Street signs: {sign_count}")

    # Manhole covers on roads
    c_manholes = col("Manholes")
    m_manhole = mat("Manhole", "#3A3A3A", 0.9)
    mh_count = 0
    for r in GIS.get("roads", []):
        coords = r.get("coords", [])
        if len(coords) < 2:
            continue
        r_cx = sum(c[0] for c in coords) / len(coords)
        r_cy = sum(c[1] for c in coords) / len(coords)
        if not (X_MIN - 10 <= r_cx <= X_MAX + 10 and Y_MIN - 10 <= r_cy <= Y_MAX + 10):
            continue
        # One manhole per road segment midpoint
        for ci_mh in range(len(coords) - 1):
            if random.random() > 0.3:
                continue
            mx_mh = (coords[ci_mh][0] + coords[ci_mh+1][0]) / 2
            my_mh = (coords[ci_mh][1] + coords[ci_mh+1][1]) / 2
            tmx, tmy = scene_transform(mx_mh, my_mh)
            bpy.ops.mesh.primitive_cylinder_add(radius=0.3, depth=0.02, location=(tmx, tmy, 0.03), vertices=12)
            mh = bpy.context.active_object
            mh.name = f"Manhole_{mh_count}"
            mh.data.materials.append(m_manhole)
            link(mh, c_manholes)
            mh_count += 1
    print(f"  Manholes: {mh_count}")

    # Sidewalk surfaces between curbs and buildings
    c_sidewalks = col("Sidewalks")
    m_sidewalk = mat("Sidewalk", "#C0C0B8", 0.85)
    sw_count = 0
    for r in GIS.get("roads", []):
        coords = r.get("coords", [])
        if len(coords) < 2:
            continue
        r_cx = sum(c[0] for c in coords) / len(coords)
        r_cy = sum(c[1] for c in coords) / len(coords)
        if not (X_MIN - 20 <= r_cx <= X_MAX + 20 and Y_MIN - 20 <= r_cy <= Y_MAX + 20):
            continue
        for side_sw in [-1, 1]:
            sw_coords = []
            for ci_sw in range(len(coords)):
                xsw, ysw = coords[ci_sw]
                if ci_sw < len(coords) - 1:
                    dxsw, dysw = coords[ci_sw+1][0] - xsw, coords[ci_sw+1][1] - ysw
                else:
                    dxsw, dysw = xsw - coords[ci_sw-1][0], ysw - coords[ci_sw-1][1]
                sl_sw = max(math.sqrt(dxsw*dxsw + dysw*dysw), 0.01)
                nxsw = -dysw/sl_sw * 5.0 * side_sw
                nysw = dxsw/sl_sw * 5.0 * side_sw
                sw_coords.append(scene_transform(xsw + nxsw, ysw + nysw))
            if len(sw_coords) >= 2:
                sw_mesh = road_mesh(sw_coords, 1.5, f"Sidewalk_{sw_count}")
                if sw_mesh:
                    sw_obj = bpy.data.objects.new(f"Sidewalk_{sw_count}", sw_mesh)
                    sw_obj.location.z = 0.04
                    sw_obj.data.materials.append(m_sidewalk)
                    link(sw_obj, c_sidewalks)
                    sw_count += 1
    print(f"  Sidewalks: {sw_count}")

    # Driveway pads (concrete patches at some house fronts)
    c_driveways = col("Driveways")
    m_driveway = mat("Driveway", "#A0A098", 0.85)
    dw_count = 0
    for addr, pos in sorted(bp.items()):
        bx_dw, by_dw = pos['x'], pos['y']
        if not (X_MIN <= bx_dw <= X_MAX and Y_MIN <= by_dw <= Y_MAX):
            continue
        if random.random() > 0.25:
            continue
        sbx_dw, sby_dw = scene_transform(bx_dw, by_dw)
        dw_x = sbx_dw + random.uniform(-3, 3)
        dw_y = sby_dw + random.uniform(-3, 3)
        bpy.ops.mesh.primitive_cube_add(size=1, location=(dw_x, dw_y, 0.02))
        dw_obj = bpy.context.active_object
        dw_obj.name = f"Driveway_{dw_count}"
        dw_obj.scale = (1.5, 2.5, 0.02)
        dw_obj.rotation_euler = (0, 0, random.uniform(-0.3, 0.3))
        dw_obj.data.materials.append(m_driveway)
        link(dw_obj, c_driveways)
        dw_count += 1
    print(f"  Driveways: {dw_count}")

    # Benches in park area
    c_benches = col("ParkBenches")
    m_bench_wood = mat("BenchWood", "#8B6914", 0.8)
    m_bench_metal = mat("BenchMetal", "#3A3A3A", 0.5)
    bench_count = 0
    park_cx_b, park_cy_b = scene_transform(6.0, -150.0)  # approx park center
    for bi_b in range(8):
        b_angle = bi_b * math.pi / 4
        bx_b = park_cx_b + math.cos(b_angle) * random.uniform(15, 35)
        by_b = park_cy_b + math.sin(b_angle) * random.uniform(15, 35)
        # Seat
        bpy.ops.mesh.primitive_cube_add(size=1, location=(bx_b, by_b, 0.45))
        bs = bpy.context.active_object
        bs.name = f"Bench_{bench_count}"
        bs.scale = (0.8, 0.25, 0.025)
        bs.rotation_euler = (0, 0, b_angle + math.pi/2)
        bs.data.materials.append(m_bench_wood)
        link(bs, c_benches)
        # Back
        bpy.ops.mesh.primitive_cube_add(size=1, location=(bx_b - 0.12*math.sin(b_angle+math.pi/2), by_b + 0.12*math.cos(b_angle+math.pi/2), 0.7))
        bb_o = bpy.context.active_object
        bb_o.name = f"BenchBack_{bench_count}"
        bb_o.scale = (0.8, 0.02, 0.15)
        bb_o.rotation_euler = (0, 0, b_angle + math.pi/2)
        bb_o.data.materials.append(m_bench_wood)
        link(bb_o, c_benches)
        # Legs
        for leg_off in [-0.35, 0.35]:
            lx_b = bx_b + math.cos(b_angle + math.pi/2) * leg_off
            ly_b = by_b + math.sin(b_angle + math.pi/2) * leg_off
            bpy.ops.mesh.primitive_cube_add(size=1, location=(lx_b, ly_b, 0.22))
            bl = bpy.context.active_object
            bl.name = f"BenchLeg_{bench_count}"
            bl.scale = (0.02, 0.2, 0.22)
            bl.rotation_euler = (0, 0, b_angle + math.pi/2)
            bl.data.materials.append(m_bench_metal)
            link(bl, c_benches)
        bench_count += 1
    print(f"  Park benches: {bench_count}")

    # Playground in park
    c_playground = col("Playground")
    pg_cx, pg_cy = scene_transform(15.0, -140.0)  # NE area of park
    m_play_orange = mat("PlayOrange", "#E06020", 0.6)
    m_play_blue = mat("PlayBlue", "#2060C0", 0.6)
    # Posts
    for pdx, pdy in [(-2,-1.5),(2,-1.5),(-2,1.5),(2,1.5)]:
        bpy.ops.mesh.primitive_cylinder_add(radius=0.06, depth=3, location=(pg_cx+pdx, pg_cy+pdy, 1.5), vertices=8)
        bpy.context.active_object.data.materials.append(m_play_orange)
        link(bpy.context.active_object, c_playground)
    # Top bars
    for pdy_t in [-1.5, 1.5]:
        bpy.ops.mesh.primitive_cylinder_add(radius=0.04, depth=4, location=(pg_cx, pg_cy+pdy_t, 3), vertices=8)
        tb = bpy.context.active_object
        tb.rotation_euler[1] = math.pi/2
        tb.data.materials.append(m_play_orange)
        link(tb, c_playground)
    # Slide
    bpy.ops.mesh.primitive_cube_add(size=1, location=(pg_cx+3, pg_cy, 1))
    sl_o = bpy.context.active_object
    sl_o.scale = (1.5, 0.4, 0.03)
    sl_o.rotation_euler[1] = -0.5
    sl_o.data.materials.append(m_play_blue)
    link(sl_o, c_playground)
    # Platform
    bpy.ops.mesh.primitive_cube_add(size=1, location=(pg_cx, pg_cy, 2.8))
    pl_o = bpy.context.active_object
    pl_o.scale = (2, 1.5, 0.05)
    pl_o.data.materials.append(mat("PGPlatform", "#888888", 0.6))
    link(pl_o, c_playground)
    print(f"  Playground: 1")

    # Park lamp posts
    c_park_lamps = col("ParkLamps")
    m_park_lamp = mat("ParkLamp", "#505050", 0.4)
    m_park_light = mat("ParkLight", "#E0E0D0", 0.3)
    for pli in range(6):
        pl_angle = pli * math.pi / 3
        plx = park_cx_b + math.cos(pl_angle) * 25
        ply = park_cy_b + math.sin(pl_angle) * 25
        bpy.ops.mesh.primitive_cylinder_add(radius=0.05, depth=4.5, location=(plx, ply, 2.25), vertices=8)
        bpy.context.active_object.data.materials.append(m_park_lamp)
        link(bpy.context.active_object, c_park_lamps)
        bpy.ops.mesh.primitive_cube_add(size=1, location=(plx, ply, 4.5))
        plh = bpy.context.active_object
        plh.scale = (0.3, 0.15, 0.05)
        plh.data.materials.append(m_park_light)
        link(plh, c_park_lamps)
    print(f"  Park lamps: 6")

    # Park boulders (decorative rocks scattered in park)
    c_boulders = col("ParkBoulders")
    m_boulder = mat("Boulder", "#787878", 0.85)
    for boul_i in range(10):
        boul_x = park_cx_b + random.uniform(-30, 30)
        boul_y = park_cy_b + random.uniform(-25, 25)
        boul_r = random.uniform(0.3, 0.6)
        bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=2, radius=boul_r, location=(boul_x, boul_y, boul_r * 0.4))
        bo_b = bpy.context.active_object
        bo_b.name = f"Boulder_{boul_i}"
        bo_b.scale = (random.uniform(0.8, 1.3), random.uniform(0.8, 1.3), random.uniform(0.4, 0.7))
        bo_b.rotation_euler = (random.uniform(0, 0.3), random.uniform(0, 0.3), random.uniform(0, 6.28))
        bo_b.data.materials.append(m_boulder)
        link(bo_b, c_boulders)
    print(f"  Park boulders: 10")

    # Park paths (crossing paths through the park)
    c_park_paths = col("ParkPaths")
    m_park_path = mat("ParkPath", "#A0A0A0", 0.75)
    # Cross paths through park center
    park_paths = [
        [(park_cx_b - 40, park_cy_b), (park_cx_b + 40, park_cy_b)],
        [(park_cx_b, park_cy_b - 30), (park_cx_b, park_cy_b + 30)],
        [(park_cx_b - 30, park_cy_b - 20), (park_cx_b + 30, park_cy_b + 20)],
    ]
    for pp_i, pp_coords in enumerate(park_paths):
        pp_mesh = road_mesh(pp_coords, 2.0, f"ParkPath_{pp_i}")
        if pp_mesh:
            pp_obj = bpy.data.objects.new(f"ParkPath_{pp_i}", pp_mesh)
            pp_obj.location.z = 0.02
            pp_obj.data.materials.append(m_park_path)
            link(pp_obj, c_park_paths)
    print(f"  Park paths: {len(park_paths)}")

    # Fire hydrants along streets
    c_hydrants = col("Hydrants")
    m_hydrant_y = mat("HydrantYellow", "#E0C020", 0.5)
    hy_count = 0
    for r in GIS.get("roads", []):
        coords = r.get("coords", [])
        if len(coords) < 2:
            continue
        r_cx = sum(c[0] for c in coords) / len(coords)
        r_cy = sum(c[1] for c in coords) / len(coords)
        if not (X_MIN - 10 <= r_cx <= X_MAX + 10 and Y_MIN - 10 <= r_cy <= Y_MAX + 10):
            continue
        # One hydrant per road segment
        for ci_hy in range(len(coords) - 1):
            if random.random() > 0.2:
                continue
            hx = coords[ci_hy][0] + random.uniform(-3, 3)
            hy_y = coords[ci_hy][1] + random.uniform(-3, 3)
            thx, thy = scene_transform(hx, hy_y)
            # Body
            bpy.ops.mesh.primitive_cylinder_add(radius=0.12, depth=0.6, location=(thx, thy, 0.3), vertices=8)
            hb = bpy.context.active_object
            hb.name = f"Hydrant_{hy_count}"
            hb.data.materials.append(m_hydrant_y)
            link(hb, c_hydrants)
            # Cap
            bpy.ops.mesh.primitive_cylinder_add(radius=0.14, depth=0.08, location=(thx, thy, 0.64), vertices=8)
            hc = bpy.context.active_object
            hc.name = f"HydrantCap_{hy_count}"
            hc.data.materials.append(m_hydrant_y)
            link(hc, c_hydrants)
            hy_count += 1
    print(f"  Hydrants: {hy_count}")

    # Garden planters/vegetation at some house fronts
    c_gardens = col("Gardens")
    m_soil = mat("Soil", "#5A4A3A", 0.9)
    m_shrub = mat("Shrub", "#3A5A2A", 0.8)
    garden_count = 0
    for addr, pos in sorted(bp.items()):
        gx, gy = pos['x'], pos['y']
        if not (X_MIN <= gx <= X_MAX and Y_MIN <= gy <= Y_MAX):
            continue
        if random.random() > 0.35:
            continue
        sgx, sgy = scene_transform(gx, gy)
        # Small garden bed
        gox = sgx + random.uniform(-3, 3)
        goy = sgy + random.uniform(-3, 3)
        bpy.ops.mesh.primitive_cube_add(size=1, location=(gox, goy, 0.1))
        gb = bpy.context.active_object
        gb.name = f"GardenBed_{garden_count}"
        gb.scale = (random.uniform(0.5, 1.5), random.uniform(0.3, 0.8), 0.1)
        gb.rotation_euler = (0, 0, random.uniform(0, math.pi))
        gb.data.materials.append(m_soil)
        link(gb, c_gardens)
        # Small shrub
        bpy.ops.mesh.primitive_uv_sphere_add(radius=random.uniform(0.3, 0.7),
            location=(gox + random.uniform(-0.3, 0.3), goy + random.uniform(-0.3, 0.3), 0.4),
            segments=6, ring_count=4)
        sh = bpy.context.active_object
        sh.name = f"Shrub_{garden_count}"
        sh.scale = (1, 1, random.uniform(0.5, 0.8))
        sh.data.materials.append(m_shrub)
        link(sh, c_gardens)
        garden_count += 1
    print(f"  Gardens: {garden_count}")

    # Newspaper boxes / community boards at intersections
    c_misc = col("StreetMisc")
    m_newsbox = mat("NewsBox", "#CC4422", 0.6)
    nb_count = 0
    for pt in GIS.get("field", {}).get("signs", []):
        xs_nb, ys_nb = pt['x'], pt['y']
        if not (X_MIN - 5 <= xs_nb <= X_MAX + 5 and Y_MIN - 5 <= ys_nb <= Y_MAX + 5):
            continue
        if random.random() > 0.4:
            continue
        tnx, tny = scene_transform(xs_nb + random.uniform(-2, 2), ys_nb + random.uniform(-2, 2))
        bpy.ops.mesh.primitive_cube_add(size=1, location=(tnx, tny, 0.5))
        nb = bpy.context.active_object
        nb.name = f"NewsBox_{nb_count}"
        nb.scale = (0.3, 0.25, 0.5)
        nb.data.materials.append(m_newsbox)
        link(nb, c_misc)
        nb_count += 1
    print(f"  News boxes: {nb_count}")

    # Crosswalk markings at road intersections
    m_crosswalk = mat("Crosswalk", "#E8E8E0", 0.7)
    cw_count = 0
    # Find road endpoints (intersections)
    road_endpoints = []
    for r in GIS.get("roads", []):
        coords = r.get("coords", [])
        if len(coords) < 2:
            continue
        r_cx = sum(c[0] for c in coords) / len(coords)
        r_cy = sum(c[1] for c in coords) / len(coords)
        if not (X_MIN - 10 <= r_cx <= X_MAX + 10 and Y_MIN - 10 <= r_cy <= Y_MAX + 10):
            continue
        road_endpoints.append(coords[0])
        road_endpoints.append(coords[-1])
    # Cluster endpoints to find intersections
    intersections = []
    used_ep = set()
    for i_ep, (ex, ey) in enumerate(road_endpoints):
        if i_ep in used_ep:
            continue
        cluster = [(ex, ey)]
        used_ep.add(i_ep)
        for j_ep, (ex2, ey2) in enumerate(road_endpoints):
            if j_ep in used_ep:
                continue
            if math.sqrt((ex-ex2)**2 + (ey-ey2)**2) < 10:
                cluster.append((ex2, ey2))
                used_ep.add(j_ep)
        if len(cluster) >= 2:
            icx = sum(c[0] for c in cluster) / len(cluster)
            icy = sum(c[1] for c in cluster) / len(cluster)
            intersections.append((icx, icy))
    for ix, iy in intersections:
        tix, tiy = scene_transform(ix, iy)
        # White stripes across the intersection
        for stripe in range(4):
            s_angle = stripe * math.pi / 2
            for si in range(4):
                sx = tix + math.cos(s_angle) * (3 + si * 0.8)
                sy = tiy + math.sin(s_angle) * (3 + si * 0.8)
                bpy.ops.mesh.primitive_cube_add(size=1, location=(sx, sy, 0.025))
                cw = bpy.context.active_object
                cw.name = f"Crosswalk_{cw_count}"
                cw.scale = (0.3, 1.5, 0.01)
                cw.rotation_euler = (0, 0, s_angle)
                cw.data.materials.append(m_crosswalk)
                link(cw, c_misc)
                cw_count += 1
    print(f"  Crosswalks: {cw_count}")

    # Road lane markings (dashed center lines)
    c_markings = col("RoadMarkings")
    m_yellow_line = mat("YellowLine", "#E8D040", 0.6)
    m_white_line = mat("WhiteLine", "#E8E8E0", 0.6)
    marking_count = 0
    for r in GIS.get("roads", []):
        coords = r.get("coords", [])
        if len(coords) < 2:
            continue
        r_cx_mk = sum(c[0] for c in coords) / len(coords)
        r_cy_mk = sum(c[1] for c in coords) / len(coords)
        if not (X_MIN - 10 <= r_cx_mk <= X_MAX + 10 and Y_MIN - 10 <= r_cy_mk <= Y_MAX + 10):
            continue
        for ci_mk in range(len(coords) - 1):
            x1_mk, y1_mk = coords[ci_mk]
            x2_mk, y2_mk = coords[ci_mk + 1]
            seg_len_mk = math.sqrt((x2_mk-x1_mk)**2 + (y2_mk-y1_mk)**2)
            if seg_len_mk < 5:
                continue
            sdx_mk = (x2_mk-x1_mk) / seg_len_mk
            sdy_mk = (y2_mk-y1_mk) / seg_len_mk
            mk_angle = math.atan2(sdy_mk, sdx_mk) + _SCENE_ROT
            # Dashed yellow center line
            n_dashes = int(seg_len_mk / 4)
            for di_mk in range(n_dashes):
                t_mk = (di_mk + 0.25) / max(n_dashes, 1)
                dx_mk = x1_mk + (x2_mk-x1_mk) * t_mk
                dy_mk = y1_mk + (y2_mk-y1_mk) * t_mk
                tdx, tdy = scene_transform(dx_mk, dy_mk)
                bpy.ops.mesh.primitive_cube_add(size=1, location=(tdx, tdy, 0.025))
                mk = bpy.context.active_object
                mk.name = f"DashLine_{marking_count}"
                mk.scale = (1.0, 0.06, 0.005)
                mk.rotation_euler = (0, 0, mk_angle)
                mk.data.materials.append(m_yellow_line)
                link(mk, c_markings)
                marking_count += 1
    print(f"  Road markings: {marking_count}")

    # Storm drains / catch basins at curb edges
    c_drains = col("StormDrains")
    m_drain_grate = mat("DrainGrate", "#2A2A2A", 0.9)
    drain_count = 0
    for r in GIS.get("roads", []):
        coords = r.get("coords", [])
        if len(coords) < 2:
            continue
        r_cx_dr = sum(c[0] for c in coords) / len(coords)
        r_cy_dr = sum(c[1] for c in coords) / len(coords)
        if not (X_MIN - 10 <= r_cx_dr <= X_MAX + 10 and Y_MIN - 10 <= r_cy_dr <= Y_MAX + 10):
            continue
        for ci_dr in range(len(coords) - 1):
            if random.random() > 0.25:
                continue
            x1_dr, y1_dr = coords[ci_dr]
            x2_dr, y2_dr = coords[ci_dr + 1]
            seg_l_dr = math.sqrt((x2_dr-x1_dr)**2 + (y2_dr-y1_dr)**2)
            if seg_l_dr < 8:
                continue
            sdx_dr = (x2_dr-x1_dr) / seg_l_dr
            sdy_dr = (y2_dr-y1_dr) / seg_l_dr
            snx_dr, sny_dr = -sdy_dr, sdx_dr
            # Drain at curb on one side
            drx = x1_dr + (x2_dr-x1_dr) * 0.5 + snx_dr * 3.7
            dry = y1_dr + (y2_dr-y1_dr) * 0.5 + sny_dr * 3.7
            tdrx, tdry = scene_transform(drx, dry)
            dr_angle = math.atan2(sdy_dr, sdx_dr) + _SCENE_ROT
            bpy.ops.mesh.primitive_cube_add(size=1, location=(tdrx, tdry, 0.03))
            dro = bpy.context.active_object
            dro.name = f"Drain_{drain_count}"
            dro.scale = (0.4, 0.2, 0.02)
            dro.rotation_euler = (0, 0, dr_angle)
            dro.data.materials.append(m_drain_grate)
            link(dro, c_drains)
            drain_count += 1
    print(f"  Storm drains: {drain_count}")

    # Puddles / wet patches on roads (flat reflective patches)
    c_puddles = col("Puddles")
    m_puddle = mat("Puddle", "#3A4A5A", 0.15)
    puddle_count = 0
    for r in GIS.get("roads", []):
        coords = r.get("coords", [])
        if len(coords) < 2:
            continue
        r_cx_pu = sum(c[0] for c in coords) / len(coords)
        r_cy_pu = sum(c[1] for c in coords) / len(coords)
        if not (X_MIN - 5 <= r_cx_pu <= X_MAX + 5 and Y_MIN - 5 <= r_cy_pu <= Y_MAX + 5):
            continue
        if random.random() > 0.3:
            continue
        # Random puddle near road
        px_pu = r_cx_pu + random.uniform(-5, 5)
        py_pu = r_cy_pu + random.uniform(-5, 5)
        tpx, tpy = scene_transform(px_pu, py_pu)
        bpy.ops.mesh.primitive_cylinder_add(radius=random.uniform(0.3, 1.2),
            depth=0.005, location=(tpx, tpy, 0.022), vertices=8)
        puo = bpy.context.active_object
        puo.name = f"Puddle_{puddle_count}"
        puo.scale = (1, random.uniform(0.5, 1.5), 1)
        puo.rotation_euler = (0, 0, random.uniform(0, 6.28))
        puo.data.materials.append(m_puddle)
        link(puo, c_puddles)
        puddle_count += 1
    print(f"  Puddles: {puddle_count}")

    # Bollards (short posts at intersections / park entrances)
    c_bollards = col("Bollards")
    m_bollard = mat("Bollard", "#3A3A3A", 0.5)
    bollard_count = 0
    for ix_bo, iy_bo in intersections:
        tix_bo, tiy_bo = scene_transform(ix_bo, iy_bo)
        # 2-4 bollards at each intersection corner
        for bi_bo in range(random.randint(2, 4)):
            bo_angle = random.uniform(0, 6.28)
            bo_dist = random.uniform(3, 6)
            box = tix_bo + math.cos(bo_angle) * bo_dist
            boy = tiy_bo + math.sin(bo_angle) * bo_dist
            bpy.ops.mesh.primitive_cylinder_add(radius=0.06, depth=0.8,
                location=(box, boy, 0.4), vertices=8)
            boo = bpy.context.active_object
            boo.name = f"Bollard_{bollard_count}"
            boo.data.materials.append(m_bollard)
            link(boo, c_bollards)
            bollard_count += 1
    print(f"  Bollards: {bollard_count}")

    # Planting strips (grass between sidewalk and road)
    c_strips = col("PlantingStrips")
    m_strip_grass = mat("StripGrass", "#4A6A2A", 0.9)
    strip_count = 0
    for r in GIS.get("roads", []):
        coords = r.get("coords", [])
        if len(coords) < 2:
            continue
        r_cx_st = sum(c[0] for c in coords) / len(coords)
        r_cy_st = sum(c[1] for c in coords) / len(coords)
        if not (X_MIN - 15 <= r_cx_st <= X_MAX + 15 and Y_MIN - 15 <= r_cy_st <= Y_MAX + 15):
            continue
        for side_st in [-1, 1]:
            strip_coords = []
            for ci_st in range(len(coords)):
                xst, yst = coords[ci_st]
                if ci_st < len(coords) - 1:
                    dxst, dyst = coords[ci_st+1][0] - xst, coords[ci_st+1][1] - yst
                else:
                    dxst, dyst = xst - coords[ci_st-1][0], yst - coords[ci_st-1][1]
                sl_st = max(math.sqrt(dxst*dxst + dyst*dyst), 0.01)
                nxst = -dyst/sl_st * 4.2 * side_st
                nyst = dxst/sl_st * 4.2 * side_st
                strip_coords.append(scene_transform(xst + nxst, yst + nyst))
            if len(strip_coords) >= 2:
                st_mesh = road_mesh(strip_coords, 0.8, f"Strip_{strip_count}")
                if st_mesh:
                    st_obj = bpy.data.objects.new(f"Strip_{strip_count}", st_mesh)
                    st_obj.location.z = 0.035
                    st_obj.data.materials.append(m_strip_grass)
                    link(st_obj, c_strips)
                    strip_count += 1
    print(f"  Planting strips: {strip_count}")

    # Utility access covers (smaller than manholes, square)
    c_utility = col("UtilityCovers")
    m_util_cover = mat("UtilCover", "#4A4A4A", 0.85)
    util_count = 0
    for r in GIS.get("roads", []):
        coords = r.get("coords", [])
        if len(coords) < 2:
            continue
        r_cx_ut = sum(c[0] for c in coords) / len(coords)
        r_cy_ut = sum(c[1] for c in coords) / len(coords)
        if not (X_MIN - 5 <= r_cx_ut <= X_MAX + 5 and Y_MIN - 5 <= r_cy_ut <= Y_MAX + 5):
            continue
        for ci_ut in range(len(coords) - 1):
            if random.random() > 0.15:
                continue
            utx = coords[ci_ut][0] + random.uniform(-2, 2)
            uty = coords[ci_ut][1] + random.uniform(-2, 2)
            tutx, tuty = scene_transform(utx, uty)
            bpy.ops.mesh.primitive_cube_add(size=1, location=(tutx, tuty, 0.025))
            uto = bpy.context.active_object
            uto.name = f"UtilCover_{util_count}"
            uto.scale = (0.25, 0.25, 0.01)
            uto.rotation_euler = (0, 0, random.uniform(0, math.pi/2))
            uto.data.materials.append(m_util_cover)
            link(uto, c_utility)
            util_count += 1
    print(f"  Utility covers: {util_count}")

    # Sidewalk cracks / expansion joints
    c_joints = col("SidewalkJoints")
    m_joint = mat("ExpJoint", "#8A8A80", 0.9)
    joint_count = 0
    for r in GIS.get("roads", []):
        coords = r.get("coords", [])
        if len(coords) < 2:
            continue
        r_cx_jt = sum(c[0] for c in coords) / len(coords)
        r_cy_jt = sum(c[1] for c in coords) / len(coords)
        if not (X_MIN - 15 <= r_cx_jt <= X_MAX + 15 and Y_MIN - 15 <= r_cy_jt <= Y_MAX + 15):
            continue
        for ci_jt in range(len(coords) - 1):
            x1_jt, y1_jt = coords[ci_jt]
            x2_jt, y2_jt = coords[ci_jt + 1]
            seg_l_jt = math.sqrt((x2_jt-x1_jt)**2 + (y2_jt-y1_jt)**2)
            if seg_l_jt < 5:
                continue
            sdx_jt = (x2_jt-x1_jt) / seg_l_jt
            sdy_jt = (y2_jt-y1_jt) / seg_l_jt
            snx_jt, sny_jt = -sdy_jt, sdx_jt
            jt_angle = math.atan2(sdy_jt, sdx_jt) + _SCENE_ROT
            # Perpendicular joints every 1.5m on sidewalk
            n_joints = int(seg_l_jt / 1.5)
            for ji in range(n_joints):
                t_jt = (ji + 0.5) / max(n_joints, 1)
                for side_jt in [-1, 1]:
                    jx = x1_jt + (x2_jt-x1_jt) * t_jt + snx_jt * 5.0 * side_jt
                    jy = y1_jt + (y2_jt-y1_jt) * t_jt + sny_jt * 5.0 * side_jt
                    tjx, tjy = scene_transform(jx, jy)
                    bpy.ops.mesh.primitive_cube_add(size=1, location=(tjx, tjy, 0.042))
                    jo = bpy.context.active_object
                    jo.name = f"Joint_{joint_count}"
                    jo.scale = (0.008, 0.75, 0.002)
                    jo.rotation_euler = (0, 0, jt_angle + math.pi/2)
                    jo.data.materials.append(m_joint)
                    link(jo, c_joints)
                    joint_count += 1
    print(f"  Sidewalk joints: {joint_count}")

    # Tree grates (metal grates around street trees)
    c_grates = col("TreeGrates")
    m_grate = mat("TreeGrate", "#3A3A3A", 0.5)
    grate_count = 0
    for pt in GIS.get("field", {}).get("trees", []):
        x_gr, y_gr = pt['x'], pt['y']
        if not (X_MIN - 5 <= x_gr <= X_MAX + 5 and Y_MIN - 5 <= y_gr <= Y_MAX + 5):
            continue
        tgx, tgy = scene_transform(x_gr, y_gr)
        bpy.ops.mesh.primitive_cube_add(size=1, location=(tgx, tgy, 0.015))
        gro = bpy.context.active_object
        gro.name = f"TreeGrate_{grate_count}"
        gro.scale = (0.6, 0.6, 0.01)
        gro.data.materials.append(m_grate)
        link(gro, c_grates)
        grate_count += 1
    print(f"  Tree grates: {grate_count}")

    # Parking meters (along commercial streets)
    c_meters = col("ParkingMeters")
    m_meter_pole = mat("MeterPole", "#5A5A5A", 0.5)
    m_meter_head = mat("MeterHead", "#4A4A4A", 0.6)
    meter_count = 0
    for r in GIS.get("roads", []):
        coords = r.get("coords", [])
        if len(coords) < 2:
            continue
        r_cx_pm = sum(c[0] for c in coords) / len(coords)
        r_cy_pm = sum(c[1] for c in coords) / len(coords)
        if not (X_MIN - 5 <= r_cx_pm <= X_MAX + 5 and Y_MIN - 5 <= r_cy_pm <= Y_MAX + 5):
            continue
        for ci_pm in range(len(coords) - 1):
            x1_pm, y1_pm = coords[ci_pm]
            x2_pm, y2_pm = coords[ci_pm + 1]
            seg_l_pm = math.sqrt((x2_pm-x1_pm)**2 + (y2_pm-y1_pm)**2)
            if seg_l_pm < 15:
                continue
            sdx_pm = (x2_pm-x1_pm) / seg_l_pm
            sdy_pm = (y2_pm-y1_pm) / seg_l_pm
            snx_pm, sny_pm = -sdy_pm, sdx_pm
            # One meter per 15m of road
            n_meters = int(seg_l_pm / 15)
            for mi in range(n_meters):
                if random.random() > 0.5:
                    continue
                t_pm = (mi + 0.5) / max(n_meters, 1)
                pmx = x1_pm + (x2_pm-x1_pm) * t_pm + snx_pm * 4.0
                pmy = y1_pm + (y2_pm-y1_pm) * t_pm + sny_pm * 4.0
                tpmx, tpmy = scene_transform(pmx, pmy)
                # Pole
                bpy.ops.mesh.primitive_cylinder_add(radius=0.025, depth=1.2,
                    location=(tpmx, tpmy, 0.6), vertices=6)
                pmo = bpy.context.active_object
                pmo.name = f"MeterPole_{meter_count}"
                pmo.data.materials.append(m_meter_pole)
                link(pmo, c_meters)
                # Head
                bpy.ops.mesh.primitive_cube_add(size=1, location=(tpmx, tpmy, 1.25))
                pmh = bpy.context.active_object
                pmh.name = f"MeterHead_{meter_count}"
                pmh.scale = (0.08, 0.06, 0.12)
                pmh.data.materials.append(m_meter_head)
                link(pmh, c_meters)
                meter_count += 1
    print(f"  Parking meters: {meter_count}")

    # Stop signs at intersections
    c_stopsigns = col("StopSigns")
    m_stop_red = mat("StopRed", "#CC2222", 0.6)
    m_stop_pole = mat("StopPole", "#6A6A6A", 0.5)
    stop_count = 0
    for ix_ss, iy_ss in intersections:
        tix_ss, tiy_ss = scene_transform(ix_ss, iy_ss)
        for si_ss in range(random.randint(1, 2)):
            ss_angle = random.uniform(0, 6.28)
            ss_dist = random.uniform(4, 7)
            ssx_p = tix_ss + math.cos(ss_angle) * ss_dist
            ssy_p = tiy_ss + math.sin(ss_angle) * ss_dist
            # Pole
            bpy.ops.mesh.primitive_cylinder_add(radius=0.04, depth=2.5,
                location=(ssx_p, ssy_p, 1.25), vertices=6)
            ssp = bpy.context.active_object
            ssp.name = f"StopPole_{stop_count}"
            ssp.data.materials.append(m_stop_pole)
            link(ssp, c_stopsigns)
            # Octagonal sign (approximate with cylinder)
            bpy.ops.mesh.primitive_cylinder_add(radius=0.2, depth=0.02,
                location=(ssx_p, ssy_p, 2.5), vertices=8)
            ssf = bpy.context.active_object
            ssf.name = f"StopSign_{stop_count}"
            ssf.rotation_euler = (math.pi/2, 0, ss_angle)
            ssf.data.materials.append(m_stop_red)
            link(ssf, c_stopsigns)
            stop_count += 1
    print(f"  Stop signs: {stop_count}")

    # Concrete pads at driveways (where driveway meets sidewalk)
    c_pads = col("DrivewayPads")
    m_conc_pad = mat("ConcPad", "#B0B0A8", 0.85)
    pad_count = 0
    for addr, pos in sorted(bp.items()):
        bx_pd, by_pd = pos['x'], pos['y']
        if not (X_MIN <= bx_pd <= X_MAX and Y_MIN <= by_pd <= Y_MAX):
            continue
        if random.random() > 0.2:
            continue
        sbx_pd, sby_pd = scene_transform(bx_pd, by_pd)
        # Pad perpendicular to road
        pd_x = sbx_pd + random.uniform(-4, 4)
        pd_y = sby_pd + random.uniform(-4, 4)
        bpy.ops.mesh.primitive_cube_add(size=1, location=(pd_x, pd_y, 0.025))
        pdo = bpy.context.active_object
        pdo.name = f"Pad_{pad_count}"
        pdo.scale = (1.3, 2.0, 0.02)
        pdo.rotation_euler = (0, 0, random.uniform(-0.3, 0.3))
        pdo.data.materials.append(m_conc_pad)
        link(pdo, c_pads)
        pad_count += 1
    print(f"  Driveway pads: {pad_count}")

    # Street gutters (shallow channel along curb)
    c_gutters_st = col("StreetGutters")
    m_gutter_st = mat("StreetGutter", "#5A5A58", 0.9)
    gutter_st_count = 0
    for r in GIS.get("roads", []):
        coords = r.get("coords", [])
        if len(coords) < 2:
            continue
        r_cx_gt = sum(c[0] for c in coords) / len(coords)
        r_cy_gt = sum(c[1] for c in coords) / len(coords)
        if not (X_MIN - 15 <= r_cx_gt <= X_MAX + 15 and Y_MIN - 15 <= r_cy_gt <= Y_MAX + 15):
            continue
        for side_gt in [-1, 1]:
            gt_coords = []
            for ci_gt in range(len(coords)):
                xgt, ygt = coords[ci_gt]
                if ci_gt < len(coords) - 1:
                    dxgt, dygt = coords[ci_gt+1][0] - xgt, coords[ci_gt+1][1] - ygt
                else:
                    dxgt, dygt = xgt - coords[ci_gt-1][0], ygt - coords[ci_gt-1][1]
                sl_gt = max(math.sqrt(dxgt*dxgt + dygt*dygt), 0.01)
                nxgt = -dygt/sl_gt * 3.6 * side_gt
                nygt = dxgt/sl_gt * 3.6 * side_gt
                gt_coords.append(scene_transform(xgt + nxgt, ygt + nygt))
            if len(gt_coords) >= 2:
                gt_mesh = road_mesh(gt_coords, 0.3, f"Gutter_{gutter_st_count}")
                if gt_mesh:
                    gt_obj = bpy.data.objects.new(f"Gutter_{gutter_st_count}", gt_mesh)
                    gt_obj.location.z = 0.015
                    gt_obj.data.materials.append(m_gutter_st)
                    link(gt_obj, c_gutters_st)
                    gutter_st_count += 1
    print(f"  Street gutters: {gutter_st_count}")

    # Litter / debris (random small objects on ground — adds realism)
    c_litter = col("Litter")
    m_litter_paper = mat("Paper", "#E8E0D0", 0.8)
    m_litter_plastic = mat("Plastic", "#A0C0E0", 0.5)
    litter_count = 0
    for _ in range(40):
        lx_lt = random.uniform(-80, 40)
        ly_lt = random.uniform(-180, 10)
        if not (X_MIN <= lx_lt <= X_MAX and Y_MIN <= ly_lt <= Y_MAX):
            continue
        tlx, tly = scene_transform(lx_lt, ly_lt)
        litter_mat = random.choice([m_litter_paper, m_litter_plastic])
        bpy.ops.mesh.primitive_cube_add(size=1,
            location=(tlx + random.uniform(-0.5, 0.5), tly + random.uniform(-0.5, 0.5), 0.01))
        lt = bpy.context.active_object
        lt.name = f"Litter_{litter_count}"
        lt.scale = (random.uniform(0.03, 0.1), random.uniform(0.03, 0.08), 0.002)
        lt.rotation_euler = (random.uniform(-0.1, 0.1), random.uniform(-0.1, 0.1), random.uniform(0, 6.28))
        lt.data.materials.append(litter_mat)
        link(lt, c_litter)
        litter_count += 1
    print(f"  Litter: {litter_count}")

    # Parking spot markings (white lines on road edge)
    c_parking_lines = col("ParkingLines")
    m_park_line = mat("ParkLine", "#E0E0D8", 0.7)
    pl_count = 0
    for r in GIS.get("roads", []):
        coords = r.get("coords", [])
        if len(coords) < 2:
            continue
        r_cx_pl = sum(c[0] for c in coords) / len(coords)
        r_cy_pl = sum(c[1] for c in coords) / len(coords)
        if not (X_MIN - 5 <= r_cx_pl <= X_MAX + 5 and Y_MIN - 5 <= r_cy_pl <= Y_MAX + 5):
            continue
        for ci_pl in range(len(coords) - 1):
            x1_pl, y1_pl = coords[ci_pl]
            x2_pl, y2_pl = coords[ci_pl + 1]
            seg_l_pl = math.sqrt((x2_pl-x1_pl)**2 + (y2_pl-y1_pl)**2)
            if seg_l_pl < 10:
                continue
            sdx_pl = (x2_pl-x1_pl) / seg_l_pl
            sdy_pl = (y2_pl-y1_pl) / seg_l_pl
            snx_pl, sny_pl = -sdy_pl, sdx_pl
            pl_angle = math.atan2(sdy_pl, sdx_pl) + _SCENE_ROT
            # Perpendicular parking lines every 5m
            n_spots = int(seg_l_pl / 5)
            for spi in range(n_spots):
                t_pl = (spi + 0.5) / max(n_spots, 1)
                plx = x1_pl + (x2_pl-x1_pl) * t_pl + snx_pl * 4.3
                ply = y1_pl + (y2_pl-y1_pl) * t_pl + sny_pl * 4.3
                tplx, tply = scene_transform(plx, ply)
                bpy.ops.mesh.primitive_cube_add(size=1, location=(tplx, tply, 0.024))
                plo = bpy.context.active_object
                plo.name = f"ParkLine_{pl_count}"
                plo.scale = (0.04, 1.0, 0.003)
                plo.rotation_euler = (0, 0, pl_angle + math.pi/2)
                plo.data.materials.append(m_park_line)
                link(plo, c_parking_lines)
                pl_count += 1
    print(f"  Parking lines: {pl_count}")

    # Speed bumps on residential streets
    c_bumps = col("SpeedBumps")
    m_bump = mat("SpeedBump", "#4A4A48", 0.85)
    bump_count = 0
    for r in GIS.get("roads", []):
        coords = r.get("coords", [])
        if len(coords) < 2:
            continue
        r_cx_sb = sum(c[0] for c in coords) / len(coords)
        r_cy_sb = sum(c[1] for c in coords) / len(coords)
        if not (X_MIN - 5 <= r_cx_sb <= X_MAX + 5 and Y_MIN - 5 <= r_cy_sb <= Y_MAX + 5):
            continue
        if random.random() > 0.3:
            continue
        # One speed bump per road segment
        ci_sb = len(coords) // 2
        if ci_sb >= len(coords) - 1:
            continue
        sbx = (coords[ci_sb][0] + coords[ci_sb+1][0]) / 2
        sby = (coords[ci_sb][1] + coords[ci_sb+1][1]) / 2
        sdx_sb = coords[ci_sb+1][0] - coords[ci_sb][0]
        sdy_sb = coords[ci_sb+1][1] - coords[ci_sb][1]
        sb_angle = math.atan2(sdy_sb, sdx_sb) + _SCENE_ROT
        tsbx, tsby = scene_transform(sbx, sby)
        bpy.ops.mesh.primitive_cube_add(size=1, location=(tsbx, tsby, 0.04))
        sbo = bpy.context.active_object
        sbo.name = f"SpeedBump_{bump_count}"
        sbo.scale = (0.3, 3.0, 0.04)
        sbo.rotation_euler = (0, 0, sb_angle + math.pi/2)
        sbo.data.materials.append(m_bump)
        link(sbo, c_bumps)
        bump_count += 1
    print(f"  Speed bumps: {bump_count}")

    # Curb cuts / wheelchair ramps at intersections
    c_ramps = col("CurbRamps")
    m_ramp = mat("CurbRamp", "#B8B8B0", 0.8)
    ramp_count = 0
    for ix_rp, iy_rp in intersections:
        tix_rp, tiy_rp = scene_transform(ix_rp, iy_rp)
        # 2-4 ramps at each intersection
        for ri_rp in range(random.randint(2, 4)):
            rp_angle = ri_rp * math.pi / 2 + random.uniform(-0.2, 0.2)
            rp_dist = random.uniform(3, 5)
            rpx = tix_rp + math.cos(rp_angle) * rp_dist
            rpy = tiy_rp + math.sin(rp_angle) * rp_dist
            bpy.ops.mesh.primitive_cube_add(size=1, location=(rpx, rpy, 0.04))
            rpo = bpy.context.active_object
            rpo.name = f"CurbRamp_{ramp_count}"
            rpo.scale = (0.6, 0.8, 0.04)
            rpo.rotation_euler = (0.05, 0, rp_angle)
            rpo.data.materials.append(m_ramp)
            link(rpo, c_ramps)
            ramp_count += 1
    print(f"  Curb ramps: {ramp_count}")

    # Flower beds in park (circular planted areas)
    c_flowerbeds = col("FlowerBeds")
    m_mulch = mat("Mulch", "#5A3A2A", 0.9)
    m_flowers = mat("Flowers", "#CC4488", 0.7)
    fb_count = 0
    for _ in range(6):
        fbx = park_cx_b + random.uniform(-25, 25)
        fby = park_cy_b + random.uniform(-20, 20)
        fb_radius = random.uniform(1.0, 2.5)
        # Mulch bed
        bpy.ops.mesh.primitive_cylinder_add(radius=fb_radius, depth=0.08,
            location=(fbx, fby, 0.04), vertices=12)
        fbo = bpy.context.active_object
        fbo.name = f"FlowerBed_{fb_count}"
        fbo.data.materials.append(m_mulch)
        link(fbo, c_flowerbeds)
        # Flowers (small coloured spheres)
        flower_colours = ["#CC4488", "#FFCC22", "#FF6644", "#8844CC", "#44AACC"]
        for fi_fl in range(random.randint(5, 12)):
            fl_angle = random.uniform(0, 6.28)
            fl_dist = random.uniform(0, fb_radius * 0.8)
            flx = fbx + math.cos(fl_angle) * fl_dist
            fly = fby + math.sin(fl_angle) * fl_dist
            fl_hex = random.choice(flower_colours)
            bpy.ops.mesh.primitive_uv_sphere_add(radius=random.uniform(0.08, 0.15),
                location=(flx, fly, 0.12), segments=4, ring_count=3)
            flo = bpy.context.active_object
            flo.name = f"Flower_{fb_count}_{fi_fl}"
            flo.data.materials.append(mat(f"Fl_{fl_hex}", fl_hex, 0.7))
            link(flo, c_flowerbeds)
        fb_count += 1
    print(f"  Flower beds: {fb_count}")

    # Park drinking fountain
    m_fountain = mat("Fountain", "#8A8A8A", 0.5)
    fx_df = park_cx_b + random.uniform(-10, 10)
    fy_df = park_cy_b + random.uniform(-10, 10)
    bpy.ops.mesh.primitive_cylinder_add(radius=0.15, depth=0.8,
        location=(fx_df, fy_df, 0.4), vertices=8)
    bpy.context.active_object.data.materials.append(m_fountain)
    link(bpy.context.active_object, c_flowerbeds)
    bpy.ops.mesh.primitive_cube_add(size=1, location=(fx_df, fy_df, 0.85))
    df_top = bpy.context.active_object
    df_top.scale = (0.2, 0.2, 0.05)
    df_top.data.materials.append(m_fountain)
    link(df_top, c_flowerbeds)
    print(f"  Drinking fountain: 1")

    # Waste bins in park
    m_waste = mat("WasteBin", "#2A4A2A", 0.7)
    for wbi in range(4):
        wb_angle = wbi * math.pi / 2 + 0.3
        wbx_p = park_cx_b + math.cos(wb_angle) * 20
        wby_p = park_cy_b + math.sin(wb_angle) * 20
        bpy.ops.mesh.primitive_cylinder_add(radius=0.2, depth=0.7,
            location=(wbx_p, wby_p, 0.35), vertices=8)
        wbo_p = bpy.context.active_object
        wbo_p.name = f"ParkBin_{wbi}"
        wbo_p.data.materials.append(m_waste)
        link(wbo_p, c_flowerbeds)
    print(f"  Park waste bins: 4")

    # Park fence/railing (low perimeter fence around park)
    park_file = SCRIPT_DIR / "outputs" / "demos" / "bellevue_complete_gis.json"
    c_park_fence = col("ParkFence")
    m_park_rail = mat("ParkRail", "#2A2A2A", 0.4)
    if park_file.exists():
        pf_data = json.load(open(park_file))
        for pk_f in pf_data.get("parks", []):
            t_ring_f = scene_transform_ring(pk_f["coords"])
            if len(t_ring_f) >= 3:
                # Posts every 3m
                for i_pf in range(len(t_ring_f)):
                    x1_pf, y1_pf = t_ring_f[i_pf]
                    x2_pf, y2_pf = t_ring_f[(i_pf + 1) % len(t_ring_f)]
                    seg_pf = math.sqrt((x2_pf-x1_pf)**2 + (y2_pf-y1_pf)**2)
                    if seg_pf < 2:
                        continue
                    n_posts = int(seg_pf / 3)
                    for pi_pf in range(n_posts):
                        t_pf = pi_pf / max(n_posts, 1)
                        pfx = x1_pf + (x2_pf-x1_pf) * t_pf
                        pfy = y1_pf + (y2_pf-y1_pf) * t_pf
                        bpy.ops.mesh.primitive_cylinder_add(radius=0.03, depth=0.9,
                            location=(pfx, pfy, 0.45), vertices=6)
                        bpy.context.active_object.data.materials.append(m_park_rail)
                        link(bpy.context.active_object, c_park_fence)
                    # Horizontal rail between posts
                    pf_angle = math.atan2(y2_pf-y1_pf, x2_pf-x1_pf)
                    pfmx = (x1_pf + x2_pf) / 2
                    pfmy = (y1_pf + y2_pf) / 2
                    bpy.ops.mesh.primitive_cube_add(size=1, location=(pfmx, pfmy, 0.7))
                    pfr = bpy.context.active_object
                    pfr.scale = (seg_pf / 2, 0.02, 0.02)
                    pfr.rotation_euler = (0, 0, pf_angle)
                    pfr.data.materials.append(m_park_rail)
                    link(pfr, c_park_fence)
                    # Lower rail
                    bpy.ops.mesh.primitive_cube_add(size=1, location=(pfmx, pfmy, 0.3))
                    pfr2 = bpy.context.active_object
                    pfr2.scale = (seg_pf / 2, 0.02, 0.02)
                    pfr2.rotation_euler = (0, 0, pf_angle)
                    pfr2.data.materials.append(m_park_rail)
                    link(pfr2, c_park_fence)
        print(f"  Park fence: perimeter")

    # TTC streetcar tracks (Toronto has streetcar tracks on some streets)
    c_tracks = col("StreetcarTracks")
    m_rail = mat("Rail", "#6A6A6A", 0.3)
    track_count = 0
    # Find the widest/longest road (likely Dundas or Spadina — has tracks)
    longest_road = None
    longest_len = 0
    for r in GIS.get("roads", []):
        coords = r.get("coords", [])
        if len(coords) < 2:
            continue
        total_len = sum(math.sqrt((coords[i+1][0]-coords[i][0])**2 + (coords[i+1][1]-coords[i][1])**2)
                       for i in range(len(coords)-1))
        if total_len > longest_len:
            r_cx_tr = sum(c[0] for c in coords) / len(coords)
            r_cy_tr = sum(c[1] for c in coords) / len(coords)
            if X_MIN - 20 <= r_cx_tr <= X_MAX + 20 and Y_MIN - 20 <= r_cy_tr <= Y_MAX + 20:
                longest_len = total_len
                longest_road = coords
    if longest_road and longest_len > 50:
        # Two parallel rails, 1.5m apart
        for rail_side in [-0.75, 0.75]:
            rail_coords = []
            for ci_tr in range(len(longest_road)):
                xtr, ytr = longest_road[ci_tr]
                if ci_tr < len(longest_road) - 1:
                    dxtr, dytr = longest_road[ci_tr+1][0] - xtr, longest_road[ci_tr+1][1] - ytr
                else:
                    dxtr, dytr = xtr - longest_road[ci_tr-1][0], ytr - longest_road[ci_tr-1][1]
                sl_tr = max(math.sqrt(dxtr*dxtr + dytr*dytr), 0.01)
                nxtr = -dytr/sl_tr * rail_side
                nytr = dxtr/sl_tr * rail_side
                rail_coords.append(scene_transform(xtr + nxtr, ytr + nytr))
            if len(rail_coords) >= 2:
                tr_mesh = road_mesh(rail_coords, 0.06, f"Rail_{track_count}")
                if tr_mesh:
                    tr_obj = bpy.data.objects.new(f"Rail_{track_count}", tr_mesh)
                    tr_obj.location.z = 0.028
                    tr_obj.data.materials.append(m_rail)
                    link(tr_obj, c_tracks)
                    track_count += 1
        print(f"  Streetcar tracks: {track_count} rails")

    # Overhead streetcar wires (catenary above tracks)
    if longest_road and longest_len > 50:
        c_catenary = col("CatenaryWires")
        m_catenary = mat("Catenary", "#2A2A2A", 0.3)
        cat_count = 0
        # Wire above center of road at 5.5m height
        cat_coords = [scene_transform(c[0], c[1]) for c in longest_road]
        for ci_cat in range(len(cat_coords) - 1):
            cx1_cat, cy1_cat = cat_coords[ci_cat]
            cx2_cat, cy2_cat = cat_coords[ci_cat + 1]
            cat_len = math.sqrt((cx2_cat-cx1_cat)**2 + (cy2_cat-cy1_cat)**2)
            if cat_len < 2:
                continue
            cat_angle = math.atan2(cy2_cat-cy1_cat, cx2_cat-cx1_cat)
            cat_mx = (cx1_cat + cx2_cat) / 2
            cat_my = (cy1_cat + cy2_cat) / 2
            bpy.ops.mesh.primitive_cylinder_add(radius=0.008, depth=cat_len,
                location=(cat_mx, cat_my, 5.5), vertices=4)
            cato = bpy.context.active_object
            cato.name = f"Catenary_{cat_count}"
            cato.rotation_euler = (math.pi/2, 0, cat_angle)
            cato.data.materials.append(m_catenary)
            link(cato, c_catenary)
            cat_count += 1
        # Support poles for catenary every 30m
        m_cat_pole = mat("CatPole", "#4A4A4A", 0.5)
        for ci_cp in range(0, len(longest_road), 3):
            if ci_cp >= len(longest_road):
                break
            cpx, cpy = longest_road[ci_cp]
            if ci_cp < len(longest_road) - 1:
                cdx, cdy = longest_road[ci_cp+1][0] - cpx, longest_road[ci_cp+1][1] - cpy
            else:
                cdx, cdy = cpx - longest_road[ci_cp-1][0], cpy - longest_road[ci_cp-1][1]
            csl = max(math.sqrt(cdx*cdx + cdy*cdy), 0.01)
            cnx_cp = -cdy/csl * 4
            cny_cp = cdx/csl * 4
            tcpx, tcpy = scene_transform(cpx + cnx_cp, cpy + cny_cp)
            bpy.ops.mesh.primitive_cylinder_add(radius=0.08, depth=6.0,
                location=(tcpx, tcpy, 3.0), vertices=8)
            cpo = bpy.context.active_object
            cpo.name = f"CatPole_{ci_cp}"
            cpo.data.materials.append(m_cat_pole)
            link(cpo, c_catenary)
            # Horizontal arm to wire
            arm_angle = math.atan2(cny_cp, cnx_cp) + _SCENE_ROT
            bpy.ops.mesh.primitive_cube_add(size=1, location=(tcpx, tcpy, 5.8))
            armo = bpy.context.active_object
            armo.name = f"CatArm_{ci_cp}"
            armo.scale = (2.0, 0.04, 0.04)
            armo.rotation_euler = (0, 0, arm_angle + math.pi/2)
            armo.data.materials.append(m_cat_pole)
            link(armo, c_catenary)
        print(f"  Catenary wires + poles: {cat_count}")

    # Retaining walls (low walls at grade changes)
    c_retaining = col("RetainingWalls")
    m_retaining = mat("RetainingWall", "#8A8A80", 0.85)
    ret_count = 0
    # Add a few random retaining walls along property edges
    for _ in range(8):
        rwx = random.uniform(-100, 20)
        rwy = random.uniform(-180, 0)
        if not (X_MIN <= rwx <= X_MAX and Y_MIN <= rwy <= Y_MAX):
            continue
        trwx, trwy = scene_transform(rwx, rwy)
        rw_len = random.uniform(3, 8)
        rw_h = random.uniform(0.3, 0.8)
        rw_angle = random.choice([0, math.pi/2, math.pi/4, -math.pi/4])
        bpy.ops.mesh.primitive_cube_add(size=1, location=(trwx, trwy, rw_h / 2))
        rwo = bpy.context.active_object
        rwo.name = f"RetWall_{ret_count}"
        rwo.scale = (rw_len / 2, 0.15, rw_h / 2)
        rwo.rotation_euler = (0, 0, rw_angle)
        rwo.data.materials.append(m_retaining)
        link(rwo, c_retaining)
        ret_count += 1
    print(f"  Retaining walls: {ret_count}")

    # Gravel/dirt patches (in alleys and vacant areas)
    c_gravel = col("GravelPatches")
    m_gravel = mat("Gravel", "#8A8070", 0.9)
    gravel_count = 0
    for r in GIS.get("alleys", []):
        coords = r.get("coords", [])
        if len(coords) < 2:
            continue
        al_cx = sum(c[0] for c in coords) / len(coords)
        al_cy = sum(c[1] for c in coords) / len(coords)
        if not (X_MIN - 10 <= al_cx <= X_MAX + 10 and Y_MIN - 10 <= al_cy <= Y_MAX + 10):
            continue
        # Gravel surface alongside alley
        t_al_coords = [scene_transform(c[0] + random.uniform(-1, 1), c[1] + random.uniform(-1, 1))
                       for c in coords]
        if len(t_al_coords) >= 2:
            gv_mesh = road_mesh(t_al_coords, 2.0, f"Gravel_{gravel_count}")
            if gv_mesh:
                gv_obj = bpy.data.objects.new(f"Gravel_{gravel_count}", gv_mesh)
                gv_obj.location.z = 0.01
                gv_obj.data.materials.append(m_gravel)
                link(gv_obj, c_gravel)
                gravel_count += 1
    print(f"  Gravel patches: {gravel_count}")

    # Weeds / grass tufts growing in cracks (small green patches)
    c_weeds = col("Weeds")
    m_weed = mat("Weed", "#5A7A3A", 0.85)
    weed_count = 0
    for _ in range(60):
        wx_w = random.uniform(-110, 50)
        wy_w = random.uniform(-190, 10)
        if not (X_MIN <= wx_w <= X_MAX and Y_MIN <= wy_w <= Y_MAX):
            continue
        twx, twy = scene_transform(wx_w, wy_w)
        bpy.ops.mesh.primitive_uv_sphere_add(radius=random.uniform(0.05, 0.15),
            location=(twx, twy, 0.03), segments=4, ring_count=3)
        wo_w = bpy.context.active_object
        wo_w.name = f"Weed_{weed_count}"
        wo_w.scale = (1, 1, random.uniform(0.3, 0.6))
        wo_w.data.materials.append(m_weed)
        link(wo_w, c_weeds)
        weed_count += 1
    print(f"  Weeds: {weed_count}")

    # Road patches / repaired sections (darker asphalt rectangles)
    c_patches = col("RoadPatches")
    m_patch_dark = mat("DarkPatch", "#2A2A28", 0.92)
    patch_count = 0
    for r in GIS.get("roads", []):
        coords = r.get("coords", [])
        if len(coords) < 2:
            continue
        r_cx_rp = sum(c[0] for c in coords) / len(coords)
        r_cy_rp = sum(c[1] for c in coords) / len(coords)
        if not (X_MIN - 5 <= r_cx_rp <= X_MAX + 5 and Y_MIN - 5 <= r_cy_rp <= Y_MAX + 5):
            continue
        if random.random() > 0.3:
            continue
        rpx = r_cx_rp + random.uniform(-3, 3)
        rpy = r_cy_rp + random.uniform(-3, 3)
        trpx, trpy = scene_transform(rpx, rpy)
        bpy.ops.mesh.primitive_cube_add(size=1, location=(trpx, trpy, 0.023))
        rpo_p = bpy.context.active_object
        rpo_p.name = f"RoadPatch_{patch_count}"
        rpo_p.scale = (random.uniform(0.5, 2.5), random.uniform(0.5, 2.0), 0.003)
        rpo_p.rotation_euler = (0, 0, random.uniform(0, math.pi))
        rpo_p.data.materials.append(m_patch_dark)
        link(rpo_p, c_patches)
        patch_count += 1
    print(f"  Road patches: {patch_count}")

    # Front walkways (concrete path from sidewalk to each door)
    c_walkways = col("FrontWalkways")
    m_walkway = mat("Walkway", "#B0B0A8", 0.85)
    walk_count = 0
    for addr, pos in sorted(bp.items()):
        bx_wk, by_wk = pos['x'], pos['y']
        if not (X_MIN <= bx_wk <= X_MAX and Y_MIN <= by_wk <= Y_MAX):
            continue
        if random.random() > 0.7:
            continue
        sbx_wk, sby_wk = scene_transform(bx_wk, by_wk)
        # Short concrete path from building to sidewalk
        parts_wk = addr.split()
        sn_wk = ""
        for si, s in enumerate(parts_wk):
            if s in ("Ave", "St", "Pl", "Sq"):
                sn_wk = " ".join(parts_wk[max(0,si-1):si+1])
                break
        ns_st = {"Bellevue Ave", "Leonard Pl", "Leonard Ave"}
        if sn_wk in ns_st:
            facing_wk = 73 if bx_wk < -70 else 253
        else:
            facing_wk = 343 if by_wk < -100 else 163
        rot_wk = math.radians((360 - facing_wk) % 360)
        rot_wk = scene_transform_angle(rot_wk)
        fnx_wk = -math.sin(rot_wk)
        fny_wk = math.cos(rot_wk)
        # Path extends 4m from building front
        for pi_wk in range(3):
            px_wk = sbx_wk + fnx_wk * (2 + pi_wk * 1.5)
            py_wk = sby_wk + fny_wk * (2 + pi_wk * 1.5)
            bpy.ops.mesh.primitive_cube_add(size=1, location=(px_wk, py_wk, 0.02))
            wko = bpy.context.active_object
            wko.name = f"Walk_{walk_count}"
            wko.scale = (0.5, 0.6, 0.015)
            wko.rotation_euler = (0, 0, rot_wk)
            wko.data.materials.append(m_walkway)
            link(wko, c_walkways)
        walk_count += 1
    print(f"  Front walkways: {walk_count}")

    # Brick front-yard retaining walls (low walls at front of lots)
    c_yard_walls = col("YardWalls")
    m_yard_wall = mat("BrickYardWall", "#8A6A5A", 0.8)
    yw_count = 0
    for addr, pos in sorted(bp.items()):
        bx_yw, by_yw = pos['x'], pos['y']
        if not (X_MIN <= bx_yw <= X_MAX and Y_MIN <= by_yw <= Y_MAX):
            continue
        if random.random() > 0.3:
            continue
        sbx_yw, sby_yw = scene_transform(bx_yw, by_yw)
        parts_yw = addr.split()
        sn_yw = ""
        for si, s in enumerate(parts_yw):
            if s in ("Ave", "St", "Pl", "Sq"):
                sn_yw = " ".join(parts_yw[max(0,si-1):si+1])
                break
        ns_st_yw = {"Bellevue Ave", "Leonard Pl", "Leonard Ave"}
        if sn_yw in ns_st_yw:
            facing_yw = 73 if bx_yw < -70 else 253
        else:
            facing_yw = 343 if by_yw < -100 else 163
        rot_yw = math.radians((360 - facing_yw) % 360)
        rot_yw = scene_transform_angle(rot_yw)
        fnx_yw = -math.sin(rot_yw)
        fny_yw = math.cos(rot_yw)
        # Low wall 5m in front of building, perpendicular to facing
        yw_x = sbx_yw + fnx_yw * 5.5
        yw_y = sby_yw + fny_yw * 5.5
        bpy.ops.mesh.primitive_cube_add(size=1, location=(yw_x, yw_y, 0.25))
        ywo = bpy.context.active_object
        ywo.name = f"YardWall_{yw_count}"
        ywo.scale = (2.5, 0.1, 0.25)
        ywo.rotation_euler = (0, 0, rot_yw)
        ywo.data.materials.append(m_yard_wall)
        link(ywo, c_yard_walls)
        # Brick pillars at ends
        for pillar_side in [-2.3, 2.3]:
            ppx = yw_x + math.cos(rot_yw) * pillar_side
            ppy = yw_y + math.sin(rot_yw) * pillar_side
            bpy.ops.mesh.primitive_cube_add(size=1, location=(ppx, ppy, 0.35))
            ppo = bpy.context.active_object
            ppo.name = f"WallPillar_{yw_count}"
            ppo.scale = (0.12, 0.12, 0.35)
            ppo.data.materials.append(m_yard_wall)
            link(ppo, c_yard_walls)
        yw_count += 1
    print(f"  Yard walls: {yw_count}")

    # Evergreen shrubs (stay green in March unlike deciduous trees)
    c_evergreens = col("Evergreens")
    m_evergreen = mat("Evergreen", "#2A4A1A", 0.85)
    ev_count = 0
    for addr, pos in sorted(bp.items()):
        bx_ev, by_ev = pos['x'], pos['y']
        if not (X_MIN <= bx_ev <= X_MAX and Y_MIN <= by_ev <= Y_MAX):
            continue
        if random.random() > 0.25:
            continue
        sbx_ev, sby_ev = scene_transform(bx_ev, by_ev)
        # Cone-shaped evergreen near front
        ex = sbx_ev + random.uniform(-3, 3)
        ey = sby_ev + random.uniform(-3, 3)
        ev_h = random.uniform(1.5, 4.0)
        bpy.ops.mesh.primitive_cone_add(radius1=ev_h * 0.3, depth=ev_h,
            location=(ex, ey, ev_h / 2), vertices=8)
        evo = bpy.context.active_object
        evo.name = f"Evergreen_{ev_count}"
        evo.data.materials.append(m_evergreen)
        link(evo, c_evergreens)
        ev_count += 1
    print(f"  Evergreens: {ev_count}")

    # Amphitheatre seating in park (stepped concrete — from night photo)
    c_amphitheatre = col("Amphitheatre")
    m_amphi = mat("AmphiConcrete", "#A0A098", 0.8)
    amphi_x = park_cx_b - 15
    amphi_y = park_cy_b + 10
    for step_a in range(5):
        bpy.ops.mesh.primitive_cube_add(size=1,
            location=(amphi_x + step_a * 0.8, amphi_y, step_a * 0.3 + 0.15))
        sto_a = bpy.context.active_object
        sto_a.name = f"AmphiStep_{step_a}"
        sto_a.scale = (0.4, 4.0, 0.15)
        sto_a.data.materials.append(m_amphi)
        link(sto_a, c_amphitheatre)
    print(f"  Amphitheatre: 5 steps")

    # Circular raised planter in park center (from night photo)
    m_raised_planter = mat("RaisedPlanter", "#8A7A6A", 0.8)
    rp_x = park_cx_b + 5
    rp_y = park_cy_b + 5
    bpy.ops.mesh.primitive_cylinder_add(radius=2.0, depth=0.4,
        location=(rp_x, rp_y, 0.2), vertices=16)
    rpo_c = bpy.context.active_object
    rpo_c.name = "RaisedPlanter"
    rpo_c.data.materials.append(m_raised_planter)
    link(rpo_c, c_amphitheatre)
    # Soil/planting inside
    bpy.ops.mesh.primitive_cylinder_add(radius=1.8, depth=0.1,
        location=(rp_x, rp_y, 0.42), vertices=16)
    rps = bpy.context.active_object
    rps.name = "PlanterSoil"
    rps.data.materials.append(mat("PlanterDirt", "#5A4A3A", 0.9))
    link(rps, c_amphitheatre)
    print(f"  Raised planter: 1")

    # Park information board / kiosk (from park photos)
    m_kiosk_frame = mat("KioskFrame", "#3A3A3A", 0.5)
    m_kiosk_board = mat("KioskBoard", "#2A4A2A", 0.7)
    kiosk_x = park_cx_b - 20
    kiosk_y = park_cy_b - 15
    # Frame
    bpy.ops.mesh.primitive_cube_add(size=1, location=(kiosk_x, kiosk_y, 1.0))
    kf = bpy.context.active_object
    kf.name = "KioskFrame"
    kf.scale = (0.8, 0.05, 0.6)
    kf.data.materials.append(m_kiosk_frame)
    link(kf, c_amphitheatre)
    # Legs
    for kl_side in [-0.35, 0.35]:
        bpy.ops.mesh.primitive_cylinder_add(radius=0.03, depth=1.4,
            location=(kiosk_x + kl_side, kiosk_y, 0.7), vertices=6)
        kl = bpy.context.active_object
        kl.data.materials.append(m_kiosk_frame)
        link(kl, c_amphitheatre)
    print(f"  Park kiosk: 1")

    # Dog waste station in park
    m_dog_station = mat("DogStation", "#2A6A2A", 0.7)
    ds_x = park_cx_b + 18
    ds_y = park_cy_b - 8
    bpy.ops.mesh.primitive_cylinder_add(radius=0.04, depth=1.0,
        location=(ds_x, ds_y, 0.5), vertices=6)
    bpy.context.active_object.data.materials.append(m_dog_station)
    link(bpy.context.active_object, c_amphitheatre)
    bpy.ops.mesh.primitive_cube_add(size=1, location=(ds_x, ds_y, 1.05))
    dsb = bpy.context.active_object
    dsb.scale = (0.15, 0.08, 0.15)
    dsb.data.materials.append(m_dog_station)
    link(dsb, c_amphitheatre)
    print(f"  Dog waste station: 1")

    # Playground swing set (from park photos — separate from climbing structure)
    swing_x = park_cx_b - 8
    swing_y = park_cy_b + 18
    m_swing = mat("SwingMetal", "#5A5A5A", 0.4)
    # A-frame supports
    for sw_side in [-1.5, 1.5]:
        bpy.ops.mesh.primitive_cylinder_add(radius=0.04, depth=3.0,
            location=(swing_x + sw_side, swing_y - 0.5, 1.5), vertices=6)
        swo = bpy.context.active_object
        swo.rotation_euler = (0.15, 0, 0)
        swo.data.materials.append(m_swing)
        link(swo, c_playground)
        bpy.ops.mesh.primitive_cylinder_add(radius=0.04, depth=3.0,
            location=(swing_x + sw_side, swing_y + 0.5, 1.5), vertices=6)
        swo2 = bpy.context.active_object
        swo2.rotation_euler = (-0.15, 0, 0)
        swo2.data.materials.append(m_swing)
        link(swo2, c_playground)
    # Top bar
    bpy.ops.mesh.primitive_cylinder_add(radius=0.04, depth=3.2,
        location=(swing_x, swing_y, 2.8), vertices=8)
    stb = bpy.context.active_object
    stb.rotation_euler = (0, math.pi/2, 0)
    stb.data.materials.append(m_swing)
    link(stb, c_playground)
    # Swing seats (2)
    m_swing_seat = mat("SwingSeat", "#2A2A2A", 0.8)
    for ss_off in [-0.5, 0.5]:
        # Chains (thin cylinders)
        for chain_side in [-0.15, 0.15]:
            bpy.ops.mesh.primitive_cylinder_add(radius=0.008, depth=2.0,
                location=(swing_x + ss_off, swing_y + chain_side, 1.8), vertices=4)
            bpy.context.active_object.data.materials.append(m_swing)
            link(bpy.context.active_object, c_playground)
        # Seat
        bpy.ops.mesh.primitive_cube_add(size=1,
            location=(swing_x + ss_off, swing_y, 0.7))
        seat = bpy.context.active_object
        seat.scale = (0.2, 0.08, 0.015)
        seat.data.materials.append(m_swing_seat)
        link(seat, c_playground)
    print(f"  Swing set: 1")

    # Land use zones (coloured ground polygons from DB)
    c_landuse = col("LandUse")
    lu_colours = {
        "park": "#3A6A2A", "grass": "#4A7A3A", "residential": "#C8B898",
        "retail": "#B8A080", "commercial": "#A89878", "industrial": "#8A8A80"
    }
    lu_count = 0
    if park_file.exists():
        lu_data = json.load(open(park_file))
        for lu in lu_data.get("land_use", []):
            lu_class = lu.get("class", "residential")
            lu_hex = lu_colours.get(lu_class, "#B0A890")
            t_ring = scene_transform_ring(lu["coords"])
            lu_mesh = poly_mesh(t_ring, 0.005, f"LU_{lu_count}")
            if lu_mesh:
                lu_obj = bpy.data.objects.new(f"LU_{lu_class}_{lu_count}", lu_mesh)
                lu_obj.data.materials.append(mat(f"LU_{lu_class}", lu_hex, 0.9))
                link(lu_obj, c_landuse)
                lu_count += 1
    print(f"  Land use zones: {lu_count}")

    # Ruelles (back alleys from field survey)
    c_ruelles = col("Ruelles")
    m_ruelle = mat("Ruelle", "#6A6A60", 0.85)
    ru_count = 0
    if park_file.exists():
        ru_data = json.load(open(park_file))
        for ru in ru_data.get("ruelles", []):
            t_coords = [scene_transform(c[0], c[1]) for c in ru["coords"]]
            ru_mesh = road_mesh(t_coords, 2.5, f"Ruelle_{ru_count}")
            if ru_mesh:
                ru_obj = bpy.data.objects.new(f"Ruelle_{ru_count}", ru_mesh)
                ru_obj.location.z = 0.015
                ru_obj.data.materials.append(m_ruelle)
                link(ru_obj, c_ruelles)
                ru_count += 1
    print(f"  Ruelles: {ru_count}")

    # HCD heritage boundary (outline)
    c_hcd = col("HCDBoundary")
    m_hcd = mat("HCDLine", "#8A4A2A", 0.7)
    if park_file.exists():
        hcd_data = json.load(open(park_file))
        for hcd in hcd_data.get("hcd_boundary", []):
            t_ring = scene_transform_ring(hcd["coords"])
            bm_hcd = bmesh.new()
            hcd_verts = [bm_hcd.verts.new((x, y, 0.06)) for x, y in t_ring]
            for iv in range(len(hcd_verts)):
                bm_hcd.edges.new([hcd_verts[iv], hcd_verts[(iv+1) % len(hcd_verts)]])
            hcd_mesh = bpy.data.meshes.new("HCD")
            bm_hcd.to_mesh(hcd_mesh)
            bm_hcd.free()
            hcd_obj = bpy.data.objects.new("HCDBoundary", hcd_mesh)
            hcd_obj.data.materials.append(m_hcd)
            link(hcd_obj, c_hcd)
            mod_hcd = hcd_obj.modifiers.new("Solidify", 'SOLIDIFY')
            mod_hcd.thickness = 0.3
            mod_hcd.offset = 0
        print(f"  HCD boundary: 1")

    # Cycling network
    if park_file.exists():
        cy_data = json.load(open(park_file))
        m_cycle = mat("CycleLane", "#2A8A2A", 0.7)
        for cy in cy_data.get("cycling", []):
            t_coords = [scene_transform(c[0], c[1]) for c in cy["coords"]]
            cy_mesh = road_mesh(t_coords, 1.5, "CycleLane")
            if cy_mesh:
                cy_obj = bpy.data.objects.new("CycleLane", cy_mesh)
                cy_obj.location.z = 0.03
                cy_obj.data.materials.append(m_cycle)
                link(cy_obj, c_ruelles)
        print(f"  Cycling: {len(cy_data.get('cycling', []))}")

    # Park polygon (from separate PostGIS export)
    park_file = SCRIPT_DIR / "outputs" / "demos" / "bellevue_complete_gis.json"
    if park_file.exists():
        park_data = json.load(open(park_file))
        c_park = col("Park")
        m_grass = mat("ParkGrass", "#4A7A2A", 0.9)
        for pk in park_data.get("parks", []):
            t_ring = scene_transform_ring(pk["coords"])
            mesh = poly_mesh(t_ring, 0.01, "Park")
            if mesh:
                obj = bpy.data.objects.new("Park", mesh)
                obj.data.materials.append(m_grass)
                link(obj, c_park)
        print(f"  Park: {len(park_data.get('parks', []))}")

    # Lot boundaries (thin outlines from footprints)
    c_lots = col("LotBoundaries")
    m_lot = mat("LotLine", "#6A6A5A", 0.8)
    lot_count = 0
    for fp in GIS.get("footprints", []):
        ring = fp.get("rings", [[]])[0]
        if not ring or len(ring) < 3:
            continue
        fp_cx = sum(c[0] for c in ring) / len(ring)
        fp_cy = sum(c[1] for c in ring) / len(ring)
        if not (X_MIN <= fp_cx <= X_MAX and Y_MIN <= fp_cy <= Y_MAX):
            continue
        t_ring = scene_transform_ring(ring)
        # Create thin outline (just edges, not filled)
        bm = bmesh.new()
        verts = [bm.verts.new((x, y, 0.03)) for x, y in t_ring]
        for i_v in range(len(verts)):
            bm.edges.new([verts[i_v], verts[(i_v+1) % len(verts)]])
        mesh = bpy.data.meshes.new(f"Lot_{lot_count}")
        bm.to_mesh(mesh)
        bm.free()
        obj = bpy.data.objects.new(f"Lot_{lot_count}", mesh)
        # Add solidify modifier to give edges thickness
        obj.data.materials.append(m_lot)
        link(obj, c_lots)
        mod = obj.modifiers.new("Solidify", 'SOLIDIFY')
        mod.thickness = 0.15
        mod.offset = 0
        lot_count += 1
    print(f"  Lot boundaries: {lot_count}")

    # Roads
    c_road = col("Roads")
    m_road = mat("Road", "#4A4A4A", 0.9)
    road_count = 0
    for r in GIS.get("roads", []):
        coords = r.get("coords", [])
        if len(coords) < 2:
            continue
        cx = sum(c[0] for c in coords) / len(coords)
        cy = sum(c[1] for c in coords) / len(coords)
        if not (X_MIN - 30 <= cx <= X_MAX + 30 and Y_MIN - 30 <= cy <= Y_MAX + 30):
            continue
        t_coords = [scene_transform(c[0], c[1]) for c in coords]
        mesh = road_mesh(t_coords, 7.0, f"Road_{road_count}")
        if mesh:
            obj = bpy.data.objects.new(f"Road_{road_count}", mesh)
            obj.data.materials.append(m_road)
            link(obj, c_road)
            road_count += 1

    # Alleys
    m_alley = mat("Alley", "#5A5A5A", 0.85)
    for r in GIS.get("alleys", []):
        coords = r.get("coords", [])
        if len(coords) < 2:
            continue
        cx = sum(c[0] for c in coords) / len(coords)
        cy = sum(c[1] for c in coords) / len(coords)
        if not (X_MIN - 20 <= cx <= X_MAX + 20 and Y_MIN - 20 <= cy <= Y_MAX + 20):
            continue
        t_coords = [scene_transform(c[0], c[1]) for c in coords]
        mesh = road_mesh(t_coords, 3.0, f"Alley_{road_count}")
        if mesh:
            obj = bpy.data.objects.new(f"Alley_{road_count}", mesh)
            obj.data.materials.append(m_alley)
            link(obj, c_road)
            road_count += 1
    # Pedestrian paths from complete GIS export
    ped_gis_file = SCRIPT_DIR / "outputs" / "demos" / "bellevue_complete_gis.json"
    m_ped = mat("Pedestrian", "#B0A898", 0.85)
    ped_count = 0
    if ped_gis_file.exists():
        ped_data = json.load(open(ped_gis_file))
        for path in ped_data.get("pedestrian", []):
            coords = path.get("coords", [])
            if len(coords) < 2:
                continue
            pcx = sum(c[0] for c in coords) / len(coords)
            pcy = sum(c[1] for c in coords) / len(coords)
            if not (X_MIN - 20 <= pcx <= X_MAX + 20 and Y_MIN - 20 <= pcy <= Y_MAX + 20):
                continue
            t_coords = [scene_transform(c[0], c[1]) for c in coords]
            mesh = road_mesh(t_coords, 1.5, f"PedPath_{ped_count}")
            if mesh:
                obj = bpy.data.objects.new(f"PedPath_{ped_count}", mesh)
                obj.data.materials.append(m_ped)
                link(obj, c_road)
                ped_count += 1
    print(f"  Roads + alleys: {road_count}, pedestrian paths: {ped_count}")

    # Trees
    c_trees = col("Trees")
    m_trunk = mat("Trunk", "#4A3520", 0.9)
    m_canopy = mat("Canopy", "#2A5A2A", 0.8)
    tree_count = 0
    for pt in GIS.get("field", {}).get("trees", []):
        x, y = pt['x'], pt['y']
        if not (X_MIN - 10 <= x <= X_MAX + 10 and Y_MIN - 10 <= y <= Y_MAX + 10):
            continue
        tx, ty = scene_transform(x, y)
        h = random.uniform(5, 9)
        # Trunk
        bpy.ops.mesh.primitive_cylinder_add(radius=0.12, depth=h, location=(tx, ty, h/2), vertices=8)
        trunk = bpy.context.active_object
        trunk.name = f"Trunk_{tree_count}"
        trunk.data.materials.append(m_trunk)
        link(trunk, c_trees)
        # Branches (3-5 bare branches, March = no leaves)
        m_branch = mat("Branch", "#5A4A38", 0.9)
        for bi in range(random.randint(3, 5)):
            b_angle = random.uniform(0, 6.28)
            b_len = random.uniform(1.5, 3.5)
            b_tilt = random.uniform(0.3, 0.7)
            b_x = tx + math.cos(b_angle) * b_len * 0.4
            b_y = ty + math.sin(b_angle) * b_len * 0.4
            b_z = h + b_len * 0.2
            bpy.ops.mesh.primitive_cylinder_add(radius=0.03, depth=b_len,
                location=(b_x, b_y, b_z), vertices=6)
            br = bpy.context.active_object
            br.name = f"Branch_{tree_count}_{bi}"
            br.rotation_euler = (b_tilt * math.cos(b_angle+1.5),
                                  b_tilt * math.sin(b_angle+1.5), b_angle)
            br.data.materials.append(m_branch)
            link(br, c_trees)
        tree_count += 1
    # Additional trees from complete GIS export
    complete_gis_file = SCRIPT_DIR / "outputs" / "demos" / "bellevue_complete_gis.json"
    if complete_gis_file.exists():
        complete_data = json.load(open(complete_gis_file))
        for st in complete_data.get("street_trees", []):
            x, y = st.get("x", 0), st.get("y", 0)
            if not (X_MIN - 10 <= x <= X_MAX + 10 and Y_MIN - 10 <= y <= Y_MAX + 10):
                continue
            tx, ty = scene_transform(x, y)
            h = random.uniform(5, 9)
            # Trunk
            bpy.ops.mesh.primitive_cylinder_add(radius=0.12, depth=h, location=(tx, ty, h/2), vertices=8)
            trunk = bpy.context.active_object
            trunk.name = f"Trunk_{tree_count}"
            trunk.data.materials.append(m_trunk)
            link(trunk, c_trees)
            # Branches (3-5 bare branches, March = no leaves)
            m_branch = mat("Branch", "#5A4A38", 0.9)
            for bi in range(random.randint(3, 5)):
                b_angle = random.uniform(0, 6.28)
                b_len = random.uniform(1.5, 3.5)
                b_tilt = random.uniform(0.3, 0.7)
                b_x = tx + math.cos(b_angle) * b_len * 0.4
                b_y = ty + math.sin(b_angle) * b_len * 0.4
                b_z = h + b_len * 0.2
                bpy.ops.mesh.primitive_cylinder_add(radius=0.03, depth=b_len,
                    location=(b_x, b_y, b_z), vertices=6)
                br = bpy.context.active_object
                br.name = f"Branch_{tree_count}_{bi}"
                br.rotation_euler = (b_tilt * math.cos(b_angle+1.5),
                                      b_tilt * math.sin(b_angle+1.5), b_angle)
                br.data.materials.append(m_branch)
                link(br, c_trees)
            tree_count += 1
    print(f"  Trees: {tree_count}")

    # Street furniture
    c_field = col("StreetFurniture")
    sf_count = 0
    m_pole_wood = mat("WoodPole", "#6A5A4A", 0.85)
    m_pole_metal = mat("MetalPole", "#5A5A5A", 0.5)
    m_wire = mat("Wire", "#2A2A2A", 0.3)

    # Utility poles with cross-arms
    for pt in GIS.get("field", {}).get("poles", []):
        x, y = pt['x'], pt['y']
        if not (X_MIN - 10 <= x <= X_MAX + 10 and Y_MIN - 10 <= y <= Y_MAX + 10):
            continue
        tx, ty = scene_transform(x, y)
        pole_h = random.uniform(7, 9)

        # Main pole
        bpy.ops.mesh.primitive_cylinder_add(radius=0.1, depth=pole_h, location=(tx, ty, pole_h/2), vertices=8)
        p = bpy.context.active_object
        p.name = f"UtilityPole_{sf_count}"
        p.data.materials.append(m_pole_wood)
        link(p, c_field)

        # Cross-arm (horizontal bar at top)
        bpy.ops.mesh.primitive_cube_add(size=1, location=(tx, ty, pole_h - 0.5))
        ca = bpy.context.active_object
        ca.name = f"CrossArm_{sf_count}"
        ca.scale = (1.0, 0.06, 0.06)
        ca.data.materials.append(m_pole_wood)
        link(ca, c_field)

        # Insulators (3 small cylinders on cross-arm)
        m_insulator = mat("Insulator", "#4A6A4A", 0.5)
        for ix in [-0.7, 0, 0.7]:
            bpy.ops.mesh.primitive_cylinder_add(radius=0.03, depth=0.12,
                location=(tx + ix, ty, pole_h - 0.35), vertices=6)
            ins = bpy.context.active_object
            ins.name = f"Insulator_{sf_count}"
            ins.data.materials.append(m_insulator)
            link(ins, c_field)

        sf_count += 1

    # Bike racks (U-shaped)
    m_bike = mat("BikeRack", "#4488CC", 0.5)
    for pt in GIS.get("field", {}).get("bike_racks", []):
        x, y = pt['x'], pt['y']
        if not (X_MIN - 10 <= x <= X_MAX + 10 and Y_MIN - 10 <= y <= Y_MAX + 10):
            continue
        tx, ty = scene_transform(x, y)
        bpy.ops.mesh.primitive_torus_add(
            major_radius=0.4, minor_radius=0.03,
            location=(tx, ty, 0.5), major_segments=16, minor_segments=6)
        br = bpy.context.active_object
        br.name = f"BikeRack_{sf_count}"
        br.rotation_euler[0] = math.pi / 2
        br.data.materials.append(m_bike)
        link(br, c_field)
        sf_count += 1

    # Fire hydrants (from field data)
    m_hydrant = mat("Hydrant", "#E0C020", 0.5)
    for pt in GIS.get("field", {}).get("parking", []):  # parking points often near hydrants
        x, y = pt['x'], pt['y']
        if not (X_MIN - 10 <= x <= X_MAX + 10 and Y_MIN - 10 <= y <= Y_MAX + 10):
            continue
        tx, ty = scene_transform(x, y)
        bpy.ops.mesh.primitive_cylinder_add(radius=0.12, depth=0.6,
            location=(tx, ty, 0.3), vertices=8)
        hy = bpy.context.active_object
        hy.name = f"Hydrant_{sf_count}"
        hy.data.materials.append(m_hydrant)
        link(hy, c_field)
        sf_count += 1

    # Street lamp posts (add some along roads)
    m_lamp_pole = mat("LampPole", "#3A3A3A", 0.4)
    m_lamp_head = mat("LampHead", "#E0E0D0", 0.3)
    lamp_count = 0
    for pt in GIS.get("field", {}).get("poles", []):
        x, y = pt['x'], pt['y']
        if not (X_MIN - 10 <= x <= X_MAX + 10 and Y_MIN - 10 <= y <= Y_MAX + 10):
            continue
        # Every 3rd pole gets a lamp post nearby
        if lamp_count % 3 != 0:
            lamp_count += 1
            continue
        tx, ty = scene_transform(x, y)
        # Offset from utility pole
        lx = tx + random.uniform(-3, 3)
        ly = ty + random.uniform(-3, 3)
        lamp_h = 4.5

        # Pole
        bpy.ops.mesh.primitive_cylinder_add(radius=0.04, depth=lamp_h,
            location=(lx, ly, lamp_h/2), vertices=8)
        lp = bpy.context.active_object
        lp.name = f"LampPost_{lamp_count}"
        lp.data.materials.append(m_lamp_pole)
        link(lp, c_field)

        # Curved arm
        bpy.ops.mesh.primitive_cylinder_add(radius=0.03, depth=0.8,
            location=(lx + 0.3, ly, lamp_h - 0.2), vertices=6)
        la = bpy.context.active_object
        la.name = f"LampArm_{lamp_count}"
        la.rotation_euler = (0, math.pi/4, 0)
        la.data.materials.append(m_lamp_pole)
        link(la, c_field)

        # Light fixture
        bpy.ops.mesh.primitive_cube_add(size=1, location=(lx + 0.5, ly, lamp_h))
        lh = bpy.context.active_object
        lh.name = f"LampLight_{lamp_count}"
        lh.scale = (0.2, 0.12, 0.06)
        lh.data.materials.append(m_lamp_head)
        link(lh, c_field)

        sf_count += 1
        lamp_count += 1
    print(f"  Street furniture: {sf_count}")

    # ── Traffic lights at major intersections ──
    c_traffic = col("TrafficLights")
    m_tl_pole = mat("TLPole", "#3A3A3A", 0.4)
    m_tl_box = mat("TLBox", "#2A2A2A", 0.5)
    m_tl_red = mat("TLRed", "#CC2222", 0.3)
    m_tl_yellow = mat("TLYellow", "#CCAA22", 0.3)
    m_tl_green = mat("TLGreen", "#22AA44", 0.3)
    intersections = [
        (-75, -55),   # Dundas/Spadina area
        (25, -55),    # Dundas/Augusta area
        (-75, 85),    # College/Spadina area
        (25, 85),     # College/Augusta area
        (-25, 15),    # Nassau/Bellevue area
        (25, 15),     # Nassau/Augusta area
    ]
    tl_count = 0
    for ix, iy in intersections:
        for corner_off in [(-3, -3), (3, 3)]:
            tlx = ix + corner_off[0]
            tly = iy + corner_off[1]
            # Pole
            bpy.ops.mesh.primitive_cylinder_add(radius=0.06, depth=5.0,
                location=(tlx, tly, 2.5), vertices=8)
            tlp = bpy.context.active_object
            tlp.name = f"TLPole_{tl_count}"
            tlp.data.materials.append(m_tl_pole)
            link(tlp, c_traffic)
            # Signal box
            bpy.ops.mesh.primitive_cube_add(size=1, location=(tlx, tly, 4.8))
            tlb = bpy.context.active_object
            tlb.name = f"TLBox_{tl_count}"
            tlb.scale = (0.15, 0.15, 0.45)
            tlb.data.materials.append(m_tl_box)
            link(tlb, c_traffic)
            # Signal lights (red/yellow/green)
            for li, (lz, lm) in enumerate([(5.0, m_tl_red), (4.8, m_tl_yellow), (4.6, m_tl_green)]):
                bpy.ops.mesh.primitive_uv_sphere_add(radius=0.05,
                    location=(tlx + 0.16, tly, lz), segments=8, ring_count=6)
                tll = bpy.context.active_object
                tll.name = f"TLLight_{tl_count}_{li}"
                tll.data.materials.append(lm)
                link(tll, c_traffic)
            tl_count += 1
    print(f"  Traffic lights: {tl_count}")

    # ── City garbage bins (large green/black) ──
    c_bins = col("GarbageBins")
    m_bin_green = mat("BinGreen", "#2A6A2A", 0.7)
    m_bin_black = mat("BinBlack", "#2A2A2A", 0.7)
    m_bin_blue = mat("BinBlue", "#2244AA", 0.7)
    bin_count = 0
    for pt in GIS.get("field", {}).get("bike_racks", []):
        x, y = pt['x'], pt['y']
        if not (X_MIN - 5 <= x <= X_MAX + 5 and Y_MIN - 5 <= y <= Y_MAX + 5):
            continue
        bx, by = scene_transform(x + random.uniform(-2, 2), y + random.uniform(-2, 2))
        bin_mat = random.choice([m_bin_green, m_bin_black, m_bin_blue])
        # Body
        bpy.ops.mesh.primitive_cylinder_add(radius=0.25, depth=0.7,
            location=(bx, by, 0.35), vertices=8)
        bo = bpy.context.active_object
        bo.name = f"GarbageBin_{bin_count}"
        bo.data.materials.append(bin_mat)
        link(bo, c_bins)
        # Lid
        bpy.ops.mesh.primitive_cylinder_add(radius=0.27, depth=0.04,
            location=(bx, by, 0.72), vertices=8)
        bl = bpy.context.active_object
        bl.name = f"BinLid_{bin_count}"
        bl.data.materials.append(bin_mat)
        link(bl, c_bins)
        bin_count += 1
    print(f"  Garbage bins: {bin_count}")

    # ── Newspaper vending machines ──
    c_news = col("NewspaperBoxes")
    m_news_red = mat("NewsRed", "#CC3333", 0.5)
    m_news_blue = mat("NewsBlue", "#3355AA", 0.5)
    m_news_yellow = mat("NewsYellow", "#CCAA22", 0.5)
    news_count = 0
    for pt in GIS.get("field", {}).get("poles", []):
        if news_count >= 15:
            break
        if random.random() > 0.15:
            continue
        x, y = pt['x'], pt['y']
        if not (X_MIN - 5 <= x <= X_MAX + 5 and Y_MIN - 5 <= y <= Y_MAX + 5):
            continue
        nx, ny = scene_transform(x + random.uniform(1, 3), y + random.uniform(-1, 1))
        n_mat = random.choice([m_news_red, m_news_blue, m_news_yellow])
        bpy.ops.mesh.primitive_cube_add(size=1, location=(nx, ny, 0.5))
        nbo = bpy.context.active_object
        nbo.name = f"NewsBox_{news_count}"
        nbo.scale = (0.2, 0.15, 0.5)
        nbo.data.materials.append(n_mat)
        link(nbo, c_news)
        news_count += 1
    print(f"  Newspaper boxes: {news_count}")

    # ── Bus stop shelters ──
    c_bus = col("BusShelters")
    m_bus_frame = mat("BusFrame", "#4A4A4A", 0.4)
    m_bus_glass = mat("BusGlass", "#8AB0C8", 0.2)
    bus_stops = [
        (-70, -50, 0),     # Spadina near Dundas
        (-70, 30, 0),      # Spadina near Nassau
        (-70, 80, 0),      # Spadina near College
        (60, -50, math.pi/2),   # Dundas east
    ]
    for bs_i, (bsx, bsy, bs_rot) in enumerate(bus_stops):
        # Back wall (glass)
        bpy.ops.mesh.primitive_cube_add(size=1, location=(bsx, bsy, 1.2))
        bsw = bpy.context.active_object
        bsw.name = f"BusShelterWall_{bs_i}"
        bsw.scale = (1.5, 0.02, 1.2)
        bsw.rotation_euler = (0, 0, bs_rot)
        bsw.data.materials.append(m_bus_glass)
        link(bsw, c_bus)
        # Roof
        bpy.ops.mesh.primitive_cube_add(size=1, location=(bsx, bsy, 2.4))
        bsr = bpy.context.active_object
        bsr.name = f"BusShelterRoof_{bs_i}"
        bsr.scale = (1.6, 0.6, 0.03)
        bsr.rotation_euler = (0, 0, bs_rot)
        bsr.data.materials.append(m_bus_frame)
        link(bsr, c_bus)
        # Support posts (2)
        for sp_off in [-1.4, 1.4]:
            spx = bsx + math.cos(bs_rot) * sp_off
            spy = bsy + math.sin(bs_rot) * sp_off
            bpy.ops.mesh.primitive_cylinder_add(radius=0.04, depth=2.4,
                location=(spx, spy, 1.2), vertices=6)
            bsp = bpy.context.active_object
            bsp.name = f"BusShelterPost_{bs_i}"
            bsp.data.materials.append(m_bus_frame)
            link(bsp, c_bus)
        # Bench
        bpy.ops.mesh.primitive_cube_add(size=1, location=(bsx, bsy + 0.2, 0.45))
        bsb = bpy.context.active_object
        bsb.name = f"BusBench_{bs_i}"
        bsb.scale = (1.0, 0.15, 0.03)
        bsb.rotation_euler = (0, 0, bs_rot)
        bsb.data.materials.append(m_bus_frame)
        link(bsb, c_bus)
    print(f"  Bus shelters: {len(bus_stops)}")

    # ── Community bulletin boards ──
    c_boards = col("BulletinBoards")
    m_board_frame = mat("BoardFrame", "#5A4030", 0.75)
    m_board_cork = mat("BoardCork", "#B8956A", 0.9)
    board_locs = [(-25, -40), (15, 20), (-10, 70), (30, -20)]
    for bb_i, (bbx, bby) in enumerate(board_locs):
        # Posts (2)
        for bp_off in [-0.4, 0.4]:
            bpy.ops.mesh.primitive_cylinder_add(radius=0.04, depth=2.0,
                location=(bbx + bp_off, bby, 1.0), vertices=6)
            bpy.context.active_object.data.materials.append(m_board_frame)
            link(bpy.context.active_object, c_boards)
        # Board
        bpy.ops.mesh.primitive_cube_add(size=1, location=(bbx, bby, 1.5))
        bbo = bpy.context.active_object
        bbo.name = f"BulletinBoard_{bb_i}"
        bbo.scale = (0.5, 0.02, 0.35)
        bbo.data.materials.append(m_board_cork)
        link(bbo, c_boards)
        # Frame overlay
        bpy.ops.mesh.primitive_cube_add(size=1, location=(bbx, bby - 0.025, 1.5))
        bbf = bpy.context.active_object
        bbf.name = f"BoardFrame_{bb_i}"
        bbf.scale = (0.52, 0.005, 0.37)
        bbf.data.materials.append(m_board_frame)
        link(bbf, c_boards)
    print(f"  Bulletin boards: {len(board_locs)}")

    # ── Alley features (dumpsters, recycling) ──
    c_alley = col("AlleyFeatures")
    m_dumpster = mat("Dumpster", "#2A5A2A", 0.7)
    m_recycling = mat("Recycling", "#2244AA", 0.7)
    alley_count = 0
    for al in GIS.get("alleys", []):
        coords = al.get("coords", [])
        if len(coords) < 2:
            continue
        mid_i = len(coords) // 2
        ax, ay = scene_transform(coords[mid_i][0], coords[mid_i][1])
        # Dumpster
        bpy.ops.mesh.primitive_cube_add(size=1, location=(ax + random.uniform(-2, 2), ay + random.uniform(-2, 2), 0.6))
        dmp = bpy.context.active_object
        dmp.name = f"Dumpster_{alley_count}"
        dmp.scale = (0.8, 0.5, 0.6)
        dmp.rotation_euler = (0, 0, random.uniform(0, math.pi))
        dmp.data.materials.append(m_dumpster)
        link(dmp, c_alley)
        # Recycling bin nearby
        bpy.ops.mesh.primitive_cylinder_add(radius=0.3, depth=0.7,
            location=(ax + random.uniform(-3, 3), ay + random.uniform(-3, 3), 0.35), vertices=8)
        rco = bpy.context.active_object
        rco.name = f"Recycling_{alley_count}"
        rco.data.materials.append(m_recycling)
        link(rco, c_alley)
        alley_count += 1
    print(f"  Alley dumpsters/recycling: {alley_count}")

    # Sun + Camera
    bpy.ops.object.light_add(type='SUN', location=(0, 0, 100))
    sun = bpy.context.active_object
    sun.data.energy = 3.0
    sun.rotation_euler = (math.radians(50), math.radians(10), math.radians(25))

    bpy.ops.object.camera_add(location=(20, -200, 80))
    cam = bpy.context.active_object
    cam.rotation_euler = (math.radians(55), 0, math.radians(10))
    bpy.context.scene.camera = cam

    out = str(SCRIPT_DIR / "outputs" / "demos" / "bellevue_footprint_demo.blend")
    bpy.ops.wm.save_as_mainfile(filepath=out)
    print(f"\nSaved: {out}")


main()
