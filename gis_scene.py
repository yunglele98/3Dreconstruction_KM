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
import math

SCRIPT_DIR = Path(os.path.dirname(os.path.abspath(__file__))) if "__file__" in dir() else Path("C:/Users/liam1/blender_buildings")
# Use enriched scene (with urban elements) if available
DATA_PATH = SCRIPT_DIR / "outputs" / "gis_scene_enriched.json"
if not DATA_PATH.exists():
    DATA_PATH = SCRIPT_DIR / "outputs" / "gis_scene.json"
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
# Urban elements — detailed geometry for each category
# ---------------------------------------------------------------------------

# Species → canopy shape profiles (shape, height_mult, canopy_r_mult, flatten_z, hex)
TREE_PROFILES = {
    # Spreading deciduous — wide flat canopy
    "gleditsia_triacanthos":   ("spread",    0.9,  1.4, 0.55, "#3A6A2A"),  # honey locust
    "platanus_x_acerifolia":   ("spread",    1.0,  1.5, 0.5,  "#2A5A1A"),  # London plane
    "ulmus":                   ("vase",      1.1,  1.2, 0.65, "#2A5A2A"),  # elm
    "tilia":                   ("oval",      1.0,  1.0, 0.75, "#2A6A2A"),  # linden
    "tilia_cordata":           ("oval",      0.9,  0.9, 0.75, "#2A6A2A"),  # little-leaf linden
    "aesculus_hippocastanum":  ("round",     1.0,  1.1, 0.85, "#1A5A1A"),  # horse chestnut
    # Columnar / narrow
    "ginkgo_biloba":           ("columnar",  1.1,  0.6, 1.2,  "#5A7A1A"),  # ginkgo (fan-shaped)
    "allianthus_altissima":    ("columnar",  1.0,  0.7, 1.0,  "#3A5A2A"),  # tree of heaven
    # Maples — round/oval
    "acer_platanoides":        ("round",     1.0,  1.2, 0.8,  "#2A5A1A"),  # Norway maple
    "acer_saccharinum":        ("spread",    1.1,  1.3, 0.6,  "#3A6A2A"),  # silver maple
    "acer_negundo":            ("spread",    0.8,  1.1, 0.6,  "#3A5A2A"),  # Manitoba maple
    # Oaks — broad
    "quercus_rubra":           ("round",     1.1,  1.3, 0.7,  "#2A4A1A"),  # red oak
    # Small ornamental
    "malus_sargentii":         ("round",     0.5,  0.7, 0.8,  "#4A6A3A"),  # Sargent crabapple
    # Conifer
    "white_cedar":             ("conical",   0.8,  0.5, 1.5,  "#1A4A2A"),  # eastern white cedar
    "abies_balsamaea":         ("conical",   0.9,  0.4, 1.6,  "#1A3A1A"),  # balsam fir
    "picea":                   ("conical",   1.0,  0.45, 1.5, "#1A4A1A"),  # spruce
}

def _make_tree(name, x, y, height=6.0, canopy_r=1.5, species="unknown",
               trunk_hex="#5A4030", canopy_hex=None):
    """Create a species-specific tree with shaped trunk + canopy."""
    profile = TREE_PROFILES.get(species, ("round", 1.0, 1.0, 0.7, "#2A5A2A"))
    shape, h_mult, r_mult, flatten, default_hex = profile
    if canopy_hex is None:
        canopy_hex = default_hex

    height = height * h_mult
    canopy_r = canopy_r * r_mult
    trunk_h = height * 0.4
    trunk_r = max(0.06, canopy_r * 0.06)

    trunk_mat = get_material(f"Tree_Trunk_Mat_{trunk_hex.lstrip('#')}", trunk_hex, roughness=0.85)
    canopy_mat = get_material(f"Tree_Canopy_Mat_{canopy_hex.lstrip('#')}", canopy_hex, roughness=0.9)
    objs = []

    # Trunk — taper for realism
    bpy.ops.mesh.primitive_cone_add(radius1=trunk_r * 1.3, radius2=trunk_r * 0.7,
                                     depth=trunk_h, vertices=8,
                                     location=(x, y, trunk_h / 2))
    trunk = bpy.context.active_object
    trunk.name = f"{name}_trunk"
    trunk.data.materials.append(trunk_mat)
    objs.append(trunk)

    canopy_z = trunk_h + canopy_r * 0.6

    if shape == "conical":
        # Cone for conifers (cedar, spruce, fir)
        cone_h = canopy_r * 2.5
        bpy.ops.mesh.primitive_cone_add(radius1=canopy_r, radius2=0.05,
                                         depth=cone_h, vertices=10,
                                         location=(x, y, trunk_h + cone_h / 2 - 0.2))
        canopy = bpy.context.active_object
        canopy.name = f"{name}_canopy"
        canopy.data.materials.append(canopy_mat)
        objs.append(canopy)

    elif shape == "columnar":
        # Tall narrow ellipsoid
        bpy.ops.mesh.primitive_ico_sphere_add(radius=canopy_r, subdivisions=2,
                                               location=(x, y, canopy_z))
        canopy = bpy.context.active_object
        canopy.name = f"{name}_canopy"
        canopy.scale = (0.6, 0.6, flatten)
        canopy.data.materials.append(canopy_mat)
        objs.append(canopy)

    elif shape == "vase":
        # Vase shape — wider at top (elm)
        bpy.ops.mesh.primitive_cone_add(radius1=canopy_r * 0.7, radius2=canopy_r * 1.1,
                                         depth=canopy_r * 1.8, vertices=10,
                                         location=(x, y, canopy_z))
        canopy = bpy.context.active_object
        canopy.name = f"{name}_canopy"
        canopy.data.materials.append(canopy_mat)
        objs.append(canopy)
        # Top dome
        bpy.ops.mesh.primitive_uv_sphere_add(radius=canopy_r * 0.9, segments=8, ring_count=6,
                                              location=(x, y, canopy_z + canopy_r * 0.7))
        top = bpy.context.active_object
        top.name = f"{name}_canopy_top"
        top.scale.z = 0.5
        top.data.materials.append(canopy_mat)
        objs.append(top)

    elif shape == "spread":
        # Wide flat canopy (honey locust, silver maple)
        bpy.ops.mesh.primitive_ico_sphere_add(radius=canopy_r, subdivisions=2,
                                               location=(x, y, canopy_z))
        canopy = bpy.context.active_object
        canopy.name = f"{name}_canopy"
        canopy.scale.z = flatten
        canopy.data.materials.append(canopy_mat)
        objs.append(canopy)

    else:  # "round" / "oval" / default
        bpy.ops.mesh.primitive_ico_sphere_add(radius=canopy_r, subdivisions=2,
                                               location=(x, y, canopy_z))
        canopy = bpy.context.active_object
        canopy.name = f"{name}_canopy"
        canopy.scale.z = flatten
        canopy.data.materials.append(canopy_mat)
        objs.append(canopy)

    return objs


def _make_pole(name, x, y, height=5.0, radius=0.06, pole_type="generic_pole"):
    """Create a type-specific utility/street pole."""
    mat = get_material("Pole_Mat", "#5A5A5A", roughness=0.4)
    wood_mat = get_material("WoodPole_Mat", "#6A5040", roughness=0.8)
    light_mat = get_material("Light_Mat", "#E8E0C0", roughness=0.3)
    objs = []

    if "utility" in pole_type:
        # Wooden utility pole — thicker, taller, with cross-arms and insulators
        bpy.ops.mesh.primitive_cone_add(radius1=radius * 1.8, radius2=radius * 1.2,
                                         depth=height, vertices=8,
                                         location=(x, y, height / 2))
        pole = bpy.context.active_object
        pole.name = f"{name}_shaft"
        pole.data.materials.append(wood_mat)
        objs.append(pole)

        # Cross arms (2 levels)
        for arm_z in [height - 0.5, height - 1.2]:
            bpy.ops.mesh.primitive_cylinder_add(radius=0.03, depth=1.2, vertices=6,
                                                 location=(x, y, arm_z))
            arm = bpy.context.active_object
            arm.name = f"{name}_arm"
            arm.rotation_euler.y = math.pi / 2
            arm.data.materials.append(wood_mat)
            objs.append(arm)

            # Insulators (3 per arm)
            for ix in [-0.4, 0, 0.4]:
                bpy.ops.mesh.primitive_cylinder_add(radius=0.025, depth=0.08, vertices=6,
                                                     location=(x + ix, y, arm_z + 0.06))
                ins = bpy.context.active_object
                ins.name = f"{name}_insulator"
                ins_mat = get_material("Insulator_Mat", "#4A7A8A", roughness=0.3)
                ins.data.materials.append(ins_mat)
                objs.append(ins)

    elif "streetlight" in pole_type:
        # Decorative streetlight — tapered metal pole + curved arm + lamp
        bpy.ops.mesh.primitive_cone_add(radius1=radius * 1.4, radius2=radius * 0.6,
                                         depth=height, vertices=10,
                                         location=(x, y, height / 2))
        pole = bpy.context.active_object
        pole.name = f"{name}_shaft"
        pole.data.materials.append(mat)
        objs.append(pole)

        # Base plate
        bpy.ops.mesh.primitive_cylinder_add(radius=0.15, depth=0.08, vertices=10,
                                             location=(x, y, 0.04))
        base = bpy.context.active_object
        base.name = f"{name}_base"
        base.data.materials.append(mat)
        objs.append(base)

        # Curved arm extending forward
        arm_len = 1.0
        bpy.ops.mesh.primitive_cylinder_add(radius=0.025, depth=arm_len, vertices=6,
                                             location=(x + arm_len / 2, y, height - 0.1))
        arm = bpy.context.active_object
        arm.name = f"{name}_arm"
        arm.rotation_euler.y = math.pi / 2
        arm.rotation_euler.x = -0.15  # slight droop
        arm.data.materials.append(mat)
        objs.append(arm)

        # Lamp housing (acorn shape)
        bpy.ops.mesh.primitive_uv_sphere_add(radius=0.12, segments=8, ring_count=6,
                                              location=(x + arm_len - 0.1, y, height - 0.25))
        lamp = bpy.context.active_object
        lamp.name = f"{name}_lamp"
        lamp.scale.z = 1.3
        lamp.data.materials.append(light_mat)
        objs.append(lamp)

    elif "sign" in pole_type:
        # Thin metal pole for sign mounting
        bpy.ops.mesh.primitive_cylinder_add(radius=radius * 0.6, depth=height * 0.8, vertices=6,
                                             location=(x, y, height * 0.4))
        pole = bpy.context.active_object
        pole.name = f"{name}_shaft"
        pole.data.materials.append(mat)
        objs.append(pole)

    else:
        # Generic pole
        bpy.ops.mesh.primitive_cylinder_add(radius=radius, depth=height, vertices=8,
                                             location=(x, y, height / 2))
        pole = bpy.context.active_object
        pole.name = f"{name}_shaft"
        pole.data.materials.append(mat)
        objs.append(pole)

        # Simple cross arm + light
        bpy.ops.mesh.primitive_cylinder_add(radius=radius * 0.5, depth=0.8, vertices=6,
                                             location=(x, y, height - 0.3))
        arm = bpy.context.active_object
        arm.name = f"{name}_arm"
        arm.rotation_euler.y = math.pi / 2
        arm.data.materials.append(mat)
        objs.append(arm)

        bpy.ops.mesh.primitive_cone_add(radius1=0.12, radius2=0.0, depth=0.15, vertices=8,
                                         location=(x + 0.3, y, height - 0.15))
        light = bpy.context.active_object
        light.name = f"{name}_light"
        light.rotation_euler.x = math.pi
        light.data.materials.append(light_mat)
        objs.append(light)

    return objs


def _make_sign(name, x, y, height=2.5, sign_w=0.6, sign_h=0.4):
    """Create a street sign with post and plate."""
    post_mat = get_material("SignPost_Mat", "#5A5A5A", roughness=0.4)
    sign_mat = get_material("SignPlate_Mat", "#CC4444", roughness=0.3)
    objs = []

    # Post
    bpy.ops.mesh.primitive_cylinder_add(radius=0.03, depth=height, vertices=6,
                                         location=(x, y, height / 2))
    post = bpy.context.active_object
    post.name = f"{name}_post"
    post.data.materials.append(post_mat)
    objs.append(post)

    # Sign plate
    bpy.ops.mesh.primitive_cube_add(size=1, location=(x, y, height - sign_h / 2))
    plate = bpy.context.active_object
    plate.name = f"{name}_plate"
    plate.scale = (sign_w / 2, 0.01, sign_h / 2)
    plate.data.materials.append(sign_mat)
    objs.append(plate)

    # Back plate (slightly darker)
    bpy.ops.mesh.primitive_cube_add(size=1, location=(x, y - 0.015, height - sign_h / 2))
    back = bpy.context.active_object
    back.name = f"{name}_back"
    back.scale = (sign_w / 2 + 0.01, 0.005, sign_h / 2 + 0.01)
    back_mat = get_material("SignBack_Mat", "#4A4A4A", roughness=0.5)
    back.data.materials.append(back_mat)
    objs.append(back)

    return objs


def _make_bikerack(name, x, y):
    """Create an inverted-U bike rack."""
    mat = get_material("BikeRack_Mat", "#4488CC", roughness=0.3)
    objs = []

    # Inverted U shape using torus (half ring)
    bpy.ops.mesh.primitive_torus_add(
        major_radius=0.35, minor_radius=0.025,
        major_segments=16, minor_segments=6,
        location=(x, y, 0.7))
    rack = bpy.context.active_object
    rack.name = f"{name}_ring"
    rack.scale.z = 1.3
    rack.data.materials.append(mat)
    objs.append(rack)

    # Two legs
    for lx in [x - 0.3, x + 0.3]:
        bpy.ops.mesh.primitive_cylinder_add(radius=0.025, depth=0.35, vertices=6,
                                             location=(lx, y, 0.175))
        leg = bpy.context.active_object
        leg.name = f"{name}_leg"
        leg.data.materials.append(mat)
        objs.append(leg)

    return objs


def _make_street_furniture(name, x, y, rotation=0, furniture_type="bench"):
    """Create street furniture by type — bench, terrace, bollard, public art."""
    objs = []

    if "terrace" in furniture_type:
        # Cafe terrace module — platform + railing + table/chairs
        plat_mat = get_material("Terrace_Platform_Mat", "#8A7A6A", roughness=0.7)
        rail_mat = get_material("Terrace_Rail_Mat", "#3A3A3A", roughness=0.4)
        tw, td = 3.0, 2.0

        # Platform deck
        bpy.ops.mesh.primitive_cube_add(size=1, location=(x, y, 0.08))
        plat = bpy.context.active_object
        plat.name = f"{name}_platform"
        plat.scale = (tw / 2, td / 2, 0.08)
        plat.rotation_euler.z = math.radians(rotation)
        plat.data.materials.append(plat_mat)
        objs.append(plat)

        # Railing on 3 sides
        for rx, ry, rw, rd2 in [
            (x, y + td / 2, tw, 0.03),        # front
            (x - tw / 2, y, 0.03, td),        # left
            (x + tw / 2, y, 0.03, td),        # right
        ]:
            bpy.ops.mesh.primitive_cube_add(size=1, location=(rx, ry, 0.6))
            rail = bpy.context.active_object
            rail.name = f"{name}_rail"
            rail.scale = (rw / 2, rd2 / 2, 0.02)
            rail.rotation_euler.z = math.radians(rotation)
            rail.data.materials.append(rail_mat)
            objs.append(rail)

        # Table + 2 chairs (simplified)
        table_mat = get_material("Table_Mat", "#8A8A8A", roughness=0.5)
        bpy.ops.mesh.primitive_cylinder_add(radius=0.35, depth=0.03, vertices=8,
                                             location=(x, y, 0.72))
        table = bpy.context.active_object
        table.name = f"{name}_table"
        table.data.materials.append(table_mat)
        objs.append(table)
        bpy.ops.mesh.primitive_cylinder_add(radius=0.03, depth=0.55, vertices=6,
                                             location=(x, y, 0.44))
        tleg = bpy.context.active_object
        tleg.name = f"{name}_table_leg"
        tleg.data.materials.append(table_mat)
        objs.append(tleg)

        # Chairs (2 simple cubes)
        for cx in [x - 0.5, x + 0.5]:
            bpy.ops.mesh.primitive_cube_add(size=1, location=(cx, y, 0.4))
            chair = bpy.context.active_object
            chair.name = f"{name}_chair"
            chair.scale = (0.2, 0.2, 0.02)
            chair.data.materials.append(table_mat)
            objs.append(chair)

    elif "sculpture" in furniture_type or "art" in furniture_type or "mural" in furniture_type:
        # Public art — abstract form on pedestal
        pedestal_mat = get_material("Pedestal_Mat", "#7A7A7A", roughness=0.6)
        art_mat = get_material("PublicArt_Mat", "#A03050", roughness=0.3)

        # Pedestal
        bpy.ops.mesh.primitive_cube_add(size=1, location=(x, y, 0.4))
        ped = bpy.context.active_object
        ped.name = f"{name}_pedestal"
        ped.scale = (0.4, 0.4, 0.4)
        ped.data.materials.append(pedestal_mat)
        objs.append(ped)

        # Art piece — abstract sphere/torus
        if "sculpture" in furniture_type:
            bpy.ops.mesh.primitive_torus_add(major_radius=0.4, minor_radius=0.12,
                                              major_segments=16, minor_segments=8,
                                              location=(x, y, 1.2))
            art = bpy.context.active_object
            art.name = f"{name}_sculpture"
            art.rotation_euler.x = math.pi / 4
            art.data.materials.append(art_mat)
            objs.append(art)
        else:
            # Mural panel — flat vertical plane
            bpy.ops.mesh.primitive_cube_add(size=1, location=(x, y, 1.5))
            panel = bpy.context.active_object
            panel.name = f"{name}_mural"
            panel.scale = (1.5, 0.02, 1.0)
            panel.data.materials.append(art_mat)
            objs.append(panel)

    elif "bus_shelter" in furniture_type:
        return _make_transit_shelter(name, x, y)

    else:
        # Default bench
        wood_mat = get_material("Bench_Wood_Mat", "#6A5040", roughness=0.7)
        metal_mat = get_material("Bench_Metal_Mat", "#3A3A3A", roughness=0.4)

        # Seat slats (3 wooden boards)
        for si, sz in enumerate([0.43, 0.45, 0.47]):
            bpy.ops.mesh.primitive_cube_add(size=1, location=(x, y, sz))
            slat = bpy.context.active_object
            slat.name = f"{name}_slat_{si}"
            slat.scale = (0.8, 0.06, 0.015)
            slat.rotation_euler.z = math.radians(rotation)
            slat.data.materials.append(wood_mat)
            objs.append(slat)

        # Back rest slats (2 boards)
        for si, bz in enumerate([0.6, 0.75]):
            bpy.ops.mesh.primitive_cube_add(size=1, location=(x, y - 0.18, bz))
            bslat = bpy.context.active_object
            bslat.name = f"{name}_back_{si}"
            bslat.scale = (0.8, 0.015, 0.06)
            bslat.rotation_euler.z = math.radians(rotation)
            bslat.data.materials.append(wood_mat)
            objs.append(bslat)

        # Cast iron legs (2 decorative end frames)
        for lx in [x - 0.35, x + 0.35]:
            bpy.ops.mesh.primitive_cube_add(size=1, location=(lx, y, 0.25))
            leg = bpy.context.active_object
            leg.name = f"{name}_leg"
            leg.scale = (0.02, 0.22, 0.25)
            leg.rotation_euler.z = math.radians(rotation)
            leg.data.materials.append(metal_mat)
            objs.append(leg)

        # Armrests
        for ax in [x - 0.38, x + 0.38]:
            bpy.ops.mesh.primitive_cylinder_add(radius=0.015, depth=0.25, vertices=6,
                                                 location=(ax, y, 0.55))
            arm = bpy.context.active_object
            arm.name = f"{name}_armrest"
            arm.rotation_euler.x = math.pi / 2
            arm.data.materials.append(metal_mat)
            objs.append(arm)

    return objs


def _make_waste_bin(name, x, y):
    """Create a city waste bin (green cylinder with lid)."""
    bin_mat = get_material("Waste_Mat", "#3A5A3A", roughness=0.6)
    lid_mat = get_material("WasteLid_Mat", "#2A4A2A", roughness=0.5)
    objs = []

    bpy.ops.mesh.primitive_cylinder_add(radius=0.25, depth=0.8, vertices=12,
                                         location=(x, y, 0.4))
    body = bpy.context.active_object
    body.name = f"{name}_body"
    body.data.materials.append(bin_mat)
    objs.append(body)

    bpy.ops.mesh.primitive_cylinder_add(radius=0.27, depth=0.05, vertices=12,
                                         location=(x, y, 0.825))
    lid = bpy.context.active_object
    lid.name = f"{name}_lid"
    lid.data.materials.append(lid_mat)
    objs.append(lid)

    return objs


def _make_transit_shelter(name, x, y):
    """Create a basic transit shelter (3 glass walls + roof)."""
    glass_mat = get_material("Shelter_Glass_Mat", "#88AACC", roughness=0.1)
    frame_mat = get_material("Shelter_Frame_Mat", "#3A3A3A", roughness=0.4)
    objs = []

    sw, sd, sh = 3.0, 1.2, 2.4

    # Roof
    bpy.ops.mesh.primitive_cube_add(size=1, location=(x, y, sh))
    roof = bpy.context.active_object
    roof.name = f"{name}_roof"
    roof.scale = (sw / 2 + 0.05, sd / 2 + 0.05, 0.03)
    roof.data.materials.append(frame_mat)
    objs.append(roof)

    # Back wall (glass)
    bpy.ops.mesh.primitive_cube_add(size=1, location=(x, y - sd / 2, sh / 2))
    back = bpy.context.active_object
    back.name = f"{name}_back"
    back.scale = (sw / 2, 0.01, sh / 2)
    back.data.materials.append(glass_mat)
    objs.append(back)

    # Side walls
    for side, sx in [("L", x - sw / 2), ("R", x + sw / 2)]:
        bpy.ops.mesh.primitive_cube_add(size=1, location=(sx, y, sh / 2))
        wall = bpy.context.active_object
        wall.name = f"{name}_side_{side}"
        wall.scale = (0.01, sd / 2, sh / 2)
        wall.data.materials.append(glass_mat)
        objs.append(wall)

    # Bench inside
    bpy.ops.mesh.primitive_cube_add(size=1, location=(x, y - sd / 4, 0.4))
    bench = bpy.context.active_object
    bench.name = f"{name}_bench"
    bench.scale = (sw / 2 - 0.1, 0.15, 0.025)
    bench.data.materials.append(frame_mat)
    objs.append(bench)

    return objs


def _make_bollard(name, x, y):
    """Create a metal bollard."""
    mat = get_material("Bollard_Mat", "#4A4A4A", roughness=0.4)
    objs = []

    bpy.ops.mesh.primitive_cylinder_add(radius=0.08, depth=0.9, vertices=8,
                                         location=(x, y, 0.45))
    post = bpy.context.active_object
    post.name = f"{name}_post"
    post.data.materials.append(mat)
    objs.append(post)

    # Cap
    bpy.ops.mesh.primitive_uv_sphere_add(radius=0.09, segments=8, ring_count=6,
                                          location=(x, y, 0.92))
    cap = bpy.context.active_object
    cap.name = f"{name}_cap"
    cap.data.materials.append(mat)
    objs.append(cap)

    return objs


def _make_fence_gate(name, x, y, rotation=0):
    """Create a fence section with gate opening — wood slat fence + metal gate."""
    wood_mat = get_material("Fence_Wood_Mat", "#6A5A40", roughness=0.8)
    metal_mat = get_material("Gate_Metal_Mat", "#3A3A3A", roughness=0.4)
    objs = []
    fence_h = 1.5
    fence_w = 3.0
    gate_w = 1.0

    # Fence posts (3)
    for px in [-fence_w / 2, -gate_w / 2, gate_w / 2 + 0.05]:
        bpy.ops.mesh.primitive_cylinder_add(radius=0.04, depth=fence_h + 0.3, vertices=6,
                                             location=(x + px, y, (fence_h + 0.3) / 2))
        post = bpy.context.active_object
        post.name = f"{name}_post"
        post.rotation_euler.z = math.radians(rotation)
        post.data.materials.append(wood_mat)
        objs.append(post)

    # Fence slats (left section)
    slat_count = 8
    section_w = (fence_w - gate_w) / 2
    for si in range(slat_count):
        sx = x - fence_w / 2 + section_w / slat_count * (si + 0.5)
        bpy.ops.mesh.primitive_cube_add(size=1, location=(sx, y, fence_h / 2))
        slat = bpy.context.active_object
        slat.name = f"{name}_slat_{si}"
        slat.scale = (0.04, 0.01, fence_h / 2)
        slat.rotation_euler.z = math.radians(rotation)
        slat.data.materials.append(wood_mat)
        objs.append(slat)

    # Horizontal rails (2)
    for rz in [0.3, fence_h - 0.15]:
        bpy.ops.mesh.primitive_cube_add(size=1, location=(x - fence_w / 4 - gate_w / 4, y, rz))
        rail = bpy.context.active_object
        rail.name = f"{name}_rail"
        rail.scale = (section_w / 2, 0.02, 0.03)
        rail.rotation_euler.z = math.radians(rotation)
        rail.data.materials.append(wood_mat)
        objs.append(rail)

    # Gate — metal frame
    bpy.ops.mesh.primitive_cube_add(size=1, location=(x, y, fence_h / 2))
    gate = bpy.context.active_object
    gate.name = f"{name}_gate"
    gate.scale = (gate_w / 2, 0.015, fence_h / 2)
    gate.rotation_euler.z = math.radians(rotation)
    gate.data.materials.append(metal_mat)
    objs.append(gate)

    return objs


def _make_alley_garage(name, x, y, rotation=0):
    """Create a simple garage structure — box with flat roof and garage door."""
    brick_mat = get_material("Garage_Brick_Mat", "#8A7A6A", roughness=0.85)
    door_mat = get_material("Garage_Door_Mat", "#5A5A5A", roughness=0.5)
    roof_mat = get_material("Garage_Roof_Mat", "#4A4A4A", roughness=0.9)
    objs = []
    gw, gd, gh = 3.0, 5.5, 2.8
    door_w, door_h = 2.4, 2.3

    # Walls (simple box)
    bpy.ops.mesh.primitive_cube_add(size=1, location=(x, y - gd / 2, gh / 2))
    walls = bpy.context.active_object
    walls.name = f"{name}_walls"
    walls.scale = (gw / 2, gd / 2, gh / 2)
    walls.rotation_euler.z = math.radians(rotation)
    walls.data.materials.append(brick_mat)
    objs.append(walls)

    # Roof slab
    bpy.ops.mesh.primitive_cube_add(size=1, location=(x, y - gd / 2, gh + 0.05))
    roof = bpy.context.active_object
    roof.name = f"{name}_roof"
    roof.scale = (gw / 2 + 0.08, gd / 2 + 0.08, 0.05)
    roof.rotation_euler.z = math.radians(rotation)
    roof.data.materials.append(roof_mat)
    objs.append(roof)

    # Garage door (front face)
    bpy.ops.mesh.primitive_cube_add(size=1, location=(x, y + 0.02, door_h / 2))
    door = bpy.context.active_object
    door.name = f"{name}_door"
    door.scale = (door_w / 2, 0.02, door_h / 2)
    door.rotation_euler.z = math.radians(rotation)
    door.data.materials.append(door_mat)
    objs.append(door)

    # Door panel lines (horizontal grooves)
    for gz in [0.6, 1.2, 1.8]:
        bpy.ops.mesh.primitive_cube_add(size=1, location=(x, y + 0.04, gz))
        groove = bpy.context.active_object
        groove.name = f"{name}_groove"
        groove.scale = (door_w / 2 - 0.02, 0.005, 0.01)
        groove.rotation_euler.z = math.radians(rotation)
        groove.data.materials.append(door_mat)
        objs.append(groove)

    return objs


def _make_parking_surface(name, x, y, w=5.0, d=8.0):
    """Create a parking pad with painted lines."""
    asphalt_mat = get_material("Parking_Asphalt_Mat", "#333333", roughness=0.95)
    line_mat = get_material("Parking_Line_Mat", "#DDDDAA", roughness=0.6)
    objs = []

    # Asphalt surface
    bpy.ops.mesh.primitive_cube_add(size=1, location=(x, y, 0.01))
    surface = bpy.context.active_object
    surface.name = f"{name}_surface"
    surface.scale = (w / 2, d / 2, 0.01)
    surface.data.materials.append(asphalt_mat)
    objs.append(surface)

    # Painted parking lines
    num_spaces = max(1, int(w / 2.7))
    for li in range(num_spaces + 1):
        lx = x - w / 2 + (w / num_spaces) * li
        bpy.ops.mesh.primitive_cube_add(size=1, location=(lx, y, 0.025))
        line = bpy.context.active_object
        line.name = f"{name}_line_{li}"
        line.scale = (0.05, d / 2 - 0.2, 0.005)
        line.data.materials.append(line_mat)
        objs.append(line)

    return objs


def _make_ground_tile(name, x, y, w=1.0, h=0.02):
    """Create a ground surface tile (sidewalk slab, paver)."""
    concrete_mat = get_material("Ground_Concrete_Mat", "#9A9A8A", roughness=0.85)
    objs = []

    bpy.ops.mesh.primitive_cube_add(size=1, location=(x, y, h / 2))
    tile = bpy.context.active_object
    tile.name = f"{name}_tile"
    tile.scale = (w / 2, w / 2, h / 2)
    tile.data.materials.append(concrete_mat)
    objs.append(tile)

    return objs


def _make_accessibility_feature(name, x, y):
    """Create accessibility feature — tactile paving pad + curb cut."""
    yellow_mat = get_material("Tactile_Mat", "#DDDD44", roughness=0.7)
    concrete_mat = get_material("CurbCut_Mat", "#9A9A8A", roughness=0.85)
    objs = []

    # Tactile paving pad
    bpy.ops.mesh.primitive_cube_add(size=1, location=(x, y, 0.015))
    pad = bpy.context.active_object
    pad.name = f"{name}_pad"
    pad.scale = (0.6, 0.6, 0.015)
    pad.data.materials.append(yellow_mat)
    objs.append(pad)

    # Curb ramp (sloped concrete)
    bm = bmesh.new()
    rw, rd = 0.8, 0.5
    v0 = bm.verts.new((x - rw / 2, y - rd, 0))
    v1 = bm.verts.new((x + rw / 2, y - rd, 0))
    v2 = bm.verts.new((x + rw / 2, y, 0.12))
    v3 = bm.verts.new((x - rw / 2, y, 0.12))
    bm.faces.new([v0, v1, v2, v3])
    # Top face
    v4 = bm.verts.new((x - rw / 2, y, 0.12))
    v5 = bm.verts.new((x + rw / 2, y, 0.12))
    v6 = bm.verts.new((x + rw / 2, y + 0.15, 0.12))
    v7 = bm.verts.new((x - rw / 2, y + 0.15, 0.12))
    bm.faces.new([v4, v5, v6, v7])

    mesh = bpy.data.meshes.new(f"{name}_ramp_mesh")
    bm.to_mesh(mesh)
    bm.free()
    ramp = bpy.data.objects.new(f"{name}_ramp", mesh)
    bpy.context.collection.objects.link(ramp)
    ramp.data.materials.append(concrete_mat)
    objs.append(ramp)

    return objs


def _make_intersection(name, x, y, size=10.0):
    """Create an intersection with road surface + crosswalk markings."""
    road_mat = get_material("Intersection_Road_Mat", "#3A3A3A", roughness=0.92)
    marking_mat = get_material("Crosswalk_Mat", "#E8E8E0", roughness=0.6)
    objs = []

    # Road surface
    bpy.ops.mesh.primitive_cube_add(size=1, location=(x, y, 0.005))
    road = bpy.context.active_object
    road.name = f"{name}_surface"
    road.scale = (size / 2, size / 2, 0.005)
    road.data.materials.append(road_mat)
    objs.append(road)

    # Crosswalk stripes (2 crosswalks, perpendicular)
    stripe_w = 0.3
    stripe_gap = 0.3
    num_stripes = 6
    for direction in [0, 1]:  # 0=N-S, 1=E-W
        for si in range(num_stripes):
            offset = -num_stripes / 2 * (stripe_w + stripe_gap) + si * (stripe_w + stripe_gap)
            if direction == 0:
                sx = x + offset
                sy = y + size / 2 - 1.5
                sw, sd = stripe_w / 2, 1.5
            else:
                sx = x + size / 2 - 1.5
                sy = y + offset
                sw, sd = 1.5, stripe_w / 2

            bpy.ops.mesh.primitive_cube_add(size=1, location=(sx, sy, 0.012))
            stripe = bpy.context.active_object
            stripe.name = f"{name}_stripe_{direction}_{si}"
            stripe.scale = (sw, sd, 0.002)
            stripe.data.materials.append(marking_mat)
            objs.append(stripe)

    return objs


def _make_alley(name, x, y, w=3.0, d=20.0):
    """Create an alley surface with rough asphalt."""
    mat = get_material("Alley_Mat", "#4A4A4A", roughness=0.95)
    objs = []

    bpy.ops.mesh.primitive_cube_add(size=1, location=(x, y, 0.005))
    surface = bpy.context.active_object
    surface.name = f"{name}_surface"
    surface.scale = (w / 2, d / 2, 0.005)
    surface.data.materials.append(mat)
    objs.append(surface)

    # Drain grate in center
    grate_mat = get_material("Grate_Mat", "#2A2A2A", roughness=0.3)
    bpy.ops.mesh.primitive_cube_add(size=1, location=(x, y, 0.015))
    grate = bpy.context.active_object
    grate.name = f"{name}_drain"
    grate.scale = (0.15, 0.15, 0.005)
    grate.data.materials.append(grate_mat)
    objs.append(grate)

    return objs


def _make_vertical_hardscape(name, x, y, h=1.2):
    """Create vertical hardscape element — retaining wall / curb / planter wall."""
    mat = get_material("VHardscape_Mat", "#8A8A8A", roughness=0.85)
    objs = []

    # Concrete wall/curb element
    bpy.ops.mesh.primitive_cube_add(size=1, location=(x, y, h / 2))
    wall = bpy.context.active_object
    wall.name = f"{name}_wall"
    wall.scale = (0.15, 0.5, h / 2)
    wall.data.materials.append(mat)
    objs.append(wall)

    # Cap stone
    cap_mat = get_material("VHardscape_Cap_Mat", "#9A9A8A", roughness=0.7)
    bpy.ops.mesh.primitive_cube_add(size=1, location=(x, y, h + 0.02))
    cap = bpy.context.active_object
    cap.name = f"{name}_cap"
    cap.scale = (0.18, 0.53, 0.02)
    cap.data.materials.append(cap_mat)
    objs.append(cap)

    return objs


def create_urban_elements():
    """Create all urban element instances with detailed geometry."""
    urban = GIS.get("urban_elements", {})
    if not urban:
        print("  Urban elements: 0 (run integrate_urban_elements.py first)")
        return

    total = 0

    # Category → builder function mapping
    BUILDERS = {
        "trees": lambda name, x, y, inst: _make_tree(name, x, y,
            height=inst.get("h", 6.0), canopy_r=1.5,
            species=inst.get("type", "unknown")),
        "poles": lambda name, x, y, inst: _make_pole(name, x, y,
            height=inst.get("h", 5.0),
            pole_type=inst.get("type", "generic_pole")),
        "signs": lambda name, x, y, inst: _make_sign(name, x, y,
            height=inst.get("h", 2.5)),
        "bikeracks": lambda name, x, y, inst: _make_bikerack(name, x, y),
        "waste": lambda name, x, y, inst: _make_waste_bin(name, x, y),
        "transit_stops": lambda name, x, y, inst: _make_transit_shelter(name, x, y),
        "fence_gates": lambda name, x, y, inst: _make_fence_gate(name, x, y,
            rotation=inst.get("rotation", 0)),
        "alley_garages": lambda name, x, y, inst: _make_alley_garage(name, x, y,
            rotation=inst.get("rotation", 0)),
        "parking": lambda name, x, y, inst: _make_parking_surface(name, x, y),
        "ground": lambda name, x, y, inst: _make_ground_tile(name, x, y),
        "accessibility": lambda name, x, y, inst: _make_accessibility_feature(name, x, y),
        "intersections": lambda name, x, y, inst: _make_intersection(name, x, y),
        "alleys": lambda name, x, y, inst: _make_alley(name, x, y),
        "vertical_hardscape": lambda name, x, y, inst: _make_vertical_hardscape(name, x, y,
            h=inst.get("h", 1.2)),
        "street_furniture": lambda name, x, y, inst: _make_street_furniture(name, x, y,
            rotation=inst.get("rotation", 0),
            furniture_type=inst.get("type", "bench")),
    }

    for category, data in sorted(urban.items()):
        instances = data.get("instances", [])
        if not instances:
            continue

        cfg = data.get("config", {})
        col_name = f"Urban_{category}"
        col = clear_collection(col_name)

        builder = BUILDERS.get(category)

        for i, inst in enumerate(instances):
            x = inst.get("x", 0)
            y = inst.get("y", 0)
            name = f"{category}_{i}"

            if builder:
                objs = builder(name, x, y, inst)
            else:
                # Fallback: simple cube/cylinder based on config
                h = inst.get("h", cfg.get("height", 1.0))
                r = cfg.get("radius", 0.5)
                shape = cfg.get("shape", "cube")
                mat = get_material(f"Urban_{category}_Mat", cfg.get("hex", "#888888"))

                if shape == "cylinder":
                    bpy.ops.mesh.primitive_cylinder_add(radius=r, depth=h, vertices=8,
                                                         location=(x, y, h / 2))
                else:
                    bpy.ops.mesh.primitive_cube_add(size=1, location=(x, y, max(0.01, h / 2)))
                    bpy.context.active_object.scale = (r, r, max(0.01, h / 2))

                obj = bpy.context.active_object
                obj.name = name
                obj.data.materials.append(mat)
                objs = [obj]

            # Apply rotation if present
            rot = inst.get("rotation", 0)
            if rot and objs:
                for obj in objs:
                    obj.rotation_euler.z = math.radians(rot)

            # Move to collection
            for obj in objs:
                for c in obj.users_collection:
                    c.objects.unlink(obj)
                col.objects.link(obj)
            total += len(objs)

        print(f"  {col_name}: {len(instances)} instances ({total} objects)")

    print(f"  Urban elements total: {total} objects")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("=== Kensington Market GIS Site Model ===")
    print(f"Origin: {ORIGIN_X}, {ORIGIN_Y} (SRID 2952)")
    print()

    create_study_area()
    create_footprints()
    create_massing()
    create_curves("roads", "GIS_Roads", "#4A4A4A", 3.0)
    create_curves("sidewalks", "GIS_Sidewalks", "#9A9A8A", 1.5)
    create_curves("alleys", "GIS_Alleys", "#6A6A6A", 1.5)
    create_field_features()
    create_urban_elements()

    print(f"\n  Building positions: {len(GIS.get('building_positions', {}))}")
    print("\nDone — GIS site model loaded.")
    collections = ["GIS_StudyArea", "GIS_Footprints", "GIS_Massing",
                    "GIS_Roads", "GIS_Sidewalks", "GIS_Alleys", "GIS_FieldSurvey"]
    for cat in GIS.get("urban_elements", {}):
        collections.append(f"Urban_{cat}")
    print(f"Collections: {', '.join(collections)}")

main()
