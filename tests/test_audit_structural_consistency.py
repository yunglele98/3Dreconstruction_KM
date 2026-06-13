#!/usr/bin/env python3
"""Tests for scripts/audit_structural_consistency.py."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import audit_structural_consistency as asc


def _write_param(tmp_path: Path, name: str, data: dict) -> Path:
    p = tmp_path / name
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return p


def _run(tmp_path: Path) -> str:
    """Redirect PARAMS_DIR and ROOT so relative_to() works, then run the audit."""
    orig_params = asc.PARAMS_DIR
    orig_root = asc.ROOT
    asc.PARAMS_DIR = tmp_path
    asc.ROOT = tmp_path.parent  # tmp_path is a child of this, so relative_to works
    try:
        import io, contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            asc.audit_structural_consistency()
        return buf.getvalue()
    finally:
        asc.PARAMS_DIR = orig_params
        asc.ROOT = orig_root


# ── audit_structural_consistency ─────────────────────────────────────────────

class TestAuditStructuralConsistency:
    def test_consistent_building_no_issues(self, tmp_path):
        _write_param(
            tmp_path,
            "22_Lippincott_St.json",
            {
                "building_name": "22 Lippincott St",
                "floors": 2,
                "floor_heights_m": [3.5, 3.0],
                "total_height_m": 6.5,
            },
        )
        out = _run(tmp_path)
        assert "No structural inconsistencies" in out

    def test_floor_count_mismatch_reported(self, tmp_path):
        _write_param(
            tmp_path,
            "44_Augusta_Ave.json",
            {
                "building_name": "44 Augusta Ave",
                "floors": 3,
                "floor_heights_m": [3.5, 3.0],  # only 2 entries, floors=3
                "total_height_m": 6.5,
            },
        )
        out = _run(tmp_path)
        assert "Floor count mismatch" in out

    def test_height_mismatch_reported(self, tmp_path):
        _write_param(
            tmp_path,
            "67_Baldwin_St.json",
            {
                "building_name": "67 Baldwin St",
                "floors": 2,
                "floor_heights_m": [3.5, 3.0],  # sum=6.5
                "total_height_m": 9.0,  # differs by 2.5 (> 0.75 threshold)
            },
        )
        out = _run(tmp_path)
        assert "Total height mismatch" in out

    def test_small_height_delta_ignored(self, tmp_path):
        _write_param(
            tmp_path,
            "10_Nassau_St.json",
            {
                "building_name": "10 Nassau St",
                "floors": 2,
                "floor_heights_m": [3.5, 3.0],  # sum=6.5
                "total_height_m": 6.7,  # delta=0.2 (within 0.75 threshold)
            },
        )
        out = _run(tmp_path)
        assert "No structural inconsistencies" in out

    def test_metadata_files_skipped(self, tmp_path):
        _write_param(
            tmp_path,
            "_site_coordinates.json",
            {
                "floors": 3,
                "floor_heights_m": [3.5, 3.0],
                "total_height_m": 999.0,
            },
        )
        out = _run(tmp_path)
        assert "No structural inconsistencies" in out

    def test_missing_floors_does_not_crash(self, tmp_path):
        _write_param(
            tmp_path,
            "no_floors.json",
            {
                "building_name": "No Floors Building",
                "floor_heights_m": [3.5, 3.0],
                "total_height_m": 6.5,
            },
        )
        out = _run(tmp_path)
        # No crash; no floor-count inconsistency since floors is missing
        assert "No structural inconsistencies" in out

    def test_missing_floor_heights_does_not_crash(self, tmp_path):
        _write_param(
            tmp_path,
            "no_heights.json",
            {
                "building_name": "No Heights Building",
                "floors": 2,
                "total_height_m": 6.5,
            },
        )
        out = _run(tmp_path)
        assert "No structural inconsistencies" in out

    def test_both_mismatches_reported_for_same_file(self, tmp_path):
        _write_param(
            tmp_path,
            "double_bad.json",
            {
                "building_name": "Double Bad",
                "floors": 4,
                "floor_heights_m": [3.5, 3.0],  # count mismatch (2 vs 4)
                "total_height_m": 20.0,          # sum 6.5 vs 20.0 -> height mismatch
            },
        )
        out = _run(tmp_path)
        assert "Floor count mismatch" in out
        assert "Total height mismatch" in out

    def test_multiple_buildings_mixed_results(self, tmp_path):
        _write_param(
            tmp_path,
            "good.json",
            {"building_name": "Good", "floors": 2, "floor_heights_m": [3.5, 3.0], "total_height_m": 6.5},
        )
        _write_param(
            tmp_path,
            "bad.json",
            {"building_name": "Bad", "floors": 3, "floor_heights_m": [3.5, 3.0], "total_height_m": 6.5},
        )
        out = _run(tmp_path)
        assert "Floor count mismatch" in out
        # "No structural inconsistencies" should NOT appear because there IS an issue
        assert "No structural inconsistencies" not in out

    def test_empty_directory(self, tmp_path):
        out = _run(tmp_path)
        assert "No structural inconsistencies" in out
