#!/usr/bin/env python3
"""Stage 8c: Export buildings as CityGML LOD2 (extruded footprints with heights).

Reads params to generate CityGML 2.0 XML with bldg:Building elements.
Each building gets measuredHeight, lod2Solid (extruded box from dimensions).

Usage:
    python scripts/export/export_citygml.py --lod 2 --output citygml/kensington_lod2.gml
    python scripts/export/export_citygml.py --lod 2 --output citygml/kensington_lod2.gml --limit 10
"""
import argparse, json, logging
from datetime import datetime
from pathlib import Path
from xml.etree.ElementTree import Element, SubElement, ElementTree, indent

logger = logging.getLogger(__name__)
REPO = Path(__file__).parent.parent.parent

NS = {
    "core": "http://www.opengis.net/citygml/2.0",
    "bldg": "http://www.opengis.net/citygml/building/2.0",
    "gml": "http://www.opengis.net/gml",
    "xsi": "http://www.w3.org/2001/XMLSchema-instance",
}

ORIGIN_X = 312672.94
ORIGIN_Y = 4834994.86


def build_citygml(buildings: list[dict], lod: int) -> Element:
    root = Element("core:CityModel")
    for prefix, uri in NS.items():
        root.set(f"xmlns:{prefix}", uri)
    root.set("xsi:schemaLocation",
             "http://www.opengis.net/citygml/2.0 http://schemas.opengis.net/citygml/2.0/cityGMLBase.xsd")

    for b in buildings:
        addr = b.get("building_name", b.get("_meta", {}).get("address", "Unknown"))
        height = b.get("total_height_m", 8.0)
        width = b.get("facade_width_m", 6.0)
        depth = b.get("facade_depth_m", 10.0)
        site = b.get("site", {})
        lon = site.get("lon")
        lat = site.get("lat")

        member = SubElement(root, "core:cityObjectMember")
        bldg = SubElement(member, "bldg:Building")
        bldg.set("gml:id", addr.replace(" ", "_"))

        # Address
        name = SubElement(bldg, "gml:name")
        name.text = addr

        # Measured height
        mh = SubElement(bldg, "bldg:measuredHeight")
        mh.set("uom", "m")
        mh.text = str(round(height, 1))

        # Storeys
        floors = b.get("floors", 2)
        sa = SubElement(bldg, "bldg:storeysAboveGround")
        sa.text = str(floors)

        # Function
        btype = b.get("context", {}).get("building_type", "")
        if btype:
            func = SubElement(bldg, "bldg:function")
            func.text = btype

        # Year
        era = b.get("hcd_data", {}).get("construction_date", "")
        if era:
            yob = SubElement(bldg, "bldg:yearOfConstruction")
            yob.text = era.split("-")[0] if "-" in era else era

        # LOD2 Solid (extruded box)
        if lod >= 2 and lon and lat:
            lod2 = SubElement(bldg, "bldg:lod2Solid")
            solid = SubElement(lod2, "gml:Solid")
            exterior = SubElement(solid, "gml:exterior")
            shell = SubElement(exterior, "gml:CompositeSurface")

            hw = width / 2
            hd = depth / 2
            # 4 corners at ground, 4 at roof (local SRID 2952 coords)
            x = lon if abs(lon) > 1000 else lon * 111320  # rough if WGS84
            y = lat if abs(lat) > 1000 else lat * 110540

            corners_ground = [
                (x - hw, y - hd, 0), (x + hw, y - hd, 0),
                (x + hw, y + hd, 0), (x - hw, y + hd, 0),
            ]
            corners_roof = [(cx, cy, height) for cx, cy, _ in corners_ground]

            # Bottom face
            face = SubElement(shell, "gml:surfaceMember")
            poly = SubElement(face, "gml:Polygon")
            ext = SubElement(poly, "gml:exterior")
            ring = SubElement(ext, "gml:LinearRing")
            pos = SubElement(ring, "gml:posList")
            pos.set("srsDimension", "3")
            coords = " ".join(f"{c[0]} {c[1]} {c[2]}" for c in corners_ground + [corners_ground[0]])
            pos.text = coords

            # Top face
            face = SubElement(shell, "gml:surfaceMember")
            poly = SubElement(face, "gml:Polygon")
            ext = SubElement(poly, "gml:exterior")
            ring = SubElement(ext, "gml:LinearRing")
            pos = SubElement(ring, "gml:posList")
            pos.set("srsDimension", "3")
            coords = " ".join(f"{c[0]} {c[1]} {c[2]}" for c in corners_roof + [corners_roof[0]])
            pos.text = coords

            # 4 wall faces
            for i in range(4):
                j = (i + 1) % 4
                face = SubElement(shell, "gml:surfaceMember")
                poly = SubElement(face, "gml:Polygon")
                ext = SubElement(poly, "gml:exterior")
                ring = SubElement(ext, "gml:LinearRing")
                pos = SubElement(ring, "gml:posList")
                pos.set("srsDimension", "3")
                wall = [corners_ground[i], corners_ground[j], corners_roof[j], corners_roof[i], corners_ground[i]]
                pos.text = " ".join(f"{c[0]} {c[1]} {c[2]}" for c in wall)

    return root


def main():
    parser = argparse.ArgumentParser(description="Export CityGML")
    parser.add_argument("--lod", type=int, default=2, choices=[2, 3])
    parser.add_argument("--output", type=Path, default=REPO / "citygml" / "kensington_lod2.gml")
    parser.add_argument("--params", type=Path, default=REPO / "params")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    buildings = []
    for f in sorted(args.params.glob("*.json")):
        if f.name.startswith("_"): continue
        d = json.load(open(f, encoding="utf-8"))
        if d.get("skipped"): continue
        buildings.append(d)
        if args.limit and len(buildings) >= args.limit: break

    logger.info("Exporting %d buildings as CityGML LOD%d", len(buildings), args.lod)
    root = build_citygml(buildings, args.lod)
    indent(root, space="  ")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    tree = ElementTree(root)
    tree.write(str(args.output), xml_declaration=True, encoding="utf-8")

    size_mb = args.output.stat().st_size / (1024 * 1024)
    logger.info("Saved: %s (%.1f MB, %d buildings)", args.output, size_mb, len(buildings))


if __name__ == "__main__":
    main()
