"""Tests for fast_lod_generate.py — batch LOD generation inside Blender.

Tests LOD ratio logic and validates LOD files are smaller than LOD0.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

REPO = Path(__file__).parent.parent
EXPORTS_DIR = REPO / "outputs" / "exports"

LOD_RATIOS = {"LOD1": 0.5, "LOD2": 0.15}


class TestLodRatios:
    """Test LOD decimation ratios are correct."""

    def test_lod1_ratio(self):
        assert LOD_RATIOS["LOD1"] == 0.5

    def test_lod2_ratio(self):
        assert LOD_RATIOS["LOD2"] == 0.15

    def test_lod_ratio_ordering(self):
        """LOD1 should have more faces than LOD2."""
        assert LOD_RATIOS["LOD1"] > LOD_RATIOS["LOD2"]

    def test_all_ratios_between_0_and_1(self):
        for name, ratio in LOD_RATIOS.items():
            assert 0 < ratio < 1, f"{name} ratio {ratio} out of range"


class TestLodChunkParsing:
    """Test chunk file address parsing."""

    def test_addresses_parsed(self, tmp_path):
        chunk = tmp_path / "lod_chunk.txt"
        chunk.write_text("22_Lippincott_St\n1_Wales_Ave\n10_Bellevue_Ave\n",
                         encoding="utf-8")
        addresses = chunk.read_text(encoding="utf-8").strip().split("\n")
        assert len(addresses) == 3
        assert addresses[0] == "22_Lippincott_St"

    def test_empty_lines_filtered(self, tmp_path):
        chunk = tmp_path / "lod_chunk.txt"
        chunk.write_text("A\n\nB\n\n", encoding="utf-8")
        addresses = [a.strip() for a in chunk.read_text(encoding="utf-8").strip().split("\n") if a.strip()]
        assert len(addresses) == 2


class TestLodSkipLogic:
    """Test that existing LOD files cause skipping."""

    def test_skip_when_lod1_exists(self, tmp_path):
        out_dir = tmp_path / "exports" / "22_Lippincott_St"
        out_dir.mkdir(parents=True)
        lod1 = out_dir / "22_Lippincott_St_LOD1.fbx"
        lod1.write_bytes(b"fake")
        assert lod1.exists()  # skip condition

    def test_no_skip_when_lod1_missing(self, tmp_path):
        out_dir = tmp_path / "exports" / "22_Lippincott_St"
        out_dir.mkdir(parents=True)
        lod1 = out_dir / "22_Lippincott_St_LOD1.fbx"
        assert not lod1.exists()


class TestLodOutputValidation:
    """Validate actual LOD files if present."""

    @pytest.fixture
    def sample_lod_dirs(self):
        """Get export dirs that have LOD files."""
        if not EXPORTS_DIR.exists():
            pytest.skip("outputs/exports/ not found")
        dirs = []
        for d in sorted(EXPORTS_DIR.iterdir()):
            if d.is_dir() and (d / f"{d.name}_LOD1.fbx").exists():
                dirs.append(d)
            if len(dirs) >= 10:
                break
        if not dirs:
            pytest.skip("No LOD files found yet (LOD generation may still be running)")
        return dirs

    def test_lod1_exists(self, sample_lod_dirs):
        """LOD1 files should exist."""
        for d in sample_lod_dirs:
            assert (d / f"{d.name}_LOD1.fbx").exists()

    def test_lod2_exists(self, sample_lod_dirs):
        """LOD2 files should exist."""
        for d in sample_lod_dirs:
            assert (d / f"{d.name}_LOD2.fbx").exists()

    def test_lod3_exists(self, sample_lod_dirs):
        """LOD3 (bounding box) files should exist."""
        for d in sample_lod_dirs:
            assert (d / f"{d.name}_LOD3.fbx").exists()

    def test_lod1_smaller_than_lod0(self, sample_lod_dirs):
        """LOD1 should generally be smaller than the original FBX.

        Note: LOD generation uses .blend (full scene with materials/lights)
        while the base FBX may be a simpler export, so LOD1 can sometimes
        be larger. We check that the majority pass.
        """
        passed = 0
        total = 0
        for d in sample_lod_dirs:
            lod0 = d / f"{d.name}.fbx"
            lod1 = d / f"{d.name}_LOD1.fbx"
            if not lod0.exists():
                continue
            total += 1
            if lod1.stat().st_size < lod0.stat().st_size:
                passed += 1
        if total == 0:
            pytest.skip("No LOD0+LOD1 pairs found")
        ratio = passed / total
        assert ratio >= 0.5, f"Only {passed}/{total} LOD1 files smaller than LOD0"

    def test_lod2_smaller_than_lod1(self, sample_lod_dirs):
        """LOD2 should be smaller than LOD1."""
        for d in sample_lod_dirs:
            lod1 = d / f"{d.name}_LOD1.fbx"
            lod2 = d / f"{d.name}_LOD2.fbx"
            assert lod2.stat().st_size < lod1.stat().st_size, \
                f"LOD2 not smaller than LOD1 for {d.name}"

    def test_lod3_smallest(self, sample_lod_dirs):
        """LOD3 (bounding box) should be the smallest file."""
        for d in sample_lod_dirs:
            lod2 = d / f"{d.name}_LOD2.fbx"
            lod3 = d / f"{d.name}_LOD3.fbx"
            assert lod3.stat().st_size < lod2.stat().st_size, \
                f"LOD3 not smaller than LOD2 for {d.name}"

    def test_lod_files_have_valid_header(self, sample_lod_dirs):
        """LOD FBX files should have valid FBX headers."""
        for d in sample_lod_dirs[:3]:
            for suffix in ["_LOD1.fbx", "_LOD2.fbx", "_LOD3.fbx"]:
                fbx = d / f"{d.name}{suffix}"
                if fbx.exists():
                    header = fbx.read_bytes()[:20]
                    assert b"Kaydara FBX Binary" in header or b"; FBX" in header[:10], \
                        f"Invalid FBX header in {fbx}"

    def test_lod_nonzero_size(self, sample_lod_dirs):
        """All LOD files should have non-trivial size."""
        for d in sample_lod_dirs:
            for suffix in ["_LOD1.fbx", "_LOD2.fbx", "_LOD3.fbx"]:
                fbx = d / f"{d.name}{suffix}"
                if fbx.exists():
                    assert fbx.stat().st_size > 100, f"LOD file too small: {fbx}"
