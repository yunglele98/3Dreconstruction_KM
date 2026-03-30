#!/usr/bin/env python3
"""Export species catalog + tree instances for Unreal/Blender from PostGIS.

Outputs:
1) outputs/trees/tree_catalog.json
2) outputs/trees/tree_instances.csv

Data sources:
- opendata.street_trees (city inventory, species-rich)
- public.field_trees (field survey trees, sometimes genus-only)
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

try:
    import psycopg2
    import psycopg2.extras
except ImportError:
    print("[ERROR] psycopg2 not installed. Run: pip install psycopg2-binary")
    sys.exit(1)

from db_config import DB_CONFIG, get_connection

# Keep coordinates aligned with export_gis_scene.py.
ORIGIN_X = 312672.94
ORIGIN_Y = 4834994.86


@dataclass
class TreeRecord:
    source_table: str
    source_id: str
    common_name: str
    scientific_name: str
    condition: str
    x_2952: float
    y_2952: float
    lon: float
    lat: float
    confidence: str
    species_key: str
    asset_id: str
    metadata: str


def slugify(value: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "_", (value or "").strip().lower())
    value = re.sub(r"_+", "_", value).strip("_")
    return value or "unknown_species"


def normalize_taxon(common_name: str, scientific_name: str) -> tuple[str, str]:
    common = (common_name or "").strip()
    scientific = (scientific_name or "").strip()

    scilo = scientific.lower()
    comlo = common.lower()

    if "picea pungens" in scilo or "spruce, colorado blue" in comlo:
        return "blue_spruce", "Picea pungens"
    if "pinus strobus" in scilo or "pine, eastern white" in comlo:
        return "eastern_white_pine", "Pinus strobus"
    if "picea glauca" in scilo or "spruce, white" in comlo:
        return "white_spruce", "Picea glauca"
    if "thuja occidentalis" in scilo or "cedar, white" in comlo:
        return "white_cedar", "Thuja occidentalis"
    if "sp." in scilo:
        genus = scientific.split()[0] if scientific else ""
        return f"{slugify(genus)}_sp" if genus else "unknown_genus_sp", scientific
    if scientific:
        return slugify(scientific), scientific
    if common:
        return slugify(common), scientific
    return "unknown_species", scientific


def infer_confidence(common_name: str, scientific_name: str) -> str:
    if scientific_name and "sp." not in scientific_name.lower():
        return "high"
    if scientific_name and "sp." in scientific_name.lower():
        return "medium"
    if common_name:
        return "medium"
    return "low"


def asset_id_for_species(species_key: str) -> str:
    # Unreal asset path convention placeholder (replace with your real assets).
    return f"/Game/Foliage/Trees/SM_{species_key}"


def fetch_street_trees(conn) -> list[TreeRecord]:
    query = """
        WITH study AS (
            SELECT ST_Transform(geometry, 2952) AS geom_2952
            FROM opendata.study_area
            LIMIT 1
        )
        SELECT
            t.gid::text AS source_id,
            COALESCE(t."COMMON_14", '') AS common_name,
            COALESCE(t."BOTANIC13", '') AS scientific_name,
            COALESCE(t.tree_condition, '') AS condition,
            ST_X(ST_Centroid(t.geometry)) AS x_2952,
            ST_Y(ST_Centroid(t.geometry)) AS y_2952,
            ST_X(ST_Transform(ST_Centroid(t.geometry), 4326)) AS lon,
            ST_Y(ST_Transform(ST_Centroid(t.geometry), 4326)) AS lat,
            COALESCE(t."STREETN5", '') AS street_name,
            COALESCE(t."ADDRESS4"::text, '') AS civic_number
        FROM opendata.street_trees t
        JOIN study s
          ON ST_Intersects(t.geometry, s.geom_2952)
    """
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(query)
    rows = cur.fetchall()
    cur.close()

    out: list[TreeRecord] = []
    for row in rows:
        common = row["common_name"]
        scientific = row["scientific_name"]
        species_key, normalized_scientific = normalize_taxon(common, scientific)
        out.append(
            TreeRecord(
                source_table="opendata.street_trees",
                source_id=row["source_id"],
                common_name=common,
                scientific_name=normalized_scientific or scientific,
                condition=row["condition"],
                x_2952=float(row["x_2952"]),
                y_2952=float(row["y_2952"]),
                lon=float(row["lon"]),
                lat=float(row["lat"]),
                confidence=infer_confidence(common, scientific),
                species_key=species_key,
                asset_id=asset_id_for_species(species_key),
                metadata=json.dumps(
                    {
                        "street_name": row["street_name"],
                        "civic_number": row["civic_number"],
                    },
                    ensure_ascii=False,
                ),
            )
        )
    return out


def fetch_field_trees(conn) -> list[TreeRecord]:
    query = """
        WITH study AS (
            SELECT ST_Transform(geometry, 2952) AS geom_2952
            FROM opendata.study_area
            LIMIT 1
        )
        SELECT
            f.id::text AS source_id,
            ''::text AS common_name,
            COALESCE(f.type_arbre, '') AS scientific_name,
            COALESCE(f.etat_arbre, '') AS condition,
            ST_X(ST_Transform(f.geom, 2952)) AS x_2952,
            ST_Y(ST_Transform(f.geom, 2952)) AS y_2952,
            ST_X(f.geom) AS lon,
            ST_Y(f.geom) AS lat,
            COALESCE(f.adresse, '') AS adresse,
            COALESCE(f.commentaires, '') AS commentaires
        FROM public.field_trees f
        JOIN study s
          ON ST_Intersects(ST_Transform(f.geom, 2952), s.geom_2952)
        WHERE f.geom IS NOT NULL
    """
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(query)
    rows = cur.fetchall()
    cur.close()

    out: list[TreeRecord] = []
    for row in rows:
        scientific = row["scientific_name"]
        species_key, normalized_scientific = normalize_taxon("", scientific)
        out.append(
            TreeRecord(
                source_table="public.field_trees",
                source_id=row["source_id"],
                common_name="",
                scientific_name=normalized_scientific or scientific,
                condition=row["condition"],
                x_2952=float(row["x_2952"]),
                y_2952=float(row["y_2952"]),
                lon=float(row["lon"]),
                lat=float(row["lat"]),
                confidence=infer_confidence("", scientific),
                species_key=species_key,
                asset_id=asset_id_for_species(species_key),
                metadata=json.dumps(
                    {
                        "adresse": row["adresse"],
                        "commentaires": row["commentaires"],
                    },
                    ensure_ascii=False,
                ),
            )
        )
    return out


def write_instances_csv(path: Path, rows: list[TreeRecord]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "instance_id",
                "source_table",
                "source_id",
                "species_key",
                "common_name",
                "scientific_name",
                "asset_id",
                "confidence",
                "condition",
                "x_2952_m",
                "y_2952_m",
                "local_x_m",
                "local_y_m",
                "lon",
                "lat",
                "metadata_json",
            ],
        )
        writer.writeheader()
        for idx, row in enumerate(rows, start=1):
            writer.writerow(
                {
                    "instance_id": f"tree_{idx:05d}",
                    "source_table": row.source_table,
                    "source_id": row.source_id,
                    "species_key": row.species_key,
                    "common_name": row.common_name,
                    "scientific_name": row.scientific_name,
                    "asset_id": row.asset_id,
                    "confidence": row.confidence,
                    "condition": row.condition,
                    "x_2952_m": f"{row.x_2952:.3f}",
                    "y_2952_m": f"{row.y_2952:.3f}",
                    "local_x_m": f"{row.x_2952 - ORIGIN_X:.3f}",
                    "local_y_m": f"{row.y_2952 - ORIGIN_Y:.3f}",
                    "lon": f"{row.lon:.8f}",
                    "lat": f"{row.lat:.8f}",
                    "metadata_json": row.metadata,
                }
            )


def default_scale_for_species(species_key: str) -> float:
    if species_key == "eastern_white_pine":
        return 1.2
    if species_key in {"blue_spruce", "white_spruce"}:
        return 1.0
    if species_key == "white_cedar":
        return 0.9
    return 1.0


def write_unreal_instances_csv(path: Path, rows: list[TreeRecord]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "instance_id",
                "asset_path",
                "species_key",
                "x_cm",
                "y_cm",
                "z_cm",
                "yaw_deg",
                "uniform_scale",
                "confidence",
                "source_table",
                "source_id",
            ],
        )
        writer.writeheader()
        for idx, row in enumerate(rows, start=1):
            local_x_m = row.x_2952 - ORIGIN_X
            local_y_m = row.y_2952 - ORIGIN_Y
            writer.writerow(
                {
                    "instance_id": f"tree_{idx:05d}",
                    "asset_path": row.asset_id,
                    "species_key": row.species_key,
                    "x_cm": f"{local_x_m * 100.0:.1f}",
                    "y_cm": f"{local_y_m * 100.0:.1f}",
                    "z_cm": "0.0",
                    "yaw_deg": "0.0",
                    "uniform_scale": f"{default_scale_for_species(row.species_key):.3f}",
                    "confidence": row.confidence,
                    "source_table": row.source_table,
                    "source_id": row.source_id,
                }
            )


def write_catalog_json(path: Path, rows: list[TreeRecord]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    grouped: dict[str, dict] = {}
    for row in rows:
        item = grouped.setdefault(
            row.species_key,
            {
                "species_key": row.species_key,
                "scientific_name": row.scientific_name,
                "common_names": set(),
                "asset_id": row.asset_id,
                "instances": 0,
                "sources": set(),
                "confidence_levels": set(),
                "generator_recommendation": "blender_sapling_or_geo_nodes",
            },
        )
        if row.common_name:
            item["common_names"].add(row.common_name)
        if row.scientific_name and not item["scientific_name"]:
            item["scientific_name"] = row.scientific_name
        item["instances"] += 1
        item["sources"].add(row.source_table)
        item["confidence_levels"].add(row.confidence)

    catalog = []
    for key in sorted(grouped):
        item = grouped[key]
        catalog.append(
            {
                "species_key": item["species_key"],
                "scientific_name": item["scientific_name"],
                "common_names": sorted(item["common_names"]),
                "asset_id": item["asset_id"],
                "instances": item["instances"],
                "sources": sorted(item["sources"]),
                "confidence_levels": sorted(item["confidence_levels"]),
                "generator_recommendation": item["generator_recommendation"],
            }
        )

    payload = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "db_name": DB_CONFIG["dbname"],
        "study_area_source": "opendata.study_area",
        "instance_count": len(rows),
        "species_count": len(catalog),
        "notes": [
            "asset_id values are Unreal placeholders; map these to real meshes.",
            "confidence is taxonomy confidence only, not geometric validation confidence.",
            "local_x_m/local_y_m use the same origin as export_gis_scene.py.",
        ],
        "catalog": catalog,
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def write_free_asset_map(path: Path, rows: list[TreeRecord]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}
    sci_names: dict[str, str] = {}
    for row in rows:
        counts[row.species_key] = counts.get(row.species_key, 0) + 1
        if row.scientific_name and row.species_key not in sci_names:
            sci_names[row.species_key] = row.scientific_name

    # Higher-fidelity manual presets for species you flagged as important.
    manual = {
        "blue_spruce": {
            "display_name": "Colorado blue spruce",
            "scientific_name": "Picea pungens",
            "free_build_tool": "Blender Sapling + Geometry Nodes",
            "notes": "Conical form; dense radial branches; blue-green needle tint.",
        },
        "white_spruce": {
            "display_name": "White spruce",
            "scientific_name": "Picea glauca",
            "free_build_tool": "Blender Sapling + Geometry Nodes",
            "notes": "Narrow conical crown; fine needle mass; lighter green than blue spruce.",
        },
        "eastern_white_pine": {
            "display_name": "Eastern white pine",
            "scientific_name": "Pinus strobus",
            "free_build_tool": "Blender Sapling + custom branch levels",
            "notes": "Whorled branching; looser/open crown; long needle clusters.",
        },
        "white_cedar": {
            "display_name": "White cedar",
            "scientific_name": "Thuja occidentalis",
            "free_build_tool": "Blender Sapling + card-based foliage",
            "notes": "Columnar/oval habit; flattened sprays, not needle tufts.",
        },
    }

    items = []
    for species_key, count in sorted(counts.items(), key=lambda kv: kv[1], reverse=True):
        base = manual.get(species_key, {})
        items.append(
            {
                "species_key": species_key,
                "display_name": base.get("display_name", species_key.replace("_", " ").title()),
                "scientific_name": base.get("scientific_name", sci_names.get(species_key, "")),
                "instance_count": count,
                "unreal_asset_path": asset_id_for_species(species_key),
                "free_build_tool": base.get("free_build_tool", "Blender Sapling or hand-tuned low-poly"),
                "notes": base.get("notes", "Use species silhouette + bark + branch density references."),
            }
        )

    payload = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "intent": "Map species keys to free build recommendations and Unreal asset placeholders.",
        "priority_order_hint": [
            "blue_spruce",
            "eastern_white_pine",
            "white_spruce",
            "white_cedar",
        ],
        "assets": items,
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Export tree data for Unreal/Blender.")
    parser.add_argument(
        "--output-dir",
        default="outputs/trees",
        help="Directory for tree_catalog.json and tree_instances.csv",
    )
    args = parser.parse_args()

    out_dir = Path(args.output_dir)
    catalog_path = out_dir / "tree_catalog.json"
    instances_path = out_dir / "tree_instances.csv"
    unreal_instances_path = out_dir / "tree_instances_unreal_cm.csv"
    free_map_path = out_dir / "tree_asset_map_free.json"

    conn = get_connection()
    try:
        street_rows = fetch_street_trees(conn)
        field_rows = fetch_field_trees(conn)
    finally:
        conn.close()

    all_rows = street_rows + field_rows
    all_rows.sort(key=lambda r: (r.species_key, r.source_table, r.source_id))

    write_instances_csv(instances_path, all_rows)
    write_unreal_instances_csv(unreal_instances_path, all_rows)
    write_catalog_json(catalog_path, all_rows)
    write_free_asset_map(free_map_path, all_rows)

    print(f"[OK] Wrote {instances_path} ({len(all_rows)} instances)")
    print(f"[OK] Wrote {unreal_instances_path}")
    print(f"[OK] Wrote {catalog_path}")
    print(f"[OK] Wrote {free_map_path}")
    print(f"      street_trees: {len(street_rows)}")
    print(f"      field_trees:  {len(field_rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

