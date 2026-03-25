#!/usr/bin/env python3
"""Geocode buildings from GIS exports: footprints (addresses) + massing (heights).

Reads two GeoJSON files exported from QGIS:
- buildings_footprints.geojson: 2D polygons with address_fu field
- 3dmassing.geojson: 3D polygons with AVG_HEIGHT field

Spatial joins massing heights onto footprints by polygon overlap,
then matches our 92 param files by address. Outputs geocode.json.
"""

import json
import math
import re
from pathlib import Path

GIS_DIR = Path("F:/GEOJSON")
PARAMS_DIR = Path(__file__).parent.parent / "params"
OUTPUT = Path(__file__).parent.parent / "geocode.json"


def polygon_coords(geom):
    """Extract first ring coordinates from GeoJSON geometry."""
    coords = geom.get("coordinates", [])
    if geom["type"] == "MultiPolygon":
        if coords and coords[0]:
            return [(p[0], p[1]) for p in coords[0][0]]
    elif geom["type"] == "Polygon":
        if coords:
            return [(p[0], p[1]) for p in coords[0]]
    return []


def centroid(pts):
    """Compute centroid of polygon ring."""
    if not pts:
        return None, None
    # Remove closing point
    if len(pts) > 1 and pts[0] == pts[-1]:
        pts = pts[:-1]
    if not pts:
        return None, None
    cx = sum(p[0] for p in pts) / len(pts)
    cy = sum(p[1] for p in pts) / len(pts)
    return cx, cy


def polygon_area(pts):
    """Shoelace formula for polygon area."""
    n = len(pts)
    if n < 3:
        return 0.0
    area = 0.0
    for i in range(n):
        j = (i + 1) % n
        area += pts[i][0] * pts[j][1]
        area -= pts[j][0] * pts[i][1]
    return abs(area) / 2.0


def bbox(pts):
    """Bounding box (min_x, min_y, max_x, max_y)."""
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def bbox_overlap(b1, b2):
    """Check if two bounding boxes overlap."""
    return b1[0] <= b2[2] and b1[2] >= b2[0] and b1[1] <= b2[3] and b1[3] >= b2[1]


def point_in_polygon(px, py, polygon):
    """Ray casting."""
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


def facade_angle(pts):
    """Get rotation angle from polygon's longest edge facing the street.

    Returns degrees from Y-axis (Blender's front = +Y).
    For Toronto row houses, the facade is typically the shortest dimension
    (narrow lot facing street), so we use the longest edge as the party wall
    and rotate 90 degrees from that.
    """
    if len(pts) < 3:
        return 0.0
    if pts[0] == pts[-1]:
        pts = pts[:-1]

    # Find the two longest edges
    edges = []
    for i in range(len(pts)):
        j = (i + 1) % len(pts)
        dx = pts[j][0] - pts[i][0]
        dy = pts[j][1] - pts[i][1]
        length = math.sqrt(dx * dx + dy * dy)
        angle = math.atan2(dy, dx)
        edges.append((length, angle))

    edges.sort(key=lambda e: e[0], reverse=True)
    # Longest edge = likely the side wall / depth direction
    # Facade faces perpendicular to depth
    depth_angle = edges[0][1]
    # Facade normal = depth_angle + 90 degrees
    facade_normal = depth_angle + math.pi / 2

    return math.degrees(facade_normal)


def normalize_address(addr):
    """Normalize address for matching."""
    if not addr:
        return ""
    a = addr.upper().strip()
    a = a.split(",")[0]
    a = a.replace(" STREET", " ST").replace(" AVENUE", " AVE")
    a = a.replace(" SQUARE", " SQ").replace(" PLACE", " PL")
    a = a.replace(" TERRACE", " TER").replace(" TERR", " TER")
    a = a.replace(" WEST", " W").replace(" EAST", " E")
    # Remove unit/suite suffixes like "R", "A", "B" after number
    a = re.sub(r"^(\d+)[A-Z]\s", r"\1 ", a)
    a = re.sub(r"\s+", " ", a)
    return a


def main():
    # Load footprints
    print("Loading footprints...")
    with open(GIS_DIR / "buildings_footprints.geojson") as f:
        fp_data = json.load(f)
    footprints = fp_data["features"]
    print(f"  {len(footprints)} footprints")

    # Load massing
    print("Loading 3D massing...")
    with open(GIS_DIR / "3dmassing.geojson") as f:
        ms_data = json.load(f)
    massings = ms_data["features"]
    print(f"  {len(massings)} massing blocks")

    # Pre-compute massing centroids and bboxes for spatial join
    ms_entries = []
    for feat in massings:
        pts = polygon_coords(feat["geometry"])
        if not pts:
            continue
        cx, cy = centroid(pts)
        bb = bbox(pts)
        h = feat["properties"].get("AVG_HEIGHT") or 0
        ms_entries.append((cx, cy, bb, pts, h, feat["properties"]))

    # Spatial join: for each footprint, find overlapping massing block
    print("Spatial joining massing heights onto footprints...")
    fp_entries = []
    height_matched = 0
    for feat in footprints:
        pts = polygon_coords(feat["geometry"])
        if not pts:
            continue
        cx, cy = centroid(pts)
        bb = bbox(pts)
        addr = feat["properties"].get("address_fu", "")
        props = feat["properties"]

        # Find best overlapping massing block
        best_height = None
        best_dist = 999999
        for mcx, mcy, mbb, mpts, mh, mprops in ms_entries:
            if not bbox_overlap(bb, mbb):
                continue
            # Check if footprint centroid is inside massing polygon
            if point_in_polygon(cx, cy, mpts):
                best_height = mh
                break
            # Otherwise check distance
            dist = math.sqrt((cx - mcx) ** 2 + (cy - mcy) ** 2)
            if dist < best_dist and dist < 15:
                best_dist = dist
                best_height = mh

        if best_height:
            height_matched += 1

        fp_entries.append({
            "address": addr,
            "cx": cx,
            "cy": cy,
            "pts": pts,
            "height": best_height,
            "props": props,
        })

    print(f"  {height_matched}/{len(fp_entries)} footprints matched to massing heights")

    # Build address lookup from footprints
    addr_lookup = {}
    for entry in fp_entries:
        norm = normalize_address(entry["address"])
        if norm:
            addr_lookup[norm] = entry

    # Load param files and match
    print("Matching param files to footprints...")
    files = sorted(PARAMS_DIR.glob("*.json"))
    files = [f for f in files if not f.name.startswith("_")]

    # Compute scene origin from all footprint centroids
    all_cx = [e["cx"] for e in fp_entries if e["cx"]]
    all_cy = [e["cy"] for e in fp_entries if e["cy"]]
    origin_x = (min(all_cx) + max(all_cx)) / 2
    origin_y = (min(all_cy) + max(all_cy)) / 2
    print(f"  Scene origin: ({origin_x:.1f}, {origin_y:.1f})")

    results = {}
    matched = 0

    for f in files:
        with open(f) as fp:
            params = json.load(fp)

        addr = params.get("_meta", {}).get("address", "")
        norm = normalize_address(addr)

        # Try exact match
        entry = addr_lookup.get(norm)

        # Try without city suffix
        if not entry:
            for key, val in addr_lookup.items():
                if key.startswith(norm.split(",")[0].strip()):
                    entry = val
                    break

        # Try fuzzy: match number + first word of street
        if not entry:
            parts = norm.split()
            if len(parts) >= 2:
                num = parts[0]
                street_start = parts[1][:5]
                for key, val in addr_lookup.items():
                    kparts = key.split()
                    if len(kparts) >= 2 and kparts[0] == num and kparts[1][:5] == street_start:
                        entry = val
                        break

        # Nearest neighbour on same street: find closest address number
        if not entry:
            parts = norm.split()
            if len(parts) >= 2 and parts[0].isdigit():
                target_num = int(parts[0])
                street_name = " ".join(parts[1:])
                best_entry = None
                best_diff = 9999
                for key, val in addr_lookup.items():
                    kparts = key.split()
                    if len(kparts) >= 2 and kparts[0].isdigit():
                        k_street = " ".join(kparts[1:])
                        if k_street == street_name:
                            diff = abs(int(kparts[0]) - target_num)
                            if diff < best_diff:
                                best_diff = diff
                                best_entry = val
                if best_entry and best_diff <= 10:
                    # Interpolate position: offset from nearest by ~3m per address number
                    entry = best_entry.copy()
                    nearest_parts = normalize_address(best_entry["address"]).split()
                    if nearest_parts[0].isdigit():
                        nearest_num = int(nearest_parts[0])
                        num_diff = target_num - nearest_num
                        # Estimate direction from street geometry
                        pts = best_entry["pts"]
                        if len(pts) >= 2:
                            # Use longest edge direction as street direction
                            max_len = 0
                            dx, dy = 0, 3.0
                            for i in range(len(pts) - 1):
                                ex = pts[i+1][0] - pts[i][0]
                                ey = pts[i+1][1] - pts[i][1]
                                el = math.sqrt(ex*ex + ey*ey)
                                if el > max_len:
                                    max_len = el
                                    dx, dy = ex / el * 3.0, ey / el * 3.0
                        entry["cx"] = best_entry["cx"] + num_diff * dx
                        entry["cy"] = best_entry["cy"] + num_diff * dy
                        entry["address"] = addr
                        source_note = "nearest_neighbour"

        if not entry:
            print(f"  [MISS] {f.name}: {norm}")
            continue

        matched += 1
        bx = entry["cx"] - origin_x
        by = entry["cy"] - origin_y
        rot = facade_angle(entry["pts"])

        results[f.stem] = {
            "address": addr,
            "footprint_address": entry["address"],
            "epsg2952_x": round(entry["cx"], 2),
            "epsg2952_y": round(entry["cy"], 2),
            "blender_x": round(bx, 2),
            "blender_y": round(by, 2),
            "rotation_deg": round(rot, 1),
            "massing_height_m": round(entry["height"], 1) if entry["height"] else None,
            "source": "gis_footprint",
            "has_footprint": True,
        }

    print(f"\nMatched: {matched}/{len(files)}")
    print(f"With massing height: {sum(1 for r in results.values() if r['massing_height_m'])}")
    print(f"Scene origin EPSG:2952: ({origin_x:.2f}, {origin_y:.2f})")

    # Save origin for Blender
    output = {
        "_origin": {
            "epsg2952_x": round(origin_x, 2),
            "epsg2952_y": round(origin_y, 2),
            "crs": "EPSG:2952",
        },
        "_footprints_file": str(GIS_DIR / "buildings_footprints.geojson"),
        "_massing_file": str(GIS_DIR / "3dmassing.geojson"),
    }
    output.update(results)

    with open(OUTPUT, "w") as fp:
        json.dump(output, fp, indent=2)
        fp.write("\n")

    print(f"Wrote: {OUTPUT}")


if __name__ == "__main__":
    main()
