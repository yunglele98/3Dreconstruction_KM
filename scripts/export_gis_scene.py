#!/usr/bin/env python3
"""Step 4: Export georeferenced GIS data to a Blender Python scene script.

Pulls real geometry from PostGIS (building footprints, 3D massing, roads,
sidewalks, alleys, field survey features) and writes a Blender Python script
that creates the full site model.

All coordinates are in SRID 2952 (NAD83 UTM17N, metres) centered on the
study area centroid so Blender coordinates are in local metres from (0,0).

Usage:
    python export_gis_scene.py [--output gis_scene.py]
    python export_gis_scene.py --massing-only   # Just 3D massing shapes
"""

import argparse
import json
import math
import sys
from pathlib import Path

try:
    import psycopg2
    import psycopg2.extras
except ImportError:
    print("[ERROR] psycopg2 not installed. Run: pip install psycopg2-binary")
    sys.exit(1)

from db_config import DB_CONFIG

OUTPUT_DIR = Path(__file__).parent.parent

# Centroid of building footprints in SRID 2952 (metres)
# All coordinates are offset by this to center the Blender scene at (0,0)
ORIGIN_X = 312672.94
ORIGIN_Y = 4834994.86


def local(x, y):
    """Convert SRID 2952 absolute to local Blender coords."""
    return round(x - ORIGIN_X, 3), round(y - ORIGIN_Y, 3)


# ---------------------------------------------------------------------------
# Data fetchers
# ---------------------------------------------------------------------------

def fetch_building_footprints(conn):
    """Fetch 2D building footprint polygons (SRID 2952)."""
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""
        SELECT gid, "ELEVATI4" as elevation,
               ST_AsGeoJSON(geom) as geojson
        FROM opendata.building_footprints
    """)
    rows = cur.fetchall()
    cur.close()
    return rows


def fetch_massing_3d(conn):
    """Fetch 3D building massing polygons clipped to study area (SRID 2952)."""
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""
        SELECT "MIN_HEIGHT" as min_h, "MAX_HEIGHT" as max_h,
               "AVG_HEIGHT" as avg_h, "SURF_ELEV" as ground_elev,
               ST_AsGeoJSON(geometry) as geojson
        FROM opendata.massing_3d m
        WHERE ST_Intersects(
            m.geometry,
            (SELECT ST_Transform(geometry, 2952) FROM opendata.study_area LIMIT 1)
        )
    """)
    rows = cur.fetchall()
    cur.close()
    return rows


def fetch_roads(conn):
    """Fetch road centerlines (SRID 2952)."""
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""
        SELECT gid,
               ST_AsGeoJSON(geom) as geojson
        FROM opendata.road_centerlines
    """)
    rows = cur.fetchall()
    cur.close()
    return rows


def fetch_sidewalks(conn):
    """Fetch sidewalk geometry (SRID 2952)."""
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""
        SELECT gid,
               ST_AsGeoJSON(geometry) as geojson
        FROM opendata.sidewalks
    """)
    rows = cur.fetchall()
    cur.close()
    return rows


def fetch_alleys(conn):
    """Fetch alley linestrings (SRID 4326 → reproject to 2952)."""
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""
        SELECT osm_id, name,
               ST_AsGeoJSON(ST_Transform(geom, 2952)) as geojson
        FROM ruelles_spatial
        WHERE geom IS NOT NULL
    """)
    rows = cur.fetchall()
    cur.close()
    return rows


def fetch_study_area(conn):
    """Fetch study area boundary (reproject to 2952)."""
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""
        SELECT ST_AsGeoJSON(ST_Transform(geometry, 2952)) as geojson
        FROM opendata.study_area
        LIMIT 1
    """)
    row = cur.fetchone()
    cur.close()
    return row


def fetch_field_points(conn, table, srid=4326):
    """Fetch point features, reprojecting to 2952 if needed."""
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    if srid == 4326:
        cur.execute(f"""
            SELECT ST_X(ST_Transform(geom, 2952)) as x,
                   ST_Y(ST_Transform(geom, 2952)) as y
            FROM {table}
            WHERE geom IS NOT NULL
        """)
    else:
        cur.execute(f"""
            SELECT ST_X(geom) as x, ST_Y(geom) as y
            FROM {table}
            WHERE geom IS NOT NULL
        """)
    rows = cur.fetchall()
    cur.close()
    return rows


# ---------------------------------------------------------------------------
# Transform geometry to local coordinates
# ---------------------------------------------------------------------------

def transform_polygon_coords(geojson_str):
    """Extract polygon rings from GeoJSON string, convert to local coords."""
    geom = json.loads(geojson_str)
    gtype = geom.get("type", "")
    coords = geom.get("coordinates", [])

    rings_list = []
    if gtype == "Polygon":
        for ring in coords:
            local_ring = []
            for pt in ring:
                lx, ly = local(pt[0], pt[1])  # ignore Z if present
                local_ring.append((lx, ly))
            rings_list.append(local_ring)
    elif gtype == "MultiPolygon":
        for poly in coords:
            for ring in poly:
                local_ring = []
                for pt in ring:
                    lx, ly = local(pt[0], pt[1])
                    local_ring.append((lx, ly))
                rings_list.append(local_ring)

    return rings_list


def transform_line_coords(geojson_str):
    """Extract line coordinates from GeoJSON, convert to local."""
    geom = json.loads(geojson_str)
    gtype = geom.get("type", "")
    coords = geom.get("coordinates", [])

    lines = []
    if gtype == "LineString":
        lines.append([local(pt[0], pt[1]) for pt in coords])
    elif gtype == "MultiLineString":
        for line in coords:
            lines.append([local(pt[0], pt[1]) for pt in line])

    return lines


def extract_primary_ring_abs(geojson_str):
    """Extract the primary polygon ring in absolute SRID 2952 coordinates."""
    if not geojson_str:
        return []
    geom = json.loads(geojson_str)
    gtype = geom.get("type", "")
    coords = geom.get("coordinates", [])

    if gtype == "Polygon" and coords:
        return [(pt[0], pt[1]) for pt in coords[0] if len(pt) >= 2]

    if gtype == "MultiPolygon" and coords:
        best = []
        best_len = -1
        for poly in coords:
            if not poly:
                continue
            ring = poly[0]
            if len(ring) > best_len:
                best = ring
                best_len = len(ring)
        return [(pt[0], pt[1]) for pt in best if len(pt) >= 2]

    return []


def polygon_centroid_abs(ring):
    """Compute a simple centroid from polygon vertices in absolute coordinates."""
    if not ring:
        return None, None
    pts = ring[:-1] if len(ring) > 1 and ring[0] == ring[-1] else ring
    if not pts:
        return None, None
    cx = sum(p[0] for p in pts) / len(pts)
    cy = sum(p[1] for p in pts) / len(pts)
    return cx, cy


def compass_bearing_from_edge(dx, dy):
    """Convert edge vector to compass bearing (0=N, clockwise)."""
    edge_deg = math.degrees(math.atan2(dy, dx))  # 0=+X (east), CCW+
    # Convert to compass bearing.
    return (90.0 - edge_deg) % 360.0


def angular_distance(a, b):
    """Smallest circular distance between angles in degrees."""
    return abs((a - b + 180.0) % 360.0 - 180.0)


def derive_facade_bearing_from_ring(ring, road_bearing=None):
    """Estimate facade bearing from longest footprint edge (+/-90 deg normal)."""
    if not ring:
        return road_bearing if road_bearing is not None else 0.0

    pts = ring[:-1] if len(ring) > 1 and ring[0] == ring[-1] else ring
    if len(pts) < 2:
        return road_bearing if road_bearing is not None else 0.0

    longest = None
    max_len = 0.0
    for i in range(len(pts)):
        j = (i + 1) % len(pts)
        dx = pts[j][0] - pts[i][0]
        dy = pts[j][1] - pts[i][1]
        seg_len = math.hypot(dx, dy)
        if seg_len > max_len:
            max_len = seg_len
            longest = (dx, dy)

    if not longest:
        return road_bearing if road_bearing is not None else 0.0

    depth_bearing = compass_bearing_from_edge(longest[0], longest[1])
    c1 = (depth_bearing + 90.0) % 360.0
    c2 = (depth_bearing - 90.0) % 360.0

    if road_bearing is None:
        return c1
    return c1 if angular_distance(c1, road_bearing) <= angular_distance(c2, road_bearing) else c2


# ---------------------------------------------------------------------------
# Build scene data
# ---------------------------------------------------------------------------

def build_scene_data(conn, include_massing=True):
    """Fetch and transform all GIS data into Blender-ready structures."""
    data = {}

    # Building footprints
    print("  Fetching building footprints...")
    footprints = fetch_building_footprints(conn)
    fp_data = []
    for fp in footprints:
        rings = transform_polygon_coords(fp["geojson"])
        if rings:
            fp_data.append({
                "gid": fp["gid"],
                "elev": fp["elevation"] or 0,
                "rings": rings,
            })
    data["footprints"] = fp_data
    print(f"    {len(fp_data)} footprints")

    # 3D massing
    if include_massing:
        print("  Fetching 3D massing (this may take a moment)...")
        massing = fetch_massing_3d(conn)
        ms_data = []
        for m in massing:
            rings = transform_polygon_coords(m["geojson"])
            if rings:
                ms_data.append({
                    "h": round(m["avg_h"] or 0, 2),
                    "max_h": round(m["max_h"] or 0, 2),
                    "ground": round(m["ground_elev"] or 0, 2),
                    "rings": rings,
                })
        data["massing"] = ms_data
        print(f"    {len(ms_data)} massing shapes")

    # Roads
    print("  Fetching roads...")
    roads = fetch_roads(conn)
    rd_data = []
    for r in roads:
        lines = transform_line_coords(r["geojson"])
        for line in lines:
            rd_data.append({"gid": r["gid"], "coords": line})
    data["roads"] = rd_data
    print(f"    {len(rd_data)} road segments")

    # Sidewalks
    print("  Fetching sidewalks...")
    sidewalks = fetch_sidewalks(conn)
    sw_data = []
    for s in sidewalks:
        lines = transform_line_coords(s["geojson"])
        for line in lines:
            sw_data.append({"gid": s["gid"], "coords": line})
    data["sidewalks"] = sw_data
    print(f"    {len(sw_data)} sidewalk segments")

    # Alleys
    print("  Fetching alleys...")
    alleys = fetch_alleys(conn)
    al_data = []
    for a in alleys:
        lines = transform_line_coords(a["geojson"])
        for line in lines:
            al_data.append({"id": a["osm_id"], "name": a["name"] or "", "coords": line})
    data["alleys"] = al_data
    print(f"    {len(al_data)} alleys")

    # Study area boundary
    print("  Fetching study area...")
    sa = fetch_study_area(conn)
    if sa:
        data["study_area"] = transform_polygon_coords(sa["geojson"])
        print(f"    1 boundary ({len(data['study_area'])} rings)")

    # Field survey features
    field_tables = {
        "trees": "field_trees",
        "poles": "field_poles",
        "signs": "field_signs",
        "bike_racks": "field_bike_racks",
        "terraces": "field_terraces",
        "parking": "field_parking",
        "public_art": "field_public_art",
        "bus_shelters": "field_bus_shelters",
        "parks": "field_parks",
    }
    print("  Fetching field survey...")
    field_data = {}
    for label, table in field_tables.items():
        pts = fetch_field_points(conn, table)
        field_data[label] = [{"x": local(p["x"], p["y"])[0], "y": local(p["x"], p["y"])[1]} for p in pts]
        print(f"    {label}: {len(field_data[label])}")
    data["field"] = field_data

    # Building positions: strict spatial match from assessment points to footprint + massing
    # for GIS-accurate placement and orientation.
    print("  Fetching building positions (address/photo points -> footprints + 3D massing)...")
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""
        SELECT ba."ADDRESS_FULL" as address,
               ST_X(ST_Transform(ba.geom, 2952)) as x,
               ST_Y(ST_Transform(ba.geom, 2952)) as y,
               fp.footprint_geojson as footprint_geojson,
               ms.avg_h as massing_height_m,
               ST_Azimuth(
                   ST_ClosestPoint(ST_Transform(r.geom, 2952), ST_Transform(ba.geom, 2952)),
                   ST_Transform(ba.geom, 2952)
               ) * 180 / pi() as facade_bearing_deg
        FROM building_assessment ba
        LEFT JOIN LATERAL (
            SELECT
                ST_Transform(bf.geom, 2952) as geom_2952,
                ST_AsGeoJSON(ST_Transform(bf.geom, 2952)) as footprint_geojson
            FROM opendata.building_footprints bf
            ORDER BY
                CASE
                    WHEN ST_Contains(ST_Transform(bf.geom, 2952), ST_Transform(ba.geom, 2952)) THEN 0
                    ELSE 1
                END,
                ST_Distance(ST_Transform(bf.geom, 2952), ST_Transform(ba.geom, 2952))
            LIMIT 1
        ) fp ON TRUE
        LEFT JOIN LATERAL (
            SELECT m."AVG_HEIGHT" as avg_h
            FROM opendata.massing_3d m
            WHERE fp.geom_2952 IS NOT NULL
              AND ST_Intersects(m.geometry, fp.geom_2952)
            ORDER BY ST_Distance(m.geometry, ST_Centroid(fp.geom_2952))
            LIMIT 1
        ) ms ON TRUE
        CROSS JOIN LATERAL (
            SELECT geom FROM opendata.road_centerlines
            ORDER BY geom <-> ST_Transform(ba.geom, 2952)
            LIMIT 1
        ) r
        WHERE ba.geom IS NOT NULL
    """)
    bldg_positions = {}
    matched_footprints = 0
    matched_massing = 0
    for r in cur.fetchall():
        road_bearing = r["facade_bearing_deg"]
        ring = extract_primary_ring_abs(r["footprint_geojson"]) if r.get("footprint_geojson") else []
        if ring:
            cx, cy = polygon_centroid_abs(ring)
            x_abs = cx if cx is not None else r["x"]
            y_abs = cy if cy is not None else r["y"]
            matched_footprints += 1
        else:
            x_abs, y_abs = r["x"], r["y"]

        lx, ly = local(x_abs, y_abs)
        bearing = derive_facade_bearing_from_ring(ring, road_bearing=road_bearing)
        # Convert bearing (0=north, clockwise) to Blender rotation.
        # Blender's default building faces -Y, so rotation = bearing - 180.
        blender_rot = (bearing - 180) % 360
        mass_h = r.get("massing_height_m")
        if mass_h is not None:
            matched_massing += 1
        bldg_positions[r["address"]] = {
            "x": lx, "y": ly,
            "bearing_deg": round(bearing, 1),
            "rotation_deg": round(blender_rot, 1),
            "massing_height_m": round(float(mass_h), 2) if mass_h is not None else None,
            "source": "assessment_to_footprint_massing" if ring else "assessment_point_fallback",
        }
    cur.close()
    data["building_positions"] = bldg_positions
    print(f"    {len(bldg_positions)} building positions")
    print(f"      footprint matches: {matched_footprints}")
    print(f"      massing matches: {matched_massing}")

    return data


# ---------------------------------------------------------------------------
# Write Blender script
# ---------------------------------------------------------------------------

def write_blender_script(data, output_path, include_massing=True):
    """Write a self-contained Blender Python script with embedded GIS data."""

    # Save heavy GIS data as a sibling JSON file when script is already in outputs/,
    # otherwise keep historical behavior of placing JSON in ./outputs/.
    if output_path.parent.name.lower() == "outputs":
        json_path = output_path.with_suffix(".json")
        data_path_expr = f'SCRIPT_DIR / "{output_path.stem}.json"'
    else:
        json_path = output_path.parent / "outputs" / (output_path.stem + ".json")
        data_path_expr = f'SCRIPT_DIR / "outputs" / "{output_path.stem}.json"'

    json_path.parent.mkdir(parents=True, exist_ok=True)
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    json_size = json_path.stat().st_size / (1024 * 1024)
    print(f"  GIS data: {json_path.name} ({json_size:.1f} MB)")

    script = f'''#!/usr/bin/env python3
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

ORIGIN_X = {ORIGIN_X}
ORIGIN_Y = {ORIGIN_Y}

# Load GIS data from JSON
SCRIPT_DIR = Path(os.path.dirname(os.path.abspath(__file__))) if "__file__" in dir() else Path("C:/Users/liam1/blender_buildings")
DATA_PATH = {data_path_expr}
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

        mesh = bpy.data.meshes.new(f"FP_{{fp['gid']}}")
        bm.to_mesh(mesh)
        bm.free()

        obj = bpy.data.objects.new(f"FP_{{fp['gid']}}", mesh)
        obj.data.materials.append(mat)
        col.objects.link(obj)

    print(f"  Footprints: {{len(GIS.get('footprints', []))}}")


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

    print(f"  Massing: {{len(GIS.get('massing', []))}}")


# ---------------------------------------------------------------------------
# Roads, sidewalks, alleys (curves)
# ---------------------------------------------------------------------------

def create_curves(key, collection_name, mat_hex, bevel_depth):
    col = clear_collection(collection_name)
    mat = get_material(f"{{collection_name}}_Mat", mat_hex)

    items = GIS.get(key, [])
    for i, item in enumerate(items):
        coords = item.get("coords", [])
        if len(coords) < 2:
            continue

        curve = bpy.data.curves.new(f"{{key}}_{{i}}", type='CURVE')
        curve.dimensions = '3D'
        spline = curve.splines.new('POLY')
        spline.points.add(len(coords) - 1)
        for j, (x, y) in enumerate(coords):
            spline.points[j].co = (x, y, 0.01, 1)

        curve.bevel_depth = bevel_depth
        curve.bevel_resolution = 0

        obj = bpy.data.objects.new(f"{{key}}_{{i}}", curve)
        obj.data.materials.append(mat)
        col.objects.link(obj)

    print(f"  {{collection_name}}: {{len(items)}}")


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

FIELD_CONFIG = {{
    "trees":        {{"hex": "#2A5A2A", "r": 1.5, "h": 6.0, "shape": "sphere"}},
    "poles":        {{"hex": "#5A5A5A", "r": 0.08, "h": 5.0, "shape": "cylinder"}},
    "signs":        {{"hex": "#CC4444", "r": 0.15, "h": 2.5, "shape": "cylinder"}},
    "bike_racks":   {{"hex": "#4488CC", "r": 0.4, "h": 0.8, "shape": "cube"}},
    "terraces":     {{"hex": "#AA8855", "r": 2.0, "h": 0.1, "shape": "cube"}},
    "parking":      {{"hex": "#333333", "r": 4.0, "h": 0.05, "shape": "cube"}},
    "public_art":   {{"hex": "#CC44CC", "r": 0.5, "h": 2.0, "shape": "cube"}},
    "bus_shelters":  {{"hex": "#44AAAA", "r": 1.5, "h": 2.5, "shape": "cube"}},
    "parks":        {{"hex": "#44AA44", "r": 5.0, "h": 0.05, "shape": "cube"}},
}}


def create_field_features():
    col = clear_collection("GIS_FieldSurvey")
    total = 0

    for layer, points in GIS.get("field", {{}}).items():
        cfg = FIELD_CONFIG.get(layer, {{"hex": "#888888", "r": 0.5, "h": 1.0, "shape": "cube"}})
        mat = get_material(f"Field_{{layer}}", cfg["hex"])

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
            obj.name = f"{{layer}}_{{i+1}}"
            obj.data.materials.append(mat)
            for c in obj.users_collection:
                c.objects.unlink(obj)
            col.objects.link(obj)
            total += 1

    print(f"  Field survey: {{total}} features")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("=== Kensington Market GIS Site Model ===")
    print(f"Origin: {{ORIGIN_X}}, {{ORIGIN_Y}} (SRID 2952)")
    print()

    create_study_area()
    create_footprints()
    {"create_massing()" if include_massing else "# create_massing()  # skipped (use --massing-only to include)"}
    create_curves("roads", "GIS_Roads", "#4A4A4A", 3.0)
    create_curves("sidewalks", "GIS_Sidewalks", "#9A9A8A", 1.5)
    create_curves("alleys", "GIS_Alleys", "#6A6A6A", 1.5)
    create_field_features()

    # Save building position lookup for generate_building.py
    print(f"\\n  Building positions: {{len(GIS.get('building_positions', {{}}))}}")
    print("\\nDone — GIS site model loaded.")
    print("Collections: GIS_StudyArea, GIS_Footprints, GIS_Massing, GIS_Roads, GIS_Sidewalks, GIS_Alleys, GIS_FieldSurvey")

main()
'''

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(script)

    script_size = output_path.stat().st_size / 1024
    print(f"  Blender script: {output_path.name} ({script_size:.0f} KB)")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Export GIS site model for Blender")
    parser.add_argument("--output", default="gis_scene.py", help="Output Blender script")
    parser.add_argument("--no-massing", action="store_true", help="Skip 3D massing (faster)")
    args = parser.parse_args()

    include_massing = not args.no_massing
    conn = psycopg2.connect(**DB_CONFIG)

    print("=== GIS Scene Export ===")
    print(f"Origin: {ORIGIN_X}, {ORIGIN_Y} (SRID 2952)")
    print()

    data = build_scene_data(conn, include_massing=include_massing)
    conn.close()

    output_path = Path(args.output)
    if not output_path.is_absolute():
        output_path = OUTPUT_DIR / output_path
    write_blender_script(data, output_path, include_massing=include_massing)

    # Also save building position lookup
    lookup_path = OUTPUT_DIR / "params" / "_site_coordinates.json"
    with open(lookup_path, "w", encoding="utf-8") as f:
        json.dump(data["building_positions"], f, indent=2, ensure_ascii=False)
    print(f"  Coordinate lookup: {lookup_path.name} ({len(data['building_positions'])} buildings)")

    print(f"\nRun in Blender:")
    print(f"  blender --background --python {args.output}")


if __name__ == "__main__":
    main()
