"""Bellevue Ave demo from full PostGIS export.

All layers: park polygon, footprints, 3D massing, roads, street trees,
pedestrian network. Real coordinates from SRID 2952.

Run: blender --python scripts/demo_bellevue_full.py
"""

import bpy
import bmesh
import json
import math
import os
from pathlib import Path

SCRIPT_DIR = Path(os.path.dirname(os.path.abspath(__file__))).parent
DATA = json.load(open(SCRIPT_DIR / "outputs" / "demos" / "bellevue_gis_data.json"))


def clear():
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete()
    for c in list(bpy.data.collections):
        bpy.data.collections.remove(c)


def mat(name, hex_c, rough=0.8):
    if name in bpy.data.materials:
        return bpy.data.materials[name]
    m = bpy.data.materials.new(name=name)
    m.use_nodes = True
    b = m.node_tree.nodes.get("Principled BSDF")
    if b:
        h = hex_c.lstrip("#")
        r, g, bl = (int(h[i:i+2], 16)/255 for i in (0,2,4))
        b.inputs["Base Color"].default_value = (r, g, bl, 1)
        b.inputs["Roughness"].default_value = rough
    return m


def col(name):
    c = bpy.data.collections.new(name)
    bpy.context.scene.collection.children.link(c)
    return c


def link(obj, collection):
    for c in obj.users_collection:
        c.objects.unlink(obj)
    collection.objects.link(obj)


def poly_to_mesh(coords, z=0, name="poly"):
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


def extrude_poly(coords, h, name="mass"):
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


def curve_from_coords(coords, name, bevel):
    curve = bpy.data.curves.new(name, type='CURVE')
    curve.dimensions = '3D'
    sp = curve.splines.new('POLY')
    sp.points.add(len(coords) - 1)
    for i, (x, y) in enumerate(coords):
        sp.points[i].co = (x, y, 0.01, 1)
    curve.bevel_depth = bevel
    curve.bevel_resolution = 0
    return curve


def road_surface(coords, width, name):
    """Create a flat road surface by offsetting a centerline."""
    if len(coords) < 2:
        return None
    bm = bmesh.new()
    verts_left = []
    verts_right = []
    hw = width / 2
    for i, (x, y) in enumerate(coords):
        # Direction vector
        if i < len(coords) - 1:
            dx = coords[i+1][0] - x
            dy = coords[i+1][1] - y
        else:
            dx = x - coords[i-1][0]
            dy = y - coords[i-1][1]
        length = max((dx*dx + dy*dy)**0.5, 0.01)
        nx, ny = -dy/length * hw, dx/length * hw
        verts_left.append(bm.verts.new((x + nx, y + ny, 0.02)))
        verts_right.append(bm.verts.new((x - nx, y - ny, 0.02)))

    # Create faces between left and right edges
    for i in range(len(coords) - 1):
        try:
            bm.faces.new([verts_left[i], verts_left[i+1], verts_right[i+1], verts_right[i]])
        except:
            pass

    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()
    return mesh


def add_windows_to_massing(obj, h, coords):
    """Add window planes to the longest face of a massing shape."""
    import random
    m_glass = mat("Window", "#3A5A7A", 0.3)
    m_frame = mat("Frame", "#4A3A2A", 0.7)

    # Find the longest edge (likely the street-facing facade)
    edges = []
    for i in range(len(coords)):
        x1, y1 = coords[i]
        x2, y2 = coords[(i+1) % len(coords)]
        length = ((x2-x1)**2 + (y2-y1)**2)**0.5
        edges.append((length, x1, y1, x2, y2))

    edges.sort(reverse=True)
    windows = []

    # Add windows to the 2 longest edges (front + back)
    for edge_idx in range(min(2, len(edges))):
        length, x1, y1, x2, y2 = edges[edge_idx]
        if length < 3:
            continue

        dx, dy = x2 - x1, y2 - y1
        el = max(length, 0.01)
        # Normal (outward)
        nx, ny = -dy/el, dx/el

        # Floor count from height
        floors = max(1, int(h / 3.0))
        floor_h = h / floors

        # Windows per floor
        n_win = max(1, int(length / 2.5))
        win_w, win_h = 0.9, 1.2

        for fi in range(floors):
            sill_z = fi * floor_h + floor_h * 0.35
            for wi in range(n_win):
                t = (wi + 1) / (n_win + 1)
                wx = x1 + dx * t + nx * 0.15
                wy = y1 + dy * t + ny * 0.15
                wz = sill_z + win_h / 2

                angle = math.atan2(dy, dx)
                bpy.ops.mesh.primitive_plane_add(size=1, location=(wx, wy, wz))
                win = bpy.context.active_object
                win.name = f"Win_{edge_idx}_{fi}_{wi}"
                win.scale = (win_w/2, win_h/2, 1)
                win.rotation_euler = (math.pi/2, 0, angle + math.pi/2)
                win.data.materials.append(m_glass)
                windows.append(win)

    return windows


def add_park_features(park_coords, collection):
    """Add playground, benches, paths, lamp posts to park polygon."""
    xs = [c[0] for c in park_coords]
    ys = [c[1] for c in park_coords]
    cx = (min(xs) + max(xs)) / 2
    cy = (min(ys) + max(ys)) / 2
    pw = max(xs) - min(xs)
    ph = max(ys) - min(ys)

    import random
    random.seed(42)

    # Paths (cross through park)
    m_path = mat("ParkPath", "#A0A0A0", 0.75)
    paths = [
        ((min(xs)+3, cy), (max(xs)-3, cy)),
        ((cx, min(ys)+3), (cx, max(ys)-3)),
    ]
    for pi, ((sx,sy),(ex,ey)) in enumerate(paths):
        mesh = road_surface([(sx,sy),(ex,ey)], 2.0, f"ParkPath_{pi}")
        if mesh:
            obj = bpy.data.objects.new(f"ParkPath_{pi}", mesh)
            obj.data.materials.append(m_path)
            link(obj, collection)

    # Playground (orange/blue posts + slide) — NE quadrant
    m_play_o = mat("PlayOrange", "#E06020", 0.6)
    m_play_b = mat("PlayBlue", "#2060C0", 0.6)
    pg_x = cx + pw * 0.2
    pg_y = cy + ph * 0.15

    for dx, dy in [(-2,-1.5),(2,-1.5),(-2,1.5),(2,1.5)]:
        bpy.ops.mesh.primitive_cylinder_add(radius=0.06, depth=3, location=(pg_x+dx, pg_y+dy, 1.5), vertices=8)
        p = bpy.context.active_object
        p.name = f"PG_post"
        p.data.materials.append(m_play_o)
        link(p, collection)
    # Slide
    bpy.ops.mesh.primitive_cube_add(size=1, location=(pg_x+3, pg_y, 1.0))
    s = bpy.context.active_object
    s.name = "PG_slide"
    s.scale = (1.5, 0.4, 0.03)
    s.rotation_euler[1] = -0.5
    s.data.materials.append(m_play_b)
    link(s, collection)
    # Platform
    bpy.ops.mesh.primitive_cube_add(size=1, location=(pg_x, pg_y, 2.8))
    pl = bpy.context.active_object
    pl.name = "PG_platform"
    pl.scale = (2, 1.5, 0.05)
    pl.data.materials.append(mat("PG_grey", "#888888", 0.6))
    link(pl, collection)

    # Benches
    m_bench = mat("Bench", "#8B6914", 0.8)
    bench_spots = [
        (cx - pw*0.3, cy, 0),
        (cx + pw*0.3, cy, math.pi),
        (cx, cy + ph*0.3, math.pi/2),
        (cx, cy - ph*0.3, -math.pi/2),
    ]
    for bx, by, rot in bench_spots:
        bpy.ops.mesh.primitive_cube_add(size=1, location=(bx, by, 0.45))
        b = bpy.context.active_object
        b.name = "Bench"
        b.scale = (0.8, 0.25, 0.025)
        b.rotation_euler[2] = rot
        b.data.materials.append(m_bench)
        link(b, collection)

    # Lamp posts
    m_lamp = mat("Lamp", "#505050", 0.4)
    for lx, ly in [(cx-pw*0.25, cy+ph*0.2), (cx+pw*0.25, cy-ph*0.2),
                    (cx, cy+ph*0.35), (cx, cy-ph*0.35)]:
        bpy.ops.mesh.primitive_cylinder_add(radius=0.05, depth=4.5, location=(lx, ly, 2.25), vertices=8)
        lp = bpy.context.active_object
        lp.name = "Lamp"
        lp.data.materials.append(m_lamp)
        link(lp, collection)
        # Light head
        bpy.ops.mesh.primitive_cube_add(size=1, location=(lx, ly, 4.5))
        lh = bpy.context.active_object
        lh.name = "LampHead"
        lh.scale = (0.3, 0.15, 0.05)
        lh.data.materials.append(mat("LampLight", "#E0E0D0", 0.3))
        link(lh, collection)

    # Boulders
    m_rock = mat("Boulder", "#787878", 0.85)
    for _ in range(6):
        bx = cx + random.uniform(-pw*0.35, pw*0.35)
        by = cy + random.uniform(-ph*0.35, ph*0.35)
        bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=2, radius=random.uniform(0.3,0.6), location=(bx, by, 0.2))
        r = bpy.context.active_object
        r.name = "Boulder"
        r.scale = (random.uniform(0.8,1.2), random.uniform(0.8,1.2), random.uniform(0.4,0.7))
        r.data.materials.append(m_rock)
        link(r, collection)

    # Yellow fire hydrants at corners
    m_hy = mat("Hydrant", "#E0C020", 0.5)
    for hx, hy in [(min(xs)+2, min(ys)+2), (max(xs)-2, min(ys)+2)]:
        bpy.ops.mesh.primitive_cylinder_add(radius=0.12, depth=0.6, location=(hx, hy, 0.3), vertices=8)
        h_obj = bpy.context.active_object
        h_obj.name = "Hydrant"
        h_obj.data.materials.append(m_hy)
        link(h_obj, collection)


def main():
    clear()
    print("=== Bellevue Full GIS Demo ===")

    # ── Ground ──
    c_env = col("Ground")
    all_x, all_y = [], []
    for layer in ['footprints', 'massing', 'parks']:
        for item in DATA.get(layer, []):
            for x, y in item.get('coords', []):
                all_x.append(x)
                all_y.append(y)
    if all_x:
        cx = (min(all_x) + max(all_x)) / 2
        cy = (min(all_y) + max(all_y)) / 2
        sx = (max(all_x) - min(all_x)) / 2 + 20
        sy = (max(all_y) - min(all_y)) / 2 + 20
        bpy.ops.mesh.primitive_plane_add(size=1, location=(cx, cy, -0.05))
        g = bpy.context.active_object
        g.name = "Ground"
        g.scale = (sx, sy, 1)
        g.data.materials.append(mat("Ground", "#3A4A2A", 0.95))
        link(g, c_env)

    # ── Park polygon ──
    c_park = col("Park")
    m_park = mat("Park_Grass", "#4A7A2A", 0.9)
    for i, p in enumerate(DATA.get('parks', [])):
        mesh = poly_to_mesh(p['coords'], z=0.03, name=f"Park_{i}")
        if mesh:
            obj = bpy.data.objects.new(f"Park_{i}", mesh)
            obj.data.materials.append(m_park)
            link(obj, c_park)
    # Add park details (playground, benches, paths, lamps, boulders, hydrants)
    if DATA.get('parks'):
        add_park_features(DATA['parks'][0]['coords'], c_park)
    print(f"  Parks: {len(DATA.get('parks', []))} (with details)")

    # ── Building footprints ──
    c_fp = col("Footprints")
    m_fp = mat("Footprint", "#8A7A6A", 0.85)
    for i, fp in enumerate(DATA.get('footprints', [])):
        mesh = poly_to_mesh(fp['coords'], z=0.05, name=f"FP_{i}")
        if mesh:
            obj = bpy.data.objects.new(f"FP_{i}", mesh)
            obj.data.materials.append(m_fp)
            link(obj, c_fp)
    print(f"  Footprints: {len(DATA.get('footprints', []))}")

    # ── 3D Massing with windows ──
    c_mass = col("Massing_3D")
    m_mass = mat("Massing", "#B8856A", 0.7)
    m_roof = mat("MassingRoof", "#5A5A5A", 0.6)
    win_objs = []
    for i, m in enumerate(DATA.get('massing', [])):
        if m['h'] <= 0:
            continue
        mesh = extrude_poly(m['coords'], m['h'], name=f"Mass_{i}")
        if mesh:
            obj = bpy.data.objects.new(f"Mass_{i}", mesh)
            obj.data.materials.append(m_mass)
            link(obj, c_mass)
            # Add windows
            wins = add_windows_to_massing(obj, m['h'], m['coords'])
            for w in wins:
                link(w, c_mass)
                win_objs.append(w)
    print(f"  Massing: {len(DATA.get('massing', []))} + {len(win_objs)} windows")

    # ── Roads (flat surfaces) ──
    c_road = col("Roads")
    m_road = mat("Road", "#2A2A2A", 0.9)
    road_count = 0
    for i, r in enumerate(DATA.get('roads', [])):
        mesh = road_surface(r['coords'], 7.0, f"Road_{i}")
        if mesh:
            obj = bpy.data.objects.new(f"Road_{i}", mesh)
            obj.data.materials.append(m_road)
            link(obj, c_road)
            road_count += 1
    print(f"  Roads: {road_count}")

    # ── Sidewalks (flat, narrower) ──
    m_sw = mat("Sidewalk", "#B0B0A8", 0.8)
    sw_count = 0
    for i, s in enumerate(DATA.get('sidewalks', [])):
        mesh = road_surface(s['coords'], 2.0, f"SW_{i}")
        if mesh:
            obj = bpy.data.objects.new(f"SW_{i}", mesh)
            obj.data.materials.append(m_sw)
            link(obj, c_road)
            sw_count += 1

    # ── Pedestrian paths (flat) ──
    c_ped = col("Pedestrian")
    m_ped = mat("Pedestrian", "#C0B8A0", 0.8)
    ped_count = 0
    for i, p in enumerate(DATA.get('pedestrian', [])):
        mesh = road_surface(p['coords'], 1.8, f"Ped_{i}")
        if mesh:
            obj = bpy.data.objects.new(f"Ped_{i}", mesh)
            obj.data.materials.append(m_ped)
            link(obj, c_ped)
            ped_count += 1
    print(f"  Sidewalks: {sw_count}, Pedestrian: {ped_count}")

    # ── Street trees ──
    c_trees = col("Street_Trees")
    m_trunk = mat("Trunk", "#4A3520", 0.9)
    m_canopy = mat("Canopy", "#2A5A2A", 0.8)
    import random
    random.seed(42)
    for i, t in enumerate(DATA.get('trees', [])):
        x, y = t['x'], t['y']
        h = random.uniform(5, 9)
        # Trunk
        bpy.ops.mesh.primitive_cylinder_add(radius=0.1, depth=h, location=(x, y, h/2), vertices=8)
        trunk = bpy.context.active_object
        trunk.name = f"Tree_{i}"
        trunk.data.materials.append(m_trunk)
        link(trunk, c_trees)
        # Canopy (bare tree = small sphere at top)
        bpy.ops.mesh.primitive_uv_sphere_add(radius=1.8, location=(x, y, h+0.5), segments=8, ring_count=6)
        canopy = bpy.context.active_object
        canopy.name = f"Canopy_{i}"
        canopy.scale = (1, 1, 0.6)
        canopy.data.materials.append(m_canopy)
        link(canopy, c_trees)
    print(f"  Trees: {len(DATA.get('trees', []))}")

    # ── Lighting + Camera ──
    bpy.ops.object.light_add(type='SUN', location=(0, 0, 100))
    sun = bpy.context.active_object
    sun.data.energy = 3.0
    sun.rotation_euler = (math.radians(50), math.radians(10), math.radians(25))

    if all_x:
        bpy.ops.object.camera_add(location=(cx + 80, cy - 120, 80))
        cam = bpy.context.active_object
        cam.rotation_euler = (math.radians(55), 0, math.radians(25))
        bpy.context.scene.camera = cam

    out = str(SCRIPT_DIR / "outputs" / "demos" / "bellevue_gis_demo.blend")
    bpy.ops.wm.save_as_mainfile(filepath=out)
    print(f"\nSaved: {out}")


main()
