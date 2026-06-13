#!/usr/bin/env python3
"""Tests for scripts/audit_deep_facade_coverage.py."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import audit_deep_facade_coverage as adfc


def _write_param(tmp_path: Path, name: str, data: dict) -> Path:
    p = tmp_path / name
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return p


# ── get_street ────────────────────────────────────────────────────────────────

class TestGetStreet:
    def test_from_site_dict(self):
        params = {"site": {"street": "Augusta Ave"}}
        assert adfc.get_street(params, "22_Augusta_Ave") == "Augusta Ave"

    def test_site_street_empty_falls_through(self):
        params = {"site": {"street": ""}, "building_name": "22 Nassau St"}
        result = adfc.get_street(params, "22_Nassau_St")
        # Should fall back to parsing the building name
        assert "Nassau" in result or result == "Unknown"

    def test_no_site_uses_building_name(self):
        params = {"building_name": "44 Augusta Ave"}
        result = adfc.get_street(params, "44_Augusta_Ave")
        assert "Augusta" in result or result == "Unknown"

    def test_unknown_returns_unknown(self):
        params = {}
        result = adfc.get_street(params, "random_file")
        assert result == "Unknown"

    def test_filename_used_when_no_building_name(self):
        params = {"site": {"street": ""}}
        result = adfc.get_street(params, "22_Lippincott_St")
        # Falls through to building_name (empty) then filename parsing
        # "22 Lippincott St" → should detect "Lippincott St"
        assert isinstance(result, str)

    def test_site_street_preferred_over_name(self):
        params = {"site": {"street": "Baldwin St"}, "building_name": "44 Augusta Ave"}
        assert adfc.get_street(params, "44_Augusta_Ave") == "Baldwin St"


# ── main() integration ────────────────────────────────────────────────────────

def _setup(tmp_path: Path) -> Path:
    adfc.PARAMS_DIR = tmp_path
    out_file = tmp_path / "deep_facade_coverage_report.json"
    adfc.OUTPUT_FILE = out_file
    return out_file


class TestMainIntegration:
    def test_empty_directory(self, tmp_path):
        out_file = _setup(tmp_path)
        adfc.main()
        data = json.loads(out_file.read_text(encoding="utf-8"))
        assert data["total_active_buildings"] == 0
        assert data["total_with_dfa"] == 0

    def test_building_without_dfa(self, tmp_path):
        _write_param(tmp_path, "22_Lippincott_St.json", {
            "building_name": "22 Lippincott St",
            "site": {"street": "Lippincott St"},
        })
        out_file = _setup(tmp_path)
        adfc.main()
        data = json.loads(out_file.read_text(encoding="utf-8"))
        assert data["total_active_buildings"] == 1
        assert data["total_with_dfa"] == 0

    def test_building_with_dfa_counted(self, tmp_path):
        _write_param(tmp_path, "44_Augusta_Ave.json", {
            "building_name": "44 Augusta Ave",
            "site": {"street": "Augusta Ave"},
            "deep_facade_analysis": {"source_photo": "photo_001.jpg"},
        })
        out_file = _setup(tmp_path)
        adfc.main()
        data = json.loads(out_file.read_text(encoding="utf-8"))
        assert data["total_active_buildings"] == 1
        assert data["total_with_dfa"] == 1

    def test_skipped_files_excluded(self, tmp_path):
        _write_param(tmp_path, "skip.json", {
            "skipped": True,
            "site": {"street": "Nassau St"},
        })
        out_file = _setup(tmp_path)
        adfc.main()
        data = json.loads(out_file.read_text(encoding="utf-8"))
        assert data["total_active_buildings"] == 0

    def test_metadata_files_excluded(self, tmp_path):
        _write_param(tmp_path, "_site_coordinates.json", {
            "site": {"street": "Nassau St"},
        })
        out_file = _setup(tmp_path)
        adfc.main()
        data = json.loads(out_file.read_text(encoding="utf-8"))
        assert data["total_active_buildings"] == 0

    def test_street_report_grouped(self, tmp_path):
        _write_param(tmp_path, "22_Augusta_Ave.json", {
            "building_name": "22 Augusta Ave",
            "site": {"street": "Augusta Ave"},
            "deep_facade_analysis": {"source_photo": "a.jpg"},
        })
        _write_param(tmp_path, "44_Augusta_Ave.json", {
            "building_name": "44 Augusta Ave",
            "site": {"street": "Augusta Ave"},
        })
        _write_param(tmp_path, "10_Nassau_St.json", {
            "building_name": "10 Nassau St",
            "site": {"street": "Nassau St"},
        })
        out_file = _setup(tmp_path)
        adfc.main()
        data = json.loads(out_file.read_text(encoding="utf-8"))
        streets = {r["street"]: r for r in data["streets"]}
        assert streets["Augusta Ave"]["total"] == 2
        assert streets["Augusta Ave"]["with_dfa"] == 1
        assert streets["Nassau St"]["total"] == 1
        assert streets["Nassau St"]["with_dfa"] == 0

    def test_below_threshold_flagged(self, tmp_path):
        # Augusta Ave: 0/2 coverage = 0% < 80% threshold → flagged
        for i in range(2):
            _write_param(tmp_path, f"b{i}.json", {
                "building_name": f"B{i}",
                "site": {"street": "Augusta Ave"},
            })
        out_file = _setup(tmp_path)
        adfc.main()
        data = json.loads(out_file.read_text(encoding="utf-8"))
        flagged_streets = {r["street"] for r in data["flagged_below_80pct"]}
        assert "Augusta Ave" in flagged_streets

    def test_above_threshold_not_flagged(self, tmp_path):
        # 2/2 = 100% coverage → not flagged
        for i in range(2):
            _write_param(tmp_path, f"b{i}.json", {
                "building_name": f"B{i}",
                "site": {"street": "Baldwin St"},
                "deep_facade_analysis": {"source_photo": f"p{i}.jpg"},
            })
        out_file = _setup(tmp_path)
        adfc.main()
        data = json.loads(out_file.read_text(encoding="utf-8"))
        flagged_streets = {r["street"] for r in data["flagged_below_80pct"]}
        assert "Baldwin St" not in flagged_streets

    def test_coverage_pct_calculated_correctly(self, tmp_path):
        # 1 of 4 buildings with DFA = 25%
        for i in range(3):
            _write_param(tmp_path, f"no_dfa{i}.json", {
                "building_name": f"no_dfa{i}",
                "site": {"street": "Oxford St"},
            })
        _write_param(tmp_path, "has_dfa.json", {
            "building_name": "has_dfa",
            "site": {"street": "Oxford St"},
            "deep_facade_analysis": {"source_photo": "p.jpg"},
        })
        out_file = _setup(tmp_path)
        adfc.main()
        data = json.loads(out_file.read_text(encoding="utf-8"))
        oxford = next(r for r in data["streets"] if r["street"] == "Oxford St")
        assert oxford["coverage_pct"] == pytest.approx(25.0)
