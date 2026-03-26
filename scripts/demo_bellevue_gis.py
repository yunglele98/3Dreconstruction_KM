"""Bellevue Ave 20-50 demo using real GIS data (3D massing, footprints, roads).

Run: blender --python scripts/demo_bellevue_gis.py
"""

import bpy
import bmesh
import json
import math
import os
from pathlib import Path

SCRIPT_DIR = Path(os.path.dirname(os.path.abspath(__file__))).parent
DATA_PATH = SCRIPT_DIR / "outputs" / "gis_scene.json"

with open(DATA_PATH, encoding="utf-8") as f:
    GIS = json.load(f)

# Bellevue 20-50 bounding box (local metres from centroid)
X_MIN, X_MAX = -130, -30
Y_MIN, Y_MAX = -160, 0


def in_bounds(ring_or_coords):
    """Check if centroid of a polygon/line is in the Bellevue area."""
    pts = ring_or_coords
    if not pts:
        return False
    cx = sum(p[0] for p in pts) / len(pts)
    cy = sum(p[1] for p in pts) / len(pts)
    return X_MIN <= cx <= X_MAX and Y_MIN <= cy <= Y_MAX


def clear_scene():
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete()
    for c in list(bpy.data.collections):
        bpy.data.collections.remove(c)


def get_mat(name, hex_colour, roughness=0.8):
    if name in bpy.data.materials:
        return bpy.data.materials[name]
    mat = bpy.data.materials.new(name=name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        h = hex_colour.lstrip("#")
        r, g, b = (int(h[i:i+2], 16) / 255.0 for i in (0, 2, 4))
        bsdf.inputs["Base Color"].default_value = (r, g, b, 1.0)
        bsdf.inputs["Roughness"].default_value = roughness
    return mat


def create_massing():
    """3D massing from city open data — extruded footprints with real heights."""
    col = bpy.data.collections.new("Massing_3D")
    bpy.context.scene.collection.children.link(col)
    mat = get_mat("Massing_Brick", "#B8856A", 0.75)
    mat_roof = get_mat("Massing_Roof", "#5A5A5A", 0.6)

    count = 0
    for m in GIS.get("massing", []):
        rings = m.get("rings", [[]])
        if not rings or not rings[0]:
            continue
        ring = rings[0]
        if len(ring) < 3 or not in_bounds(ring):
            continue

        h = m.get("h", 0)
        if h <= 0:
            continue

        bm = bmesh.new()
        bottom_verts = [bm.verts.new((x, y, 0)) for x, y in ring]
        try:
            bottom_face = bm.faces.new(bottom_verts)
        except ValueError:
            bm.free()
            continue

        # Extrude to height
        result = bmesh.ops.extrude_face_region(bm, geom=[bottom_face])
        extruded_verts = [v for v in result["geom"] if isinstance(v, bmesh.types.BMVert)]
        for v in extruded_verts:
            v.co.z = h

        bm.normal_update()
        mesh = bpy.data.meshes.new(f"Mass_{count}")
        bm.to_mesh(mesh)
        bm.free()

        obj = bpy.data.objects.new(f"Massing_{count}", mesh)
        obj.data.materials.append(mat)
        obj["height_m"] = h
        col.objects.link(obj)
        count += 1

    print(f"  Massing: {count} buildings")


def create_footprints():
    """2D footprints as ground-level polygons."""
    col = bpy.data.collections.new("Footprints")
    bpy.context.scene.collection.children.link(col)
    mat = get_mat("Footprint_Mat", "#8A7A6A", 0.9)

    count = 0
    for fp in GIS.get("footprints", []):
        rings = fp.get("rings", [[]])
        if not rings or not rings[0]:
            continue
        ring = rings[0]
        if len(ring) < 3 or not in_bounds(ring):
            continue

        bm = bmesh.new()
        verts = [bm.verts.new((x, y, 0.01)) for x, y in ring]
        try:
            bm.faces.new(verts)
        except ValueError:
            bm.free()
            continue

        mesh = bpy.data.meshes.new(f"FP_{count}")
        bm.to_mesh(mesh)
        bm.free()

        obj = bpy.data.objects.new(f"Footprint_{count}", mesh)
        obj.data.materials.append(mat)
        col.objects.link(obj)
        count += 1

    print(f"  Footprints: {count}")


def create_roads():
    """Road centerlines as beveled curves."""
    col = bpy.data.collections.new("Roads")
    bpy.context.scene.collection.children.link(col)
    mat = get_mat("Road_Mat", "#3A3A3A", 0.85)

    count = 0
    for r in GIS.get("roads", []):
        coords = r.get("coords", [])
        if len(coords) < 2:
            continue
        # Broader bounds for roads (they extend beyond buildings)
        cx = sum(p[0] for p in coords) / len(coords)
        cy = sum(p[1] for p in coords) / len(coords)
        if not (X_MIN - 30 <= cx <= X_MAX + 30 and Y_MIN - 30 <= cy <= Y_MAX + 30):
            continue

        curve = bpy.data.curves.new(f"Road_{count}", type='CURVE')
        curve.dimensions = '3D'
        spline = curve.splines.new('POLY')
        spline.points.add(len(coords) - 1)
        for j, (x, y) in enumerate(coords):
            spline.points[j].co = (x, y, 0.02, 1)

        curve.bevel_depth = 3.5  # ~7m road width
        curve.bevel_resolution = 0

        obj = bpy.data.objects.new(f"Road_{count}", curve)
        obj.data.materials.append(mat)
        col.objects.link(obj)
        count += 1

    # Also add sidewalks
    mat_sw = get_mat("Sidewalk_Mat", "#A0A098", 0.8)
    for r in GIS.get("sidewalks", []):
        coords = r.get("coords", [])
        if len(coords) < 2:
            continue
        cx = sum(p[0] for p in coords) / len(coords)
        cy = sum(p[1] for p in coords) / len(coords)
        if not (X_MIN - 20 <= cx <= X_MAX + 20 and Y_MIN - 20 <= cy <= Y_MAX + 20):
            continue

        curve = bpy.data.curves.new(f"Sidewalk_{count}", type='CURVE')
        curve.dimensions = '3D'
        spline = curve.splines.new('POLY')
        spline.points.add(len(coords) - 1)
        for j, (x, y) in enumerate(coords):
            spline.points[j].co = (x, y, 0.03, 1)

        curve.bevel_depth = 1.5
        curve.bevel_resolution = 0

        obj = bpy.data.objects.new(f"Sidewalk_{count}", curve)
        obj.data.materials.append(mat_sw)
        col.objects.link(obj)
        count += 1

    print(f"  Roads + sidewalks: {count}")


def create_park():
    """Bellevue Square Park — grass, trees, playground."""
    col = bpy.data.collections.new("Park")
    bpy.context.scene.collection.children.link(col)

    # Park bounds: between the two rows of houses
    # West row x ~ -85 to -105, East row x ~ -42 to -66
    # Park is roughly x=-95 to -50, y=-130 to -40
    park_cx, park_cy = -72, -85
    park_w, park_d = 28, 80

    # Ground
    bpy.ops.mesh.primitive_plane_add(size=1, location=(park_cx, park_cy, 0.005))
    ground = bpy.context.active_object
    ground.name = "Park_Ground"
    ground.scale = (park_w / 2, park_d / 2, 1)
    mat_grass = get_mat("Grass", "#4A6A2A", 0.95)
    ground.data.materials.append(mat_grass)
    for c in ground.users_collection:
        c.objects.unlink(ground)
    col.objects.link(ground)

    # Trees
    mat_bark = get_mat("Bark", "#4A3528", 0.9)
    import random
    random.seed(42)
    tree_spots = []
    for _ in range(16):
        tx = park_cx + random.uniform(-park_w/2 + 2, park_w/2 - 2)
        ty = park_cy + random.uniform(-park_d/2 + 3, park_d/2 - 3)
        tree_spots.append((tx, ty))

    for tx, ty in tree_spots:
        h = random.uniform(5, 9)
        bpy.ops.mesh.primitive_cylinder_add(radius=0.1, depth=h, location=(tx, ty, h/2))
        trunk = bpy.context.active_object
        trunk.name = f"Tree_{tx:.0f}_{ty:.0f}"
        trunk.data.materials.append(mat_bark)
        for c in trunk.users_collection:
            c.objects.unlink(trunk)
        col.objects.link(trunk)

        # 3-4 branches
        for bi in range(random.randint(3, 5)):
            angle = random.uniform(0, 6.28)
            blen = random.uniform(1.5, 3.5)
            tilt = random.uniform(0.3, 0.7)
            bx = tx + math.cos(angle) * blen * 0.4
            by = ty + math.sin(angle) * blen * 0.4
            bz = h + blen * 0.2
            bpy.ops.mesh.primitive_cylinder_add(radius=0.03, depth=blen, location=(bx, by, bz))
            br = bpy.context.active_object
            br.name = f"Branch_{tx:.0f}_{bi}"
            br.rotation_euler = (tilt * math.cos(angle+1.5), tilt * math.sin(angle+1.5), angle)
            br.data.materials.append(mat_bark)
            for c in br.users_collection:
                c.objects.unlink(br)
            col.objects.link(br)

    # Playground (NE area)
    mat_play = get_mat("Playground", "#D06020", 0.6)
    pg_x, pg_y = park_cx + 6, park_cy + 25
    for dx, dy in [(-2,-1.5),(2,-1.5),(-2,1.5),(2,1.5)]:
        bpy.ops.mesh.primitive_cylinder_add(radius=0.05, depth=3, location=(pg_x+dx, pg_y+dy, 1.5))
        p = bpy.context.active_object
        p.data.materials.append(mat_play)
        for c in p.users_collection:
            c.objects.unlink(p)
        col.objects.link(p)

    # Pathways
    mat_path = get_mat("Path_Concrete", "#A0A0A0", 0.7)
    paths = [
        ((park_cx, park_cy - park_d/2), (park_cx, park_cy + park_d/2)),
        ((park_cx - park_w/2, park_cy), (park_cx + park_w/2, park_cy)),
    ]
    for (sx, sy), (ex, ey) in paths:
        dx, dy = ex - sx, ey - sy
        length = math.sqrt(dx*dx + dy*dy)
        angle = math.atan2(dy, dx)
        bpy.ops.mesh.primitive_cube_add(size=1, location=((sx+ex)/2, (sy+ey)/2, 0.015))
        p = bpy.context.active_object
        p.name = f"Path_{sx:.0f}"
        p.scale = (length/2, 0.9, 0.015)
        p.rotation_euler[2] = angle
        p.data.materials.append(mat_path)
        for c in p.users_collection:
            c.objects.unlink(p)
        col.objects.link(p)

    print(f"  Park: ground + {len(tree_spots)} trees + playground + paths")


def setup_camera_and_light():
    """Add camera and sun for a decent viewport."""
    # Sun
    bpy.ops.object.light_add(type='SUN', location=(50, -50, 80))
    sun = bpy.context.active_object
    sun.name = "Sun"
    sun.data.energy = 3.0
    sun.rotation_euler = (math.radians(45), math.radians(15), math.radians(30))

    # Camera looking at the block from SE
    bpy.ops.object.camera_add(location=(-20, -180, 80))
    cam = bpy.context.active_object
    cam.name = "Demo_Camera"
    cam.rotation_euler = (math.radians(55), 0, math.radians(-10))
    bpy.context.scene.camera = cam


def main():
    clear_scene()
    print("=== Bellevue Ave Demo (GIS Data) ===")
    create_massing()
    create_footprints()
    create_roads()
    create_park()
    setup_camera_and_light()

    out = str(SCRIPT_DIR / "outputs" / "demos" / "bellevue_gis_demo.blend")
    bpy.ops.wm.save_as_mainfile(filepath=out)
    print(f"\nSaved: {out}")


main()
