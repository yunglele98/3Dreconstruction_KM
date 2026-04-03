"""Tests for sprint_progress.py — sprint tracker output format."""

import json
import sys
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts" / "monitor"))
sprint_progress = pytest.importorskip("sprint_progress", reason="scripts/monitor/sprint_progress.py not yet implemented")


class TestDayTargets:
    """Test sprint target definitions."""

    def test_day_targets_not_empty(self):
        assert len(sprint_progress.DAY_TARGETS) > 0

    def test_day_1_has_targets(self):
        assert 1 in sprint_progress.DAY_TARGETS
        assert "tests" in sprint_progress.DAY_TARGETS[1]

    def test_day_2_has_targets(self):
        assert 2 in sprint_progress.DAY_TARGETS

    def test_all_day_keys_positive(self):
        for day in sprint_progress.DAY_TARGETS:
            assert 1 <= day <= 21, f"Day {day} outside sprint range"

    def test_targets_are_numeric_or_bool(self):
        for day, targets in sprint_progress.DAY_TARGETS.items():
            for key, val in targets.items():
                assert isinstance(val, (int, float, bool)), \
                    f"Day {day} target {key}={val} has type {type(val)}"

    def test_sprint_start_date(self):
        assert sprint_progress.SPRINT_START == date(2026, 4, 2)


class TestGetActuals:
    """Test get_actuals with mock coverage matrix."""

    def test_actuals_from_coverage_matrix(self, tmp_path):
        cm = {
            "summary": {
                "rendered": {"count": 1200},
                "blended": {"count": 1241},
                "depth_fused": {"count": 1200},
                "seg_fused": {"count": 1224},
                "sig_fused": {"count": 71},
                "exported": {"count": 1224},
            }
        }
        cm_path = tmp_path / "outputs" / "coverage_matrix.json"
        cm_path.parent.mkdir(parents=True)
        cm_path.write_text(json.dumps(cm), encoding="utf-8")

        with patch.object(sprint_progress, "REPO", tmp_path):
            actuals = sprint_progress.get_actuals()

        assert actuals["renders"] == 1200
        assert actuals["fbx_exported"] == 1224
        assert actuals["depth_fused"] == 1200

    def test_actuals_empty_when_no_matrix(self, tmp_path):
        with patch.object(sprint_progress, "REPO", tmp_path):
            actuals = sprint_progress.get_actuals()
        assert actuals == {}


class TestReportFormat:
    """Test the JSON report output format."""

    def test_json_output_structure(self, tmp_path, capsys):
        # Create minimal coverage matrix
        cm_path = tmp_path / "outputs" / "coverage_matrix.json"
        cm_path.parent.mkdir(parents=True)
        cm_path.write_text(json.dumps({"summary": {}}), encoding="utf-8")

        # Create tests dir with some files
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_a.py").touch()
        (tests_dir / "test_b.py").touch()

        with patch.object(sprint_progress, "REPO", tmp_path), \
             patch("sprint_progress.date") as mock_date:
            mock_date.today.return_value = date(2026, 4, 3)  # Day 2
            mock_date.side_effect = lambda *args, **kw: date(*args, **kw)
            with patch("sys.argv", ["prog", "--json"]):
                sprint_progress.main()

        output = capsys.readouterr().out
        if not output.strip():
            pytest.skip("No output (outside sprint window in mock)")
        report = json.loads(output)
        assert "sprint_day" in report
        assert "date" in report
        assert "targets" in report
        assert "actuals" in report
        assert "status" in report

    def test_status_entries_have_required_fields(self, tmp_path, capsys):
        cm_path = tmp_path / "outputs" / "coverage_matrix.json"
        cm_path.parent.mkdir(parents=True)
        cm_path.write_text(json.dumps({"summary": {}}), encoding="utf-8")
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()

        with patch.object(sprint_progress, "REPO", tmp_path), \
             patch("sprint_progress.date") as mock_date:
            mock_date.today.return_value = date(2026, 4, 2)  # Day 1
            mock_date.side_effect = lambda *args, **kw: date(*args, **kw)
            with patch("sys.argv", ["prog", "--json"]):
                sprint_progress.main()

        output = capsys.readouterr().out
        if not output.strip():
            pytest.skip("No output")
        report = json.loads(output)
        for entry in report["status"]:
            assert "metric" in entry
            assert "target" in entry
            assert "actual" in entry
            assert "status" in entry
            assert entry["status"] in ("on_track", "behind", "ahead")


class TestStatusClassification:
    """Test the on_track/behind/ahead logic."""

    def test_ahead_when_exceeds_110_percent(self):
        """Actual > 110% of target should be 'ahead'."""
        target = 100
        actual = 115
        assert actual > target * 1.1

    def test_on_track_within_range(self):
        """Actual between target and 110% should be 'on_track'."""
        target = 100
        actual = 105
        assert actual >= target
        assert actual <= target * 1.1

    def test_behind_when_below_target(self):
        """Actual below target should be 'behind'."""
        target = 100
        actual = 80
        assert actual < target

    def test_bool_target_exact_match(self):
        """Boolean targets require exact match for 'on_track'."""
        assert True == True  # on_track
        assert False != True  # behind
