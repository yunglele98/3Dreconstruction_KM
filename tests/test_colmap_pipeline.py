"""Tests for COLMAP pipeline shared utilities and integration scripts."""

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts" / "reconstruct"))

from _colmap import (
    find_colmap,
    acquire_gpu_lock,
    release_gpu_lock,
    validate_sparse_model,
)


class TestFindColmap:
    def test_returns_string_or_none(self):
        result = find_colmap()
        assert result is None or isinstance(result, str)


class TestGpuLock:
    def test_acquire_and_release(self, tmp_path, monkeypatch):
        lock_file = tmp_path / ".gpu_lock"
        monkeypatch.setattr("_colmap.GPU_LOCK", lock_file)

        assert acquire_gpu_lock("test")
        assert lock_file.exists()

        info = json.loads(lock_file.read_text(encoding="utf-8"))
        assert info["holder"] == "test"

        release_gpu_lock()
        assert not lock_file.exists()

    def test_double_acquire_fails(self, tmp_path, monkeypatch):
        lock_file = tmp_path / ".gpu_lock"
        monkeypatch.setattr("_colmap.GPU_LOCK", lock_file)

        assert acquire_gpu_lock("first")
        assert not acquire_gpu_lock("second")

        release_gpu_lock()

    def test_release_without_lock(self, tmp_path, monkeypatch):
        lock_file = tmp_path / ".gpu_lock"
        monkeypatch.setattr("_colmap.GPU_LOCK", lock_file)
        release_gpu_lock()  # Should not raise


class TestValidateSparseModel:
    def test_empty_dir(self, tmp_path):
        result = validate_sparse_model(tmp_path)
        assert result["valid"] is False

    def test_valid_text_model(self, tmp_path):
        (tmp_path / "cameras.txt").write_text("# Camera list\n1 SIMPLE_PINHOLE 1920 1080 1500 960 540\n")
        (tmp_path / "images.txt").write_text(
            "# Image list\n"
            "1 0 0 0 1 0 0 0 1 img1.jpg\n0.5 0.5 1\n"
            "2 0 0 0 1 0 0 0 1 img2.jpg\n0.6 0.6 2\n"
        )
        (tmp_path / "points3D.txt").write_text(
            "# Point3D list\n"
            "1 1.0 2.0 3.0 128 128 128 0.5 1 1\n"
            "2 4.0 5.0 6.0 200 200 200 0.3 2 2\n"
        )

        result = validate_sparse_model(tmp_path)
        assert result["valid"] is True
        assert result["format"] == "text"
        assert result["images"] == 2
        assert result["points"] == 2

    def test_valid_binary_model(self, tmp_path):
        (tmp_path / "cameras.bin").write_bytes(b"\x00")
        (tmp_path / "images.bin").write_bytes(b"\x00")
        (tmp_path / "points3D.bin").write_bytes(b"\x00")

        result = validate_sparse_model(tmp_path)
        assert result["valid"] is True
        assert result["format"] == "binary"


class TestClipBlockMesh:
    """Test point cloud clipping from clip_block_mesh.py."""

    def test_clip_ply_basic(self, tmp_path):
        from clip_block_mesh import clip_point_cloud_to_polygon

        # Create a simple PLY with 4 points
        ply_content = (
            "ply\nformat ascii 1.0\n"
            "element vertex 4\n"
            "property float x\nproperty float y\nproperty float z\n"
            "end_header\n"
            "0.0 0.0 0.0\n"
            "1.0 1.0 0.0\n"
            "5.0 5.0 0.0\n"
            "10.0 10.0 0.0\n"
        )
        ply_path = tmp_path / "block.ply"
        ply_path.write_text(ply_content, encoding="utf-8")

        # Polygon covering only the first two points
        polygon = [[-.5, -.5], [2.5, -.5], [2.5, 2.5], [-.5, 2.5]]

        output = tmp_path / "clipped.ply"
        result = clip_point_cloud_to_polygon(ply_path, polygon, output)

        assert result["status"] == "clipped"
        assert result["input_vertices"] == 4
        assert result["output_vertices"] == 2
        assert output.exists()

    def test_clip_no_matches(self, tmp_path):
        from clip_block_mesh import clip_point_cloud_to_polygon

        ply_content = (
            "ply\nformat ascii 1.0\n"
            "element vertex 2\n"
            "property float x\nproperty float y\nproperty float z\n"
            "end_header\n"
            "100.0 100.0 0.0\n"
            "200.0 200.0 0.0\n"
        )
        ply_path = tmp_path / "block.ply"
        ply_path.write_text(ply_content, encoding="utf-8")

        polygon = [[0, 0], [1, 0], [1, 1], [0, 1]]
        output = tmp_path / "clipped.ply"
        result = clip_point_cloud_to_polygon(ply_path, polygon, output)

        assert result["status"] == "no_points_in_footprint"

    def test_clip_block_dry_run(self, tmp_path):
        from clip_block_mesh import clip_block

        ply_path = tmp_path / "block.ply"
        ply_path.write_text("ply\n", encoding="utf-8")

        footprints = [
            {"address": "22 Test St", "polygon": [[0, 0], [1, 0], [1, 1], [0, 1]]},
        ]
        results = clip_block(ply_path, footprints, tmp_path / "out", dry_run=True)
        assert len(results) == 1
        assert results[0]["status"] == "would_clip"


class TestSelectCandidatesIntegration:
    """Test that select_candidates output feeds into run_photogrammetry."""

    def test_candidates_format_matches_photogrammetry_input(self, tmp_path):
        from select_candidates import select_candidates

        params_dir = tmp_path / "params"
        params_dir.mkdir()
        idx = tmp_path / "index.csv"

        p = {
            "_meta": {"address": "22 Test St"},
            "site": {"street": "Test St"},
            "hcd_data": {"contributing": "Yes"},
        }
        (params_dir / "22_Test_St.json").write_text(
            json.dumps(p), encoding="utf-8"
        )
        idx.write_text(
            "filename,address_or_location,source\n"
            "IMG_1.jpg,22 Test St,confirmed\n"
            "IMG_2.jpg,22 Test St,confirmed\n"
            "IMG_3.jpg,22 Test St,confirmed\n",
            encoding="utf-8",
        )

        candidates = select_candidates(params_dir, idx, tmp_path / "audit.json", min_views=3)

        assert len(candidates) == 1
        c = candidates[0]

        # Verify all fields expected by run_photogrammetry.py
        assert "address" in c
        assert "photos" in c
        assert isinstance(c["photos"], list)
        assert "photo_count" in c
        assert c["photo_count"] >= 3
        assert "contributing" in c
        assert "street" in c
