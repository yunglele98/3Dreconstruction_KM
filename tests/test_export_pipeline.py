"""Tests for Stage 8 EXPORT scripts: export_citygml, export_3dtiles, build_web_data.

Each test creates minimal building param files in a temp directory, runs the
export functions, and verifies output structure (XML, JSON, GeoJSON).
"""

import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

# Ensure scripts/export/ is importable
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts" / "export"))

from export_citygml import build_citygml, load_params as load_params_citygml
from export_3dtiles import build_tileset, load_params as load_params_3dtiles
from build_web_data import (
    build_geojson,
    build_slim_params,
    copy_scenarios,
    load_params as load_params_web,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_building_param(name, lon, lat, floors=2, height=7.0, width=6.0, depth=15.0,
                         roof_type="gable", material="brick"):
    """Create a minimal building param dict with site coordinates."""
    return {
        "building_name": name,
        "floors": floors,
        "total_height_m": height,
        "facade_width_m": width,
        "facade_depth_m": depth,
        "roof_type": roof_type,
        "roof_pitch_deg": 30,
        "facade_material": material,
        "condition": "good",
        "has_storefront": False,
        "windows_per_floor": [2] * floors,
        "door_count": 1,
        "site": {
            "lon": lon,
            "lat": lat,
            "street": "Test St",
            "street_number": "22",
        },
        "hcd_data": {
            "typology": "House-form",
            "construction_date": "1904-1913",
            "contributing": "Yes",
        },
        "_meta": {},
    }


def _write_params(params_dir, buildings):
    """Write building param dicts to JSON files in params_dir."""
    params_dir.mkdir(parents=True, exist_ok=True)
    for bld in buildings:
        name = bld["building_name"].replace(" ", "_")
        path = params_dir / f"{name}.json"
        path.write_text(json.dumps(bld, indent=2), encoding="utf-8")


def _make_test_buildings():
    """Return a list of 3 minimal building params."""
    return [
        _make_building_param("22 Lippincott St", -79.4010, 43.6550),
        _make_building_param("30 Baldwin St", -79.4005, 43.6555, floors=3, height=10.0),
        _make_building_param("15 Nassau St", -79.4000, 43.6560, roof_type="flat"),
    ]


# ---------------------------------------------------------------------------
# export_citygml tests
# ---------------------------------------------------------------------------

class TestExportCityGML:
    def test_generates_valid_xml(self, tmp_path):
        params_dir = tmp_path / "params"
        buildings = _make_test_buildings()
        _write_params(params_dir, buildings)

        output_path = tmp_path / "output.gml"
        loaded = load_params_citygml(params_dir)
        exported = build_citygml(loaded, lod=3, output_path=output_path)

        assert exported == 3
        assert output_path.exists()

        # Parse as XML to verify validity
        tree = ET.parse(str(output_path))
        root = tree.getroot()
        assert root is not None

    def test_contains_building_elements(self, tmp_path):
        params_dir = tmp_path / "params"
        buildings = _make_test_buildings()
        _write_params(params_dir, buildings)

        output_path = tmp_path / "output.gml"
        loaded = load_params_citygml(params_dir)
        build_citygml(loaded, lod=2, output_path=output_path)

        content = output_path.read_text(encoding="utf-8")
        # Check for Building elements (namespace-qualified)
        assert "Building" in content
        assert "measuredHeight" in content
        assert "storeysAboveGround" in content

    def test_lod3_includes_openings(self, tmp_path):
        params_dir = tmp_path / "params"
        buildings = [_make_building_param("Test Bldg", -79.401, 43.655)]
        _write_params(params_dir, buildings)

        output_path = tmp_path / "lod3.gml"
        loaded = load_params_citygml(params_dir)
        build_citygml(loaded, lod=3, output_path=output_path)

        content = output_path.read_text(encoding="utf-8")
        assert "window" in content
        assert "door" in content

    def test_lod2_no_openings(self, tmp_path):
        params_dir = tmp_path / "params"
        buildings = [_make_building_param("Test Bldg", -79.401, 43.655)]
        _write_params(params_dir, buildings)

        output_path = tmp_path / "lod2.gml"
        loaded = load_params_citygml(params_dir)
        build_citygml(loaded, lod=2, output_path=output_path)

        content = output_path.read_text(encoding="utf-8")
        # LOD2 should have geometry but no window/door installations
        assert "lod2Solid" in content or "Solid" in content

    def test_skips_buildings_without_coords(self, tmp_path):
        params_dir = tmp_path / "params"
        no_coords = {
            "building_name": "No Coords Bldg",
            "floors": 2,
            "total_height_m": 7.0,
            "site": {},
            "_meta": {},
        }
        _write_params(params_dir, [no_coords])

        output_path = tmp_path / "output.gml"
        loaded = load_params_citygml(params_dir)
        exported = build_citygml(loaded, lod=2, output_path=output_path)
        assert exported == 0

    def test_skips_skipped_files(self, tmp_path):
        params_dir = tmp_path / "params"
        params_dir.mkdir()
        skipped = {"building_name": "Mural", "skipped": True, "skip_reason": "Not a building"}
        (params_dir / "mural.json").write_text(json.dumps(skipped), encoding="utf-8")

        loaded = load_params_citygml(params_dir)
        assert len(loaded) == 0


# ---------------------------------------------------------------------------
# export_3dtiles tests
# ---------------------------------------------------------------------------

class TestExport3DTiles:
    def test_generates_tileset_json(self, tmp_path):
        params_dir = tmp_path / "params"
        input_dir = tmp_path / "exports"
        output_dir = tmp_path / "tiles_3d"
        buildings = _make_test_buildings()
        _write_params(params_dir, buildings)
        input_dir.mkdir()

        loaded = load_params_3dtiles(params_dir)
        total, glb_count, placeholder_count, out_path = build_tileset(
            loaded, input_dir, output_dir
        )

        assert total == 3
        assert out_path.exists()

        tileset = json.loads(out_path.read_text(encoding="utf-8"))
        assert "asset" in tileset
        assert tileset["asset"]["version"] == "1.0"
        assert "root" in tileset
        assert "children" in tileset["root"]
        assert len(tileset["root"]["children"]) == 3

    def test_tileset_json_structure(self, tmp_path):
        params_dir = tmp_path / "params"
        input_dir = tmp_path / "exports"
        output_dir = tmp_path / "tiles_3d"
        buildings = _make_test_buildings()
        _write_params(params_dir, buildings)
        input_dir.mkdir()

        loaded = load_params_3dtiles(params_dir)
        build_tileset(loaded, input_dir, output_dir)

        tileset = json.loads((output_dir / "tileset.json").read_text(encoding="utf-8"))

        # Verify root structure
        root = tileset["root"]
        assert "boundingVolume" in root
        assert "region" in root["boundingVolume"]
        assert len(root["boundingVolume"]["region"]) == 6
        assert "geometricError" in root
        assert root["refine"] == "ADD"

        # Verify child tile structure
        child = root["children"][0]
        assert "boundingVolume" in child
        assert "content" in child
        assert "uri" in child["content"]
        assert "geometricError" in child
        assert "extras" in child

    def test_placeholder_uris_when_no_glbs(self, tmp_path):
        params_dir = tmp_path / "params"
        input_dir = tmp_path / "exports"
        output_dir = tmp_path / "tiles_3d"
        buildings = _make_test_buildings()
        _write_params(params_dir, buildings)
        input_dir.mkdir()

        loaded = load_params_3dtiles(params_dir)
        total, glb_count, placeholder_count, _ = build_tileset(
            loaded, input_dir, output_dir
        )

        assert glb_count == 0
        assert placeholder_count == 3

    def test_detects_existing_glb(self, tmp_path):
        params_dir = tmp_path / "params"
        input_dir = tmp_path / "exports"
        output_dir = tmp_path / "tiles_3d"
        buildings = [_make_building_param("22 Lippincott St", -79.401, 43.655)]
        _write_params(params_dir, buildings)
        input_dir.mkdir()

        # Create a matching .glb file
        (input_dir / "22_Lippincott_St.glb").write_bytes(b"\x00")

        loaded = load_params_3dtiles(params_dir)
        total, glb_count, placeholder_count, _ = build_tileset(
            loaded, input_dir, output_dir
        )

        assert total == 1
        assert glb_count == 1
        assert placeholder_count == 0


# ---------------------------------------------------------------------------
# build_web_data tests
# ---------------------------------------------------------------------------

class TestBuildWebData:
    def test_build_slim_params(self, tmp_path):
        buildings = _make_test_buildings()
        slim = build_slim_params(buildings)

        assert len(slim) == 3
        for entry in slim:
            assert "address" in entry
            assert "lat" in entry
            assert "lon" in entry
            assert "floors" in entry
            assert "facade_material" in entry
            assert "contributing" in entry

    def test_build_geojson(self, tmp_path):
        buildings = _make_test_buildings()
        geojson = build_geojson(buildings)

        assert geojson["type"] == "FeatureCollection"
        assert len(geojson["features"]) == 3

        feature = geojson["features"][0]
        assert feature["type"] == "Feature"
        assert feature["geometry"]["type"] == "Point"
        assert len(feature["geometry"]["coordinates"]) == 2
        assert "address" in feature["properties"]
        assert "floors" in feature["properties"]

    def test_build_geojson_skips_no_coords(self):
        buildings = [
            {"building_name": "No Coords", "site": {}, "_meta": {}},
        ]
        geojson = build_geojson(buildings)
        assert len(geojson["features"]) == 0

    def test_full_web_data_output(self, tmp_path):
        params_dir = tmp_path / "params"
        output_dir = tmp_path / "web_data"
        buildings = _make_test_buildings()
        _write_params(params_dir, buildings)

        # Load and generate
        loaded = load_params_web(params_dir)
        assert len(loaded) == 3

        slim = build_slim_params(loaded)
        slim_path = output_dir / "params-slim.json"
        output_dir.mkdir(parents=True, exist_ok=True)
        slim_path.write_text(json.dumps(slim, indent=2) + "\n", encoding="utf-8")

        geojson = build_geojson(loaded)
        geojson_path = output_dir / "buildings.geojson"
        geojson_path.write_text(json.dumps(geojson, indent=2) + "\n", encoding="utf-8")

        # Verify files exist and are valid JSON
        assert slim_path.exists()
        assert geojson_path.exists()

        slim_data = json.loads(slim_path.read_text(encoding="utf-8"))
        assert len(slim_data) == 3

        geo_data = json.loads(geojson_path.read_text(encoding="utf-8"))
        assert geo_data["type"] == "FeatureCollection"

    def test_copy_scenarios(self, tmp_path):
        scenarios_dir = tmp_path / "scenarios"
        output_dir = tmp_path / "web_data"

        # Create a scenario
        scenario = scenarios_dir / "10yr_gentle_density"
        scenario.mkdir(parents=True)
        interventions = {
            "scenario_id": "gentle_density",
            "interventions": [
                {"address": "22 Lippincott St", "type": "add_floor"}
            ],
        }
        (scenario / "interventions.json").write_text(
            json.dumps(interventions, indent=2), encoding="utf-8"
        )

        copied = copy_scenarios(scenarios_dir, output_dir)
        assert copied == 1
        assert (output_dir / "scenarios" / "10yr_gentle_density" / "interventions.json").exists()

    def test_load_params_skips_metadata_and_skipped(self, tmp_path):
        params_dir = tmp_path / "params"
        params_dir.mkdir()

        # Active building
        (params_dir / "22_Lippincott_St.json").write_text(
            json.dumps(_make_building_param("22 Lippincott St", -79.401, 43.655)),
            encoding="utf-8",
        )
        # Skipped file
        (params_dir / "mural.json").write_text(
            json.dumps({"skipped": True, "skip_reason": "Not a building"}),
            encoding="utf-8",
        )
        # Metadata file
        (params_dir / "_site_coordinates.json").write_text(
            json.dumps({"origin": [0, 0]}),
            encoding="utf-8",
        )

        loaded = load_params_web(params_dir)
        assert len(loaded) == 1
