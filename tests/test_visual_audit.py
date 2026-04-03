"""Tests for Phase 0 visual audit: run_full_audit.py.

Tests use synthetic render + photo pairs (small PNGs) to verify
priority_queue.json and audit_summary.json generation, graceful
handling of missing renders, and --limit behaviour.
"""

import json
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

# Ensure scripts/visual_audit/ is importable
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts" / "visual_audit"))

from run_full_audit import (
    run_audit,
    build_summary,
    find_render,
    detect_issues,
    score_to_tier,
    _compute_ssim,
    _load_image_as_array,
    load_photo_index,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_solid_png(directory, filename, colour=128, size=(64, 64)):
    """Create a small solid-colour PNG.  Returns the file path."""
    arr = np.full((*size, 3), colour, dtype=np.uint8)
    img = Image.fromarray(arr, mode="RGB")
    path = directory / filename
    img.save(path)
    return path


def _create_gradient_png(directory, filename, size=(64, 64)):
    """Create a vertical gradient PNG (different from solid)."""
    w, h = size
    arr = np.zeros((h, w, 3), dtype=np.uint8)
    for y in range(h):
        v = int(y / h * 255)
        arr[y, :] = [v, v, v]
    img = Image.fromarray(arr, mode="RGB")
    path = directory / filename
    img.save(path)
    return path


def _build_photo_index(photos_dir, addresses_and_files):
    """Build a photo_index dict mapping address -> [photo_path].

    addresses_and_files: list of (address, filename) tuples.
    Each filename must already exist in photos_dir.
    """
    index = {}
    for address, filename in addresses_and_files:
        path = photos_dir / filename
        index.setdefault(address, []).append(path)
    return index


# ---------------------------------------------------------------------------
# Unit tests for scoring helpers
# ---------------------------------------------------------------------------

class TestScoringHelpers:
    def test_detect_issues_critical(self):
        issues = detect_issues(0.10)
        assert "major_geometry_mismatch" in issues
        assert "colour_mismatch" in issues

    def test_detect_issues_acceptable(self):
        issues = detect_issues(0.80)
        assert issues == ["acceptable"]

    def test_detect_issues_medium(self):
        issues = detect_issues(0.40)
        assert "moderate_discrepancy" in issues

    def test_score_to_tier_mapping(self):
        assert score_to_tier(0.10) == "critical"
        assert score_to_tier(0.25) == "high"
        assert score_to_tier(0.40) == "medium"
        assert score_to_tier(0.55) == "low"
        assert score_to_tier(0.80) == "acceptable"

    def test_ssim_identical_images(self, tmp_path):
        path = _create_solid_png(tmp_path, "same.png", colour=100)
        arr = _load_image_as_array(path)
        score = _compute_ssim(arr, arr)
        # Identical images should score very close to 1.0
        assert score > 0.99

    def test_ssim_different_images(self, tmp_path):
        path_a = _create_solid_png(tmp_path, "white.png", colour=255)
        path_b = _create_solid_png(tmp_path, "black.png", colour=0)
        arr_a = _load_image_as_array(path_a)
        arr_b = _load_image_as_array(path_b)
        score = _compute_ssim(arr_a, arr_b)
        # Very different images should score low
        assert score < 0.5


# ---------------------------------------------------------------------------
# find_render tests
# ---------------------------------------------------------------------------

class TestFindRender:
    def test_find_exact_match(self, tmp_path):
        renders_dir = tmp_path / "renders"
        renders_dir.mkdir()
        _create_solid_png(renders_dir, "22_Lippincott_St.png")

        result = find_render("22 Lippincott St", renders_dir)
        assert result is not None
        assert result.name == "22_Lippincott_St.png"

    def test_find_render_missing(self, tmp_path):
        renders_dir = tmp_path / "renders"
        renders_dir.mkdir()

        result = find_render("99 Nonexistent Ave", renders_dir)
        assert result is None

    def test_find_render_with_suffix(self, tmp_path):
        renders_dir = tmp_path / "renders"
        renders_dir.mkdir()
        _create_solid_png(renders_dir, "10_Augusta_Ave_render.png")

        result = find_render("10 Augusta Ave", renders_dir)
        assert result is not None


# ---------------------------------------------------------------------------
# run_audit tests
# ---------------------------------------------------------------------------

class TestRunAudit:
    def test_audit_with_matching_pairs(self, tmp_path):
        photos_dir = tmp_path / "photos"
        renders_dir = tmp_path / "renders"
        photos_dir.mkdir()
        renders_dir.mkdir()

        # Create photo and render for two addresses
        _create_solid_png(photos_dir, "addr1_photo.png", colour=100)
        _create_solid_png(renders_dir, "22_Lippincott_St.png", colour=120)

        _create_gradient_png(photos_dir, "addr2_photo.png")
        _create_solid_png(renders_dir, "10_Augusta_Ave.png", colour=200)

        photo_index = {
            "22 Lippincott St": [photos_dir / "addr1_photo.png"],
            "10 Augusta Ave": [photos_dir / "addr2_photo.png"],
        }

        results = run_audit(photo_index, renders_dir)

        assert len(results) == 2
        # Results should be sorted by score (worst first)
        assert results[0]["score"] <= results[1]["score"]
        # Each result should have required fields
        for r in results:
            assert "address" in r
            assert "score" in r
            assert "tier" in r
            assert "needs" in r
            assert 0.0 <= r["score"] <= 1.0

    def test_audit_skips_missing_renders(self, tmp_path):
        photos_dir = tmp_path / "photos"
        renders_dir = tmp_path / "renders"
        photos_dir.mkdir()
        renders_dir.mkdir()

        _create_solid_png(photos_dir, "photo.png", colour=100)
        # No render created

        photo_index = {
            "99 Missing Building": [photos_dir / "photo.png"],
        }

        results = run_audit(photo_index, renders_dir)
        assert len(results) == 0  # skipped because no render exists

    def test_audit_limit_flag(self, tmp_path):
        photos_dir = tmp_path / "photos"
        renders_dir = tmp_path / "renders"
        photos_dir.mkdir()
        renders_dir.mkdir()

        # Create 5 photo-render pairs
        addresses = []
        for i in range(5):
            addr = f"{i}_Test_St"
            _create_solid_png(photos_dir, f"photo_{i}.png", colour=50 + i * 40)
            _create_solid_png(renders_dir, f"{addr}.png", colour=100 + i * 30)
            addresses.append(f"{i} Test St")

        photo_index = {
            addr: [photos_dir / f"photo_{i}.png"]
            for i, addr in enumerate(addresses)
        }

        # Without limit
        results_all = run_audit(photo_index, renders_dir)
        assert len(results_all) == 5

        # With limit=2
        results_limited = run_audit(photo_index, renders_dir, limit=2)
        assert len(results_limited) == 2


# ---------------------------------------------------------------------------
# build_summary tests
# ---------------------------------------------------------------------------

class TestBuildSummary:
    def test_summary_with_results(self):
        results = [
            {"address": "A", "score": 0.1, "tier": "critical", "needs": ["major_geometry_mismatch"]},
            {"address": "B", "score": 0.5, "tier": "medium", "needs": ["moderate_discrepancy"]},
            {"address": "C", "score": 0.9, "tier": "acceptable", "needs": ["acceptable"]},
        ]

        summary = build_summary(results)

        assert summary["total_audited"] == 3
        assert 0.0 < summary["avg_score"] < 1.0
        assert summary["min_score"] == 0.1
        assert summary["max_score"] == 0.9
        assert "tier_distribution" in summary
        assert summary["tier_distribution"]["critical"] == 1
        assert summary["tier_distribution"]["medium"] == 1
        assert summary["tier_distribution"]["acceptable"] == 1

    def test_summary_empty_results(self):
        summary = build_summary([])

        assert summary["total_audited"] == 0
        assert summary["avg_score"] == 0
        assert summary["tier_distribution"] == {}


# ---------------------------------------------------------------------------
# Integration: full audit pipeline
# ---------------------------------------------------------------------------

class TestFullAuditIntegration:
    def test_full_pipeline_writes_output_files(self, tmp_path):
        photos_dir = tmp_path / "photos"
        renders_dir = tmp_path / "renders"
        output_dir = tmp_path / "audit_output"
        photos_dir.mkdir()
        renders_dir.mkdir()
        output_dir.mkdir()

        _create_solid_png(photos_dir, "photo_a.png", colour=80)
        _create_solid_png(renders_dir, "22_Lippincott_St.png", colour=120)

        photo_index = {
            "22 Lippincott St": [photos_dir / "photo_a.png"],
        }

        results = run_audit(photo_index, renders_dir)
        summary = build_summary(results)

        # Write outputs the same way the CLI does
        priority_path = output_dir / "priority_queue.json"
        priority_path.write_text(
            json.dumps({"buildings": results}, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        summary_path = output_dir / "audit_summary.json"
        summary_path.write_text(
            json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

        assert priority_path.exists()
        assert summary_path.exists()

        pq = json.loads(priority_path.read_text(encoding="utf-8"))
        assert len(pq["buildings"]) == 1
        assert pq["buildings"][0]["address"] == "22 Lippincott St"

        sm = json.loads(summary_path.read_text(encoding="utf-8"))
        assert sm["total_audited"] == 1

    def test_load_photo_index_missing_file(self, tmp_path):
        """load_photo_index should return empty dict for missing CSV."""
        result = load_photo_index(tmp_path / "nonexistent.csv")
        assert result == {}

    def test_load_photo_index_valid_csv(self, tmp_path):
        """load_photo_index should parse a simple CSV correctly."""
        photos_dir = tmp_path / "PHOTOS KENSINGTON"
        csv_dir = photos_dir / "csv"
        photos_dir.mkdir()
        csv_dir.mkdir()

        # Create a photo file
        _create_solid_png(photos_dir, "IMG_001.png")

        # Create CSV index
        csv_path = csv_dir / "photo_address_index.csv"
        csv_path.write_text(
            "filename,address\nIMG_001.png,22 Lippincott St\n",
            encoding="utf-8",
        )

        result = load_photo_index(csv_path)
        assert "22 Lippincott St" in result
        assert len(result["22 Lippincott St"]) == 1
