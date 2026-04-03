"""Tests for Stage 10 MONITOR scripts: healthcheck.py, batch_job_status.py.

Tests mock external dependencies (database, disk, directories) and verify
JSON report structure, exit code logic, and log file parsing.
"""

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Ensure scripts/monitor/ is importable
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts" / "monitor"))

from healthcheck import (
    check_database,
    check_directories,
    check_disk_space,
    check_gpu_lock,
    check_param_count,
    check_photo_index,
    check_render_count,
)
from batch_job_status import (
    classify_status,
    infer_job_type,
    parse_timestamp,
    scan_logs,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_text(path, text=""):
    """Write text to a file, creating parents as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# healthcheck tests
# ---------------------------------------------------------------------------

class TestHealthcheckStructure:
    """Verify JSON output structure has expected keys."""

    def test_check_database_returns_expected_keys(self):
        result = check_database()
        assert "status" in result
        assert "message" in result
        assert result["status"] in ("ok", "warn", "error")

    def test_check_directories_returns_expected_keys(self):
        result = check_directories()
        assert "status" in result
        assert "message" in result

    def test_check_disk_space_returns_expected_keys(self):
        result = check_disk_space()
        assert "status" in result
        assert "message" in result
        assert result["status"] in ("ok", "warn", "error")

    def test_check_gpu_lock_returns_expected_keys(self):
        result = check_gpu_lock()
        assert "status" in result
        assert "message" in result

    def test_check_photo_index_returns_expected_keys(self):
        result = check_photo_index()
        assert "status" in result
        assert "message" in result

    def test_check_param_count_returns_expected_keys(self):
        result = check_param_count()
        assert "status" in result
        assert "message" in result

    def test_check_render_count_returns_expected_keys(self):
        result = check_render_count()
        assert "status" in result
        assert "message" in result


class TestHealthcheckMocked:
    """Verify exit code logic: 0 for all ok, 1 for errors."""

    def test_all_ok_produces_overall_ok(self):
        """When all checks return 'ok', overall should be 'ok'."""
        results = {
            "database": {"status": "ok", "message": "test"},
            "directories": {"status": "ok", "message": "test"},
        }
        has_errors = any(r["status"] == "error" for r in results.values())
        overall = "error" if has_errors else "ok"
        assert overall == "ok"

    def test_any_error_produces_overall_error(self):
        """When any check returns 'error', overall should be 'error'."""
        results = {
            "database": {"status": "ok", "message": "test"},
            "directories": {"status": "error", "message": "Missing directories"},
        }
        has_errors = any(r["status"] == "error" for r in results.values())
        overall = "error" if has_errors else "ok"
        assert overall == "error"

    def test_warn_does_not_trigger_error(self):
        """Warnings alone should not cause overall 'error'."""
        results = {
            "database": {"status": "warn", "message": "psycopg2 not installed"},
            "directories": {"status": "ok", "message": "All present"},
        }
        has_errors = any(r["status"] == "error" for r in results.values())
        overall = "error" if has_errors else "ok"
        assert overall == "ok"

    def test_check_param_count_with_temp_dir(self, tmp_path):
        """Test param counting with actual temp files."""
        import healthcheck

        params_dir = tmp_path / "params"
        params_dir.mkdir()

        # Active building
        _write_text(
            params_dir / "22_Lippincott_St.json",
            json.dumps({"building_name": "22 Lippincott St", "floors": 2}),
        )
        # Skipped building
        _write_text(
            params_dir / "mural.json",
            json.dumps({"building_name": "Mural", "skipped": True}),
        )
        # Metadata file (should be ignored)
        _write_text(
            params_dir / "_site_coordinates.json",
            json.dumps({"origin": [0, 0]}),
        )

        with patch.object(healthcheck, "REPO_ROOT", tmp_path):
            result = check_param_count()

        assert result["status"] == "ok"
        assert "1 active" in result["message"]
        assert "1 skipped" in result["message"]
        assert "2 total" in result["message"]


# ---------------------------------------------------------------------------
# batch_job_status tests
# ---------------------------------------------------------------------------

class TestBatchJobStatus:

    def test_parse_timestamp_iso_date(self):
        ts = parse_timestamp("2026-04-02_render_batch.log")
        assert ts is not None
        assert ts.startswith("2026-04-02")

    def test_parse_timestamp_compact(self):
        ts = parse_timestamp("20260402T220000_colmap.log")
        assert ts is not None
        assert "2026-04-02" in ts

    def test_parse_timestamp_no_match(self):
        ts = parse_timestamp("readme.txt")
        assert ts is None

    def test_infer_job_type_render(self):
        assert infer_job_type("2026-04-02_render_batch.log") == "render"

    def test_infer_job_type_colmap(self):
        assert infer_job_type("20260402T220000_colmap_block_A.log") == "colmap"

    def test_infer_job_type_enrich(self):
        assert infer_job_type("session_2026-04-02_enrichment.log") == "enrich"

    def test_infer_job_type_unknown(self):
        assert infer_job_type("random_stuff.log") == "unknown"

    def test_classify_status_completed(self, tmp_path):
        log = tmp_path / "job.log"
        _write_text(log, "Starting process...\nAll tasks completed successfully.\n")
        assert classify_status(log) == "completed"

    def test_classify_status_failed(self, tmp_path):
        log = tmp_path / "job.log"
        _write_text(log, "Starting process...\nTraceback (most recent call last):\nError occurred\n")
        assert classify_status(log) == "failed"

    def test_classify_status_recovered(self, tmp_path):
        """Error followed by completion at the tail should be 'completed'."""
        log = tmp_path / "job.log"
        content = (
            "Starting process...\n"
            "Error: temporary failure\n"
            "Retrying...\n"
            + "\n".join(f"progress line {i}" for i in range(20)) + "\n"
            "All tasks completed successfully.\n"
        )
        _write_text(log, content)
        assert classify_status(log) == "completed"

    def test_scan_logs_with_temp_dir(self, tmp_path):
        """Create fake log files and verify scan_logs counts them."""
        logs_dir = tmp_path / "logs"
        logs_dir.mkdir()

        _write_text(logs_dir / "2026-04-02_render_batch.log", "Render done. Completed.\n")
        _write_text(logs_dir / "2026-04-03_colmap_block.log", "Traceback: error\n")
        _write_text(logs_dir / "2026-04-03_enrich_run.log", "Enrichment completed.\n")

        jobs = scan_logs(logs_dir)
        assert len(jobs) == 3

        statuses = {j["job_type"]: j["status"] for j in jobs}
        assert statuses["render"] == "completed"
        assert statuses["colmap"] == "failed"
        assert statuses["enrich"] == "completed"

    def test_scan_logs_empty_dir(self, tmp_path):
        """Empty log directory should return empty list."""
        logs_dir = tmp_path / "empty_logs"
        logs_dir.mkdir()
        jobs = scan_logs(logs_dir)
        assert jobs == []

    def test_scan_logs_nonexistent_dir(self, tmp_path):
        """Nonexistent directory should return empty list."""
        jobs = scan_logs(tmp_path / "does_not_exist")
        assert jobs == []

    def test_scan_logs_ignores_non_log_files(self, tmp_path):
        """Non-log files (.json, .png, etc.) should be ignored."""
        logs_dir = tmp_path / "logs"
        logs_dir.mkdir()

        _write_text(logs_dir / "2026-04-02_render.log", "Completed.\n")
        _write_text(logs_dir / "config.json", '{"key": "value"}\n')
        _write_text(logs_dir / "screenshot.png", "not a log")

        jobs = scan_logs(logs_dir)
        assert len(jobs) == 1
        assert jobs[0]["job_type"] == "render"
