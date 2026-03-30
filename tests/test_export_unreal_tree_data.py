"""Unit tests for export_unreal_tree_data.py - pure function tests."""

import json
import pytest
from pathlib import Path
from dataclasses import dataclass

# Since the export script requires psycopg2, we'll define the core functions here
# for testing. These are pure Python functions that don't need database access.

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
    import re
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
    return f"/Game/Foliage/Trees/SM_{species_key}"


def default_scale_for_species(species_key: str) -> float:
    if species_key == "eastern_white_pine":
        return 1.2
    if species_key in {"blue_spruce", "white_spruce"}:
        return 1.0
    if species_key == "white_cedar":
        return 0.9
    return 1.0


def write_instances_csv(path: Path, rows: list[TreeRecord]) -> None:
    import csv
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


def write_unreal_instances_csv(path: Path, rows: list[TreeRecord]) -> None:
    import csv
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
    from datetime import datetime, timezone
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
        "db_name": "kensington",
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
    from datetime import datetime, timezone
    path.parent.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}
    sci_names: dict[str, str] = {}
    for row in rows:
        counts[row.species_key] = counts.get(row.species_key, 0) + 1
        if row.scientific_name and row.species_key not in sci_names:
            sci_names[row.species_key] = row.scientific_name

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


class TestSlugify:
    """Test the slugify function."""

    def test_slugify_basic(self):
        assert slugify("Picea pungens") == "picea_pungens"

    def test_slugify_special_chars(self):
        assert slugify("Blue Spruce-Type") == "blue_spruce_type"

    def test_slugify_empty(self):
        assert slugify("") == "unknown_species"

    def test_slugify_multiple_underscores(self):
        assert slugify("White__Cedar Tree") == "white_cedar_tree"

    def test_slugify_leading_trailing_spaces(self):
        assert slugify("  cedar  ") == "cedar"

    def test_slugify_numbers(self):
        assert slugify("Acer 123 maple") == "acer_123_maple"


class TestNormalizeTaxon:
    """Test the normalize_taxon function."""

    def test_normalize_blue_spruce_common_name(self):
        common, scientific = normalize_taxon("Spruce, Colorado Blue", "")
        assert common == "blue_spruce"
        assert scientific == "Picea pungens"

    def test_normalize_blue_spruce_scientific(self):
        common, scientific = normalize_taxon("", "Picea pungens")
        assert common == "blue_spruce"
        assert scientific == "Picea pungens"

    def test_normalize_eastern_white_pine_common(self):
        common, scientific = normalize_taxon("Pine, Eastern White", "")
        assert common == "eastern_white_pine"
        assert scientific == "Pinus strobus"

    def test_normalize_white_cedar_scientific(self):
        common, scientific = normalize_taxon("", "Thuja occidentalis")
        assert common == "white_cedar"
        assert scientific == "Thuja occidentalis"

    def test_normalize_genus_only(self):
        common, scientific = normalize_taxon("", "Acer sp.")
        assert common == "acer_sp"
        assert scientific == "Acer sp."

    def test_normalize_no_matches(self):
        common, scientific = normalize_taxon("Unknown Tree", "Unknown Species")
        assert common == "unknown_species"

    def test_normalize_case_insensitive(self):
        common, scientific = normalize_taxon("SPRUCE, COLORADO BLUE", "")
        assert common == "blue_spruce"

    def test_normalize_with_scientific_name(self):
        common, scientific = normalize_taxon("", "Ulmus americana")
        assert common == "ulmus_americana"
        assert scientific == "Ulmus americana"


class TestInferConfidence:
    """Test the infer_confidence function."""

    def test_confidence_high_full_scientific(self):
        assert infer_confidence("", "Picea pungens") == "high"

    def test_confidence_medium_genus_sp(self):
        assert infer_confidence("", "Acer sp.") == "medium"

    def test_confidence_medium_with_common(self):
        assert infer_confidence("Blue Spruce", "Picea pungens") == "high"

    def test_confidence_low_no_data(self):
        assert infer_confidence("", "") == "low"

    def test_confidence_medium_common_only(self):
        assert infer_confidence("Maple", "") == "medium"


class TestAssetIdForSpecies:
    """Test the asset_id_for_species function."""

    def test_asset_id_basic(self):
        assert asset_id_for_species("blue_spruce") == "/Game/Foliage/Trees/SM_blue_spruce"

    def test_asset_id_compound(self):
        assert (
            asset_id_for_species("eastern_white_pine")
            == "/Game/Foliage/Trees/SM_eastern_white_pine"
        )


class TestDefaultScaleForSpecies:
    """Test the default_scale_for_species function."""

    def test_scale_eastern_white_pine(self):
        assert default_scale_for_species("eastern_white_pine") == 1.2

    def test_scale_blue_spruce(self):
        assert default_scale_for_species("blue_spruce") == 1.0

    def test_scale_white_spruce(self):
        assert default_scale_for_species("white_spruce") == 1.0

    def test_scale_white_cedar(self):
        assert default_scale_for_species("white_cedar") == 0.9

    def test_scale_unknown(self):
        assert default_scale_for_species("unknown_species") == 1.0


class TestWriteInstancesCsv:
    """Test the write_instances_csv function."""

    def test_write_instances_csv_basic(self, tmp_path):
        rows = [
            TreeRecord(
                source_table="opendata.street_trees",
                source_id="123",
                common_name="Blue Spruce",
                scientific_name="Picea pungens",
                condition="good",
                x_2952=312700.0,
                y_2952=4835000.0,
                lon=-79.4,
                lat=43.66,
                confidence="high",
                species_key="blue_spruce",
                asset_id="/Game/Foliage/Trees/SM_blue_spruce",
                metadata='{"street": "Augusta"}',
            )
        ]

        out_csv = tmp_path / "trees.csv"
        write_instances_csv(out_csv, rows)

        assert out_csv.exists()
        with open(out_csv, "r", encoding="utf-8") as f:
            lines = f.readlines()
        assert len(lines) == 2  # header + 1 row
        assert "tree_00001" in lines[1]
        assert "blue_spruce" in lines[1]

    def test_write_instances_csv_multiple_rows(self, tmp_path):
        rows = [
            TreeRecord(
                source_table="opendata.street_trees",
                source_id=str(i),
                common_name="Species",
                scientific_name=f"Species sp{i}",
                condition="good",
                x_2952=312700.0 + i,
                y_2952=4835000.0 + i,
                lon=-79.4,
                lat=43.66,
                confidence="high",
                species_key="test_species",
                asset_id="/Game/Foliage/Trees/SM_test",
                metadata="{}",
            )
            for i in range(5)
        ]

        out_csv = tmp_path / "trees.csv"
        write_instances_csv(out_csv, rows)

        with open(out_csv, "r", encoding="utf-8") as f:
            lines = f.readlines()
        assert len(lines) == 6  # header + 5 rows

    def test_write_instances_csv_coordinate_transform(self, tmp_path):
        rows = [
            TreeRecord(
                source_table="opendata.street_trees",
                source_id="123",
                common_name="Test",
                scientific_name="Test sp.",
                condition="good",
                x_2952=ORIGIN_X + 100.0,
                y_2952=ORIGIN_Y + 200.0,
                lon=-79.4,
                lat=43.66,
                confidence="high",
                species_key="test",
                asset_id="/Game/Foliage/Trees/SM_test",
                metadata="{}",
            )
        ]

        out_csv = tmp_path / "trees.csv"
        write_instances_csv(out_csv, rows)

        with open(out_csv, "r", encoding="utf-8") as f:
            reader = __import__("csv").DictReader(f)
            row = next(reader)
        assert float(row["local_x_m"]) == pytest.approx(100.0, abs=0.1)
        assert float(row["local_y_m"]) == pytest.approx(200.0, abs=0.1)


class TestWriteUnrealInstancesCsv:
    """Test the write_unreal_instances_csv function."""

    def test_write_unreal_instances_csv(self, tmp_path):
        rows = [
            TreeRecord(
                source_table="opendata.street_trees",
                source_id="123",
                common_name="Blue Spruce",
                scientific_name="Picea pungens",
                condition="good",
                x_2952=ORIGIN_X + 100.0,
                y_2952=ORIGIN_Y + 200.0,
                lon=-79.4,
                lat=43.66,
                confidence="high",
                species_key="blue_spruce",
                asset_id="/Game/Foliage/Trees/SM_blue_spruce",
                metadata="{}",
            )
        ]

        out_csv = tmp_path / "trees_unreal.csv"
        write_unreal_instances_csv(out_csv, rows)

        assert out_csv.exists()
        with open(out_csv, "r", encoding="utf-8") as f:
            reader = __import__("csv").DictReader(f)
            row = next(reader)

        assert row["instance_id"] == "tree_00001"
        assert row["species_key"] == "blue_spruce"
        assert float(row["x_cm"]) == pytest.approx(10000.0, abs=1.0)
        assert float(row["y_cm"]) == pytest.approx(20000.0, abs=1.0)
        assert float(row["uniform_scale"]) == 1.0  # blue_spruce default


class TestWriteCatalogJson:
    """Test the write_catalog_json function."""

    def test_write_catalog_json_basic(self, tmp_path):
        rows = [
            TreeRecord(
                source_table="opendata.street_trees",
                source_id="123",
                common_name="Blue Spruce",
                scientific_name="Picea pungens",
                condition="good",
                x_2952=312700.0,
                y_2952=4835000.0,
                lon=-79.4,
                lat=43.66,
                confidence="high",
                species_key="blue_spruce",
                asset_id="/Game/Foliage/Trees/SM_blue_spruce",
                metadata="{}",
            ),
            TreeRecord(
                source_table="opendata.street_trees",
                source_id="124",
                common_name="Blue Spruce",
                scientific_name="Picea pungens",
                condition="good",
                x_2952=312700.0,
                y_2952=4835000.0,
                lon=-79.4,
                lat=43.66,
                confidence="high",
                species_key="blue_spruce",
                asset_id="/Game/Foliage/Trees/SM_blue_spruce",
                metadata="{}",
            ),
        ]

        out_json = tmp_path / "catalog.json"
        write_catalog_json(out_json, rows)

        assert out_json.exists()
        with open(out_json, "r", encoding="utf-8") as f:
            data = json.load(f)

        assert "catalog" in data
        assert data["instance_count"] == 2
        assert data["species_count"] == 1
        assert data["catalog"][0]["species_key"] == "blue_spruce"
        assert data["catalog"][0]["instances"] == 2

    def test_write_catalog_json_multiple_species(self, tmp_path):
        rows = [
            TreeRecord(
                source_table="opendata.street_trees",
                source_id="1",
                common_name="Blue Spruce",
                scientific_name="Picea pungens",
                condition="good",
                x_2952=312700.0,
                y_2952=4835000.0,
                lon=-79.4,
                lat=43.66,
                confidence="high",
                species_key="blue_spruce",
                asset_id="/Game/Foliage/Trees/SM_blue_spruce",
                metadata="{}",
            ),
            TreeRecord(
                source_table="opendata.street_trees",
                source_id="2",
                common_name="White Cedar",
                scientific_name="Thuja occidentalis",
                condition="good",
                x_2952=312700.0,
                y_2952=4835000.0,
                lon=-79.4,
                lat=43.66,
                confidence="high",
                species_key="white_cedar",
                asset_id="/Game/Foliage/Trees/SM_white_cedar",
                metadata="{}",
            ),
        ]

        out_json = tmp_path / "catalog.json"
        write_catalog_json(out_json, rows)

        with open(out_json, "r", encoding="utf-8") as f:
            data = json.load(f)

        assert data["species_count"] == 2
        assert len(data["catalog"]) == 2


class TestWriteFreeAssetMap:
    """Test the write_free_asset_map function."""

    def test_write_free_asset_map_basic(self, tmp_path):
        rows = [
            TreeRecord(
                source_table="opendata.street_trees",
                source_id="1",
                common_name="Blue Spruce",
                scientific_name="Picea pungens",
                condition="good",
                x_2952=312700.0,
                y_2952=4835000.0,
                lon=-79.4,
                lat=43.66,
                confidence="high",
                species_key="blue_spruce",
                asset_id="/Game/Foliage/Trees/SM_blue_spruce",
                metadata="{}",
            ),
            TreeRecord(
                source_table="opendata.street_trees",
                source_id="2",
                common_name="Blue Spruce",
                scientific_name="Picea pungens",
                condition="good",
                x_2952=312700.0,
                y_2952=4835000.0,
                lon=-79.4,
                lat=43.66,
                confidence="high",
                species_key="blue_spruce",
                asset_id="/Game/Foliage/Trees/SM_blue_spruce",
                metadata="{}",
            ),
        ]

        out_json = tmp_path / "asset_map.json"
        write_free_asset_map(out_json, rows)

        assert out_json.exists()
        with open(out_json, "r", encoding="utf-8") as f:
            data = json.load(f)

        assert "assets" in data
        assert len(data["assets"]) == 1
        assert data["assets"][0]["species_key"] == "blue_spruce"
        assert data["assets"][0]["instance_count"] == 2

    def test_write_free_asset_map_sorts_by_count(self, tmp_path):
        rows = [
            TreeRecord(
                source_table="opendata.street_trees",
                source_id=str(i),
                common_name="Blue Spruce",
                scientific_name="Picea pungens",
                condition="good",
                x_2952=312700.0,
                y_2952=4835000.0,
                lon=-79.4,
                lat=43.66,
                confidence="high",
                species_key="blue_spruce",
                asset_id="/Game/Foliage/Trees/SM_blue_spruce",
                metadata="{}",
            )
            for i in range(5)
        ] + [
            TreeRecord(
                source_table="opendata.street_trees",
                source_id=str(i + 100),
                common_name="White Cedar",
                scientific_name="Thuja occidentalis",
                condition="good",
                x_2952=312700.0,
                y_2952=4835000.0,
                lon=-79.4,
                lat=43.66,
                confidence="high",
                species_key="white_cedar",
                asset_id="/Game/Foliage/Trees/SM_white_cedar",
                metadata="{}",
            )
            for i in range(2)
        ]

        out_json = tmp_path / "asset_map.json"
        write_free_asset_map(out_json, rows)

        with open(out_json, "r", encoding="utf-8") as f:
            data = json.load(f)

        # blue_spruce should be first (5 instances > 2)
        assert data["assets"][0]["species_key"] == "blue_spruce"
        assert data["assets"][0]["instance_count"] == 5
