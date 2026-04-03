"""Tests for Stage 9 VERIFY: visual_regression.py.

Tests image comparison logic with synthetic images, verifying score ranges,
status classification, report JSON structure, and exit code behavior.
"""

import json
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

# Ensure scripts/verify/ is importable
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts" / "verify"))

from visual_regression import (
    _compute_ssim,
    _load_image_as_array,
    collect_png_files,
    run_regression,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_solid_png(directory, filename, colour=128, size=(64, 64)):
    """Create a solid-colour PNG image. Returns the file path."""
    path = directory / filename
    directory.mkdir(parents=True, exist_ok=True)
    arr = np.full((size[1], size[0]), colour, dtype=np.uint8)
    img = Image.fromarray(arr, mode="L")
    img.save(path)
    return path


def _create_gradient_png(directory, filename, size=(64, 64)):
    """Create a gradient PNG image. Returns the file path."""
    path = directory / filename
    directory.mkdir(parents=True, exist_ok=True)
    w, h = size
    arr = np.zeros((h, w), dtype=np.uint8)
    for y in range(h):
        arr[y, :] = int(y / h * 255)
    img = Image.fromarray(arr, mode="L")
    img.save(path)
    return path


def _create_noise_png(directory, filename, size=(64, 64)):
    """Create a random noise PNG image. Returns the file path."""
    path = directory / filename
    directory.mkdir(parents=True, exist_ok=True)
    arr = np.random.randint(0, 256, (size[1], size[0]), dtype=np.uint8)
    img = Image.fromarray(arr, mode="L")
    img.save(path)
    return path


# ---------------------------------------------------------------------------
# Test identical images -> score ~1.0, status "pass"
# ---------------------------------------------------------------------------

class TestIdenticalImages:
    def test_identical_images_score_near_one(self, tmp_path):
        renders = tmp_path / "renders"
        refs = tmp_path / "refs"

        _create_solid_png(renders, "building_a.png", colour=128)
        _create_solid_png(refs, "building_a.png", colour=128)

        summary, results = run_regression(renders, refs, threshold=0.85)
        assert len(results) == 1

        r = results[0]
        assert r["status"] == "pass"
        assert r["score"] is not None
        assert r["score"] >= 0.99

    def test_identical_gradient_images(self, tmp_path):
        renders = tmp_path / "renders"
        refs = tmp_path / "refs"

        _create_gradient_png(renders, "facade.png")
        _create_gradient_png(refs, "facade.png")

        summary, results = run_regression(renders, refs, threshold=0.85)
        assert results[0]["status"] == "pass"
        assert results[0]["score"] >= 0.99


# ---------------------------------------------------------------------------
# Test different images -> lower score, status "regression"
# ---------------------------------------------------------------------------

class TestDifferentImages:
    def test_very_different_images_regression(self, tmp_path):
        renders = tmp_path / "renders"
        refs = tmp_path / "refs"

        _create_solid_png(renders, "building_b.png", colour=0)
        _create_solid_png(refs, "building_b.png", colour=255)

        summary, results = run_regression(renders, refs, threshold=0.85)
        r = results[0]
        assert r["status"] == "regression"
        assert r["score"] is not None
        assert r["score"] < 0.85

    def test_noise_vs_solid_regression(self, tmp_path):
        renders = tmp_path / "renders"
        refs = tmp_path / "refs"

        _create_noise_png(renders, "noisy.png")
        _create_solid_png(refs, "noisy.png", colour=128)

        summary, results = run_regression(renders, refs, threshold=0.85)
        r = results[0]
        # Noise vs solid should produce a low score
        assert r["score"] is not None
        assert r["score"] < 0.85


# ---------------------------------------------------------------------------
# Test new file (render exists, no reference)
# ---------------------------------------------------------------------------

class TestNewFile:
    def test_new_render_no_reference(self, tmp_path):
        renders = tmp_path / "renders"
        refs = tmp_path / "refs"
        refs.mkdir()

        _create_solid_png(renders, "new_building.png")

        summary, results = run_regression(renders, refs, threshold=0.85)
        assert len(results) == 1
        assert results[0]["status"] == "new"
        assert results[0]["score"] is None
        assert summary["new"] == 1


# ---------------------------------------------------------------------------
# Test missing file (reference exists, no render)
# ---------------------------------------------------------------------------

class TestMissingFile:
    def test_missing_render(self, tmp_path):
        renders = tmp_path / "renders"
        refs = tmp_path / "refs"
        renders.mkdir()

        _create_solid_png(refs, "old_building.png")

        summary, results = run_regression(renders, refs, threshold=0.85)
        assert len(results) == 1
        assert results[0]["status"] == "missing"
        assert results[0]["score"] is None
        assert summary["missing"] == 1


# ---------------------------------------------------------------------------
# Test report JSON structure
# ---------------------------------------------------------------------------

class TestReportStructure:
    def test_summary_has_all_keys(self, tmp_path):
        renders = tmp_path / "renders"
        refs = tmp_path / "refs"

        _create_solid_png(renders, "a.png", colour=128)
        _create_solid_png(refs, "a.png", colour=128)
        _create_solid_png(renders, "b.png", colour=0)
        _create_solid_png(refs, "b.png", colour=255)
        _create_solid_png(renders, "new_only.png")
        _create_solid_png(refs, "missing_only.png")

        summary, results = run_regression(renders, refs, threshold=0.85)

        # Check summary keys
        assert "total" in summary
        assert "passed" in summary
        assert "regressions" in summary
        assert "new" in summary
        assert "missing" in summary
        assert "avg_score" in summary

        assert summary["total"] == 4
        assert summary["passed"] >= 1
        assert summary["new"] == 1
        assert summary["missing"] == 1

    def test_result_entries_have_expected_fields(self, tmp_path):
        renders = tmp_path / "renders"
        refs = tmp_path / "refs"

        _create_solid_png(renders, "test.png", colour=128)
        _create_solid_png(refs, "test.png", colour=128)

        _, results = run_regression(renders, refs, threshold=0.85)
        assert len(results) == 1

        r = results[0]
        assert "file" in r
        assert "score" in r
        assert "status" in r
        assert r["file"] == "test.png"

    def test_results_sorted_regressions_first(self, tmp_path):
        renders = tmp_path / "renders"
        refs = tmp_path / "refs"

        # Pass
        _create_solid_png(renders, "good.png", colour=128)
        _create_solid_png(refs, "good.png", colour=128)
        # Regression
        _create_solid_png(renders, "bad.png", colour=0)
        _create_solid_png(refs, "bad.png", colour=255)

        _, results = run_regression(renders, refs, threshold=0.85)
        # Regressions should come first
        assert results[0]["status"] == "regression"
        assert results[1]["status"] == "pass"


# ---------------------------------------------------------------------------
# Test exit code logic (1 when regressions found)
# ---------------------------------------------------------------------------

class TestExitCode:
    def test_no_regressions_exit_zero(self, tmp_path):
        renders = tmp_path / "renders"
        refs = tmp_path / "refs"

        _create_solid_png(renders, "ok.png", colour=128)
        _create_solid_png(refs, "ok.png", colour=128)

        summary, _ = run_regression(renders, refs, threshold=0.85)
        # Exit code logic: exit 1 if regressions > 0
        exit_code = 1 if summary["regressions"] > 0 else 0
        assert exit_code == 0

    def test_regressions_exit_one(self, tmp_path):
        renders = tmp_path / "renders"
        refs = tmp_path / "refs"

        _create_solid_png(renders, "regressed.png", colour=0)
        _create_solid_png(refs, "regressed.png", colour=255)

        summary, _ = run_regression(renders, refs, threshold=0.85)
        exit_code = 1 if summary["regressions"] > 0 else 0
        assert exit_code == 1

    def test_mixed_results_exit_one_on_regression(self, tmp_path):
        renders = tmp_path / "renders"
        refs = tmp_path / "refs"

        # Good match
        _create_solid_png(renders, "pass.png", colour=128)
        _create_solid_png(refs, "pass.png", colour=128)
        # Bad match
        _create_solid_png(renders, "fail.png", colour=0)
        _create_solid_png(refs, "fail.png", colour=255)

        summary, _ = run_regression(renders, refs, threshold=0.85)
        exit_code = 1 if summary["regressions"] > 0 else 0
        assert exit_code == 1


# ---------------------------------------------------------------------------
# Helper function tests
# ---------------------------------------------------------------------------

class TestHelpers:
    def test_collect_png_files(self, tmp_path):
        _create_solid_png(tmp_path, "a.png")
        _create_solid_png(tmp_path, "b.png")
        (tmp_path / "not_a_png.txt").write_text("hello", encoding="utf-8")

        files = collect_png_files(tmp_path)
        assert len(files) == 2
        assert "a.png" in files
        assert "b.png" in files
        assert "not_a_png.txt" not in files

    def test_collect_png_files_empty_dir(self, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        files = collect_png_files(empty)
        assert files == {}

    def test_collect_png_files_nonexistent_dir(self, tmp_path):
        files = collect_png_files(tmp_path / "nope")
        assert files == {}

    def test_load_image_as_array(self, tmp_path):
        _create_gradient_png(tmp_path, "test.png", size=(64, 64))
        arr = _load_image_as_array(tmp_path / "test.png")
        # Should be resized to 256x256
        assert arr.shape == (256, 256)
        assert arr.dtype == np.float64

    def test_compute_ssim_identical(self, tmp_path):
        arr = np.full((256, 256), 128.0, dtype=np.float64)
        score = _compute_ssim(arr, arr)
        assert score >= 0.99

    def test_compute_ssim_different(self, tmp_path):
        a = np.zeros((256, 256), dtype=np.float64)
        b = np.full((256, 256), 255.0, dtype=np.float64)
        score = _compute_ssim(a, b)
        assert score < 0.5
