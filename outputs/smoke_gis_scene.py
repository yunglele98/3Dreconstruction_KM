#!/usr/bin/env python3
"""GIS site model for Kensington Market — auto-generated.

Run inside Blender:
    blender --background --python gis_scene.py
    blender --python gis_scene.py   (with GUI)
"""

import bpy
import bmesh
import json
import os
from pathlib import Path
from mathutils import Vector

ORIGIN_X = 312672.94
ORIGIN_Y = 4834994.86

# Load GIS data from JSON
SCRIPT_DIR = Path(os.path.dirname(os.path.abspath(__file__))) if "__file__" in dir() else Path("C:/Users/liam1/blender_buildings")
DATA_PATH = SCRIPT_DIR / "smoke_gis_scene.json"
with open(DATA_PATH, encoding="utf-8") as _f:
    GIS = json.load(_f)


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def clear_collection(name):
    if name in bpy.data.collections:
        col = bpy.data.collections[name]
        for obj in list(col.objects):
            bpy.data.objects.remove(obj, do_unlink=True)
    else:
        col = bpy.data.collections.new(name)
        bpy.context.scene.collection.children.link(col)
    return col


def get_material(name, hex_colour, roughness=0.9):
    if name in bpy.data.materials:
        return bpy.data.materials[name]
    mat = bpy.data.materials.new(name=name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf and hex_colour:
        h = hex_colour.lstrip("#")
        r, g, b = (int(h[i:i+2], 16) / 255.0 for i in (0, 2, 4))
        bsdf.inputs["Base Color"].default_value = (r, g, b, 1.0)
        bsdf.inputs["Roughness"].default_value = roughness
    return mat


# ---------------------------------------------------------------------------
# Building footprints (real polygons from city data)
# ---------------------------------------------------------------------------

def create_footprints():
    col = clear_collection("GIS_Footprints")
    mat = get_material("Footprint_Mat", "#8A7A6A")

    for fp in GIS.get("footprints", []):
        rings = fp["rings"]
        if not rings:
            continue
        ring = rings[0]  # exterior ring
        if len(ring) < 3:
            continue

        bm = bmesh.new()
        verts = [bm.verts.new((x, y, 0)) for x, y in ring]
        try:
            bm.faces.new(verts)
        except ValueError:
            bm.free()
            continue

        mesh = bpy.data.meshes.new(f"FP_{fp['gid']}")
        bm.to_mesh(mesh)
        bm.free()

        obj = bpy.data.objects.new(f"FP_{fp['gid']}", mesh)
        obj.data.materials.append(mat)
        col.objects.link(obj)

    print(f"  Footprints: {len(GIS.get('footprints', []))}")


# ---------------------------------------------------------------------------
# 3D massing (extruded polygons with heights from LiDAR)
# ---------------------------------------------------------------------------

def create_massing():
    col = clear_collection("GIS_Massing")
    mat = get_material("Massing_Mat", "#B0A898", roughness=0.7)

    for m in GIS.get("massing", []):
        rings = m["rings"]
        h = m.get("h", 0)
        if not rings or h <= 0:
            continue
        ring = rings[0]
        if len(ring) < 3:
            continue

        bm = bmesh.new()
        # Create bottom face
        bottom_verts = [bm.verts.new((x, y, 0)) for x, y in ring]
        try:
            bottom_face = bm.faces.new(bottom_verts)
        except ValueError:
            bm.free()
            continue

        # Extrude up to building height
        result = bmesh.ops.extrude_face_region(bm, geom=[bottom_face])
        extruded_verts = [v for v in result["geom"] if isinstance(v, bmesh.types.BMVert)]
        for v in extruded_verts:
            v.co.z = h

        mesh = bpy.data.meshes.new("Massing")
        bm.to_mesh(mesh)
        bm.free()

        obj = bpy.data.objects.new("Massing", mesh)
        obj.data.materials.append(mat)
        obj["height_m"] = h
        col.objects.link(obj)

    print(f"  Massing: {len(GIS.get('massing', []))}")


# ---------------------------------------------------------------------------
# Roads, sidewalks, alleys (curves)
# ---------------------------------------------------------------------------

def create_curves(key, collection_name, mat_hex, bevel_depth):
    col = clear_collection(collection_name)
    mat = get_material(f"{collection_name}_Mat", mat_hex)

    items = GIS.get(key, [])
    for i, item in enumerate(items):
        coords = item.get("coords", [])
        if len(coords) < 2:
            continue

        curve = bpy.data.curves.new(f"{key}_{i}", type='CURVE')
        curve.dimensions = '3D'
        spline = curve.splines.new('POLY')
        spline.points.add(len(coords) - 1)
        for j, (x, y) in enumerate(coords):
            spline.points[j].co = (x, y, 0.01, 1)

        curve.bevel_depth = bevel_depth
        curve.bevel_resolution = 0

        obj = bpy.data.objects.new(f"{key}_{i}", curve)
        obj.data.materials.append(mat)
        col.objects.link(obj)

    print(f"  {collection_name}: {len(items)}")


# ---------------------------------------------------------------------------
# Study area boundary
# ---------------------------------------------------------------------------

def create_study_area():
    col = clear_collection("GIS_StudyArea")
    mat = get_material("StudyArea_Mat", "#2A3A2A", roughness=1.0)

    rings = GIS.get("study_area", [])
    if not rings:
        return
    ring = rings[0]
    if len(ring) < 3:
        return

    bm = bmesh.new()
    verts = [bm.verts.new((x, y, -0.1)) for x, y in ring]
    try:
        bm.faces.new(verts)
    except ValueError:
        bm.free()
        return

    mesh = bpy.data.meshes.new("StudyArea")
    bm.to_mesh(mesh)
    bm.free()

    obj = bpy.data.objects.new("StudyArea", mesh)
    obj.data.materials.append(mat)
    col.objects.link(obj)
    print("  Study area boundary: 1")


# ---------------------------------------------------------------------------
# Field survey features
# ---------------------------------------------------------------------------

FIELD_CONFIG = {
    "trees":        {"hex": "#2A5A2A", "r": 1.5, "h": 6.0, "shape": "sphere"},
    "poles":        {"hex": "#5A5A5A", "r": 0.08, "h": 5.0, "shape": "cylinder"},
    "signs":        {"hex": "#CC4444", "r": 0.15, "h": 2.5, "shape": "cylinder"},
    "bike_racks":   {"hex": "#4488CC", "r": 0.4, "h": 0.8, "shape": "cube"},
    "terraces":     {"hex": "#AA8855", "r": 2.0, "h": 0.1, "shape": "cube"},
    "parking":      {"hex": "#333333", "r": 4.0, "h": 0.05, "shape": "cube"},
    "public_art":   {"hex": "#CC44CC", "r": 0.5, "h": 2.0, "shape": "cube"},
    "bus_shelters":  {"hex": "#44AAAA", "r": 1.5, "h": 2.5, "shape": "cube"},
    "parks":        {"hex": "#44AA44", "r": 5.0, "h": 0.05, "shape": "cube"},
}


def create_field_features():
    col = clear_collection("GIS_FieldSurvey")
    total = 0

    for layer, points in GIS.get("field", {}).items():
        cfg = FIELD_CONFIG.get(layer, {"hex": "#888888", "r": 0.5, "h": 1.0, "shape": "cube"})
        mat = get_material(f"Field_{layer}", cfg["hex"])

        for i, pt in enumerate(points):
            x, y = pt["x"], pt["y"]
            if cfg["shape"] == "sphere":
                bpy.ops.mesh.primitive_uv_sphere_add(radius=cfg["r"], location=(x, y, cfg["h"]), segments=8, ring_count=6)
            elif cfg["shape"] == "cylinder":
                bpy.ops.mesh.primitive_cylinder_add(radius=cfg["r"], depth=cfg["h"], location=(x, y, cfg["h"]/2), vertices=8)
            else:
                bpy.ops.mesh.primitive_cube_add(size=1, location=(x, y, cfg["h"]/2))
                bpy.context.active_object.scale = (cfg["r"], cfg["r"], cfg["h"]/2)

            obj = bpy.context.active_object
            obj.name = f"{layer}_{i+1}"
            obj.data.materials.append(mat)
            for c in obj.users_collection:
                c.objects.unlink(obj)
            col.objects.link(obj)
            total += 1

    print(f"  Field survey: {total} features")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("=== Kensington Market GIS Site Model ===")
    print(f"Origin: {ORIGIN_X}, {ORIGIN_Y} (SRID 2952)")
    print()

    create_study_area()
    create_footprints()
    # create_massing()  # skipped (use --massing-only to include)
    create_curves("roads", "GIS_Roads", "#4A4A4A", 3.0)
    create_curves("sidewalks", "GIS_Sidewalks", "#9A9A8A", 1.5)
    create_curves("alleys", "GIS_Alleys", "#6A6A6A", 1.5)
    create_field_features()

    # Save building position lookup for generate_building.py
    print(f"\n  Building positions: {len(GIS.get('building_positions', {}))}")
    print("\nDone — GIS site model loaded.")
    print("Collections: GIS_StudyArea, GIS_Footprints, GIS_Massing, GIS_Roads, GIS_Sidewalks, GIS_Alleys, GIS_FieldSurvey")

main()
