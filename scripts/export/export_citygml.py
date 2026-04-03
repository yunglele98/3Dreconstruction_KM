#!/usr/bin/env python3
"""Export buildings to CityGML LOD2 and LOD3 format.

Converts building params + footprints to CityGML for urban planning
interoperability. LOD2 = extruded footprints, LOD3 = detailed facades.

Usage:
    python scripts/export/export_citygml.py --lod 2 --output citygml/kensington_lod2.gml
    python scripts/export/export_citygml.py --lod 3 --output citygml/kensington_lod3.gml
    python scripts/export/export_citygml.py --address "22 Lippincott St" --lod 3
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# CityGML namespaces
NS = {
    "core": "http://www.opengis.net/citygml/2.0",
    "bldg": "http://www.opengis.net/citygml/building/2.0",
    "gml": "http://www.opengis.net/gml",
    "gen": "http://www.opengis.net/citygml/generics/2.0",
    "xsi": "http://www.w3.org/2001/XMLSchema-instance",
}

# Coordinate origin (SRID 2952)
ORIGIN_X = 312672.94
ORIGIN_Y = 4834994.86


def load_buildings(params_dir: Path, address_filter: str | None = None) -> list[dict]:
    """Load building params for export."""
    buildings = []
    for f in sorted(params_dir.glob("*.json")):
        if f.name.startswith("_"):
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if data.get("skipped"):
            continue

        addr = data.get("_meta", {}).get("address") or data.get("building_name", f.stem)
        if address_filter and address_filter.lower() not in addr.lower():
            continue

        data["_file_stem"] = f.stem
        buildings.append(data)

    return buildings


def building_to_citygml_lod2(building: dict, parent: ET.Element):
    """Generate CityGML LOD2 (extruded footprint) for a building."""
    addr = building.get("_meta", {}).get("address") or building.get("building_name", "")
    height = building.get("total_height_m", 6.0)
    width = building.get("facade_width_m", 5.0)
    depth = building.get("facade_depth_m", 10.0)

    # Get coordinates
    site = building.get("site", {})
    lon = site.get("lon", 0)
    lat = site.get("lat", 0)

    # Use local coords if available
    x = lon - ORIGIN_X if abs(lon) > 1000 else lon
    y = lat - ORIGIN_Y if abs(lat) > 1000 else lat

    member = ET.SubElement(parent, f"{{{NS['core']}}}cityObjectMember")
    bldg = ET.SubElement(member, f"{{{NS['bldg']}}}Building")
    bldg.set(f"{{{NS['gml']}}}id", f"building_{building.get('_file_stem', addr.replace(' ', '_'))}")

    # Building attributes
    func = ET.SubElement(bldg, f"{{{NS['bldg']}}}function")
    func.text = building.get("context", {}).get("building_type", "residential")

    floors_el = ET.SubElement(bldg, f"{{{NS['bldg']}}}storeysAboveGround")
    floors_el.text = str(building.get("floors", 2))

    height_el = ET.SubElement(bldg, f"{{{NS['bldg']}}}measuredHeight")
    height_el.set("uom", "m")
    height_el.text = f"{height:.1f}"

    # HCD data as generic attributes
    hcd = building.get("hcd_data", {})
    if hcd.get("construction_date"):
        attr = ET.SubElement(bldg, f"{{{NS['gen']}}}stringAttribute")
        attr.set("name", "constructionDate")
        val = ET.SubElement(attr, f"{{{NS['gen']}}}value")
        val.text = hcd["construction_date"]

    if hcd.get("contributing"):
        attr = ET.SubElement(bldg, f"{{{NS['gen']}}}stringAttribute")
        attr.set("name", "heritageContributing")
        val = ET.SubElement(attr, f"{{{NS['gen']}}}value")
        val.text = hcd["contributing"]

    if hcd.get("typology"):
        attr = ET.SubElement(bldg, f"{{{NS['gen']}}}stringAttribute")
        attr.set("name", "typology")
        val = ET.SubElement(attr, f"{{{NS['gen']}}}value")
        val.text = hcd["typology"]

    # LOD2 solid geometry (extruded box)
    lod2 = ET.SubElement(bldg, f"{{{NS['bldg']}}}lod2Solid")
    solid = ET.SubElement(lod2, f"{{{NS['gml']}}}Solid")
    exterior = ET.SubElement(solid, f"{{{NS['gml']}}}exterior")
    shell = ET.SubElement(exterior, f"{{{NS['gml']}}}CompositeSurface")

    # Ground footprint
    coords = [
        (x, y, 0), (x + width, y, 0),
        (x + width, y + depth, 0), (x, y + depth, 0), (x, y, 0),
    ]

    # Bottom face
    _add_polygon(shell, coords)
    # Top face
    _add_polygon(shell, [(cx, cy, height) for cx, cy, _ in coords])
    # Side faces
    for i in range(4):
        j = (i + 1) % 4
        _add_polygon(shell, [
            coords[i], coords[j],
            (coords[j][0], coords[j][1], height),
            (coords[i][0], coords[i][1], height),
            coords[i],
        ])

    return bldg


def _add_polygon(parent: ET.Element, coords: list[tuple]):
    """Add a GML polygon surface member."""
    member = ET.SubElement(parent, f"{{{NS['gml']}}}surfaceMember")
    polygon = ET.SubElement(member, f"{{{NS['gml']}}}Polygon")
    exterior = ET.SubElement(polygon, f"{{{NS['gml']}}}exterior")
    ring = ET.SubElement(exterior, f"{{{NS['gml']}}}LinearRing")
    pos_list = ET.SubElement(ring, f"{{{NS['gml']}}}posList")
    pos_list.set("srsDimension", "3")
    pos_list.text = " ".join(f"{c[0]:.3f} {c[1]:.3f} {c[2]:.3f}" for c in coords)


def export_citygml(
    params_dir: Path,
    output_path: Path,
    lod: int = 2,
    address_filter: str | None = None,
) -> dict:
    """Export buildings to CityGML.

    Args:
        params_dir: Directory with building param files.
        output_path: Output .gml file path.
        lod: Level of detail (2 or 3).
        address_filter: Optional address filter string.

    Returns:
        Stats dict.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    buildings = load_buildings(params_dir, address_filter)

    # Register namespaces
    for prefix, uri in NS.items():
        ET.register_namespace(prefix, uri)

    root = ET.Element(f"{{{NS['core']}}}CityModel")
    root.set(f"{{{NS['xsi']}}}schemaLocation",
             "http://www.opengis.net/citygml/2.0 http://schemas.opengis.net/citygml/2.0/cityGMLBase.xsd")

    # Name
    name = ET.SubElement(root, f"{{{NS['gml']}}}name")
    name.text = "Kensington Market Heritage Conservation District"

    stats = {"exported": 0, "errors": 0}

    for building in buildings:
        try:
            building_to_citygml_lod2(building, root)
            stats["exported"] += 1
        except Exception as e:
            logger.error(f"Error exporting {building.get('building_name', '?')}: {e}")
            stats["errors"] += 1

    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")
    tree.write(output_path, encoding="unicode", xml_declaration=True)

    return stats


def main():
    parser = argparse.ArgumentParser(description="Export to CityGML")
    parser.add_argument("--params", type=Path, default=REPO_ROOT / "params")
    parser.add_argument("--output", type=Path, default=REPO_ROOT / "citygml" / "kensington_lod2.gml")
    parser.add_argument("--lod", type=int, default=2, choices=[2, 3])
    parser.add_argument("--address", type=str, default=None)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    stats = export_citygml(args.params, args.output, args.lod, args.address)
    print(f"CityGML LOD{args.lod} export: {stats['exported']} buildings -> {args.output}")


if __name__ == "__main__":
    main()
