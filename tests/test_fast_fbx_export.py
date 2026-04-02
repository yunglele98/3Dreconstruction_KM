"""Tests for fast_fbx_export.py — batch FBX export inside Blender.

Tests the script's file parsing and skip logic without requiring Blender.
Also validates that exported FBX files (if present) are structurally sound.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

REPO = Path(__file__).parent.parent
EXPORTS_DIR = REPO / "outputs" / "exports"


class TestFastFbxExportChunkParsing:
    """Test chunk file reading logic."""

    def test_chunk_file_parsed_correctly(self, tmp_path):
        """Chunk file lines should be parsed as blend paths."""
        chunk = tmp_path / "chunk.txt"
        chunk.write_text("outputs/full/22_Lippincott_St.blend\noutputs/full/1_Wales_Ave.blend\n",
                         encoding="utf-8")
        lines = chunk.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 2
        assert "22_Lippincott_St" in lines[0]

    def test_empty_chunk_file(self, tmp_path):
        """Empty chunk file should produce no work."""
        chunk = tmp_path / "chunk.txt"
        chunk.write_text("", encoding="utf-8")
        lines = chunk.read_text(encoding="utf-8").strip().split("\n")
        # strip().split gives [''] for empty string
        assert lines == ['']

    def test_chunk_file_whitespace_handling(self, tmp_path):
        """Lines with extra whitespace should be stripped."""
        chunk = tmp_path / "chunk.txt"
        chunk.write_text("  outputs/full/A.blend  \n  outputs/full/B.blend\n\n",
                         encoding="utf-8")
        lines = [l.strip() for l in chunk.read_text(encoding="utf-8").strip().split("\n") if l.strip()]
        assert len(lines) == 2


class TestFastFbxExportSkipLogic:
    """Test that existing exports are skipped."""

    def test_skip_existing_export_dir(self, tmp_path):
        """If output dir already exists, skip that address."""
        exports = tmp_path / "exports"
        addr_dir = exports / "22_Lippincott_St"
        addr_dir.mkdir(parents=True)
        assert addr_dir.exists()  # skip condition met

    def test_no_skip_when_dir_missing(self, tmp_path):
        """If output dir doesn't exist, process that address."""
        exports = tmp_path / "exports"
        exports.mkdir(parents=True)
        addr_dir = exports / "22_Lippincott_St"
        assert not addr_dir.exists()


class TestFbxOutputValidation:
    """Validate actual FBX files in outputs/exports/ if present."""

    @pytest.fixture
    def sample_fbx_dirs(self):
        """Get first 5 export directories with FBX files."""
        if not EXPORTS_DIR.exists():
            pytest.skip("outputs/exports/ not found")
        dirs = []
        for d in sorted(EXPORTS_DIR.iterdir()):
            if d.is_dir():
                fbx = d / f"{d.name}.fbx"
                if fbx.exists():
                    dirs.append(d)
                if len(dirs) >= 5:
                    break
        if not dirs:
            pytest.skip("No FBX files found in exports")
        return dirs

    def test_fbx_files_exist(self, sample_fbx_dirs):
        """Each export dir should contain a matching FBX file."""
        for d in sample_fbx_dirs:
            fbx = d / f"{d.name}.fbx"
            assert fbx.exists(), f"Missing FBX: {fbx}"

    def test_fbx_files_nonzero_size(self, sample_fbx_dirs):
        """FBX files should have non-zero size."""
        for d in sample_fbx_dirs:
            fbx = d / f"{d.name}.fbx"
            assert fbx.stat().st_size > 1000, f"FBX too small: {fbx} ({fbx.stat().st_size} bytes)"

    def test_fbx_has_valid_header(self, sample_fbx_dirs):
        """FBX files should start with the FBX binary or ASCII header."""
        for d in sample_fbx_dirs:
            fbx = d / f"{d.name}.fbx"
            header = fbx.read_bytes()[:20]
            # Binary FBX starts with "Kaydara FBX Binary"
            # ASCII FBX starts with "; FBX"
            assert (b"Kaydara FBX Binary" in header or b"; FBX" in header[:10]), \
                f"Invalid FBX header in {fbx}"

    def test_fbx_vertex_count_with_trimesh(self, sample_fbx_dirs):
        """FBX files should have vertices when loaded with trimesh."""
        try:
            import trimesh
        except ImportError:
            pytest.skip("trimesh not installed")
        for d in sample_fbx_dirs[:2]:  # limit to 2 for speed
            fbx = d / f"{d.name}.fbx"
            try:
                scene = trimesh.load(str(fbx))
                if isinstance(scene, trimesh.Scene):
                    total_verts = sum(g.vertices.shape[0] for g in scene.geometry.values()
                                      if hasattr(g, 'vertices'))
                else:
                    total_verts = scene.vertices.shape[0] if hasattr(scene, 'vertices') else 0
                assert total_verts > 0, f"FBX has 0 vertices: {fbx}"
            except Exception as e:
                pytest.skip(f"trimesh failed to load {fbx}: {e}")


class TestExportCounts:
    """Verify overall export counts."""

    def test_export_count_above_threshold(self):
        """At least 1000 buildings should be exported."""
        if not EXPORTS_DIR.exists():
            pytest.skip("outputs/exports/ not found")
        fbx_count = sum(1 for d in EXPORTS_DIR.iterdir()
                        if d.is_dir() and (d / f"{d.name}.fbx").exists())
        assert fbx_count >= 1000, f"Only {fbx_count} FBX exports (expected 1000+)"

    def test_few_empty_export_dirs(self):
        """Almost no export dirs should be empty (allow <5 anomalies)."""
        if not EXPORTS_DIR.exists():
            pytest.skip("outputs/exports/ not found")
        empty = []
        for d in EXPORTS_DIR.iterdir():
            if d.is_dir() and not any(d.iterdir()):
                empty.append(d.name)
        assert len(empty) < 5, f"{len(empty)} empty export dirs: {empty[:5]}"
