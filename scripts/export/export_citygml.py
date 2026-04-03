#!/usr/bin/env python3
"""Export building params as CityGML 2.0 XML.

Generates CityGML with bounding-box geometry per building.
LOD2 includes roof shape; LOD3 adds window/door openings.

Usage:
    python scripts/export/export_citygml.py --params params/ --lod 3 --output citygml/kensington_lod3.gml
    python scripts/export/export_citygml.py --params params/ --lod 2 --output citygml/kensington_lod2.gml
"""

from __future__ import annotations

import argparse
import json
import xml.etree.ElementTree as ET
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PARAMS_DIR = REPO_ROOT / "params"
OUTPUT_DIR = REPO_ROOT / "citygml"

# CityGML 2.0 namespaces
NS = {
    "core": "http://www.opengis.net/citygml/2.0",
    "bldg": "http://www.opengis.net/citygml/building/2.0",
    "gml": "http://www.opengis.net/gml",
    "xsi": "http://www.w3.org/2001/XMLSchema-instance",
    "xAL": "urn:oasis:names:tc:ciq:xsdschema:xAL:2.0",
}

SCHEMA_LOCATION = (
    "http://www.opengis.net/citygml/2.0 "
    "http://schemas.opengis.net/citygml/2.0/cityGMLBase.xsd "
    "http://www.opengis.net/citygml/building/2.0 "
    "http://schemas.opengis.net/citygml/building/2.0/building.xsd"
)


def load_params(params_dir):
    """Load all non-skipped building param files."""
    buildings = []
    for f in sorted(params_dir.glob("*.json")):
        if f.name.startswith("_"):
            continue
        try:
            p = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if p.get("skipped"):
            continue
        buildings.append(p)
    return buildings


def _sanitize_id(name):
    """Create a valid GML id from a building name."""
    return name.replace(" ", "_").replace(",", "").replace(".", "")


def _pos_list(coords):
    """Format a list of (x, y, z) tuples as a gml:posList string."""
    return " ".join(f"{c[0]} {c[1]} {c[2]}" for c in coords)


def _add_polygon(parent, coords, gml_id):
    """Add a gml:Polygon with a LinearRing to parent element."""
    poly = ET.SubElement(parent, f"{{{NS['gml']}}}Polygon")
    poly.set(f"{{{NS['gml']}}}id", gml_id)
    exterior = ET.SubElement(poly, f"{{{NS['gml']}}}exterior")
    ring = ET.SubElement(exterior, f"{{{NS['gml']}}}LinearRing")
    pos_list = ET.SubElement(ring, f"{{{NS['gml']}}}posList")
    pos_list.set("srsDimension", "3")
    pos_list.text = _pos_list(coords)


def _box_coords(lon, lat, w, d, h):
    """Compute 8 corner coords for a bounding box centred on lon/lat.

    Returns dict with keys: ground (4 corners), roof (4 corners).
    Coordinates in WGS84 degrees + metres height.
    """
    m_per_deg_lat = 111320.0
    m_per_deg_lon = m_per_deg_lat * 0.7  # cos(~43.65)

    dlon = (w / 2.0) / m_per_deg_lon
    dlat = (d / 2.0) / m_per_deg_lat

    g = [
        (lon - dlon, lat - dlat, 0),
        (lon + dlon, lat - dlat, 0),
        (lon + dlon, lat + dlat, 0),
        (lon - dlon, lat + dlat, 0),
    ]
    r = [(x, y, h) for (x, y, _) in g]
    return {"ground": g, "roof": r}


def _build_lod2_geometry(bldg_elem, bld_id, lon, lat, w, d, h, roof_type, pitch_deg):
    """Add LOD2 solid geometry (box + roof shape)."""
    lod2 = ET.SubElement(bldg_elem, f"{{{NS['bldg']}}}lod2Solid")
    solid = ET.SubElement(lod2, f"{{{NS['gml']}}}Solid")
    solid.set(f"{{{NS['gml']}}}id", f"{bld_id}_solid")
    exterior = ET.SubElement(solid, f"{{{NS['gml']}}}exterior")
    shell = ET.SubElement(exterior, f"{{{NS['gml']}}}CompositeSurface")
    shell.set(f"{{{NS['gml']}}}id", f"{bld_id}_shell")

    box = _box_coords(lon, lat, w, d, h)
    g = box["ground"]
    r = box["roof"]

    # Ground face (reversed winding for outward normal)
    _add_polygon(shell, [g[0], g[3], g[2], g[1], g[0]], f"{bld_id}_ground")

    # Four wall faces
    for i, name in enumerate(["front", "right", "back", "left"]):
        j = (i + 1) % 4
        _add_polygon(shell, [g[i], g[j], r[j], r[i], g[i]], f"{bld_id}_wall_{name}")

    # Roof
    if (roof_type or "").lower() == "gable" and pitch_deg and pitch_deg > 0:
        import math
        ridge_h = h + (w / 2.0) * math.tan(math.radians(pitch_deg))
        m_per_deg_lon = 111320.0 * 0.7
        dlon = (w / 2.0) / m_per_deg_lon

        # Ridge runs along depth (lat axis), centred on lon
        ridge_front = (lon, lat - (d / 2.0) / 111320.0, ridge_h)
        ridge_back = (lon, lat + (d / 2.0) / 111320.0, ridge_h)

        # Two sloped faces
        _add_polygon(shell, [r[0], r[1], ridge_front, r[0]], f"{bld_id}_roof_left")
        _add_polygon(shell, [r[1], r[2], ridge_back, ridge_front, r[1]], f"{bld_id}_roof_slope_r")
        _add_polygon(shell, [r[2], r[3], ridge_back, r[2]], f"{bld_id}_roof_right")
        _add_polygon(shell, [r[3], r[0], ridge_front, ridge_back, r[3]], f"{bld_id}_roof_slope_l")
    else:
        # Flat roof
        _add_polygon(shell, [r[0], r[1], r[2], r[3], r[0]], f"{bld_id}_roof")


def _build_lod3_openings(bldg_elem, bld_id, params, lon, lat, w, d, h):
    """Add LOD3 window and door openings on the front wall."""
    floors = params.get("floors") or 2
    total_h = h
    windows_per_floor = params.get("windows_per_floor") or [2] * floors
    if isinstance(windows_per_floor, int):
        windows_per_floor = [windows_per_floor] * floors
    door_count = params.get("door_count") or 1

    m_per_deg_lon = 111320.0 * 0.7
    m_per_deg_lat = 111320.0
    half_w = w / 2.0
    half_d = d / 2.0

    # Front wall is at lat - half_d/m_per_deg_lat
    front_lat = lat - half_d / m_per_deg_lat

    floor_h = total_h / max(floors, 1)
    win_w = params.get("window_width_m") or 0.9
    win_h = params.get("window_height_m") or 1.2

    opening_idx = 0
    for fi in range(floors):
        n_win = windows_per_floor[fi] if fi < len(windows_per_floor) else 2
        if not n_win:
            continue
        base_z = fi * floor_h + floor_h * 0.3  # sill at 30% of floor
        for wi in range(n_win):
            spacing = w / (n_win + 1)
            cx = -half_w + spacing * (wi + 1)
            cx_lon = lon + cx / m_per_deg_lon

            half_ww = (win_w / 2.0) / m_per_deg_lon
            opening = ET.SubElement(bldg_elem, f"{{{NS['bldg']}}}outerBuildingInstallation")
            inst = ET.SubElement(opening, f"{{{NS['bldg']}}}BuildingInstallation")
            inst.set(f"{{{NS['gml']}}}id", f"{bld_id}_win_{opening_idx}")
            func = ET.SubElement(inst, f"{{{NS['bldg']}}}function")
            func.text = "window"

            lod3 = ET.SubElement(inst, f"{{{NS['bldg']}}}lod3Geometry")
            surf = ET.SubElement(lod3, f"{{{NS['gml']}}}MultiSurface")
            sm = ET.SubElement(surf, f"{{{NS['gml']}}}surfaceMember")
            coords = [
                (cx_lon - half_ww, front_lat, base_z),
                (cx_lon + half_ww, front_lat, base_z),
                (cx_lon + half_ww, front_lat, base_z + win_h),
                (cx_lon - half_ww, front_lat, base_z + win_h),
                (cx_lon - half_ww, front_lat, base_z),
            ]
            _add_polygon(sm, coords, f"{bld_id}_win_{opening_idx}_poly")
            opening_idx += 1

    # Doors on ground floor
    door_w = 1.0
    door_h = 2.2
    for di in range(door_count or 0):
        spacing = w / ((door_count or 1) + 1)
        cx = -half_w + spacing * (di + 1)
        cx_lon = lon + cx / m_per_deg_lon
        half_dw = (door_w / 2.0) / m_per_deg_lon

        opening = ET.SubElement(bldg_elem, f"{{{NS['bldg']}}}outerBuildingInstallation")
        inst = ET.SubElement(opening, f"{{{NS['bldg']}}}BuildingInstallation")
        inst.set(f"{{{NS['gml']}}}id", f"{bld_id}_door_{di}")
        func = ET.SubElement(inst, f"{{{NS['bldg']}}}function")
        func.text = "door"

        lod3 = ET.SubElement(inst, f"{{{NS['bldg']}}}lod3Geometry")
        surf = ET.SubElement(lod3, f"{{{NS['gml']}}}MultiSurface")
        sm = ET.SubElement(surf, f"{{{NS['gml']}}}surfaceMember")
        coords = [
            (cx_lon - half_dw, front_lat, 0),
            (cx_lon + half_dw, front_lat, 0),
            (cx_lon + half_dw, front_lat, door_h),
            (cx_lon - half_dw, front_lat, door_h),
            (cx_lon - half_dw, front_lat, 0),
        ]
        _add_polygon(sm, coords, f"{bld_id}_door_{di}_poly")


def build_citygml(buildings, lod, output_path):
    """Generate CityGML 2.0 XML from building params."""
    # Register namespaces for clean output
    for prefix, uri in NS.items():
        ET.register_namespace(prefix, uri)

    root = ET.Element(f"{{{NS['core']}}}CityModel")
    root.set(f"{{{NS['xsi']}}}schemaLocation", SCHEMA_LOCATION)

    # Envelope (bounding box of all buildings)
    name_elem = ET.SubElement(root, f"{{{NS['gml']}}}name")
    name_elem.text = "Kensington Market Heritage Conservation District"

    exported = 0
    for params in buildings:
        site = params.get("site", {}) if isinstance(params.get("site"), dict) else {}
        lon = site.get("lon")
        lat = site.get("lat")
        if not lon or not lat:
            continue

        address = params.get("building_name", "Unknown")
        bld_id = _sanitize_id(address)
        w = params.get("facade_width_m") or 6.0
        d = params.get("facade_depth_m") or 15.0
        h = params.get("total_height_m") or 7.0
        floors = params.get("floors") or 2
        roof_type = (params.get("roof_type") or "gable")
        roof_pitch = params.get("roof_pitch_deg") or 0
        hcd = params.get("hcd_data", {}) if isinstance(params.get("hcd_data"), dict) else {}

        member = ET.SubElement(root, f"{{{NS['core']}}}cityObjectMember")
        bldg = ET.SubElement(member, f"{{{NS['bldg']}}}Building")
        bldg.set(f"{{{NS['gml']}}}id", bld_id)

        # Address
        addr_elem = ET.SubElement(bldg, f"{{{NS['bldg']}}}address")
        addr_obj = ET.SubElement(addr_elem, f"{{{NS['core']}}}Address")
        xal = ET.SubElement(addr_obj, f"{{{NS['core']}}}xalAddress")
        addr_detail = ET.SubElement(xal, f"{{{NS['xAL']}}}AddressDetails")
        country = ET.SubElement(addr_detail, f"{{{NS['xAL']}}}Country")
        locality = ET.SubElement(country, f"{{{NS['xAL']}}}Locality")
        locality.set("Type", "Town")
        ln = ET.SubElement(locality, f"{{{NS['xAL']}}}LocalityName")
        ln.text = "Toronto"
        thoroughfare = ET.SubElement(locality, f"{{{NS['xAL']}}}Thoroughfare")
        thoroughfare.set("Type", "Street")
        tn = ET.SubElement(thoroughfare, f"{{{NS['xAL']}}}ThoroughfareName")
        tn.text = site.get("street", "")
        tnum = ET.SubElement(thoroughfare, f"{{{NS['xAL']}}}ThoroughfareNumber")
        tnum.text = str(site.get("street_number", ""))

        # Attributes
        storeys = ET.SubElement(bldg, f"{{{NS['bldg']}}}storeysAboveGround")
        storeys.text = str(floors)
        mh = ET.SubElement(bldg, f"{{{NS['bldg']}}}measuredHeight")
        mh.set("uom", "m")
        mh.text = str(round(float(h), 2))
        rt = ET.SubElement(bldg, f"{{{NS['bldg']}}}roofType")
        rt.text = roof_type

        if hcd.get("construction_date"):
            year_elem = ET.SubElement(bldg, f"{{{NS['bldg']}}}yearOfConstruction")
            year_elem.text = str(hcd["construction_date"])

        # LOD2 geometry
        _build_lod2_geometry(bldg, bld_id, lon, lat, w, d, h, roof_type, roof_pitch)

        # LOD3 openings
        if lod >= 3:
            _build_lod3_openings(bldg, bld_id, params, lon, lat, w, d, h)

        exported += 1

    # Write XML
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")
    tree.write(str(output_path), xml_declaration=True, encoding="utf-8")

    return exported


def main():
    parser = argparse.ArgumentParser(description="Export building params as CityGML 2.0.")
    parser.add_argument("--params", type=Path, default=PARAMS_DIR,
                        help="Directory containing building param JSON files")
    parser.add_argument("--lod", type=int, default=3, choices=[2, 3],
                        help="Level of detail: 2 (box+roof) or 3 (add openings)")
    parser.add_argument("--output", type=Path, default=None,
                        help="Output GML file path")
    args = parser.parse_args()

    if args.output is None:
        args.output = OUTPUT_DIR / f"kensington_lod{args.lod}.gml"

    buildings = load_params(args.params)
    if not buildings:
        print(f"No building params found in {args.params}")
        return

    exported = build_citygml(buildings, args.lod, args.output)
    print(f"Exported {exported} buildings as CityGML LOD{args.lod} -> {args.output}")


if __name__ == "__main__":
    main()
