"""Tests for Stage 3 ENRICH fusion scripts: fuse_depth, fuse_segmentation,
fuse_lidar, fuse_photogrammetry, fuse_signage.

Each test creates minimal param files and mock data files, then verifies
fusion results, _meta.fusion_applied tracking, idempotency, and skip logic.
"""

import json
import struct
import sys
from pathlib import Path

import numpy as np
import pytest

# Ensure scripts/enrich/ is importable
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts" / "enrich"))

from fuse_depth import fuse_depth
from fuse_segmentation import fuse_segmentation
from fuse_lidar import fuse_lidar
from fuse_photogrammetry import fuse_photogrammetry
from fuse_signage import fuse_signage


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def create_test_param_file(temp_dir, filename, content):
    """Write a JSON param file and return its path."""
    filepath = temp_dir / filename
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(content, f, indent=2)
    return filepath


def _load_param(filepath):
    """Load and return a param JSON dict."""
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


def _make_minimal_param():
    """Return a minimal building param dict."""
    return {
        "building_name": "Test Building",
        "floors": 2,
        "_meta": {},
    }


def _make_skipped_param():
    """Return a skipped (non-building) param dict."""
    return {
        "building_name": "Street mural photo",
        "skipped": True,
        "skip_reason": "Not a building",
        "_meta": {},
    }


def _create_npy_depth(depth_dir, stem, shape=(64, 64)):
    """Create a synthetic .npy depth map file."""
    arr = np.random.rand(*shape).astype(np.float32)
    np.save(depth_dir / f"{stem}.npy", arr)


def _create_segmentation_json(seg_dir, stem):
    """Create a synthetic segmentation elements JSON file."""
    data = {
        "image": f"{stem}.png",
        "method": "fallback-edge-detection",
        "width": 64,
        "height": 64,
        "elements": [
            {"class": "window", "confidence": 0.8, "bbox": [10, 10, 30, 30]},
            {"class": "window", "confidence": 0.7, "bbox": [35, 10, 55, 30]},
            {"class": "door", "confidence": 0.6, "bbox": [20, 40, 40, 60]},
        ],
    }
    path = seg_dir / f"{stem}_elements.json"
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _create_fake_las(lidar_dir, stem):
    """Create a minimal LAS 1.2 file header with known Z bounds."""
    path = lidar_dir / f"{stem}.las"
    with open(path, "wb") as f:
        # Build a 375-byte LAS header (>= 235 required by _read_las_header_stats)
        header = bytearray(375)
        # Signature
        header[0:4] = b"LASF"
        # Version 1.2
        header[24] = 1  # major
        header[25] = 2  # minor
        # Point count at offset 107
        struct.pack_into("<I", header, 107, 100)
        # Scale factors at offset 131 (x,y,z)
        struct.pack_into("<3d", header, 131, 1.0, 1.0, 1.0)
        # Offsets at offset 155 (x,y,z)
        struct.pack_into("<3d", header, 155, 0.0, 0.0, 0.0)
        # Max X, Min X, Max Y, Min Y, Max Z, Min Z at offset 179
        struct.pack_into("<6d", header, 179,
                         10.0, 0.0,   # max_x, min_x
                         8.0, 0.0,    # max_y, min_y
                         9.5, 0.0)    # max_z, min_z
        f.write(header)


def _create_fake_obj(mesh_dir, stem):
    """Create a minimal OBJ mesh file."""
    path = mesh_dir / f"{stem}.obj"
    lines = [
        "v 0.0 0.0 0.0",
        "v 1.0 0.0 0.0",
        "v 1.0 1.0 0.0",
        "v 0.0 1.0 0.0",
        "f 1 2 3 4",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def _create_signage_json(signage_dir, stem):
    """Create a synthetic signage OCR JSON file."""
    data = {
        "image": f"{stem}.png",
        "method": "paddleocr",
        "texts": ["FANCY BAKERY", "OPEN 9-5"],
    }
    path = signage_dir / f"{stem}_signage.json"
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# fuse_depth tests
# ---------------------------------------------------------------------------

class TestFuseDepth:
    def test_fuse_depth_basic(self, tmp_path):
        params_dir = tmp_path / "params"
        depth_dir = tmp_path / "depth_maps"
        params_dir.mkdir()
        depth_dir.mkdir()

        create_test_param_file(params_dir, "22_Lippincott_St.json", _make_minimal_param())
        _create_npy_depth(depth_dir, "22_Lippincott_St")

        fuse_depth(depth_dir, params_dir)

        data = _load_param(params_dir / "22_Lippincott_St.json")
        assert "depth" in data["_meta"]["fusion_applied"]
        assert "depth_observations" in data
        assert "depth_range" in data["depth_observations"]
        assert "source_file" in data["depth_observations"]

    def test_fuse_depth_idempotency(self, tmp_path):
        params_dir = tmp_path / "params"
        depth_dir = tmp_path / "depth_maps"
        params_dir.mkdir()
        depth_dir.mkdir()

        create_test_param_file(params_dir, "10_Augusta_Ave.json", _make_minimal_param())
        _create_npy_depth(depth_dir, "10_Augusta_Ave")

        fuse_depth(depth_dir, params_dir)
        data_first = _load_param(params_dir / "10_Augusta_Ave.json")

        fuse_depth(depth_dir, params_dir)
        data_second = _load_param(params_dir / "10_Augusta_Ave.json")

        # Should only have "depth" once in fusion_applied
        assert data_second["_meta"]["fusion_applied"].count("depth") == 1
        assert data_first["depth_observations"] == data_second["depth_observations"]

    def test_fuse_depth_skips_skipped_files(self, tmp_path):
        params_dir = tmp_path / "params"
        depth_dir = tmp_path / "depth_maps"
        params_dir.mkdir()
        depth_dir.mkdir()

        create_test_param_file(params_dir, "mural_photo.json", _make_skipped_param())
        _create_npy_depth(depth_dir, "mural_photo")

        fuse_depth(depth_dir, params_dir)

        data = _load_param(params_dir / "mural_photo.json")
        assert "depth" not in data.get("_meta", {}).get("fusion_applied", [])
        assert "depth_observations" not in data

    def test_fuse_depth_skips_metadata_files(self, tmp_path):
        params_dir = tmp_path / "params"
        depth_dir = tmp_path / "depth_maps"
        params_dir.mkdir()
        depth_dir.mkdir()

        create_test_param_file(params_dir, "_site_coordinates.json", {"origin": [0, 0]})

        fuse_depth(depth_dir, params_dir)
        # Should not crash on metadata files


# ---------------------------------------------------------------------------
# fuse_segmentation tests
# ---------------------------------------------------------------------------

class TestFuseSegmentation:
    def test_fuse_segmentation_basic(self, tmp_path):
        params_dir = tmp_path / "params"
        seg_dir = tmp_path / "segmentation"
        params_dir.mkdir()
        seg_dir.mkdir()

        create_test_param_file(params_dir, "22_Lippincott_St.json", _make_minimal_param())
        _create_segmentation_json(seg_dir, "22_Lippincott_St")

        fuse_segmentation(seg_dir, params_dir)

        data = _load_param(params_dir / "22_Lippincott_St.json")
        assert "segmentation" in data["_meta"]["fusion_applied"]
        obs = data["segmentation_observations"]
        assert obs["windows_total"] == 2
        assert obs["door_count"] == 1
        assert obs["has_storefront"] is False
        assert obs["source_file"] == "22_Lippincott_St_elements.json"

    def test_fuse_segmentation_idempotency(self, tmp_path):
        params_dir = tmp_path / "params"
        seg_dir = tmp_path / "segmentation"
        params_dir.mkdir()
        seg_dir.mkdir()

        create_test_param_file(params_dir, "15_Nassau_St.json", _make_minimal_param())
        _create_segmentation_json(seg_dir, "15_Nassau_St")

        fuse_segmentation(seg_dir, params_dir)
        fuse_segmentation(seg_dir, params_dir)

        data = _load_param(params_dir / "15_Nassau_St.json")
        assert data["_meta"]["fusion_applied"].count("segmentation") == 1

    def test_fuse_segmentation_skips_skipped(self, tmp_path):
        params_dir = tmp_path / "params"
        seg_dir = tmp_path / "segmentation"
        params_dir.mkdir()
        seg_dir.mkdir()

        create_test_param_file(params_dir, "lane_photo.json", _make_skipped_param())
        _create_segmentation_json(seg_dir, "lane_photo")

        fuse_segmentation(seg_dir, params_dir)

        data = _load_param(params_dir / "lane_photo.json")
        assert "segmentation_observations" not in data


# ---------------------------------------------------------------------------
# fuse_lidar tests
# ---------------------------------------------------------------------------

class TestFuseLidar:
    def test_fuse_lidar_basic(self, tmp_path):
        params_dir = tmp_path / "params"
        lidar_dir = tmp_path / "lidar"
        params_dir.mkdir()
        lidar_dir.mkdir()

        create_test_param_file(params_dir, "22_Lippincott_St.json", _make_minimal_param())
        _create_fake_las(lidar_dir, "22_Lippincott_St")

        fuse_lidar(lidar_dir, params_dir)

        data = _load_param(params_dir / "22_Lippincott_St.json")
        assert "lidar" in data["_meta"]["fusion_applied"]
        obs = data["lidar_observations"]
        assert obs["total_height_m"] == 9.5
        assert obs["footprint_width_m"] == 10.0
        assert obs["footprint_depth_m"] == 8.0
        assert obs["point_count"] == 100

    def test_fuse_lidar_idempotency(self, tmp_path):
        params_dir = tmp_path / "params"
        lidar_dir = tmp_path / "lidar"
        params_dir.mkdir()
        lidar_dir.mkdir()

        create_test_param_file(params_dir, "50_Kensington_Ave.json", _make_minimal_param())
        _create_fake_las(lidar_dir, "50_Kensington_Ave")

        fuse_lidar(lidar_dir, params_dir)
        fuse_lidar(lidar_dir, params_dir)

        data = _load_param(params_dir / "50_Kensington_Ave.json")
        assert data["_meta"]["fusion_applied"].count("lidar") == 1

    def test_fuse_lidar_skips_skipped(self, tmp_path):
        params_dir = tmp_path / "params"
        lidar_dir = tmp_path / "lidar"
        params_dir.mkdir()
        lidar_dir.mkdir()

        create_test_param_file(params_dir, "sign_photo.json", _make_skipped_param())
        _create_fake_las(lidar_dir, "sign_photo")

        fuse_lidar(lidar_dir, params_dir)

        data = _load_param(params_dir / "sign_photo.json")
        assert "lidar_observations" not in data


# ---------------------------------------------------------------------------
# fuse_photogrammetry tests
# ---------------------------------------------------------------------------

class TestFusePhotogrammetry:
    def test_fuse_photogrammetry_basic(self, tmp_path):
        params_dir = tmp_path / "params"
        mesh_dir = tmp_path / "meshes"
        params_dir.mkdir()
        mesh_dir.mkdir()

        create_test_param_file(params_dir, "22_Lippincott_St.json", _make_minimal_param())
        _create_fake_obj(mesh_dir, "22_Lippincott_St")

        fuse_photogrammetry(mesh_dir, params_dir)

        data = _load_param(params_dir / "22_Lippincott_St.json")
        assert "photogrammetry" in data["_meta"]["fusion_applied"]
        assert data["_meta"]["has_photogrammetric_mesh"] is True
        assert data["_meta"]["generation_method"] == "photogrammetric"
        assert "photogrammetric_mesh_stats" in data["_meta"]
        stats = data["_meta"]["photogrammetric_mesh_stats"]
        assert stats["vertex_count"] == 4
        assert stats["face_count"] == 1

    def test_fuse_photogrammetry_idempotency(self, tmp_path):
        params_dir = tmp_path / "params"
        mesh_dir = tmp_path / "meshes"
        params_dir.mkdir()
        mesh_dir.mkdir()

        create_test_param_file(params_dir, "30_Baldwin_St.json", _make_minimal_param())
        _create_fake_obj(mesh_dir, "30_Baldwin_St")

        fuse_photogrammetry(mesh_dir, params_dir)
        fuse_photogrammetry(mesh_dir, params_dir)

        data = _load_param(params_dir / "30_Baldwin_St.json")
        assert data["_meta"]["fusion_applied"].count("photogrammetry") == 1

    def test_fuse_photogrammetry_skips_skipped(self, tmp_path):
        params_dir = tmp_path / "params"
        mesh_dir = tmp_path / "meshes"
        params_dir.mkdir()
        mesh_dir.mkdir()

        create_test_param_file(params_dir, "graffiti.json", _make_skipped_param())
        _create_fake_obj(mesh_dir, "graffiti")

        fuse_photogrammetry(mesh_dir, params_dir)

        data = _load_param(params_dir / "graffiti.json")
        assert "photogrammetry" not in data.get("_meta", {}).get("fusion_applied", [])

    def test_fuse_photogrammetry_no_mesh_available(self, tmp_path):
        params_dir = tmp_path / "params"
        mesh_dir = tmp_path / "meshes"
        params_dir.mkdir()
        mesh_dir.mkdir()

        create_test_param_file(params_dir, "99_Missing_St.json", _make_minimal_param())
        # No mesh created for this address

        fuse_photogrammetry(mesh_dir, params_dir)

        data = _load_param(params_dir / "99_Missing_St.json")
        assert "photogrammetry" not in data.get("_meta", {}).get("fusion_applied", [])


# ---------------------------------------------------------------------------
# fuse_signage tests
# ---------------------------------------------------------------------------

class TestFuseSignage:
    def test_fuse_signage_basic(self, tmp_path):
        params_dir = tmp_path / "params"
        signage_dir = tmp_path / "signage"
        params_dir.mkdir()
        signage_dir.mkdir()

        create_test_param_file(params_dir, "22_Lippincott_St.json", _make_minimal_param())
        _create_signage_json(signage_dir, "22_Lippincott_St")

        fuse_signage(signage_dir, params_dir)

        data = _load_param(params_dir / "22_Lippincott_St.json")
        assert "signage" in data["_meta"]["fusion_applied"]
        assert data["context"]["business_name"] == "FANCY BAKERY"
        assert "FANCY BAKERY" in data["assessment"]["signage"]
        assert "OPEN 9-5" in data["assessment"]["signage"]

    def test_fuse_signage_idempotency(self, tmp_path):
        params_dir = tmp_path / "params"
        signage_dir = tmp_path / "signage"
        params_dir.mkdir()
        signage_dir.mkdir()

        create_test_param_file(params_dir, "5_Bellevue_Ave.json", _make_minimal_param())
        _create_signage_json(signage_dir, "5_Bellevue_Ave")

        fuse_signage(signage_dir, params_dir)
        fuse_signage(signage_dir, params_dir)

        data = _load_param(params_dir / "5_Bellevue_Ave.json")
        assert data["_meta"]["fusion_applied"].count("signage") == 1

    def test_fuse_signage_skips_skipped(self, tmp_path):
        params_dir = tmp_path / "params"
        signage_dir = tmp_path / "signage"
        params_dir.mkdir()
        signage_dir.mkdir()

        create_test_param_file(params_dir, "alley_photo.json", _make_skipped_param())
        _create_signage_json(signage_dir, "alley_photo")

        fuse_signage(signage_dir, params_dir)

        data = _load_param(params_dir / "alley_photo.json")
        assert "signage" not in data.get("_meta", {}).get("fusion_applied", [])
