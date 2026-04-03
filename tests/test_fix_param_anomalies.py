"""Tests for scripts/fix_param_anomalies.py."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from fix_param_anomalies import (
    estimate_floors_from_height,
    compute_floor_heights,
    fix_building,
    run,
)


class TestEstimateFloors:
    def test_short_building(self):
        assert estimate_floors_from_height(3.0) == 1

    def test_two_storey(self):
        assert estimate_floors_from_height(6.5) == 2

    def test_three_storey(self):
        assert estimate_floors_from_height(9.0) == 3

    def test_tall_building(self):
        floors = estimate_floors_from_height(20.0)
        assert 5 <= floors <= 7

    def test_zero_height(self):
        assert estimate_floors_from_height(0) == 1


class TestComputeFloorHeights:
    def test_single_floor(self):
        fh = compute_floor_heights(3.5, 1)
        assert len(fh) == 1
        assert fh[0] == 3.5

    def test_two_floors_sum(self):
        fh = compute_floor_heights(6.5, 2)
        assert len(fh) == 2
        assert abs(sum(fh) - 6.5) < 0.01

    def test_ground_taller(self):
        fh = compute_floor_heights(9.0, 3)
        assert fh[0] > fh[1]

    def test_five_floors_sum(self):
        fh = compute_floor_heights(15.0, 5)
        assert len(fh) == 5
        assert abs(sum(fh) - 15.0) < 0.01


class TestFixBuilding:
    def test_fixes_bad_condition(self):
        params = {"condition": "weathered", "floors": 2,
                  "total_height_m": 7.0, "floor_heights_m": [3.5, 3.5]}
        result, fixes = fix_building(params, "test.json")
        assert result["condition"] == "poor"
        assert len(fixes) == 1

    def test_infers_floors_from_tall_single(self):
        params = {"floors": 1, "total_height_m": 14.0,
                  "floor_heights_m": [14.0], "windows_per_floor": [4]}
        result, fixes = fix_building(params, "test.json")
        assert result["floors"] > 1
        assert len(result["floor_heights_m"]) == result["floors"]
        assert abs(sum(result["floor_heights_m"]) - 14.0) < 0.01

    def test_reduces_unreasonable_floor_count(self):
        params = {"floors": 5, "total_height_m": 9.0,
                  "floor_heights_m": [1.8, 1.8, 1.8, 1.8, 1.8],
                  "windows_per_floor": [3, 3, 3, 3, 3]}
        result, fixes = fix_building(params, "test.json")
        assert result["floors"] < 5
        assert abs(sum(result["floor_heights_m"]) - 9.0) < 0.01

    def test_recalcs_oversized_per_floor(self):
        params = {"floors": 3, "total_height_m": 25.0,
                  "floor_heights_m": [5.0, 10.0, 10.0]}
        result, fixes = fix_building(params, "test.json")
        assert max(result["floor_heights_m"]) < 10.0
        assert abs(sum(result["floor_heights_m"]) - 25.0) < 0.01

    def test_leaves_normal_building_alone(self):
        params = {"floors": 2, "total_height_m": 7.0,
                  "floor_heights_m": [3.5, 3.5], "condition": "good"}
        result, fixes = fix_building(params, "test.json")
        assert fixes == []
        assert result["floor_heights_m"] == [3.5, 3.5]

    def test_no_crash_on_missing_fields(self):
        params = {"building_name": "Minimal"}
        result, fixes = fix_building(params, "test.json")
        assert fixes == []


class TestRunBatch:
    def test_fixes_and_writes(self, tmp_path):
        params_dir = tmp_path / "params"
        params_dir.mkdir()

        # One good, one bad
        good = {"building_name": "Good", "floors": 2,
                "total_height_m": 7.0, "floor_heights_m": [3.5, 3.5],
                "_meta": {"address": "Good"}}
        (params_dir / "Good.json").write_text(
            json.dumps(good), encoding="utf-8"
        )

        bad = {"building_name": "Bad", "floors": 1,
               "total_height_m": 15.0, "floor_heights_m": [15.0],
               "windows_per_floor": [3],
               "_meta": {"address": "Bad"}}
        (params_dir / "Bad.json").write_text(
            json.dumps(bad), encoding="utf-8"
        )

        stats = run(params_dir)
        assert stats["fixed"] == 1
        assert stats["total"] == 2

        # Check Bad was fixed on disk
        fixed = json.loads((params_dir / "Bad.json").read_text(encoding="utf-8"))
        assert fixed["floors"] > 1
        assert len(fixed["floor_heights_m"]) == fixed["floors"]
        assert "anomaly_fixes" in fixed["_meta"]

    def test_dry_run_no_write(self, tmp_path):
        params_dir = tmp_path / "params"
        params_dir.mkdir()

        bad = {"building_name": "Bad", "floors": 1,
               "total_height_m": 12.0, "floor_heights_m": [12.0],
               "_meta": {"address": "Bad"}}
        (params_dir / "Bad.json").write_text(
            json.dumps(bad), encoding="utf-8"
        )

        stats = run(params_dir, dry_run=True)
        assert stats["fixed"] == 1

        # Original unchanged
        orig = json.loads((params_dir / "Bad.json").read_text(encoding="utf-8"))
        assert orig["floors"] == 1

    def test_idempotent(self, tmp_path):
        params_dir = tmp_path / "params"
        params_dir.mkdir()

        bad = {"building_name": "Bad", "floors": 1,
               "total_height_m": 15.0, "floor_heights_m": [15.0],
               "windows_per_floor": [3],
               "_meta": {"address": "Bad"}}
        (params_dir / "Bad.json").write_text(
            json.dumps(bad), encoding="utf-8"
        )

        # Run twice
        run(params_dir)
        stats2 = run(params_dir)
        assert stats2["fixed"] == 0
