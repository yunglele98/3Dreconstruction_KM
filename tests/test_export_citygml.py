"""Tests for scripts/export/export_citygml.py and export_3dtiles.py."""

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts" / "export"))

from export_citygml import load_buildings, export_citygml
from export_3dtiles import load_building_metadata, create_tileset_json


# ── CityGML ─────────────────────────────────────────────────────────

def test_load_buildings_skips_metadata(tmp_path):
    params = tmp_path / "params"
    params.mkdir()
    (params / "_site.json").write_text('{"x": 1}', encoding="utf-8")
    (params / "test.json").write_text(
        json.dumps({"building_name": "Test", "floors": 2}),
        encoding="utf-8",
    )
    (params / "skip.json").write_text(
        json.dumps({"skipped": True}),
        encoding="utf-8",
    )
    buildings = load_buildings(params)
    assert len(buildings) == 1
    assert buildings[0]["building_name"] == "Test"


def test_export_citygml_produces_xml(tmp_path):
    params = tmp_path / "params"
    params.mkdir()
    (params / "test.json").write_text(json.dumps({
        "building_name": "Test",
        "floors": 2,
        "total_height_m": 7.0,
        "facade_width_m": 5.0,
        "facade_depth_m": 10.0,
        "hcd_data": {"contributing": "Yes", "construction_date": "Pre-1889"},
        "_meta": {"address": "Test"},
    }), encoding="utf-8")

    output = tmp_path / "output.gml"
    stats = export_citygml(params, output, lod=2)
    assert stats["exported"] == 1
    assert output.exists()
    content = output.read_text(encoding="utf-8")
    assert "Building" in content
    assert "Pre-1889" in content


# ── 3D Tiles ────────────────────────────────────────────────────────

def test_load_building_metadata(tmp_path):
    params = tmp_path / "params"
    params.mkdir()
    (params / "test.json").write_text(json.dumps({
        "building_name": "Test",
        "floors": 2,
        "total_height_m": 7.0,
        "facade_material": "brick",
    }), encoding="utf-8")
    meta = load_building_metadata(params)
    assert "test" in meta
    assert meta["test"]["floors"] == 2


def test_create_tileset_json():
    buildings = {
        "test": {"name": "Test", "floors": 2, "height": 7.0,
                 "material": "brick", "hcd_contributing": "Yes",
                 "construction_date": "Pre-1889", "lon": 0, "lat": 0},
    }
    tileset = create_tileset_json(buildings, Path("/tmp"))
    assert tileset["asset"]["version"] == "1.1"
    assert len(tileset["root"]["children"]) == 1
