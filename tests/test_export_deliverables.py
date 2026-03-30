"""Tests for export scripts: CSV, GeoJSON, street profiles."""

import csv
import json
import pytest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

DELIVERABLES = Path(__file__).parent.parent / "outputs" / "deliverables"


class TestBuildingSummaryCSV:
    @pytest.fixture
    def csv_path(self):
        return DELIVERABLES / "building_summary.csv"

    def test_csv_exists(self, csv_path):
        assert csv_path.exists(), "building_summary.csv not found"

    def test_csv_parseable(self, csv_path):
        if not csv_path.exists():
            pytest.skip("CSV not found")
        with open(csv_path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        assert len(rows) > 1000

    def test_csv_has_required_columns(self, csv_path):
        if not csv_path.exists():
            pytest.skip("CSV not found")
        with open(csv_path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames
        for col in ["address", "street", "floors", "total_height_m", "facade_material"]:
            assert col in headers, f"Missing column: {col}"

    def test_csv_no_empty_address(self, csv_path):
        if not csv_path.exists():
            pytest.skip("CSV not found")
        with open(csv_path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                assert row.get("address", "").strip(), f"Empty address found"


class TestGeoJSON:
    @pytest.fixture
    def geojson_path(self):
        return DELIVERABLES / "kensington_buildings.geojson"

    def test_geojson_exists(self, geojson_path):
        assert geojson_path.exists(), "GeoJSON not found"

    def test_geojson_valid_structure(self, geojson_path):
        if not geojson_path.exists():
            pytest.skip("GeoJSON not found")
        data = json.loads(geojson_path.read_text(encoding="utf-8"))
        assert data["type"] == "FeatureCollection"
        assert len(data["features"]) > 500

    def test_geojson_point_geometry(self, geojson_path):
        if not geojson_path.exists():
            pytest.skip("GeoJSON not found")
        data = json.loads(geojson_path.read_text(encoding="utf-8"))
        for feat in data["features"][:50]:
            assert feat["geometry"]["type"] == "Point"

    def test_geojson_toronto_bbox(self, geojson_path):
        if not geojson_path.exists():
            pytest.skip("GeoJSON not found")
        data = json.loads(geojson_path.read_text(encoding="utf-8"))
        for feat in data["features"][:50]:
            lon, lat = feat["geometry"]["coordinates"]
            assert -79.45 < lon < -79.38, f"lon {lon} outside Toronto"
            assert 43.64 < lat < 43.67, f"lat {lat} outside Toronto"


class TestStreetProfiles:
    @pytest.fixture
    def profiles_path(self):
        return DELIVERABLES / "street_profiles.json"

    def test_profiles_exists(self, profiles_path):
        assert profiles_path.exists(), "street_profiles.json not found"

    def test_profiles_all_streets(self, profiles_path):
        if not profiles_path.exists():
            pytest.skip("Profiles not found")
        data = json.loads(profiles_path.read_text(encoding="utf-8"))
        streets = set()
        for p in data:
            name = p.get("street_name") or p.get("name") or p.get("street", "")
            if name:
                streets.add(name)
        assert len(streets) >= 20

    def test_profiles_positive_counts(self, profiles_path):
        if not profiles_path.exists():
            pytest.skip("Profiles not found")
        data = json.loads(profiles_path.read_text(encoding="utf-8"))
        for p in data:
            count = p.get("building_count", 0)
            assert count > 0, f"Street {p.get('name', '?')} has 0 buildings"
