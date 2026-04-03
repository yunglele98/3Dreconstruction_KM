#!/usr/bin/env python3
"""Stage 8 — EXPORT: Export buildings to CityGML LOD2/LOD3 format.

Reads params/*.json and generates CityGML XML files suitable for
urban planning platforms and GIS tools.

Usage:
    python scripts/export/export_citygml.py --lod 3 --output citygml/kensington_lod3.gml
    python scripts/export/export_citygml.py --lod 2 --output citygml/kensington_lod2.gml --dry-run
"""

import argparse
import json
import sys
from pathlib import Path
from xml.etree.ElementTree import Element, SubElement, tostring

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_PARAMS = REPO_ROOT / "params"
DEFAULT_OUTPUT = REPO_ROOT / "citygml"

# CityGML namespaces
NS_CITYGML = "http://www.opengis.net/citygml/2.0"
NS_BLDG = "http://www.opengis.net/citygml/building/2.0"
NS_GML = "http://www.opengis.net/gml"

# Coordinate reference: SRID 2952 (NAD83 / Ontario MTM Zone 10)
ORIGIN_X = 312672.94
ORIGIN_Y = 4834994.86


def building_to_citygml(params: dict, lod: int = 3) -> Element:
    """Convert a building params dict to a CityGML Building element."""
    bldg = Element(f"{{{NS_BLDG}}}Building")
    bldg.set(f"{{{NS_GML}}}id", params.get("building_name", "unknown"))

    # Measured height
    height = SubElement(bldg, f"{{{NS_BLDG}}}measuredHeight")
    height.set("uom", "m")
    height.text = str(params.get("total_height_m", 0))

    # Storeys above ground
    storeys = SubElement(bldg, f"{{{NS_BLDG}}}storeysAboveGround")
    storeys.text = str(params.get("floors", 0))

    # Roof type
    roof = SubElement(bldg, f"{{{NS_BLDG}}}roofType")
    roof_type = params.get("roof_type", "flat")
    roof_type_code = {
        "flat": "1000", "gable": "1010", "hip": "1020",
        "cross-gable": "1030", "mansard": "1040",
    }.get(roof_type, "1000")
    roof.text = roof_type_code

    # Function
    function = SubElement(bldg, f"{{{NS_BLDG}}}function")
    if params.get("has_storefront"):
        function.text = "1120"  # commercial+residential
    else:
        function.text = "1000"  # residential

    return bldg


def export_citygml(
    params_dir: Path,
    output_path: Path,
    *,
    lod: int = 3,
    dry_run: bool = False,
) -> dict:
    """Export all buildings to a CityGML file."""
    buildings = []
    for f in sorted(params_dir.glob("*.json")):
        if f.name.startswith("_"):
            continue
        data = json.loads(f.read_text(encoding="utf-8"))
        if data.get("skipped"):
            continue
        buildings.append(data)

    result = {
        "building_count": len(buildings),
        "lod": lod,
        "output": str(output_path),
    }

    if dry_run:
        result["status"] = "would_export"
        return result

    # Build CityGML document
    root = Element("CityModel")
    root.set("xmlns", NS_CITYGML)
    root.set("xmlns:bldg", NS_BLDG)
    root.set("xmlns:gml", NS_GML)

    for params in buildings:
        member = SubElement(root, "cityObjectMember")
        bldg_elem = building_to_citygml(params, lod=lod)
        member.append(bldg_elem)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    xml_bytes = tostring(root, encoding="unicode", xml_declaration=True)
    output_path.write_text(xml_bytes, encoding="utf-8")

    result["status"] = "exported"
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Export to CityGML")
    parser.add_argument("--params", type=Path, default=DEFAULT_PARAMS)
    parser.add_argument("--lod", type=int, default=3, choices=[2, 3])
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT / "kensington_lod3.gml")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    result = export_citygml(args.params, args.output, lod=args.lod, dry_run=args.dry_run)

    prefix = "[DRY RUN] " if args.dry_run else ""
    print(f"{prefix}CityGML LOD{args.lod}: {result['building_count']} buildings → {result['output']}")


if __name__ == "__main__":
    main()
