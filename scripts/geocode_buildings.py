#!/usr/bin/env python3
"""Geocode buildings using heritage register, OSM footprints, and 3D massing.

Matches building params to real-world coordinates (EPSG:2952) and extracts
footprint orientation from polygon geometry. Outputs geocode.json with
position and rotation for each building.
"""

import json
import math
import re
import sqlite3
from pathlib import Path

DB_PATH = "C:/GDB/02_WORKING/04_SQL_DATABASE/KENSINGTON_PROD.sqlite"
PARAMS_DIR = Path(__file__).parent.parent / "params"
OUTPUT = Path(__file__).parent.parent / "geocode.json"

# Kensington Market approximate center in EPSG:2952
# Used as origin for Blender coordinates (offset so buildings cluster near 0,0)
ORIGIN_X = 312830.0
ORIGIN_Y = 4834650.0


def normalize_address(addr):
    """Normalize address for matching."""
    a = addr.upper().strip()
    a = a.split(",")[0]  # drop city
    a = a.replace(" STREET", " ST").replace(" AVENUE", " AVE")
    a = a.replace(" SQUARE", " SQ").replace(" PLACE", " PL")
    a = a.replace(" TERRACE", " TER").replace(" TERR", " TER")
    a = re.sub(r"\s+", " ", a)
    return a


def parse_wkt_polygon(wkt):
    """Extract coordinate pairs from WKT POLYGON or POLYGON Z or MULTIPOLYGON."""
    # Strip to first ring
    # Remove MULTIPOLYGON/POLYGON Z prefix, get the innermost coordinate list
    cleaned = wkt.replace("MULTIPOLYGON", "").replace("POLYGON Z", "").replace("POLYGON", "")
    # Find first coordinate ring between innermost parens
    cleaned = cleaned.strip()
    # Remove all parens and split on comma
    depth = 0
    start = None
    for i, ch in enumerate(cleaned):
        if ch == "(":
            depth += 1
            if depth == 1 or (start is None and depth > 0):
                start = i + 1
        elif ch == ")":
            if start is not None:
                coords_str = cleaned[start:i]
                break
            depth -= 1
    else:
        return []

    points = []
    for pt in coords_str.split(","):
        parts = pt.strip().split()
        if len(parts) >= 2:
            try:
                points.append((float(parts[0]), float(parts[1])))
            except ValueError:
                continue
    return points


def polygon_centroid(points):
    """Compute centroid of polygon."""
    if not points:
        return None, None
    # Remove closing point if same as first
    if len(points) > 1 and points[0] == points[-1]:
        points = points[:-1]
    cx = sum(p[0] for p in points) / len(points)
    cy = sum(p[1] for p in points) / len(points)
    return cx, cy


def polygon_orientation(points):
    """Get facade orientation angle (degrees) from polygon's longest edge.

    Returns rotation in degrees from Y-axis (Blender's front direction).
    """
    if len(points) < 3:
        return 0.0

    # Remove closing point
    if points[0] == points[-1]:
        points = points[:-1]

    # Find longest edge
    max_len = 0
    best_angle = 0
    for i in range(len(points)):
        j = (i + 1) % len(points)
        dx = points[j][0] - points[i][0]
        dy = points[j][1] - points[i][1]
        length = math.sqrt(dx * dx + dy * dy)
        if length > max_len:
            max_len = length
            # Angle from east (X-axis), convert to rotation from north (Y-axis)
            best_angle = math.atan2(dy, dx)

    # Convert: facade faces perpendicular to longest edge
    # In Blender, 0 deg = facing +Y. Streets in Kensington generally run N-S or E-W
    deg = math.degrees(best_angle)
    return deg


def build_heritage_lookup(conn):
    """Build address -> (X, Y) from heritage register."""
    rows = conn.execute(
        "SELECT X, Y, Address FROM heritage_register_address_points_wgs84_mtm10"
    ).fetchall()
    lookup = {}
    for x, y, addr in rows:
        if addr and x and y:
            key = normalize_address(addr)
            lookup[key] = (x, y)
    return lookup


def build_street_anchors(conn):
    """Build per-street interpolation anchors from heritage register + OSM.

    Only uses points within 500m of Kensington Market center to avoid
    interpolating with distant same-named streets.
    """
    anchors = {}  # street_name -> [(number, x, y), ...]

    # Heritage register — filter to Kensington area only
    rows = conn.execute(
        "SELECT X, Y, Address FROM heritage_register_address_points_wgs84_mtm10"
    ).fetchall()
    for x, y, addr in rows:
        if not addr or not x or not y:
            continue
        # Skip points far from Kensington Market
        if abs(x - ORIGIN_X) > 500 or abs(y - ORIGIN_Y) > 500:
            continue
        norm = normalize_address(addr)
        parts = norm.split()
        if len(parts) < 2:
            continue
        m = re.match(r"(\d+)", parts[0])
        if not m:
            continue
        num = int(m.group(1))
        street = " ".join(parts[1:])
        if street not in anchors:
            anchors[street] = []
        anchors[street].append((num, x, y))

    # OSM buildings — also filter to local area
    osm_rows = conn.execute(
        "SELECT addr_house, addr_stree, geometry_wkt FROM building_mtm10 "
        "WHERE addr_house IS NOT NULL AND addr_stree IS NOT NULL"
    ).fetchall()
    for house, stree, wkt in osm_rows:
        m = re.match(r"(\d+)", str(house))
        if not m:
            continue
        num = int(m.group(1))
        street = normalize_address(f"0 {stree}").split(None, 1)[1] if stree else None
        if not street:
            continue
        points = parse_wkt_polygon(wkt)
        cx, cy = polygon_centroid(points)
        if cx and cy:
            if abs(cx - ORIGIN_X) > 500 or abs(cy - ORIGIN_Y) > 500:
                continue
            if street not in anchors:
                anchors[street] = []
            anchors[street].append((num, cx, cy))

    # Sort and deduplicate
    for street in anchors:
        anchors[street].sort(key=lambda p: p[0])
        seen = set()
        deduped = []
        for num, x, y in anchors[street]:
            if num not in seen:
                seen.add(num)
                deduped.append((num, x, y))
        anchors[street] = deduped

    return anchors


def interpolate_address(number, street, anchors):
    """Interpolate position along street from anchor points.

    Uses linear interpolation between bracketing anchors, and clamped
    extrapolation (max 3m per address number) to avoid wild overshoots
    when anchor points are far from the target address.
    """
    if street not in anchors or len(anchors[street]) < 1:
        return None, None

    pts = anchors[street]

    # Exact match
    for num, x, y in pts:
        if num == number:
            return x, y

    # Compute street direction vector from all anchors
    if len(pts) >= 2:
        # Use overall street direction
        dx = pts[-1][1] - pts[0][1]
        dy = pts[-1][2] - pts[0][2]
        dn = pts[-1][0] - pts[0][0]
        if dn > 0:
            # Per-address-number displacement
            dx_per = dx / dn
            dy_per = dy / dn
            # Clamp to max ~3m per number (typical Toronto lot = 6m, even/odd = 2 numbers per lot)
            dist_per = math.sqrt(dx_per**2 + dy_per**2)
            if dist_per > 3.0:
                scale = 3.0 / dist_per
                dx_per *= scale
                dy_per *= scale
        else:
            dx_per, dy_per = 0.0, 3.0
    else:
        dx_per, dy_per = 0.0, 3.0

    if len(pts) == 1:
        num0, x0, y0 = pts[0]
        diff = number - num0
        return x0 + diff * dx_per, y0 + diff * dy_per

    # Find bracketing anchors — interpolate normally
    for i in range(len(pts) - 1):
        n0, x0, y0 = pts[i]
        n1, x1, y1 = pts[i + 1]
        if n0 <= number <= n1:
            if n1 == n0:
                return x0, y0
            t = (number - n0) / (n1 - n0)
            return x0 + t * (x1 - x0), y0 + t * (y1 - y0)

    # Extrapolate using clamped per-number displacement
    if number < pts[0][0]:
        n0, x0, y0 = pts[0]
        diff = number - n0
        return x0 + diff * dx_per, y0 + diff * dy_per
    else:
        n0, x0, y0 = pts[-1]
        diff = number - n0
        return x0 + diff * dx_per, y0 + diff * dy_per


def build_osm_lookup(conn):
    """Build address -> (centroid_x, centroid_y, polygon_points) from OSM buildings."""
    rows = conn.execute(
        "SELECT addr_house, addr_stree, geometry_wkt FROM building_mtm10 "
        "WHERE addr_house IS NOT NULL AND addr_stree IS NOT NULL"
    ).fetchall()
    lookup = {}
    for house, street, wkt in rows:
        if house and street and wkt:
            addr = normalize_address(f"{house} {street}")
            points = parse_wkt_polygon(wkt)
            cx, cy = polygon_centroid(points)
            if cx and cy:
                lookup[addr] = (cx, cy, points)
    return lookup


def build_massing_index(conn):
    """Build spatial index from 3D massing for point-in-polygon lookup."""
    rows = conn.execute(
        'SELECT AVG_HEIGHT, geometry_wkt FROM "3dmassingshapefile_2025_wgs84_mtm10" '
        'WHERE AVG_HEIGHT IS NOT NULL AND AVG_HEIGHT > 0'
    ).fetchall()
    entries = []
    for height, wkt in rows:
        points = parse_wkt_polygon(wkt)
        if points:
            cx, cy = polygon_centroid(points)
            if cx and cy:
                entries.append((cx, cy, height, points))
    return entries


def point_in_polygon(px, py, polygon):
    """Ray casting point-in-polygon test."""
    n = len(polygon)
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        if ((yi > py) != (yj > py)) and (px < (xj - xi) * (py - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


def find_massing_height(x, y, massing_index):
    """Find building height from 3D massing at given point."""
    # First try within 5m radius for centroid match
    best_dist = 50.0
    best_height = None
    for cx, cy, h, poly in massing_index:
        dist = math.sqrt((cx - x) ** 2 + (cy - y) ** 2)
        if dist < best_dist:
            if dist < 5.0 or point_in_polygon(x, y, poly):
                best_dist = dist
                best_height = h
    return best_height


def main():
    conn = sqlite3.connect(DB_PATH)

    print("Loading heritage register...")
    heritage = build_heritage_lookup(conn)
    print(f"  {len(heritage)} heritage addresses")

    print("Loading OSM building footprints...")
    osm = build_osm_lookup(conn)
    print(f"  {len(osm)} addressed buildings")

    print("Building street interpolation anchors...")
    anchors = build_street_anchors(conn)
    print(f"  {len(anchors)} streets with anchors")

    print("Loading 3D massing (this may take a moment)...")
    # Only load massing near Kensington (within ~500m of center)
    rows = conn.execute(
        'SELECT AVG_HEIGHT, geometry_wkt FROM "3dmassingshapefile_2025_wgs84_mtm10" '
        'WHERE AVG_HEIGHT IS NOT NULL AND AVG_HEIGHT > 0'
    ).fetchall()

    massing = []
    for height, wkt in rows:
        points = parse_wkt_polygon(wkt)
        if points:
            cx, cy = polygon_centroid(points)
            if cx and cy and abs(cx - ORIGIN_X) < 500 and abs(cy - ORIGIN_Y) < 500:
                massing.append((cx, cy, height, points))
    print(f"  {len(massing)} massing polygons near Kensington")

    conn.close()

    # Process each building
    files = sorted(PARAMS_DIR.glob("*.json"))
    files = [f for f in files if not f.name.startswith("_")]

    results = {}
    matched = 0
    footprint_matched = 0

    for f in files:
        with open(f) as fp:
            params = json.load(fp)

        addr = params.get("_meta", {}).get("address", "")
        norm = normalize_address(addr)

        x, y = None, None
        rotation = 0.0
        footprint = None
        source = None

        # 1. Try heritage register (most accurate point)
        if norm in heritage:
            x, y = heritage[norm]
            source = "heritage_register"

        # 2. Try OSM footprint (has polygon for orientation)
        if norm in osm:
            ox, oy, points = osm[norm]
            if x is None:
                x, y = ox, oy
                source = "osm_footprint"
            footprint = points
            rotation = polygon_orientation(points)
            footprint_matched += 1

        # 3. Fuzzy match: try without street type
        if x is None:
            parts = norm.split()
            if len(parts) >= 2:
                number = parts[0]
                street_word = parts[1][:5]  # first 5 chars of street name
                for key, val in heritage.items():
                    kparts = key.split()
                    if len(kparts) >= 2 and kparts[0] == number and kparts[1][:5] == street_word:
                        x, y = val
                        source = "heritage_fuzzy"
                        break

        # 4. Street interpolation fallback
        if x is None:
            parts = norm.split()
            if len(parts) >= 2:
                m = re.match(r"(\d+)", parts[0])
                if m:
                    num = int(m.group(1))
                    street = " ".join(parts[1:])
                    ix, iy = interpolate_address(num, street, anchors)
                    if ix is not None:
                        x, y = ix, iy
                        source = "interpolated"

        # 5. Manual street baselines — OVERRIDE interpolation for streets
        #    with bad/distant anchors. Based on known Kensington Market geometry.
        parts = norm.split()
        if len(parts) >= 2:
            m_num = re.match(r"(\d+)", parts[0])
            street_name = " ".join(parts[1:])
            # Street baselines: (start_x, start_y, dx_per_num, dy_per_num, start_num)
            # Kensington Ave: even side X~312815, odd side X~312865, Y increases N
            # Parallel streets offset W: Lippincott ~75m, then Augusta ~150m
            street_baselines = {
                "LIPPINCOTT ST": (312755, 4834575, -0.8, 2.8, 9),
                "LEONARD AVE":  (312675, 4834555, -0.5, 2.5, 1),
            }
            if m_num and street_name in street_baselines:
                num = int(m_num.group(1))
                bx, by, dx, dy, sn = street_baselines[street_name]
                x = bx + (num - sn) * dx
                y = by + (num - sn) * dy
                source = "baseline"
                footprint = None
                rotation = 0.0

        # Specific manual entries
        manual = {
            "1A LEONARD AVE": (312675.0, 4834555.0),
        }
        if x is None and norm in manual:
            x, y = manual[norm]
            source = "manual"

        if x is None:
            print(f"  [MISS] {f.name}: {norm}")
            continue

        matched += 1

        # Get massing height
        massing_height = find_massing_height(x, y, massing)

        # Convert to Blender coordinates (relative to origin)
        bx = x - ORIGIN_X
        by = y - ORIGIN_Y

        results[f.stem] = {
            "address": addr,
            "epsg2952_x": round(x, 2),
            "epsg2952_y": round(y, 2),
            "blender_x": round(bx, 2),
            "blender_y": round(by, 2),
            "rotation_deg": round(rotation, 1),
            "massing_height_m": round(massing_height, 1) if massing_height else None,
            "source": source,
            "has_footprint": footprint is not None,
        }

    print(f"\nMatched: {matched}/{len(files)}")
    print(f"With footprint orientation: {footprint_matched}")
    print(f"With massing height: {sum(1 for r in results.values() if r['massing_height_m'])}")

    with open(OUTPUT, "w") as fp:
        json.dump(results, fp, indent=2)
        fp.write("\n")

    print(f"Wrote: {OUTPUT}")


if __name__ == "__main__":
    main()
