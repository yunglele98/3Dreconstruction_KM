"""Bellevue demo: parametric buildings + GIS base layers.

Step 1: Load parametric buildings (already generated with generate_building.py)
Step 2: Add GIS base layers (roads, park, trees, footprints)

Run: blender <parametric_scene.blend> --python scripts/demo_bellevue_combined.py
"""

import bpy
import bmesh
import json
import math
import os
import random
from pathlib import Path

random.seed(42)

SCRIPT_DIR = Path(os.path.dirname(os.path.abspath(__file__))).parent
GIS = json.load(open(SCRIPT_DIR / "outputs" / "gis_scene.json"))

# Use gis_scene.json for ALL layers (same coordinate system as buildings)
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


def poly_mesh(coords, z, name):
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


def main():
    # Don't clear — keep parametric buildings already in scene
    print("=== Adding GIS layers to parametric scene ===")

    # Ground
    c_env = col("GIS_Ground")
    bpy.ops.mesh.primitive_plane_add(size=1, location=(-35, -85, -0.1))
    g = bpy.context.active_object
    g.name = "Ground"
    g.scale = (120, 130, 1)
    g.data.materials.append(mat("Ground", "#3A4A2A", 0.95))
    link(g, c_env)

    # Helper to check if coords are in Bellevue area
    def near(coords):
        if not coords: return False
        cx = sum(c[0] for c in coords) / len(coords)
        cy = sum(c[1] for c in coords) / len(coords)
        return X_MIN <= cx <= X_MAX and Y_MIN <= cy <= Y_MAX

    # Footprints from gis_scene (2D ground polygons)
    c_fp = col("GIS_Footprints")
    m_fp = mat("Footprint", "#8A7A6A", 0.85)
    fp_count = 0
    for fp in GIS.get("footprints", []):
        ring = fp.get("rings", [[]])[0]
        if len(ring) < 3 or not near(ring): continue
        mesh = poly_mesh(ring, 0.03, f"FP_{fp_count}")
        if mesh:
            obj = bpy.data.objects.new(f"FP_{fp_count}", mesh)
            obj.data.materials.append(m_fp)
            link(obj, c_fp)
            fp_count += 1
    print(f"  Footprints: {fp_count}")

    # Roads from gis_scene (flat surfaces)
    c_road = col("GIS_Roads")
    m_road = mat("Road", "#2A2A2A", 0.9)
    road_count = 0
    for r in GIS.get("roads", []):
        coords = r.get("coords", [])
        if len(coords) < 2: continue
        cx = sum(c[0] for c in coords) / len(coords)
        cy = sum(c[1] for c in coords) / len(coords)
        if not (X_MIN - 30 <= cx <= X_MAX + 30 and Y_MIN - 30 <= cy <= Y_MAX + 30): continue
        mesh = road_mesh(coords, 7.0, f"Road_{road_count}")
        if mesh:
            obj = bpy.data.objects.new(f"Road_{road_count}", mesh)
            obj.data.materials.append(m_road)
            link(obj, c_road)
            road_count += 1
    # Alleys
    m_alley = mat("Alley", "#4A4A4A", 0.85)
    for r in GIS.get("alleys", []):
        coords = r.get("coords", [])
        if len(coords) < 2: continue
        cx = sum(c[0] for c in coords) / len(coords)
        cy = sum(c[1] for c in coords) / len(coords)
        if not (X_MIN - 20 <= cx <= X_MAX + 20 and Y_MIN - 20 <= cy <= Y_MAX + 20): continue
        mesh = road_mesh(coords, 3.0, f"Alley_{road_count}")
        if mesh:
            obj = bpy.data.objects.new(f"Alley_{road_count}", mesh)
            obj.data.materials.append(m_alley)
            link(obj, c_road)
            road_count += 1
    print(f"  Roads + alleys: {road_count}")

    # Trees from field survey (gis_scene)
    c_trees = col("GIS_Trees")
    m_trunk = mat("Trunk", "#4A3520", 0.9)
    m_canopy = mat("Canopy", "#2A5A2A", 0.8)
    tree_count = 0
    for pt in GIS.get("field", {}).get("trees", []):
        x, y = pt['x'], pt['y']
        if not (X_MIN - 10 <= x <= X_MAX + 10 and Y_MIN - 10 <= y <= Y_MAX + 10): continue
        h = random.uniform(5, 9)
        bpy.ops.mesh.primitive_cylinder_add(radius=0.1, depth=h, location=(x,y,h/2), vertices=8)
        bpy.context.active_object.data.materials.append(m_trunk)
        link(bpy.context.active_object, c_trees)
        bpy.ops.mesh.primitive_uv_sphere_add(radius=1.8, location=(x,y,h+0.5), segments=8, ring_count=6)
        ca = bpy.context.active_object
        ca.scale = (1,1,0.6)
        ca.data.materials.append(m_canopy)
        link(ca, c_trees)
        tree_count += 1
    print(f"  Trees: {tree_count}")

    # Field features
    c_field = col("GIS_StreetFurniture")
    m_pole = mat("Pole", "#5A5A5A", 0.5)
    count = 0
    for layer, cfg in [("poles", (0.06, 6, "#5A5A5A")), ("signs", (0.04, 2.5, "#CC4444"))]:
        for pt in GIS.get("field", {}).get(layer, []):
            x, y = pt['x'], pt['y']
            if not (X_MIN <= x <= X_MAX and Y_MIN <= y <= Y_MAX):
                continue
            bpy.ops.mesh.primitive_cylinder_add(radius=cfg[0], depth=cfg[1], location=(x,y,cfg[1]/2), vertices=8)
            bpy.context.active_object.data.materials.append(mat(f"F_{layer}", cfg[2], 0.5))
            link(bpy.context.active_object, c_field)
            count += 1
    print(f"  Street furniture: {count}")

    # Sun
    bpy.ops.object.light_add(type='SUN', location=(0,0,100))
    sun = bpy.context.active_object
    sun.data.energy = 3.0
    sun.rotation_euler = (math.radians(50), math.radians(10), math.radians(25))

    # Camera
    bpy.ops.object.camera_add(location=(40, -220, 80))
    cam = bpy.context.active_object
    cam.rotation_euler = (math.radians(55), 0, math.radians(15))
    bpy.context.scene.camera = cam

    out = str(SCRIPT_DIR / "outputs" / "demos" / "bellevue_final_demo.blend")
    bpy.ops.wm.save_as_mainfile(filepath=out)
    print(f"\nSaved: {out}")


main()
