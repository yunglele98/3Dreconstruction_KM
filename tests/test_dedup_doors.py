#!/usr/bin/env python3
"""Tests for scripts/dedup_doors.py – door deduplication helpers."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import dedup_doors as dd


# ── _door_position ──────────────────────────────────────────────────────────

class TestDoorPosition:
    def test_named_left(self):
        assert dd._door_position({"position": "left"}) == pytest.approx(0.2)

    def test_named_center(self):
        assert dd._door_position({"position": "center"}) == pytest.approx(0.5)

    def test_named_centre(self):
        assert dd._door_position({"position": "centre"}) == pytest.approx(0.5)

    def test_named_right(self):
        assert dd._door_position({"position": "right"}) == pytest.approx(0.8)

    def test_numeric_position_m_overrides_named(self):
        assert dd._door_position({"position": "left", "position_m": 1.5}) == pytest.approx(1.5)

    def test_numeric_position_m_float_string(self):
        assert dd._door_position({"position_m": "2.3"}) == pytest.approx(2.3)

    def test_invalid_position_m_falls_back_to_name(self):
        assert dd._door_position({"position": "right", "position_m": "bad"}) == pytest.approx(0.8)

    def test_unknown_position_returns_default(self):
        assert dd._door_position({"position": "middle"}) == pytest.approx(0.5)

    def test_empty_dict_returns_default(self):
        assert dd._door_position({}) == pytest.approx(0.5)

    def test_none_position_m_falls_through(self):
        assert dd._door_position({"position": "left", "position_m": None}) == pytest.approx(0.2)


# ── _completeness ────────────────────────────────────────────────────────────

class TestCompleteness:
    def test_all_none_values_is_zero(self):
        assert dd._completeness({"a": None, "b": None}) == 0

    def test_all_empty_string_is_zero(self):
        assert dd._completeness({"a": "", "b": ""}) == 0

    def test_all_empty_list_is_zero(self):
        assert dd._completeness({"a": [], "b": {}}) == 0

    def test_non_empty_values_counted(self):
        assert dd._completeness({"type": "door", "width_m": 1.0, "material": None}) == 2

    def test_zero_value_counts_as_present(self):
        # 0 is not None/""/[]/{}
        assert dd._completeness({"count": 0}) == 1

    def test_false_value_counts_as_present(self):
        assert dd._completeness({"has_transom": False}) == 1


# ── dedup_doors_list ─────────────────────────────────────────────────────────

class TestDedupDoorsList:
    def _door(self, position: str, typ: str = "door", **kwargs) -> dict:
        return {"position": position, "type": typ, **kwargs}

    def test_empty_list_unchanged(self):
        result, removed = dd.dedup_doors_list([])
        assert result == []
        assert removed == 0

    def test_single_entry_unchanged(self):
        door = self._door("center")
        result, removed = dd.dedup_doors_list([door])
        assert result == [door]
        assert removed == 0

    def test_two_identical_position_same_type_deduped(self):
        d1 = self._door("center", "door", width_m=1.0)
        d2 = self._door("center", "door", width_m=0.9)
        result, removed = dd.dedup_doors_list([d1, d2])
        assert removed == 1
        assert len(result) == 1

    def test_more_complete_door_kept(self):
        d1 = self._door("center", "door", width_m=1.0)
        d2 = self._door("center", "door", width_m=1.0, height_m=2.1, material="wood")
        result, removed = dd.dedup_doors_list([d1, d2])
        assert removed == 1
        assert result[0].get("material") == "wood"

    def test_different_positions_not_deduped(self):
        d1 = self._door("left")
        d2 = self._door("right")
        result, removed = dd.dedup_doors_list([d1, d2])
        assert removed == 0
        assert len(result) == 2

    def test_different_types_not_deduped(self):
        d1 = self._door("center", "door")
        d2 = self._door("center", "window")
        result, removed = dd.dedup_doors_list([d1, d2])
        assert removed == 0
        assert len(result) == 2

    def test_tolerance_boundary_inside(self):
        d1 = {"position_m": 1.0, "type": "door"}
        d2 = {"position_m": 1.25, "type": "door"}
        result, removed = dd.dedup_doors_list([d1, d2], tolerance=0.3)
        assert removed == 1

    def test_tolerance_boundary_outside(self):
        d1 = {"position_m": 1.0, "type": "door"}
        d2 = {"position_m": 1.4, "type": "door"}
        result, removed = dd.dedup_doors_list([d1, d2], tolerance=0.3)
        assert removed == 0

    def test_three_doors_two_near_duplicates(self):
        d1 = self._door("left")
        d2 = self._door("center")
        d3 = self._door("centre")  # maps to same 0.5
        # Use a tight tolerance so only center/centre (both 0.5) are deduped;
        # left (0.2) is 0.3 away and must not be merged with them.
        result, removed = dd.dedup_doors_list([d1, d2, d3], tolerance=0.1)
        assert removed == 1
        assert len(result) == 2

    def test_first_door_is_preferred_if_equally_complete(self):
        d1 = self._door("center", "door", width_m=1.0)
        d2 = self._door("center", "door", width_m=1.2)
        result, removed = dd.dedup_doors_list([d1, d2])
        # d1 was first; both have same completeness so first is kept
        assert result[0]["width_m"] == 1.0


# ── main() integration via temp files ───────────────────────────────────────

class TestMainIntegration:
    def _write_param(self, tmp_path: Path, name: str, data: dict) -> Path:
        p = tmp_path / name
        p.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return p

    def test_dry_run_reports_duplicates(self, tmp_path, capsys):
        self._write_param(
            tmp_path,
            "22_Lippincott_St.json",
            {
                "building_name": "22 Lippincott St",
                "doors_detail": [
                    {"position": "center", "type": "door", "width_m": 1.0},
                    {"position": "center", "type": "door", "width_m": 0.9},
                ],
            },
        )
        # Patch default paths and call main with args
        import argparse

        args = argparse.Namespace(params_dir=str(tmp_path), dry_run=True, fix=False)
        original = dd.parse_args
        dd.parse_args = lambda: args
        try:
            dd.main()
        finally:
            dd.parse_args = original

        captured = capsys.readouterr()
        assert "Buildings affected: 1" in captured.out
        assert "Duplicate doors found: 1" in captured.out

    def test_fix_writes_deduped_file(self, tmp_path, capsys):
        param_file = self._write_param(
            tmp_path,
            "44_Augusta_Ave.json",
            {
                "building_name": "44 Augusta Ave",
                "doors_detail": [
                    {"position": "right", "type": "door"},
                    {"position": "right", "type": "door", "material": "wood"},
                ],
            },
        )
        import argparse

        args = argparse.Namespace(params_dir=str(tmp_path), dry_run=False, fix=True)
        original = dd.parse_args
        dd.parse_args = lambda: args
        try:
            dd.main()
        finally:
            dd.parse_args = original

        data = json.loads(param_file.read_text(encoding="utf-8"))
        assert len(data["doors_detail"]) == 1
        assert data["_meta"]["doors_deduped"] is True
        assert data["_meta"]["doors_dedup_count"] == 1

    def test_skipped_files_not_processed(self, tmp_path, capsys):
        self._write_param(
            tmp_path,
            "skipped.json",
            {
                "skipped": True,
                "doors_detail": [
                    {"position": "center", "type": "door"},
                    {"position": "center", "type": "door"},
                ],
            },
        )
        import argparse

        args = argparse.Namespace(params_dir=str(tmp_path), dry_run=True, fix=False)
        original = dd.parse_args
        dd.parse_args = lambda: args
        try:
            dd.main()
        finally:
            dd.parse_args = original

        captured = capsys.readouterr()
        assert "Buildings affected: 0" in captured.out

    def test_metadata_files_skipped(self, tmp_path, capsys):
        self._write_param(
            tmp_path,
            "_site_coordinates.json",
            {
                "doors_detail": [
                    {"position": "center", "type": "door"},
                    {"position": "center", "type": "door"},
                ],
            },
        )
        import argparse

        args = argparse.Namespace(params_dir=str(tmp_path), dry_run=True, fix=False)
        original = dd.parse_args
        dd.parse_args = lambda: args
        try:
            dd.main()
        finally:
            dd.parse_args = original

        captured = capsys.readouterr()
        assert "Buildings affected: 0" in captured.out
