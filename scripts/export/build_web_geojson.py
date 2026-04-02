"""Export building footprints as GeoJSON for the web platform, with height + params data."""

import json
import sys
from pathlib import Path

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
    HAS_DB = True
except ImportError:
    HAS_DB = False

REPO_ROOT = Path(__file__).parent.parent.parent
PARAMS_DIR = REPO_ROOT / "params"
OUTPUT_DIR = REPO_ROOT / "web" / "public" / "data"


def export_geojson(output_dir=None):
    output_dir = Path(output_dir or OUTPUT_DIR)
    output_dir.mkdir(parents=True, exist_ok=True)

    if not HAS_DB:
        print("psycopg2 not available — using params lon/lat only (no real footprints)")
        export_from_params(output_dir)
        return

    try:
        conn = psycopg2.connect(
            host="localhost", port=5432,
            dbname="kensington", user="postgres", password="test123"
        )
    except Exception as e:
        print(f"DB connection failed: {e} — using params lon/lat only")
        export_from_params(output_dir)
        return

    cur = conn.cursor(cursor_factory=RealDictCursor)

    # Spatial join: real footprint polygons + building assessment addresses
    cur.execute("""
        SELECT
            ba."ADDRESS_FULL" as address,
            ST_AsGeoJSON(ST_Transform(bf.geom, 4326)) as geojson,
            ba.ba_stories,
            ba.ba_facade_material
        FROM opendata.building_footprints bf
        JOIN building_assessment ba
            ON ST_Intersects(bf.geom, ba.geom_2952)
        WHERE bf.geom IS NOT NULL
          AND ba.geom_2952 IS NOT NULL
    """)

    rows = cur.fetchall()
    conn.close()

    # Load param data for enrichment
    param_data = {}
    for f in PARAMS_DIR.glob("*.json"):
        if f.name.startswith("_"):
            continue
        try:
            p = json.loads(f.read_text(encoding="utf-8"))
            if p.get("skipped"):
                continue
            name = p.get("building_name", f.stem.replace("_", " "))
            param_data[name] = p
        except Exception:
            continue

    # Build GeoJSON
    features = []
    for row in rows:
        address = row["address"]
        geom = json.loads(row["geojson"])

        # Match to params
        params = param_data.get(address, {})
        palette = params.get("colour_palette", {}) if isinstance(params.get("colour_palette"), dict) else {}
        facade_detail = params.get("facade_detail", {}) if isinstance(params.get("facade_detail"), dict) else {}
        hcd = params.get("hcd_data", {}) if isinstance(params.get("hcd_data"), dict) else {}

        height = params.get("total_height_m") or 7.0
        facade_hex = facade_detail.get("brick_colour_hex") or palette.get("facade") or None

        site = params.get("site", {}) if isinstance(params.get("site"), dict) else {}
        properties = {
            "address": address,
            "street": site.get("street", ""),
            "height": float(height) if height else 7.0,
            "floors": params.get("floors") or row.get("ba_stories") or 2,
            "total_height_m": params.get("total_height_m"),
            "facade_width_m": params.get("facade_width_m"),
            "facade_depth_m": params.get("facade_depth_m"),
            "facade_material": params.get("facade_material") or row.get("ba_facade_material") or "brick",
            "facade_hex": facade_hex,
            "trim_hex": facade_detail.get("trim_colour_hex") or palette.get("trim"),
            "roof_hex": palette.get("roof"),
            "roof_type": params.get("roof_type", "gable"),
            "condition": params.get("condition", "fair"),
            "has_storefront": params.get("has_storefront", False),
            "typology": hcd.get("typology", ""),
            "era": hcd.get("construction_date", ""),
            "contributing": hcd.get("contributing", ""),
            "party_wall_left": params.get("party_wall_left", False),
            "party_wall_right": params.get("party_wall_right", False),
        }

        features.append({
            "type": "Feature",
            "geometry": geom,
            "properties": properties,
        })

    # Add buildings that have params+coords but no PostGIS footprint
    matched_addrs = {f["properties"]["address"] for f in features}
    added = 0
    for name, p in param_data.items():
        if name in matched_addrs:
            continue
        site = p.get("site", {}) if isinstance(p.get("site"), dict) else {}
        lon = site.get("lon")
        lat = site.get("lat")
        if not lon or not lat:
            continue

        palette = p.get("colour_palette", {}) if isinstance(p.get("colour_palette"), dict) else {}
        facade_detail = p.get("facade_detail", {}) if isinstance(p.get("facade_detail"), dict) else {}
        hcd = p.get("hcd_data", {}) if isinstance(p.get("hcd_data"), dict) else {}

        w = (p.get("facade_width_m") or 6) / 2
        d = (p.get("facade_depth_m") or 15) / 2
        m_per_deg = 111320
        lon_scale = m_per_deg * 0.7
        dLon = w / lon_scale
        dLat = d / m_per_deg

        geom = {
            "type": "Polygon",
            "coordinates": [[
                [lon - dLon, lat - dLat], [lon + dLon, lat - dLat],
                [lon + dLon, lat + dLat], [lon - dLon, lat + dLat],
                [lon - dLon, lat - dLat],
            ]]
        }
        features.append({
            "type": "Feature",
            "geometry": geom,
            "properties": {
                "address": name,
                "street": site.get("street", ""),
                "height": p.get("total_height_m", 7.0),
                "floors": p.get("floors", 2),
                "total_height_m": p.get("total_height_m"),
                "facade_width_m": p.get("facade_width_m"),
                "facade_depth_m": p.get("facade_depth_m"),
                "facade_material": p.get("facade_material", "brick"),
                "facade_hex": facade_detail.get("brick_colour_hex") or palette.get("facade"),
                "trim_hex": facade_detail.get("trim_colour_hex") or palette.get("trim"),
                "roof_hex": palette.get("roof"),
                "roof_type": p.get("roof_type", "gable"),
                "condition": p.get("condition", "fair"),
                "has_storefront": p.get("has_storefront", False),
                "typology": hcd.get("typology", ""),
                "era": hcd.get("construction_date", ""),
                "contributing": hcd.get("contributing", ""),
                "party_wall_left": p.get("party_wall_left", False),
                "party_wall_right": p.get("party_wall_right", False),
            },
        })
        added += 1

    geojson = {
        "type": "FeatureCollection",
        "features": features,
    }

    out_path = output_dir / "buildings.geojson"
    out_path.write_text(json.dumps(geojson), encoding="utf-8")
    print(f"Exported {len(features)} building footprints ({len(features) - added} PostGIS + {added} params fallback) to {out_path}")


def export_from_params(output_dir):
    """Fallback: create point features from params lon/lat."""
    features = []
    for f in sorted(PARAMS_DIR.glob("*.json")):
        if f.name.startswith("_"):
            continue
        try:
            p = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        if p.get("skipped"):
            continue

        site = p.get("site", {}) if isinstance(p.get("site"), dict) else {}
        lon = site.get("lon")
        lat = site.get("lat")
        if not lon or not lat:
            continue

        palette = p.get("colour_palette", {}) if isinstance(p.get("colour_palette"), dict) else {}
        facade_detail = p.get("facade_detail", {}) if isinstance(p.get("facade_detail"), dict) else {}
        hcd = p.get("hcd_data", {}) if isinstance(p.get("hcd_data"), dict) else {}

        # Create approximate rectangle footprint from width/depth
        w = (p.get("facade_width_m") or 6) / 2
        d = (p.get("facade_depth_m") or 15) / 2
        m_per_deg = 111320
        lon_scale = m_per_deg * 0.7  # cos(43.65deg)

        dLon = w / lon_scale
        dLat = d / m_per_deg

        geom = {
            "type": "Polygon",
            "coordinates": [[
                [lon - dLon, lat - dLat],
                [lon + dLon, lat - dLat],
                [lon + dLon, lat + dLat],
                [lon - dLon, lat + dLat],
                [lon - dLon, lat - dLat],
            ]]
        }

        features.append({
            "type": "Feature",
            "geometry": geom,
            "properties": {
                "address": p.get("building_name", f.stem.replace("_", " ")),
                "street": site.get("street", ""),
                "height": p.get("total_height_m", 7.0),
                "floors": p.get("floors", 2),
                "total_height_m": p.get("total_height_m"),
                "facade_width_m": p.get("facade_width_m"),
                "facade_depth_m": p.get("facade_depth_m"),
                "facade_material": p.get("facade_material", "brick"),
                "facade_hex": facade_detail.get("brick_colour_hex") or palette.get("facade"),
                "trim_hex": facade_detail.get("trim_colour_hex") or palette.get("trim"),
                "roof_hex": palette.get("roof"),
                "roof_type": p.get("roof_type", "gable"),
                "condition": p.get("condition", "fair"),
                "has_storefront": p.get("has_storefront", False),
                "typology": hcd.get("typology", ""),
                "era": hcd.get("construction_date", ""),
                "contributing": hcd.get("contributing", ""),
                "party_wall_left": p.get("party_wall_left", False),
                "party_wall_right": p.get("party_wall_right", False),
            },
        })

    geojson = {"type": "FeatureCollection", "features": features}
    out_path = output_dir / "buildings.geojson"
    out_path.write_text(json.dumps(geojson), encoding="utf-8")
    print(f"Exported {len(features)} building footprints (from params) to {out_path}")


if __name__ == "__main__":
    export_geojson()
