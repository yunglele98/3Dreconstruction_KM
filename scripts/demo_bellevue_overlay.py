"""Bellevue Ave demo: GIS massing + parametric building facades.

Loads real 3D massing from city data as building envelopes,
then generates parametric facades (from params) positioned at
correct GIS coordinates facing the street.

Run: blender --python scripts/demo_bellevue_overlay.py
"""

import bpy
import bmesh
import json
import math
import os
import sys
from pathlib import Path

SCRIPT_DIR = Path(os.path.dirname(os.path.abspath(__file__))).parent
sys.path.insert(0, str(SCRIPT_DIR))

DATA_PATH = SCRIPT_DIR / "outputs" / "gis_scene.json"
SITE_COORDS = SCRIPT_DIR / "params" / "_site_coordinates.json"
PARAMS_DIR = SCRIPT_DIR / "params"

with open(DATA_PATH, encoding="utf-8") as f:
    GIS = json.load(f)
with open(SITE_COORDS, encoding="utf-8") as f:
    SITE = json.load(f)

# Bellevue 20-50 bounding box
X_MIN, X_MAX = -135, -15
Y_MIN, Y_MAX = -170, 15


def in_bounds(pts, margin=0):
    if not pts:
        return False
    cx = sum(p[0] for p in pts) / len(pts)
    cy = sum(p[1] for p in pts) / len(pts)
    return (X_MIN - margin) <= cx <= (X_MAX + margin) and \
           (Y_MIN - margin) <= cy <= (Y_MAX + margin)


def clear_scene():
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete()
    for c in list(bpy.data.collections):
        bpy.data.collections.remove(c)


def get_mat(name, hex_colour, roughness=0.8, alpha=1.0):
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
        if alpha < 1.0:
            bsdf.inputs["Alpha"].default_value = alpha
            mat.blend_method = 'BLEND' if hasattr(mat, 'blend_method') else None
    return mat


def make_collection(name):
    col = bpy.data.collections.new(name)
    bpy.context.scene.collection.children.link(col)
    return col


def link_to(obj, col):
    for c in obj.users_collection:
        c.objects.unlink(obj)
    col.objects.link(obj)


# ── GIS Layers ──────────────────────────────────────────────

def create_massing(col):
    """Real 3D massing from city open data."""
    mat = get_mat("Massing", "#C4A882", 0.75)

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
        bottom = [bm.verts.new((x, y, 0)) for x, y in ring]
        try:
            face = bm.faces.new(bottom)
        except ValueError:
            bm.free()
            continue

        result = bmesh.ops.extrude_face_region(bm, geom=[face])
        for v in (v for v in result["geom"] if isinstance(v, bmesh.types.BMVert)):
            v.co.z = h

        bm.normal_update()
        mesh = bpy.data.meshes.new(f"Mass_{count}")
        bm.to_mesh(mesh)
        bm.free()

        obj = bpy.data.objects.new(f"Massing_{count}", mesh)
        obj.data.materials.append(mat)
        link_to(obj, col)
        count += 1

    print(f"  Massing: {count}")


def create_footprints(col):
    """2D building footprints."""
    mat = get_mat("Footprint", "#7A6A5A", 0.9)
    count = 0
    for fp in GIS.get("footprints", []):
        rings = fp.get("rings", [[]])
        if not rings or not rings[0]:
            continue
        ring = rings[0]
        if len(ring) < 3 or not in_bounds(ring):
            continue

        bm = bmesh.new()
        verts = [bm.verts.new((x, y, 0.02)) for x, y in ring]
        try:
            bm.faces.new(verts)
        except ValueError:
            bm.free()
            continue

        mesh = bpy.data.meshes.new(f"FP_{count}")
        bm.to_mesh(mesh)
        bm.free()

        obj = bpy.data.objects.new(f"FP_{count}", mesh)
        obj.data.materials.append(mat)
        link_to(obj, col)
        count += 1

    print(f"  Footprints: {count}")


def create_roads(col):
    """Roads and alleys from GIS."""
    mat_road = get_mat("Road", "#3A3A3A", 0.85)
    mat_alley = get_mat("Alley", "#5A5A5A", 0.85)

    count = 0
    for key, mat, bevel in [("roads", mat_road, 3.5), ("alleys", mat_alley, 1.5)]:
        for r in GIS.get(key, []):
            coords = r.get("coords", [])
            if len(coords) < 2:
                continue
            cx = sum(p[0] for p in coords) / len(coords)
            cy = sum(p[1] for p in coords) / len(coords)
            if not (X_MIN - 40 <= cx <= X_MAX + 40 and Y_MIN - 40 <= cy <= Y_MAX + 40):
                continue

            curve = bpy.data.curves.new(f"{key}_{count}", type='CURVE')
            curve.dimensions = '3D'
            spline = curve.splines.new('POLY')
            spline.points.add(len(coords) - 1)
            for j, (x, y) in enumerate(coords):
                spline.points[j].co = (x, y, 0.01, 1)
            curve.bevel_depth = bevel
            curve.bevel_resolution = 0

            obj = bpy.data.objects.new(f"{key}_{count}", curve)
            obj.data.materials.append(mat)
            link_to(obj, col)
            count += 1

    print(f"  Roads + alleys: {count}")


def create_field_features(col):
    """Field survey: trees, poles, bike racks from GIS."""
    FIELD_CONFIG = {
        "trees":      {"hex": "#2A5A2A", "r": 1.2, "h": 6.0, "shape": "sphere"},
        "poles":      {"hex": "#5A5A5A", "r": 0.06, "h": 5.0, "shape": "cylinder"},
        "bike_racks": {"hex": "#4488CC", "r": 0.3, "h": 0.8, "shape": "cube"},
        "terraces":   {"hex": "#AA8855", "r": 1.5, "h": 0.1, "shape": "cube"},
        "parking":    {"hex": "#333333", "r": 3.0, "h": 0.05, "shape": "cube"},
    }
    count = 0
    for layer, points in GIS.get("field", {}).items():
        cfg = FIELD_CONFIG.get(layer)
        if not cfg:
            continue
        mat = get_mat(f"Field_{layer}", cfg["hex"])
        for pt in points:
            x, y = pt["x"], pt["y"]
            if not (X_MIN - 10 <= x <= X_MAX + 10 and Y_MIN - 10 <= y <= Y_MAX + 10):
                continue

            if cfg["shape"] == "sphere":
                bpy.ops.mesh.primitive_uv_sphere_add(
                    radius=cfg["r"], location=(x, y, cfg["h"]),
                    segments=8, ring_count=6)
            elif cfg["shape"] == "cylinder":
                bpy.ops.mesh.primitive_cylinder_add(
                    radius=cfg["r"], depth=cfg["h"],
                    location=(x, y, cfg["h"] / 2), vertices=8)
            else:
                bpy.ops.mesh.primitive_cube_add(size=1, location=(x, y, cfg["h"] / 2))
                bpy.context.active_object.scale = (cfg["r"], cfg["r"], cfg["h"] / 2)

            obj = bpy.context.active_object
            obj.name = f"{layer}_{count}"
            obj.data.materials.append(mat)
            link_to(obj, col)
            count += 1

    print(f"  Field features: {count}")


def create_ground(col):
    """Ground plane."""
    bpy.ops.mesh.primitive_plane_add(
        size=1, location=((X_MIN + X_MAX) / 2, (Y_MIN + Y_MAX) / 2, -0.01))
    ground = bpy.context.active_object
    ground.name = "Ground"
    ground.scale = ((X_MAX - X_MIN) / 2 + 30, (Y_MAX - Y_MIN) / 2 + 30, 1)
    mat = get_mat("Ground", "#4A5A3A", 0.95)
    ground.data.materials.append(mat)
    link_to(ground, col)


# ── Parametric facades ──────────────────────────────────────

def create_facade(params, x, y, rot, col):
    """Simple parametric facade plane with window/door cutouts, positioned at GIS coords."""
    import re

    name = params.get("building_name", "?")
    w = params.get("facade_width_m", 5.2)
    h = params.get("total_height_m", 7.0)
    floors = params.get("floors", 2)
    mat_name = (params.get("facade_material") or "brick").lower()
    roof_type = (params.get("roof_type") or "gable").lower()

    # Material colour
    colour_map = {
        "brick": "#B8654A", "stone": "#A09880", "stucco": "#D8D0C0",
        "clapboard": "#E8E0D0", "paint": "#C8D0C8", "siding": "#C0C8C0",
        "wood": "#8A7050", "concrete": "#A0A0A0",
    }
    hex_col = colour_map.get(mat_name, "#B8654A")
    mat = get_mat(f"Facade_{name[:20]}", hex_col, 0.7)
    mat_window = get_mat("Window_Glass", "#3A5A7A", 0.3)
    mat_door = get_mat("Door_Wood", "#5A3A2A", 0.8)
    mat_trim = get_mat("Trim", "#E8E0D0", 0.6)

    # Create facade wall (thin box facing street)
    wall_depth = 0.3  # thin facade shell
    bpy.ops.mesh.primitive_cube_add(size=1, location=(x, y, h / 2))
    facade = bpy.context.active_object
    facade.name = f"Facade_{name[:30]}"
    facade.scale = (w / 2, wall_depth / 2, h / 2)
    facade.rotation_euler[2] = math.radians(rot)
    facade.data.materials.append(mat)
    link_to(facade, col)

    # Add windows as small boxes on the facade
    wpf = params.get("windows_per_floor", [2] * floors)
    win_w = params.get("window_width_m", 0.9)
    win_h = params.get("window_height_m", 1.2)
    fh = params.get("floor_heights_m", [h / floors] * floors)

    rad = math.radians(rot)
    # Normal direction (perpendicular to facade, towards street)
    nx = -math.sin(rad)
    ny = math.cos(rad)
    # Along-facade direction
    fx = math.cos(rad)
    fy = math.sin(rad)

    z_base = 0
    for fi in range(min(len(wpf), len(fh))):
        floor_h = fh[fi] if fi < len(fh) else 3.0
        n_win = wpf[fi] if fi < len(wpf) else 2
        if not isinstance(n_win, (int, float)) or n_win <= 0:
            z_base += floor_h
            continue

        n_win = min(int(n_win), max(1, int(w / 1.0)))  # cap to width
        sill_z = z_base + floor_h * 0.35
        spacing = w / (n_win + 1)

        for wi in range(n_win):
            offset_along = -w / 2 + spacing * (wi + 1)
            wx = x + fx * offset_along + nx * (wall_depth / 2 + 0.01)
            wy = y + fy * offset_along + ny * (wall_depth / 2 + 0.01)
            wz = sill_z + win_h / 2

            bpy.ops.mesh.primitive_cube_add(size=1, location=(wx, wy, wz))
            win = bpy.context.active_object
            win.name = f"Win_{name[:15]}_{fi}_{wi}"
            win.scale = (win_w / 2, 0.03, win_h / 2)
            win.rotation_euler[2] = rad
            win.data.materials.append(mat_window)
            link_to(win, col)

        z_base += floor_h

    # Door
    door_w = 1.0
    door_h = 2.2
    dx = x + nx * (wall_depth / 2 + 0.01)
    dy = y + ny * (wall_depth / 2 + 0.01)
    bpy.ops.mesh.primitive_cube_add(size=1, location=(dx, dy, door_h / 2))
    door = bpy.context.active_object
    door.name = f"Door_{name[:20]}"
    door.scale = (door_w / 2, 0.04, door_h / 2)
    door.rotation_euler[2] = rad
    door.data.materials.append(mat_door)
    link_to(door, col)

    # Gable roof indicator (triangle on top)
    if "gable" in roof_type:
        pitch = 25
        ridge_h = (w / 2) * math.tan(math.radians(pitch))
        bm = bmesh.new()
        # Triangle in local coords, then position
        v1 = bm.verts.new((-w/2, 0, 0))
        v2 = bm.verts.new((w/2, 0, 0))
        v3 = bm.verts.new((0, 0, ridge_h))
        bm.faces.new([v1, v2, v3])

        mesh = bpy.data.meshes.new(f"Gable_{name[:20]}")
        bm.to_mesh(mesh)
        bm.free()

        gable = bpy.data.objects.new(f"Gable_{name[:20]}", mesh)
        gable.location = (x, y, h)
        gable.rotation_euler[2] = rad
        gable.data.materials.append(mat)
        link_to(gable, col)


def create_parametric_facades(col):
    """Load params for Bellevue 20-50 and create facade overlays."""
    import re
    count = 0
    for addr, pos in sorted(SITE.items()):
        if "Bellevue" not in addr:
            continue
        m = re.match(r"(\d+)", addr)
        if not m or not (20 <= int(m.group(1)) <= 50):
            continue

        # Load params
        stem = addr.replace(" ", "_")
        param_file = PARAMS_DIR / f"{stem}.json"
        if not param_file.exists():
            continue
        params = json.load(open(param_file, encoding="utf-8"))
        if params.get("skipped"):
            continue

        create_facade(params, pos["x"], pos["y"], pos.get("rotation_deg", 0), col)
        count += 1

    print(f"  Parametric facades: {count}")


# ── Camera + Lighting ───────────────────────────────────────

def setup_scene():
    # Sun
    bpy.ops.object.light_add(type='SUN', location=(0, 0, 100))
    sun = bpy.context.active_object
    sun.name = "Sun"
    sun.data.energy = 3.0
    sun.rotation_euler = (math.radians(50), math.radians(10), math.radians(20))

    # Camera from SE looking NW at the block
    cx = (X_MIN + X_MAX) / 2
    cy = (Y_MIN + Y_MAX) / 2
    bpy.ops.object.camera_add(location=(cx + 60, cy - 100, 60))
    cam = bpy.context.active_object
    cam.name = "Camera"
    cam.rotation_euler = (math.radians(60), 0, math.radians(30))
    bpy.context.scene.camera = cam


# ── Main ────────────────────────────────────────────────────

def main():
    clear_scene()
    print("=== Bellevue Ave Demo: GIS Massing + Parametric Facades ===")

    col_env = make_collection("Environment")
    col_massing = make_collection("Massing_3D")
    col_facades = make_collection("Facades")
    col_field = make_collection("Field_Survey")

    create_ground(col_env)
    create_massing(col_massing)
    create_footprints(col_env)
    create_roads(col_env)
    create_field_features(col_field)
    create_parametric_facades(col_facades)
    setup_scene()

    out = str(SCRIPT_DIR / "outputs" / "demos" / "bellevue_gis_demo.blend")
    bpy.ops.wm.save_as_mainfile(filepath=out)
    print(f"\nSaved: {out}")


main()
