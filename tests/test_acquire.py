"""Tests for Stage 0 ACQUIRE scripts: acquire_ipad_scans, acquire_extract_elements,
acquire_streetview, acquire_open_data.

Each test creates minimal temp directories with fake files and verifies
output structure, element categorization, and graceful error handling.
"""

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Ensure scripts/ is importable (conftest.py adds repo root and scripts/)
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from acquire_ipad_scans import (
    derive_address,
    discover_scans,
    ingest_scans,
    sanitize_address,
)
from acquire_extract_elements import (
    classify_element,
    discover_scans as discover_scans_elements,
    extract_elements,
    load_metadata,
)
from acquire_streetview import assign_street, get_api_key
from acquire_open_data import acquire_source, resolve_sources


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_fake_obj(directory, filename):
    """Create a minimal .obj file and return its path."""
    path = directory / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("v 0 0 0\nv 1 0 0\nv 1 1 0\nf 1 2 3\n", encoding="utf-8")
    return path


def _write_fake_ply(directory, filename):
    """Create a minimal .ply file and return its path."""
    path = directory / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "ply\nformat ascii 1.0\nelement vertex 3\n"
        "property float x\nproperty float y\nproperty float z\n"
        "end_header\n0 0 0\n1 0 0\n1 1 0\n",
        encoding="utf-8",
    )
    return path


# ---------------------------------------------------------------------------
# acquire_ipad_scans tests
# ---------------------------------------------------------------------------

class TestAcquireIpadScans:
    def test_sanitize_address(self):
        assert sanitize_address("22_Lippincott_St.obj") == "22 Lippincott St"
        assert sanitize_address("  test_file  ") == "test file"

    def test_discover_scans_finds_obj_files(self, tmp_path):
        scan_dir = tmp_path / "scans"
        scan_dir.mkdir()
        _write_fake_obj(scan_dir, "building_a.obj")
        _write_fake_obj(scan_dir, "building_b.obj")
        # Non-scan file should be ignored
        (scan_dir / "readme.txt").write_text("notes", encoding="utf-8")

        scans = discover_scans(scan_dir)
        assert len(scans) == 2
        assert all(s.suffix == ".obj" for s in scans)

    def test_discover_scans_recursive(self, tmp_path):
        scan_dir = tmp_path / "scans"
        sub = scan_dir / "subdir"
        sub.mkdir(parents=True)
        _write_fake_obj(sub, "nested.obj")

        scans = discover_scans(scan_dir)
        assert len(scans) == 1

    def test_derive_address_from_subfolder(self, tmp_path):
        scan_dir = tmp_path / "scans"
        sub = scan_dir / "22_Lippincott_St"
        sub.mkdir(parents=True)
        scan_path = _write_fake_obj(sub, "scan_001.obj")

        address = derive_address(scan_path, scan_dir)
        assert address == "22 Lippincott St"

    def test_derive_address_from_filename(self, tmp_path):
        scan_dir = tmp_path / "scans"
        scan_dir.mkdir()
        scan_path = _write_fake_obj(scan_dir, "30_Baldwin_St.obj")

        address = derive_address(scan_path, scan_dir)
        assert address == "30 Baldwin St"

    def test_ingest_scans_copies_files(self, tmp_path):
        input_dir = tmp_path / "input"
        output_dir = tmp_path / "output"
        input_dir.mkdir()

        _write_fake_obj(input_dir, "building.obj")
        _write_fake_ply(input_dir, "building.ply")

        ingested, skipped = ingest_scans(input_dir, output_dir)
        assert ingested == 2
        assert skipped == 0

        # Check manifest was created
        manifest = output_dir / "ingest_manifest.json"
        assert manifest.exists()
        data = json.loads(manifest.read_text(encoding="utf-8"))
        assert len(data["scans"]) == 2

    def test_ingest_scans_skips_existing(self, tmp_path):
        input_dir = tmp_path / "input"
        output_dir = tmp_path / "output"
        input_dir.mkdir()

        _write_fake_obj(input_dir, "building.obj")

        # First run
        ingest_scans(input_dir, output_dir)
        # Second run should skip
        ingested, skipped = ingest_scans(input_dir, output_dir)
        assert ingested == 0
        assert skipped == 1

    def test_ingest_scans_organizes_by_address(self, tmp_path):
        input_dir = tmp_path / "input"
        output_dir = tmp_path / "output"
        addr_dir = input_dir / "50_Augusta_Ave"
        addr_dir.mkdir(parents=True)
        _write_fake_obj(addr_dir, "scan.obj")

        ingest_scans(input_dir, output_dir)

        # Should be organized into an address subfolder
        assert (output_dir / "50_Augusta_Ave" / "scan.obj").exists()


# ---------------------------------------------------------------------------
# acquire_extract_elements tests
# ---------------------------------------------------------------------------

class TestAcquireExtractElements:
    def test_classify_element_by_filename_window(self):
        assert classify_element("victorian_window_01.obj") == "windows"

    def test_classify_element_by_filename_door(self):
        assert classify_element("front_entrance.obj") == "doors"

    def test_classify_element_by_filename_cornice(self):
        assert classify_element("cornice_band_detail.obj") == "cornices"

    def test_classify_element_unknown_falls_to_misc(self):
        assert classify_element("random_geometry.obj") == "misc"

    def test_classify_element_by_metadata(self):
        meta = {"element_type": "window"}
        assert classify_element("scan_001.obj", metadata=meta) == "windows"

    def test_load_metadata_json(self, tmp_path):
        scan = tmp_path / "element.obj"
        scan.write_text("v 0 0 0\n", encoding="utf-8")
        meta_path = tmp_path / "element.json"
        meta_path.write_text(json.dumps({"element_type": "door"}), encoding="utf-8")

        meta = load_metadata(scan)
        assert meta is not None
        assert meta["element_type"] == "door"

    def test_load_metadata_missing(self, tmp_path):
        scan = tmp_path / "no_meta.obj"
        scan.write_text("v 0 0 0\n", encoding="utf-8")

        meta = load_metadata(scan)
        assert meta is None

    def test_extract_elements_categorizes(self, tmp_path):
        input_dir = tmp_path / "scans"
        output_dir = tmp_path / "elements"
        input_dir.mkdir()

        _write_fake_obj(input_dir, "window_01.obj")
        _write_fake_obj(input_dir, "door_front.obj")
        _write_fake_obj(input_dir, "random_thing.obj")

        total, skipped = extract_elements(input_dir, output_dir)
        assert total == 3
        assert skipped == 0

        # Check categorization
        assert (output_dir / "windows" / "window_01.obj").exists()
        assert (output_dir / "doors" / "door_front.obj").exists()
        assert (output_dir / "misc" / "random_thing.obj").exists()

        # Check catalog
        catalog_path = output_dir / "element_catalog.json"
        assert catalog_path.exists()
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
        assert "counts_by_category" in catalog
        assert catalog["counts_by_category"]["windows"] == 1
        assert catalog["counts_by_category"]["doors"] == 1

    def test_extract_elements_skips_existing(self, tmp_path):
        input_dir = tmp_path / "scans"
        output_dir = tmp_path / "elements"
        input_dir.mkdir()

        _write_fake_obj(input_dir, "window_01.obj")

        extract_elements(input_dir, output_dir)
        total, skipped = extract_elements(input_dir, output_dir)
        assert total == 0
        assert skipped == 1


# ---------------------------------------------------------------------------
# acquire_streetview tests
# ---------------------------------------------------------------------------

class TestAcquireStreetview:
    def test_no_api_key_returns_empty_string(self):
        """With no env var and no CLI arg, get_api_key returns empty string."""
        with patch.dict(os.environ, {}, clear=True):
            # Remove MAPILLARY_API_KEY if it exists
            env_copy = os.environ.copy()
            env_copy.pop("MAPILLARY_API_KEY", None)
            with patch.dict(os.environ, env_copy, clear=True):
                key = get_api_key(None)
                assert key == ""

    def test_assign_street_known_location(self):
        """A coordinate inside Augusta Ave zone should return 'Augusta Ave'."""
        street = assign_street(-79.4010, 43.6555)
        assert street == "Augusta Ave"

    def test_assign_street_outside_zones(self):
        """A coordinate outside all zones should return 'other'."""
        street = assign_street(-80.0, 40.0)
        assert street == "other"


# ---------------------------------------------------------------------------
# acquire_open_data tests
# ---------------------------------------------------------------------------

class TestAcquireOpenData:
    def test_resolve_sources_all(self):
        names = resolve_sources("all")
        assert "overture" in names
        assert "toronto-trees" in names
        assert "toronto-massing" in names

    def test_resolve_sources_specific(self):
        names = resolve_sources("overture,toronto-trees")
        assert names == ["overture", "toronto-trees"]

    def test_acquire_source_unreachable_url(self, tmp_path):
        """Unreachable URLs should be handled gracefully with a placeholder."""
        config = {
            "description": "Test source",
            "url": "http://localhost:1/nonexistent.geojson",
            "filename": "test_data.geojson",
            "format": "geojson",
        }

        downloaded, skipped, error = acquire_source("test", config, tmp_path)
        assert downloaded is False
        assert skipped is False
        assert error is not None

        # Should have written a placeholder
        placeholder = tmp_path / "test_data.placeholder.json"
        assert placeholder.exists()
        placeholder_data = json.loads(placeholder.read_text(encoding="utf-8"))
        assert placeholder_data["source"] == "test"
        assert "error" in placeholder_data

    def test_acquire_source_skips_existing(self, tmp_path):
        """If the file already exists, it should be skipped."""
        config = {
            "description": "Test source",
            "url": "http://example.com/data.geojson",
            "filename": "existing_data.geojson",
            "format": "geojson",
        }

        # Pre-create the file
        (tmp_path / "existing_data.geojson").write_text("{}", encoding="utf-8")

        downloaded, skipped, error = acquire_source("test", config, tmp_path)
        assert downloaded is False
        assert skipped is True
        assert error is None
