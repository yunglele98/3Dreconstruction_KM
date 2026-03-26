"""Bellevue Ave detailed demo — all GIS layers + architectural detail.

Layers:
- 3D massing with per-building materials, windows, doors from params
- Roofs (gable/hip/flat from params)
- Storefronts on commercial ground floors
- Park polygon with playground, benches, lamps, boulders, paths
- Flat road/pedestrian surfaces
- Street trees (trunks + canopy)
- Field survey: poles, signs, bike racks, terraces

Run: blender --python scripts/demo_bellevue_detailed.py
"""

import bpy
import bmesh
import json
import math
import os
import re
import random
from pathlib import Path

random.seed(42)

SCRIPT_DIR = Path(os.path.dirname(os.path.abspath(__file__))).parent
DATA = json.load(open(SCRIPT_DIR / "outputs" / "demos" / "bellevue_gis_data.json"))
GIS = json.load(open(SCRIPT_DIR / "outputs" / "gis_scene.json"))
SITE = json.load(open(SCRIPT_DIR / "params" / "_site_coordinates.json", encoding="utf-8"))

# Load all params for address matching
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
                PARAMS[f.stem.replace("_", " ")] = d
    except:
        pass

# Bounds
X_MIN, X_MAX = -140, 70
Y_MIN, Y_MAX = -200, 30


def clear():
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete()
    for c in list(bpy.data.collections):
        bpy.data.collections.remove(c)


_mats = {}
def mat(name, hex_c, rough=0.8):
    if name in _mats:
        return _mats[name]
    m = bpy.data.materials.new(name=name)
    m.use_nodes = True
    b = m.node_tree.nodes.get("Principled BSDF")
    if b:
        h = hex_c.lstrip("#")
        r, g, bl = (int(h[i:i+2], 16)/255 for i in (0,2,4))
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


def poly_mesh(coords, z=0, name="p"):
    bm = bmesh.new()
    verts = [bm.verts.new((x, y, z)) for x, y in coords]
    try:
        bm.faces.new(verts)
    except:
        bm.free()
        return None
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()
    return mesh


def extrude_mesh(coords, h, name="m"):
    bm = bmesh.new()
    verts = [bm.verts.new((x, y, 0)) for x, y in coords]
    try:
        face = bm.faces.new(verts)
    except:
        bm.free()
        return None
    result = bmesh.ops.extrude_face_region(bm, geom=[face])
    for v in (v for v in result["geom"] if isinstance(v, bmesh.types.BMVert)):
        v.co.z = h
    bm.normal_update()
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()
    return mesh


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
        l = max((dx*dx+dy*dy)**0.5, 0.01)
        nx, ny = -dy/l*hw, dx/l*hw
        L.append(bm.verts.new((x+nx, y+ny, 0.02)))
        R.append(bm.verts.new((x-nx, y-ny, 0.02)))
    for i in range(len(coords)-1):
        try:
            bm.faces.new([L[i], L[i+1], R[i+1], R[i]])
        except:
            pass
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()
    return mesh


def find_params_for_position(x, y):
    """Find nearest building params by position."""
    best, best_d = None, 999
    for addr, pos in SITE.items():
        d = ((pos['x']-x)**2 + (pos['y']-y)**2)**0.5
        if d < best_d:
            best_d = d
            best = addr
    if best and best_d < 15:
        return PARAMS.get(best)
    return None


MATERIAL_COLOURS = {
    "brick": "#B8654A", "stone": "#A09880", "stucco": "#D8D0C0",
    "clapboard": "#E8DCC8", "paint": "#C8D0C8", "siding": "#C0C8C0",
    "wood": "#8A7050", "concrete": "#A0A0A0", "glass": "#6090B0",
}


def add_building_detail(massing_obj, h, coords, collection):
    """Add windows, doors, roof, material from matched params."""
    # Find center
    xs = [c[0] for c in coords]
    ys = [c[1] for c in coords]
    cx, cy = sum(xs)/len(xs), sum(ys)/len(ys)

    params = find_params_for_position(cx, cy)

    # Material
    facade_mat_name = "brick"
    if params:
        facade_mat_name = (params.get("facade_material") or "brick").lower()
    hex_col = MATERIAL_COLOURS.get(facade_mat_name, "#B8654A")
    facade_mat = mat(f"Facade_{facade_mat_name}", hex_col, 0.7)
    if massing_obj.data.materials:
        massing_obj.data.materials[0] = facade_mat
    else:
        massing_obj.data.materials.append(facade_mat)

    # Find edges sorted by length
    edges = []
    for i in range(len(coords)):
        x1, y1 = coords[i]
        x2, y2 = coords[(i+1) % len(coords)]
        length = ((x2-x1)**2 + (y2-y1)**2)**0.5
        edges.append((length, x1, y1, x2, y2, i))
    edges.sort(reverse=True)

    m_glass = mat("Glass", "#3A5A7A", 0.2)
    m_door = mat("Door", "#5A3A20", 0.75)
    m_store = mat("Storefront", "#2A4A5A", 0.25)

    floors = 2
    has_storefront = False
    if params:
        floors = params.get("floors", 2) or 2
        has_storefront = params.get("has_storefront", False)

    floor_h = h / max(floors, 1)

    # Windows on top 2 longest edges
    for ei in range(min(2, len(edges))):
        length, x1, y1, x2, y2, _ = edges[ei]
        if length < 2.5:
            continue

        dx, dy = x2-x1, y2-y1
        el = max(length, 0.01)
        nx, ny = -dy/el, dx/el  # outward normal
        angle = math.atan2(dy, dx)

        n_win = max(1, int(length / 2.5))
        win_w, win_h = 0.85, 1.1

        for fi in range(int(floors)):
            if fi == 0 and has_storefront and ei == 0:
                continue  # skip ground floor windows on storefront facade
            sill_z = fi * floor_h + floor_h * 0.3
            for wi in range(n_win):
                t = (wi + 1) / (n_win + 1)
                wx = x1 + dx*t + nx*0.16
                wy = y1 + dy*t + ny*0.16
                wz = sill_z + win_h/2

                bpy.ops.mesh.primitive_plane_add(size=1, location=(wx, wy, wz))
                w = bpy.context.active_object
                w.name = f"W_{ei}_{fi}_{wi}"
                w.scale = (win_w/2, win_h/2, 1)
                w.rotation_euler = (math.pi/2, 0, angle + math.pi/2)
                w.data.materials.append(m_glass)
                link(w, collection)

        # Door on ground floor (longest edge only)
        if ei == 0:
            door_t = 0.5  # center
            door_w, door_h = 0.95, 2.1
            dox = x1 + dx*door_t + nx*0.16
            doy = y1 + dy*door_t + ny*0.16
            bpy.ops.mesh.primitive_plane_add(size=1, location=(dox, doy, door_h/2))
            d = bpy.context.active_object
            d.name = f"Door_{ei}"
            d.scale = (door_w/2, door_h/2, 1)
            d.rotation_euler = (math.pi/2, 0, angle + math.pi/2)
            d.data.materials.append(m_door)
            link(d, collection)

        # Storefront glazing on ground floor
        if ei == 0 and has_storefront:
            sf_h = min(floor_h * 0.7, 2.8)
            sf_w = length * 0.7
            sf_x = x1 + dx*0.5 + nx*0.16
            sf_y = y1 + dy*0.5 + ny*0.16
            bpy.ops.mesh.primitive_plane_add(size=1, location=(sf_x, sf_y, sf_h/2 + 0.3))
            sf = bpy.context.active_object
            sf.name = "Storefront"
            sf.scale = (sf_w/2, sf_h/2, 1)
            sf.rotation_euler = (math.pi/2, 0, angle + math.pi/2)
            sf.data.materials.append(m_store)
            link(sf, collection)

    # Roof — sits directly on the massing polygon top face
    roof_type = "flat"
    if params:
        roof_type = (params.get("roof_type") or "flat").lower()

    m_roof = mat("Roof_Shingle", "#4A4A4A", 0.85)

    if "gable" in roof_type and len(coords) >= 3:
        # Find the oriented bounding box principal axis
        # Use the longest edge as ridge direction
        best_len, best_dx, best_dy = 0, 1, 0
        for i in range(len(coords)):
            x1, y1 = coords[i]
            x2, y2 = coords[(i+1) % len(coords)]
            el = ((x2-x1)**2 + (y2-y1)**2)**0.5
            if el > best_len:
                best_len = el
                best_dx = (x2-x1) / max(el, 0.01)
                best_dy = (y2-y1) / max(el, 0.01)

        # Project all coords onto ridge axis and perpendicular
        perp_dx, perp_dy = -best_dy, best_dx
        ridge_projs = []
        perp_projs = []
        for x, y in coords:
            rx = (x - cx) * best_dx + (y - cy) * best_dy
            ry = (x - cx) * perp_dx + (y - cy) * perp_dy
            ridge_projs.append(rx)
            perp_projs.append(ry)

        ridge_min, ridge_max = min(ridge_projs), max(ridge_projs)
        perp_min, perp_max = min(perp_projs), max(perp_projs)
        bw = perp_max - perp_min  # building width across ridge
        ridge_len = ridge_max - ridge_min

        ridge_h = min(bw * 0.35, 2.5)
        if ridge_h < 0.5:
            ridge_h = 1.0

        # Ridge endpoints (along the longest axis, at center of perpendicular span)
        r1x = cx + best_dx * ridge_min
        r1y = cy + best_dy * ridge_min
        r2x = cx + best_dx * ridge_max
        r2y = cy + best_dy * ridge_max

        # Eave points (offset perpendicular from ridge line to polygon edges)
        e1x = cx + perp_dx * perp_min  # one side
        e1y = cy + perp_dy * perp_min
        e2x = cx + perp_dx * perp_max  # other side
        e2y = cy + perp_dy * perp_max

        bm = bmesh.new()
        # Four eave corners + two ridge endpoints
        c1 = bm.verts.new((r1x + perp_dx * perp_min, r1y + perp_dy * perp_min, h))
        c2 = bm.verts.new((r1x + perp_dx * perp_max, r1y + perp_dy * perp_max, h))
        c3 = bm.verts.new((r2x + perp_dx * perp_max, r2y + perp_dy * perp_max, h))
        c4 = bm.verts.new((r2x + perp_dx * perp_min, r2y + perp_dy * perp_min, h))
        ridge1 = bm.verts.new((r1x, r1y, h + ridge_h))
        ridge2 = bm.verts.new((r2x, r2y, h + ridge_h))
        try:
            bm.faces.new([c1, c4, ridge2, ridge1])  # slope 1
            bm.faces.new([c2, ridge1, ridge2, c3])   # slope 2
            bm.faces.new([c1, c2, ridge1])            # gable end 1
            bm.faces.new([c4, ridge2, c3])            # gable end 2
        except:
            pass
        mesh = bpy.data.meshes.new("GableRoof")
        bm.to_mesh(mesh)
        bm.free()
        roof = bpy.data.objects.new("GableRoof", mesh)
        roof.data.materials.append(m_roof)
        link(roof, collection)

    elif "hip" in roof_type and len(coords) >= 3:
        # Hip roof: pyramid from polygon top face to center peak
        ridge_h = min((max(xs) - min(xs)) * 0.25, (max(ys) - min(ys)) * 0.25, 2.5)
        bm = bmesh.new()
        bottom = [bm.verts.new((x, y, h)) for x, y in coords]
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

    elif roof_type == "flat" or not roof_type:
        # Flat roof cap (just a polygon on top — already part of massing extrusion)
        pass


def add_field_features(collection):
    """Add poles, signs, bike racks, terraces from field survey."""
    gis_field = GIS.get("field", {})
    count = 0

    # Poles
    m_pole = mat("Pole", "#5A5A5A", 0.5)
    for pt in gis_field.get("poles", []):
        x, y = pt['x'], pt['y']
        if not (X_MIN <= x <= X_MAX and Y_MIN <= y <= Y_MAX):
            continue
        bpy.ops.mesh.primitive_cylinder_add(radius=0.06, depth=6, location=(x, y, 3), vertices=8)
        p = bpy.context.active_object
        p.name = f"Pole_{count}"
        p.data.materials.append(m_pole)
        link(p, collection)
        count += 1

    # Signs
    m_sign = mat("Sign", "#CC4444", 0.6)
    for pt in gis_field.get("signs", []):
        x, y = pt['x'], pt['y']
        if not (X_MIN <= x <= X_MAX and Y_MIN <= y <= Y_MAX):
            continue
        # Pole
        bpy.ops.mesh.primitive_cylinder_add(radius=0.04, depth=2.5, location=(x, y, 1.25), vertices=8)
        p = bpy.context.active_object
        p.name = f"SignPole_{count}"
        p.data.materials.append(m_pole)
        link(p, collection)
        # Sign face
        bpy.ops.mesh.primitive_cube_add(size=1, location=(x, y, 2.5))
        s = bpy.context.active_object
        s.name = f"Sign_{count}"
        s.scale = (0.3, 0.3, 0.02)
        s.data.materials.append(m_sign)
        link(s, collection)
        count += 1

    # Bike racks
    m_bike = mat("BikeRack", "#4488CC", 0.5)
    for pt in gis_field.get("bike_racks", []):
        x, y = pt['x'], pt['y']
        if not (X_MIN <= x <= X_MAX and Y_MIN <= y <= Y_MAX):
            continue
        bpy.ops.mesh.primitive_torus_add(
            major_radius=0.4, minor_radius=0.03,
            location=(x, y, 0.5), major_segments=16, minor_segments=8)
        b = bpy.context.active_object
        b.name = f"BikeRack_{count}"
        b.rotation_euler[0] = math.pi/2
        b.data.materials.append(m_bike)
        link(b, collection)
        count += 1

    # Terraces
    m_terrace = mat("Terrace", "#AA8855", 0.8)
    for pt in gis_field.get("terraces", []):
        x, y = pt['x'], pt['y']
        if not (X_MIN <= x <= X_MAX and Y_MIN <= y <= Y_MAX):
            continue
        bpy.ops.mesh.primitive_cube_add(size=1, location=(x, y, 0.05))
        t = bpy.context.active_object
        t.name = f"Terrace_{count}"
        t.scale = (2.0, 1.5, 0.05)
        t.data.materials.append(m_terrace)
        link(t, collection)
        count += 1

    return count


def add_park_detail(park_coords, collection):
    """Park features: playground, benches, lamps, boulders, paths, hydrants."""
    xs = [c[0] for c in park_coords]
    ys = [c[1] for c in park_coords]
    cx = (min(xs)+max(xs))/2
    cy = (min(ys)+max(ys))/2
    pw = max(xs)-min(xs)
    ph = max(ys)-min(ys)

    # Paths crossing park
    m_path = mat("ParkPath", "#A0A0A0", 0.75)
    for (sx,sy),(ex,ey) in [((min(xs)+3,cy),(max(xs)-3,cy)), ((cx,min(ys)+3),(cx,max(ys)-3)),
                             ((min(xs)+5,min(ys)+5),(max(xs)-5,max(ys)-5))]:
        mesh = road_mesh([(sx,sy),(ex,ey)], 2.0, "PP")
        if mesh:
            obj = bpy.data.objects.new("ParkPath", mesh)
            obj.data.materials.append(m_path)
            link(obj, collection)

    # Playground (NE quadrant)
    m_play_o = mat("PlayOrange", "#E06020", 0.6)
    m_play_b = mat("PlayBlue", "#2060C0", 0.6)
    pg_x, pg_y = cx + pw*0.15, cy + ph*0.15
    for dx, dy in [(-2,-1.5),(2,-1.5),(-2,1.5),(2,1.5)]:
        bpy.ops.mesh.primitive_cylinder_add(radius=0.06, depth=3, location=(pg_x+dx,pg_y+dy,1.5), vertices=8)
        link(bpy.context.active_object, collection)
        bpy.context.active_object.data.materials.append(m_play_o)
    # Top bars
    for dy in [-1.5, 1.5]:
        bpy.ops.mesh.primitive_cylinder_add(radius=0.04, depth=4, location=(pg_x,pg_y+dy,3), vertices=8)
        bpy.context.active_object.rotation_euler[1] = math.pi/2
        link(bpy.context.active_object, collection)
        bpy.context.active_object.data.materials.append(m_play_o)
    # Slide
    bpy.ops.mesh.primitive_cube_add(size=1, location=(pg_x+3,pg_y,1))
    s = bpy.context.active_object
    s.scale = (1.5,0.4,0.03); s.rotation_euler[1] = -0.5
    s.data.materials.append(m_play_b)
    link(s, collection)
    # Platform
    bpy.ops.mesh.primitive_cube_add(size=1, location=(pg_x,pg_y,2.8))
    p = bpy.context.active_object
    p.scale = (2,1.5,0.05)
    p.data.materials.append(mat("PG_plat","#888888",0.6))
    link(p, collection)
    # Fence
    m_fence = mat("Fence","#2A2A2A",0.5)
    for a in range(0,360,12):
        r = math.radians(a)
        bpy.ops.mesh.primitive_cylinder_add(radius=0.02, depth=0.9, location=(pg_x+5*math.cos(r),pg_y+5*math.sin(r),0.45), vertices=6)
        link(bpy.context.active_object, collection)
        bpy.context.active_object.data.materials.append(m_fence)

    # Benches
    m_bench = mat("Bench","#8B6914",0.8)
    for bx,by,rot in [(cx-pw*0.25,cy,0),(cx+pw*0.25,cy,math.pi),
                       (cx,cy+ph*0.25,math.pi/2),(cx,cy-ph*0.25,-math.pi/2),
                       (cx-pw*0.1,cy+ph*0.3,0.3),(cx+pw*0.1,cy-ph*0.3,-0.3)]:
        bpy.ops.mesh.primitive_cube_add(size=1, location=(bx,by,0.45))
        b = bpy.context.active_object
        b.scale = (0.8,0.25,0.025); b.rotation_euler[2] = rot
        b.data.materials.append(m_bench)
        link(b, collection)

    # Lamp posts
    m_lamp = mat("Lamp","#505050",0.4)
    m_light = mat("LampLight","#E0E0D0",0.3)
    for lx,ly in [(cx-pw*0.3,cy),(cx+pw*0.3,cy),(cx,cy+ph*0.3),(cx,cy-ph*0.3),
                   (cx-pw*0.15,cy+ph*0.2),(cx+pw*0.15,cy-ph*0.2)]:
        bpy.ops.mesh.primitive_cylinder_add(radius=0.05, depth=4.5, location=(lx,ly,2.25), vertices=8)
        link(bpy.context.active_object, collection)
        bpy.context.active_object.data.materials.append(m_lamp)
        bpy.ops.mesh.primitive_cube_add(size=1, location=(lx,ly,4.5))
        h = bpy.context.active_object
        h.scale = (0.3,0.15,0.05)
        h.data.materials.append(m_light)
        link(h, collection)

    # Boulders
    m_rock = mat("Boulder","#787878",0.85)
    for _ in range(8):
        bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=2,
            radius=random.uniform(0.3,0.6),
            location=(cx+random.uniform(-pw*0.35,pw*0.35),cy+random.uniform(-ph*0.35,ph*0.35),0.2))
        r = bpy.context.active_object
        r.scale = (random.uniform(0.8,1.2),random.uniform(0.8,1.2),random.uniform(0.4,0.7))
        r.data.materials.append(m_rock)
        link(r, collection)

    # Hydrants (yellow)
    m_hy = mat("Hydrant","#E0C020",0.5)
    for hx,hy in [(min(xs)+2,min(ys)+2),(max(xs)-2,min(ys)+2),(min(xs)+2,max(ys)-2)]:
        bpy.ops.mesh.primitive_cylinder_add(radius=0.12, depth=0.6, location=(hx,hy,0.3), vertices=8)
        link(bpy.context.active_object, collection)
        bpy.context.active_object.data.materials.append(m_hy)


def main():
    clear()
    print("=== Bellevue Detailed Demo ===")

    # Ground
    c_ground = col("Ground")
    bpy.ops.mesh.primitive_plane_add(size=1, location=(-35, -85, -0.05))
    g = bpy.context.active_object
    g.name = "Ground"; g.scale = (120, 130, 1)
    g.data.materials.append(mat("Ground","#3A4A2A",0.95))
    link(g, c_ground)

    # Park
    c_park = col("Park")
    m_grass = mat("Grass","#4A7A2A",0.9)
    for p in DATA.get('parks', []):
        mesh = poly_mesh(p['coords'], 0.03, "Park")
        if mesh:
            obj = bpy.data.objects.new("Park", mesh)
            obj.data.materials.append(m_grass)
            link(obj, c_park)
        add_park_detail(p['coords'], c_park)
    print(f"  Park: {len(DATA.get('parks',[]))} with details")

    # Footprints
    c_fp = col("Footprints")
    m_fp = mat("FP","#8A7A6A",0.85)
    for i, fp in enumerate(DATA.get('footprints',[])):
        mesh = poly_mesh(fp['coords'], 0.05, f"FP_{i}")
        if mesh:
            obj = bpy.data.objects.new(f"FP_{i}", mesh)
            obj.data.materials.append(m_fp)
            link(obj, c_fp)
    print(f"  Footprints: {len(DATA.get('footprints',[]))}")

    # Massing with detail
    c_mass = col("Buildings")
    win_count = 0
    for i, m in enumerate(DATA.get('massing',[])):
        if m['h'] <= 0:
            continue
        mesh = extrude_mesh(m['coords'], m['h'], f"Mass_{i}")
        if mesh:
            obj = bpy.data.objects.new(f"Mass_{i}", mesh)
            obj.data.materials.append(mat("DefaultBrick","#B8654A",0.7))
            link(obj, c_mass)
            add_building_detail(obj, m['h'], m['coords'], c_mass)
    print(f"  Massing: {len(DATA.get('massing',[]))} with details")

    # Roads
    c_road = col("Roads")
    m_road = mat("Road","#2A2A2A",0.9)
    for i, r in enumerate(DATA.get('roads',[])):
        mesh = road_mesh(r['coords'], 7.0, f"Road_{i}")
        if mesh:
            obj = bpy.data.objects.new(f"Road_{i}", mesh)
            obj.data.materials.append(m_road)
            link(obj, c_road)
    print(f"  Roads: {len(DATA.get('roads',[]))}")

    # Pedestrian
    m_ped = mat("Ped","#C0B8A0",0.8)
    for i, p in enumerate(DATA.get('pedestrian',[])):
        mesh = road_mesh(p['coords'], 1.8, f"Ped_{i}")
        if mesh:
            obj = bpy.data.objects.new(f"Ped_{i}", mesh)
            obj.data.materials.append(m_ped)
            link(obj, c_road)
    print(f"  Pedestrian: {len(DATA.get('pedestrian',[]))}")

    # Street trees
    c_trees = col("Trees")
    m_trunk = mat("Trunk","#4A3520",0.9)
    m_canopy = mat("Canopy","#2A5A2A",0.8)
    for i, t in enumerate(DATA.get('trees',[])):
        x, y = t['x'], t['y']
        h = random.uniform(5,9)
        bpy.ops.mesh.primitive_cylinder_add(radius=0.1, depth=h, location=(x,y,h/2), vertices=8)
        tr = bpy.context.active_object
        tr.data.materials.append(m_trunk)
        link(tr, c_trees)
        bpy.ops.mesh.primitive_uv_sphere_add(radius=1.8, location=(x,y,h+0.5), segments=8, ring_count=6)
        ca = bpy.context.active_object
        ca.scale = (1,1,0.6)
        ca.data.materials.append(m_canopy)
        link(ca, c_trees)
    print(f"  Trees: {len(DATA.get('trees',[]))}")

    # Field features
    c_field = col("StreetFurniture")
    fc = add_field_features(c_field)
    print(f"  Street furniture: {fc}")

    # Lighting
    bpy.ops.object.light_add(type='SUN', location=(0,0,100))
    sun = bpy.context.active_object
    sun.data.energy = 3.0
    sun.rotation_euler = (math.radians(50), math.radians(10), math.radians(25))

    # Camera
    bpy.ops.object.camera_add(location=(40, -220, 100))
    cam = bpy.context.active_object
    cam.rotation_euler = (math.radians(55), 0, math.radians(15))
    bpy.context.scene.camera = cam

    out = str(SCRIPT_DIR / "outputs" / "demos" / "bellevue_gis_demo.blend")
    bpy.ops.wm.save_as_mainfile(filepath=out)
    print(f"\nSaved: {out}")


main()
