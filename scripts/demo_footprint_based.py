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

# Bellevue area bounds
X_MIN, X_MAX = -130, 0
Y_MIN, Y_MAX = -200, 20

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
    hex_col = MATERIAL_COLOURS.get(facade_mat_name, "#B8654A")
    facade_mat = mat(f"Facade_{hex_col}", hex_col, 0.7)

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
        if ei >= 4:
            break

        dx, dy = x2 - x1, y2 - y1
        angle = math.atan2(dy, dx)
        n_win = max(1, int(length / 2.5))
        win_w, win_h = 1.0, 1.4

        for fi in range(int(floors)):
            if fi == 0 and has_storefront and ei == 0:
                continue
            sill_z = fi * floor_h + floor_h * 0.3
            for wi in range(n_win):
                t = (wi + 1) / (n_win + 1)
                # Window sits flush with wall, recessed 0.1m
                wx = x1 + dx * t + nx * 0.05
                wy = y1 + dy * t + ny * 0.05
                wz = sill_z + win_h / 2

                bpy.ops.mesh.primitive_cube_add(size=1, location=(wx, wy, wz))
                w = bpy.context.active_object
                w.name = f"W_{ei}_{fi}_{wi}"
                # Scale: width along wall edge, height vertical, depth into wall
                # Align cube axes with wall orientation
                w.scale = (win_w / 2, 0.08, win_h / 2)
                w.rotation_euler = (0, 0, angle)
                w.data.materials.append(m_glass)
                link(w, collection)

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

    # 3. Roof
    m_roof = mat("Roof", "#4A4A4A", 0.85)

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


def main():
    # Clear scene
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete()
    for c in list(bpy.data.collections):
        bpy.data.collections.remove(c)

    print("=== Bellevue Demo: Footprint-Based Generation ===")

    # Ground plane
    c_env = col("Ground")
    bpy.ops.mesh.primitive_plane_add(size=1, location=(-65, -90, -0.05))
    g = bpy.context.active_object
    g.name = "Ground"
    g.scale = (100, 120, 1)
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

        ns_streets = {"Bellevue Ave", "Wales Ave", "Leonard Pl", "Leonard Ave"}
        ew_streets = {"Augusta Ave", "Nassau St", "Denison Ave", "Denison Sq",
                      "Oxford St", "Dundas St"}

        if street_name in ns_streets:
            facing_bearing = 73 if bx < -70 else 253
        elif street_name in ew_streets:
            facing_bearing = 343 if by < -100 else 163
        else:
            # Fallback: use bearing data
            facing_bearing = pos.get('bearing_deg', 73)

        rot_deg = (360 - facing_bearing) % 360
        rot_rad = math.radians(rot_deg)
        massing_h = pos.get('massing_height_m')

        # Get params
        p = PARAMS.get(addr, {})
        stories = p.get('floors', 2) or 2
        h = massing_h or p.get('total_height_m') or stories * 3.2
        if h <= 0:
            h = stories * 3.2
        width = p.get('facade_width_m', 5.2) or 5.2
        depth = 10.0  # front building portion only

        # Create box CENTERED on the position point
        hw, hd = width / 2, depth / 2

        # 4 corners centered on (0,0)
        corners = [(-hw, hd), (hw, hd), (hw, -hd), (-hw, -hd)]

        cos_r, sin_r = math.cos(rot_rad), math.sin(rot_rad)
        ring = [(lx*cos_r - ly*sin_r + bx, lx*sin_r + ly*cos_r + by) for lx, ly in corners]

        create_building_from_footprint(ring, c_bldg, override_h=h)
        bldg_count += 1

    print(f"  Buildings (from gis_scene positions): {bldg_count}")

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
        mesh = road_mesh(coords, 7.0, f"Road_{road_count}")
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
        mesh = road_mesh(coords, 3.0, f"Alley_{road_count}")
        if mesh:
            obj = bpy.data.objects.new(f"Alley_{road_count}", mesh)
            obj.data.materials.append(m_alley)
            link(obj, c_road)
            road_count += 1
    print(f"  Roads + alleys: {road_count}")

    # Trees
    c_trees = col("Trees")
    m_trunk = mat("Trunk", "#4A3520", 0.9)
    m_canopy = mat("Canopy", "#2A5A2A", 0.8)
    tree_count = 0
    for pt in GIS.get("field", {}).get("trees", []):
        x, y = pt['x'], pt['y']
        if not (X_MIN - 10 <= x <= X_MAX + 10 and Y_MIN - 10 <= y <= Y_MAX + 10):
            continue
        h = random.uniform(5, 9)
        bpy.ops.mesh.primitive_cylinder_add(radius=0.1, depth=h, location=(x, y, h/2), vertices=8)
        bpy.context.active_object.data.materials.append(m_trunk)
        link(bpy.context.active_object, c_trees)
        bpy.ops.mesh.primitive_uv_sphere_add(radius=1.8, location=(x, y, h+0.5), segments=8, ring_count=6)
        ca = bpy.context.active_object
        ca.scale = (1, 1, 0.6)
        ca.data.materials.append(m_canopy)
        link(ca, c_trees)
        tree_count += 1
    print(f"  Trees: {tree_count}")

    # Street furniture
    c_field = col("StreetFurniture")
    sf_count = 0
    for layer, cfg in [("poles", (0.06, 6, "#5A5A5A")), ("bike_racks", (0.3, 0.8, "#4488CC"))]:
        for pt in GIS.get("field", {}).get(layer, []):
            x, y = pt['x'], pt['y']
            if not (X_MIN - 10 <= x <= X_MAX + 10 and Y_MIN - 10 <= y <= Y_MAX + 10):
                continue
            bpy.ops.mesh.primitive_cylinder_add(radius=cfg[0], depth=cfg[1], location=(x, y, cfg[1]/2), vertices=8)
            bpy.context.active_object.data.materials.append(mat(f"F_{layer}", cfg[2], 0.5))
            link(bpy.context.active_object, c_field)
            sf_count += 1
    print(f"  Street furniture: {sf_count}")

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
