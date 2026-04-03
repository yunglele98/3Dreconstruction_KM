"""Tests for COLMAP analysis scripts: analyze_photo_coverage,
analyze_colmap_quality, colmap_report, analyze_sparse_model.

Each test creates synthetic temp data and verifies the analysis
functions produce correctly structured and accurate outputs.
"""

import json
import struct
import sys
from pathlib import Path

import pytest

# Ensure scripts/reconstruct/ is importable
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts" / "reconstruct"))

from analyze_photo_coverage import (
    load_photo_index,
    load_active_buildings,
    classify_coverage,
)
from analyze_colmap_quality import find_workspaces, analyze_workspace
from colmap_report import generate_report
from analyze_sparse_model import analyze_model


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_photo_index_csv(directory, rows):
    """Create a photo_address_index.csv with given (address, filename) rows."""
    csv_path = directory / "photo_address_index.csv"
    lines = ["address_or_location,filename"]
    for addr, fname in rows:
        lines.append(f"{addr},{fname}")
    csv_path.write_text("\n".join(lines), encoding="utf-8")
    return csv_path


def _create_param_file(params_dir, address, extra=None):
    """Create a minimal param JSON file for a given address."""
    stem = address.replace(" ", "_")
    data = {
        "building_name": address,
        "_meta": {"address": address, "source": "test"},
    }
    if extra:
        data.update(extra)
    path = params_dir / f"{stem}.json"
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path


def _write_empty_colmap_bin(model_dir):
    """Write minimal COLMAP binary model files with 0 entries each."""
    model_dir.mkdir(parents=True, exist_ok=True)
    (model_dir / "cameras.bin").write_bytes(struct.pack("<Q", 0))
    (model_dir / "images.bin").write_bytes(struct.pack("<Q", 0))
    (model_dir / "points3D.bin").write_bytes(struct.pack("<Q", 0))


# ---------------------------------------------------------------------------
# test_analyze_photo_coverage
# ---------------------------------------------------------------------------

class TestAnalyzePhotoCoverage:
    def test_load_photo_index_counts(self, tmp_path):
        """Create 5 addresses with varying photo counts, verify index counts."""
        csv_dir = tmp_path / "csv"
        csv_dir.mkdir()

        photo_rows = [
            ("20 Augusta Ave", "photo_20a.jpg"),        # 1 photo
            ("30 Augusta Ave", "photo_30a.jpg"),         # 2 photos
            ("30 Augusta Ave", "photo_30b.jpg"),
            ("40 Augusta Ave", "photo_40a.jpg"),         # 4 photos
            ("40 Augusta Ave", "photo_40b.jpg"),
            ("40 Augusta Ave", "photo_40c.jpg"),
            ("40 Augusta Ave", "photo_40d.jpg"),
            ("50 Augusta Ave", "photo_50a.jpg"),         # 7 photos
            ("50 Augusta Ave", "photo_50b.jpg"),
            ("50 Augusta Ave", "photo_50c.jpg"),
            ("50 Augusta Ave", "photo_50d.jpg"),
            ("50 Augusta Ave", "photo_50e.jpg"),
            ("50 Augusta Ave", "photo_50f.jpg"),
            ("50 Augusta Ave", "photo_50g.jpg"),
        ]

        csv_path = _create_photo_index_csv(csv_dir, photo_rows)
        photo_index = load_photo_index(csv_path)

        assert len(photo_index["20 Augusta Ave"]) == 1
        assert len(photo_index["30 Augusta Ave"]) == 2
        assert len(photo_index["40 Augusta Ave"]) == 4
        assert len(photo_index["50 Augusta Ave"]) == 7
        # 10 Augusta not in CSV
        assert "10 Augusta Ave" not in photo_index

    def test_gap_analysis_identifies_zero_photo_buildings(self, tmp_path):
        """Buildings not in photo index should be identified as gaps."""
        csv_dir = tmp_path / "csv"
        csv_dir.mkdir()
        params_dir = tmp_path / "params"
        params_dir.mkdir()

        addresses = ["100 Bellevue Ave", "200 Bellevue Ave", "300 Bellevue Ave"]
        photo_rows = [
            ("200 Bellevue Ave", "photo_200.jpg"),
        ]

        csv_path = _create_photo_index_csv(csv_dir, photo_rows)
        for addr in addresses:
            _create_param_file(params_dir, addr)

        photo_index = load_photo_index(csv_path)
        buildings = load_active_buildings(params_dir)

        # Buildings without photos
        no_photo = [addr for addr in buildings if addr not in photo_index]
        assert "100 Bellevue Ave" in no_photo
        assert "300 Bellevue Ave" in no_photo
        assert "200 Bellevue Ave" not in no_photo
        assert len(no_photo) == 2

    def test_classify_coverage(self):
        """Verify coverage classification function."""
        assert classify_coverage(0) == "none"
        assert classify_coverage(1) == "single_angle"
        assert classify_coverage(2) == "single_angle"
        assert classify_coverage(3) == "limited"
        assert classify_coverage(5) == "limited"
        assert classify_coverage(6) == "multi_angle"
        assert classify_coverage(10) == "multi_angle"

    def test_skipped_buildings_excluded(self, tmp_path):
        """Buildings with skipped: true should not appear in active buildings."""
        params_dir = tmp_path / "params"
        params_dir.mkdir()

        _create_param_file(params_dir, "10 Active St")
        _create_param_file(params_dir, "20 Skipped St", extra={"skipped": True})

        buildings = load_active_buildings(params_dir)
        assert len(buildings) == 1
        assert "10 Active St" in buildings

    def test_missing_photo_index(self, tmp_path):
        """Missing photo index CSV should return empty defaultdict."""
        fake_path = tmp_path / "nonexistent.csv"
        result = load_photo_index(fake_path)
        assert len(result) == 0


# ---------------------------------------------------------------------------
# test_analyze_colmap_quality
# ---------------------------------------------------------------------------

class TestAnalyzeColmapQuality:
    def test_finds_all_workspaces(self, tmp_path):
        """Create 2 workspace dirs with markers, verify both are found."""
        colmap_dir = tmp_path / "colmap"
        colmap_dir.mkdir()

        # Workspace 1: has sparse directory
        ws1 = colmap_dir / "22_Lippincott_St"
        ws1.mkdir()
        (ws1 / "sparse").mkdir()

        # Workspace 2: has placeholder.json
        ws2 = colmap_dir / "44_Nassau_St"
        ws2.mkdir()
        (ws2 / "placeholder.json").write_text(
            '{"reason": "insufficient photos"}', encoding="utf-8"
        )

        workspaces = find_workspaces(colmap_dir)
        assert len(workspaces) == 2

    def test_quality_metrics_keys(self, tmp_path):
        """Verify each workspace dict has expected keys."""
        colmap_dir = tmp_path / "colmap"
        ws = colmap_dir / "test_building"
        ws.mkdir(parents=True)
        (ws / "placeholder.json").write_text("{}", encoding="utf-8")

        result = analyze_workspace(ws)

        assert "workspace" in result
        assert "status" in result
        assert "has_sparse" in result

    def test_placeholder_status(self, tmp_path):
        """Workspace with only placeholder.json should be 'placeholder'."""
        colmap_dir = tmp_path / "colmap"
        ws = colmap_dir / "placeholder_building"
        ws.mkdir(parents=True)
        (ws / "placeholder.json").write_text("{}", encoding="utf-8")

        result = analyze_workspace(ws)
        assert result["status"] == "placeholder"

    def test_no_sparse_model_status(self, tmp_path):
        """Workspace with images but no sparse model."""
        colmap_dir = tmp_path / "colmap"
        ws = colmap_dir / "images_only"
        ws.mkdir(parents=True)
        images_dir = ws / "images"
        images_dir.mkdir()
        (images_dir / "photo_01.jpg").write_bytes(b"fake jpeg")

        result = analyze_workspace(ws)
        assert result["status"] == "no_sparse_model"

    def test_workspace_with_sparse_model(self, tmp_path):
        """Workspace with sparse model should be 'analyzed'."""
        colmap_dir = tmp_path / "colmap"
        ws = colmap_dir / "good_building"
        ws.mkdir(parents=True)

        sparse = ws / "sparse" / "0"
        _write_empty_colmap_bin(sparse)

        images_dir = ws / "images"
        images_dir.mkdir()
        (images_dir / "photo_01.jpg").write_bytes(b"fake jpeg")

        result = analyze_workspace(ws)
        assert result["status"] == "analyzed"
        assert result["has_sparse"] is True

    def test_empty_colmap_dir(self, tmp_path):
        """Empty colmap dir should return empty workspace list."""
        colmap_dir = tmp_path / "empty_colmap"
        colmap_dir.mkdir()

        workspaces = find_workspaces(colmap_dir)
        assert len(workspaces) == 0

    def test_nonexistent_colmap_dir(self, tmp_path):
        """Nonexistent colmap dir should return empty workspace list."""
        colmap_dir = tmp_path / "does_not_exist"

        workspaces = find_workspaces(colmap_dir)
        assert len(workspaces) == 0


# ---------------------------------------------------------------------------
# test_colmap_report
# ---------------------------------------------------------------------------

class TestColmapReport:
    def test_report_json_structure(self, tmp_path):
        """Verify report has expected top-level keys."""
        colmap_dir = tmp_path / "colmap"
        colmap_dir.mkdir()

        ws = colmap_dir / "building_b"
        ws.mkdir()
        (ws / "placeholder.json").write_text("{}", encoding="utf-8")

        report = generate_report(colmap_dir)

        assert "generated_at" in report
        assert "colmap_dir" in report
        assert "workspaces" in report
        assert "counts" in report
        assert isinstance(report["workspaces"], list)

    def test_report_counts_correct(self, tmp_path):
        """Verify placeholder and success counts in report."""
        colmap_dir = tmp_path / "colmap"
        colmap_dir.mkdir()

        # 2 placeholder workspaces
        for name in ["placeholder_a", "placeholder_b"]:
            ws = colmap_dir / name
            ws.mkdir()
            (ws / "placeholder.json").write_text("{}", encoding="utf-8")

        # 1 analyzed workspace
        ws_good = colmap_dir / "good_building"
        ws_good.mkdir()
        sparse = ws_good / "sparse" / "0"
        _write_empty_colmap_bin(sparse)
        images_dir = ws_good / "images"
        images_dir.mkdir()
        (images_dir / "photo.jpg").write_bytes(b"fake")

        report = generate_report(colmap_dir)

        assert report["counts"]["total"] == 3
        assert report["counts"]["placeholder"] == 2
        assert report["counts"]["success"] == 1

    def test_report_empty_dir(self, tmp_path):
        """Report on empty colmap dir should produce zero counts."""
        colmap_dir = tmp_path / "empty_colmap"
        colmap_dir.mkdir()

        report = generate_report(colmap_dir)

        assert report["counts"]["total"] == 0
        assert len(report["workspaces"]) == 0

    def test_report_nonexistent_dir(self, tmp_path):
        """Report on nonexistent dir should produce zero counts gracefully."""
        colmap_dir = tmp_path / "does_not_exist"

        report = generate_report(colmap_dir)

        assert report["counts"]["total"] == 0


# ---------------------------------------------------------------------------
# test_analyze_sparse_model
# ---------------------------------------------------------------------------

class TestAnalyzeSparseModel:
    def test_nonexistent_model_dir(self, tmp_path):
        """Nonexistent model dir should return error gracefully."""
        fake_dir = tmp_path / "nonexistent_model"
        result = analyze_model(fake_dir)

        assert result["format"] is None
        assert "error" in result

    def test_empty_dir_reports_no_model_files(self, tmp_path):
        """Empty directory should report no model files found."""
        empty_dir = tmp_path / "empty_model"
        empty_dir.mkdir()

        result = analyze_model(empty_dir)

        assert result["format"] is None
        assert "error" in result

    def test_text_model_detected(self, tmp_path):
        """Directory with cameras.txt, images.txt, points3D.txt should be detected."""
        model_dir = tmp_path / "text_model"
        model_dir.mkdir()

        (model_dir / "cameras.txt").write_text(
            "# Camera list\n1 SIMPLE_PINHOLE 1920 1080 1500 960 540\n",
            encoding="utf-8",
        )
        (model_dir / "images.txt").write_text(
            "# Image list\n"
            "1 1.0 0.0 0.0 0.0 0.0 0.0 0.0 1 photo_01.jpg\n"
            "0.5 0.5 1 0.6 0.6 2\n"
            "2 1.0 0.0 0.0 0.0 1.0 2.0 3.0 1 photo_02.jpg\n"
            "0.3 0.4 1\n",
            encoding="utf-8",
        )
        (model_dir / "points3D.txt").write_text(
            "# 3D point list\n"
            "1 0.1 0.2 0.3 255 0 0 0.5 1 1 2 2\n"
            "2 0.4 0.5 0.6 0 255 0 0.3 1 3\n"
            "3 0.7 0.8 0.9 0 0 255 0.2 2 4\n",
            encoding="utf-8",
        )

        result = analyze_model(model_dir)

        assert result["format"] == "text"
        assert len(result.get("cameras", [])) == 1
        assert result["registered_images"]["count"] == 2
        assert result["point_cloud"]["total_points"] == 3
        assert "error" not in result

    def test_binary_model_empty(self, tmp_path):
        """Directory with empty binary model files should be analyzed."""
        model_dir = tmp_path / "bin_model"
        _write_empty_colmap_bin(model_dir)

        result = analyze_model(model_dir)

        assert result["format"] == "binary"
        assert len(result.get("cameras", [])) == 0
        assert result["registered_images"]["count"] == 0
        assert result["point_cloud"]["total_points"] == 0
        assert "error" not in result

    def test_unknown_format(self, tmp_path):
        """Directory with unrelated files should report error."""
        model_dir = tmp_path / "random_model"
        model_dir.mkdir()
        (model_dir / "some_file.dat").write_bytes(b"data")

        result = analyze_model(model_dir)
        assert result["format"] is None
        assert "error" in result
