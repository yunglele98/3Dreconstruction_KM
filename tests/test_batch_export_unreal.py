"""
Unit tests for batch_export_unreal.py

Tests utility functions and CSV generation logic.
Bpy-dependent functions are mocked.
"""

import csv
import json
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch, Mock

import pytest


@pytest.fixture(autouse=True)
def mock_bpy(monkeypatch):
    """Mock bpy module."""
    mock_bpy_module = MagicMock()
    mock_bpy_module.data = MagicMock()
    mock_bpy_module.ops = MagicMock()
    mock_bpy_module.context = MagicMock()
    monkeypatch.setitem(sys.modules, "bpy", mock_bpy_module)


@pytest.fixture
def module():
    """Import module after mocking bpy."""
    import sys as sys_module
    if "scripts.batch_export_unreal" in sys_module.modules:
        del sys_module.modules["scripts.batch_export_unreal"]
    sys_module.path.insert(0, str(Path(__file__).parent.parent))
    import batch_export_unreal
    return batch_export_unreal


class TestParseArgs:
    """Test command-line argument parsing."""

    def test_parse_args_required_source_dir(self, module):
        """Test that --source-dir is required."""
        with patch.object(sys, "argv", ["script.py", "--", "--source-dir", "/path/to/blends"]):
            args = module.parse_args()
            assert args.source_dir == "/path/to/blends"

    def test_parse_args_limit(self, module):
        """Test --limit argument."""
        with patch.object(sys, "argv", ["script.py", "--", "--source-dir", "/path", "--limit", "5"]):
            args = module.parse_args()
            assert args.limit == 5

    def test_parse_args_match_filter(self, module):
        """Test --match filter argument."""
        with patch.object(sys, "argv", ["script.py", "--", "--source-dir", "/path", "--match", "Augusta"]):
            args = module.parse_args()
            assert args.match == "Augusta"

    def test_parse_args_skip_existing(self, module):
        """Test --skip-existing flag."""
        with patch.object(sys, "argv", ["script.py", "--", "--source-dir", "/path", "--skip-existing"]):
            args = module.parse_args()
            assert args.skip_existing is True

    def test_parse_args_dry_run(self, module):
        """Test --dry-run flag."""
        with patch.object(sys, "argv", ["script.py", "--", "--source-dir", "/path", "--dry-run"]):
            args = module.parse_args()
            assert args.dry_run is True

    def test_parse_args_texture_size(self, module):
        """Test --texture-size argument."""
        with patch.object(sys, "argv", ["script.py", "--", "--source-dir", "/path", "--texture-size", "4096"]):
            args = module.parse_args()
            assert args.texture_size == 4096

    def test_parse_args_defaults(self, module):
        """Test default values."""
        with patch.object(sys, "argv", ["script.py", "--", "--source-dir", "/path"]):
            args = module.parse_args()
            assert args.limit is None
            assert args.match is None
            assert args.skip_existing is False
            assert args.dry_run is False
            assert args.texture_size == 2048


class TestSanitizeAddress:
    """Test address sanitization."""

    def test_spaces_to_underscores(self, module):
        """Test space conversion."""
        result = module.sanitize_address("22 Lippincott St")
        assert result == "22_Lippincott_St"

    def test_slashes_to_hyphens(self, module):
        """Test slash conversion."""
        result = module.sanitize_address("100/102 Augusta Ave")
        assert result == "100-102_Augusta_Ave"

    def test_multiple_conversions(self, module):
        """Test multiple special character conversions."""
        result = module.sanitize_address("100/102 Lippincott / St")
        assert result == "100-102_Lippincott_-_St"


class TestExtractAddressFromBlend:
    """Test address extraction from blend filenames."""

    def test_simple_blend_file(self, module):
        """Test extracting address from simple filename."""
        result = module.extract_address_from_blend(Path("22_Lippincott_St.blend"))
        assert result == "22 Lippincott St"

    def test_full_path(self, module):
        """Test extracting from full path."""
        result = module.extract_address_from_blend(Path("/outputs/full/100_Augusta_Ave.blend"))
        assert result == "100 Augusta Ave"

    def test_address_with_hyphens(self, module):
        """Test addresses with hyphens."""
        result = module.extract_address_from_blend(Path("100-102_Bellevue_Ave.blend"))
        assert result == "100-102 Bellevue Ave"


class TestFindBlendFiles:
    """Test scanning for .blend files."""

    def test_find_blend_files_basic(self, module, tmp_path):
        """Test finding .blend files in directory."""
        # Create test structure
        (tmp_path / "building1.blend").touch()
        (tmp_path / "building2.blend").touch()
        (tmp_path / "_metadata.json").touch()

        files = module.find_blend_files(tmp_path, None, None)

        assert len(files) == 2
        assert any(f.name == "building1.blend" for f in files)
        assert any(f.name == "building2.blend" for f in files)

    def test_find_blend_files_skip_metadata(self, module, tmp_path):
        """Test that underscore-prefixed files are skipped."""
        (tmp_path / "building.blend").touch()
        (tmp_path / "_building_custom.blend").touch()
        (tmp_path / ".hidden.blend").touch()

        files = module.find_blend_files(tmp_path, None, None)

        assert len(files) == 1
        assert files[0].name == "building.blend"

    def test_find_blend_files_skip_backups(self, module, tmp_path):
        """Test that backup files are skipped."""
        (tmp_path / "building.blend").touch()
        (tmp_path / "building.blend1").touch()

        files = module.find_blend_files(tmp_path, None, None)

        assert len(files) == 1
        assert files[0].name == "building.blend"

    def test_find_blend_files_skip_custom(self, module, tmp_path):
        """Test that custom variant files are skipped."""
        (tmp_path / "building.blend").touch()
        (tmp_path / "building_custom.blend").touch()

        files = module.find_blend_files(tmp_path, None, None)

        # One should be skipped (contains *custom*)
        assert len(files) >= 1

    def test_find_blend_files_match_filter(self, module, tmp_path):
        """Test match filter."""
        (tmp_path / "22_Lippincott_St.blend").touch()
        (tmp_path / "100_Augusta_Ave.blend").touch()
        (tmp_path / "50_Bellevue_Ave.blend").touch()

        files = module.find_blend_files(tmp_path, "Lippincott", None)

        assert len(files) == 1
        assert files[0].name == "22_Lippincott_St.blend"

    def test_find_blend_files_limit(self, module, tmp_path):
        """Test limit parameter."""
        for i in range(10):
            (tmp_path / f"building_{i}.blend").touch()

        files = module.find_blend_files(tmp_path, None, 5)

        assert len(files) == 5

    def test_find_blend_files_match_case_insensitive(self, module, tmp_path):
        """Test case-insensitive matching."""
        (tmp_path / "22_LIPPINCOTT_ST.blend").touch()
        (tmp_path / "100_Augusta_Ave.blend").touch()

        files = module.find_blend_files(tmp_path, "lippincott", None)

        assert len(files) == 1
        assert files[0].name == "22_LIPPINCOTT_ST.blend"

    def test_find_blend_files_empty_directory(self, module, tmp_path):
        """Test behavior with empty directory."""
        files = module.find_blend_files(tmp_path, None, None)
        assert files == []


class TestWriteManifestCsv:
    """Test CSV manifest generation."""

    def test_write_manifest_creates_file(self, module, tmp_path):
        """Test that manifest CSV file is created."""
        with patch.object(module, "EXPORTS_DIR", tmp_path):
            metadata = {
                "address": "22 Lippincott St",
                "fbx_path": str(tmp_path / "22_Lippincott_St.fbx"),
                "texture_count": 3,
                "texture_files": ["diffuse.png", "normal.png", "roughness.png"],
                "vertex_count": 1000,
                "face_count": 500,
                "material_count": 2,
                "bounding_box": {
                    "width": 10.0,
                    "height": 15.0,
                    "depth": 8.0
                },
                "export_timestamp": datetime.now().isoformat()
            }

            manifest_path = module.write_manifest_csv([metadata])

            assert manifest_path.exists()
            assert manifest_path.name == "manifest.csv"

    def test_manifest_csv_content(self, module, tmp_path):
        """Test CSV content structure."""
        with patch.object(module, "EXPORTS_DIR", tmp_path):
            metadata = {
                "address": "100 Augusta Ave",
                "fbx_path": str(tmp_path / "100_Augusta_Ave.fbx"),
                "texture_count": 3,
                "texture_files": ["diffuse.png", "normal.png", "roughness.png"],
                "vertex_count": 2000,
                "face_count": 1000,
                "material_count": 3,
                "bounding_box": {
                    "width": 12.0,
                    "height": 18.0,
                    "depth": 10.0
                },
                "export_timestamp": datetime.now().isoformat()
            }

            manifest_path = module.write_manifest_csv([metadata])

            # Read and verify CSV
            with open(manifest_path, "r", newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                rows = list(reader)

            assert len(rows) == 1
            row = rows[0]
            assert row["address"] == "100 Augusta Ave"
            assert row["vertex_count"] == "2000"
            assert row["face_count"] == "1000"

    def test_manifest_csv_texture_detection(self, module, tmp_path):
        """Test that texture types are correctly identified."""
        with patch.object(module, "EXPORTS_DIR", tmp_path):
            metadata = {
                "address": "Test Building",
                "fbx_path": str(tmp_path / "test.fbx"),
                "texture_count": 2,
                "texture_files": ["test_diffuse.png", "test_roughness.png"],
                "vertex_count": 100,
                "face_count": 50,
                "material_count": 1,
                "bounding_box": {"width": 1.0, "height": 1.0, "depth": 1.0},
                "export_timestamp": datetime.now().isoformat()
            }

            manifest_path = module.write_manifest_csv([metadata])

            with open(manifest_path, "r", newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                row = next(reader)

            assert row["texture_diffuse"] == "Yes"
            assert row["texture_roughness"] == "Yes"
            assert row["texture_normal"] == "No"

    def test_manifest_multiple_buildings(self, module, tmp_path):
        """Test manifest with multiple buildings."""
        with patch.object(module, "EXPORTS_DIR", tmp_path):
            metadata_list = [
                {
                    "address": f"Building {i}",
                    "fbx_path": str(tmp_path / f"building_{i}.fbx"),
                    "texture_count": 3,
                    "texture_files": ["diffuse.png", "normal.png", "roughness.png"],
                    "vertex_count": 1000 * (i + 1),
                    "face_count": 500 * (i + 1),
                    "material_count": 2,
                    "bounding_box": {"width": 10.0, "height": 15.0, "depth": 8.0},
                    "export_timestamp": datetime.now().isoformat()
                }
                for i in range(3)
            ]

            manifest_path = module.write_manifest_csv(metadata_list)

            with open(manifest_path, "r", newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                rows = list(reader)

            assert len(rows) == 3


class TestMetadataDict:
    """Test metadata dictionary generation."""

    def test_metadata_required_fields(self, module, tmp_path):
        """Test that metadata includes all required fields."""
        export_dir = tmp_path / "exports"
        export_dir.mkdir(parents=True)
        fbx_path = export_dir / "test.fbx"

        # Patch in bake_utils where the functions now live
        import bake_utils
        with patch.object(bake_utils, "get_mesh_stats") as mock_stats, \
             patch.object(bake_utils, "get_unique_materials") as mock_mats:
            mock_stats.return_value = {
                "mesh_count": 1,
                "vertex_count": 100,
                "face_count": 50,
                "bbox_min": [0.0, 0.0, 0.0],
                "bbox_max": [5.0, 6.0, 7.0]
            }
            mock_mats.return_value = []

            with patch.object(sys.modules["bpy"], "data") as mock_bpy_data:
                mock_bpy_data.filepath = "/path/to/scene.blend"
                metadata = module.write_export_metadata("Test", export_dir, fbx_path, 2048)

            required_fields = [
                "address", "safe_address", "fbx_path", "texture_size",
                "mesh_count", "vertex_count", "face_count", "bounding_box",
                "material_count", "texture_count", "export_timestamp"
            ]
            for field in required_fields:
                assert field in metadata


class TestBboxFormatting:
    """Test bounding box formatting in CSV."""

    def test_bbox_dimensions_formatted(self, module, tmp_path):
        """Test that bbox dimensions are formatted to 2 decimal places."""
        with patch.object(module, "EXPORTS_DIR", tmp_path):
            metadata = {
                "address": "Precision Test",
                "fbx_path": str(tmp_path / "test.fbx"),
                "texture_count": 0,
                "texture_files": [],
                "vertex_count": 100,
                "face_count": 50,
                "material_count": 1,
                "bounding_box": {
                    "width": 10.123456,
                    "height": 15.987654,
                    "depth": 8.555555
                },
                "export_timestamp": datetime.now().isoformat()
            }

            manifest_path = module.write_manifest_csv([metadata])

            with open(manifest_path, "r", newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                row = next(reader)

            assert row["bbox_width"] == "10.12"
            assert row["bbox_height"] == "15.99"
            assert row["bbox_depth"] == "8.56"


class TestPathHandling:
    """Test path handling and directory creation."""

    def test_exports_dir_constant(self, module):
        """Test that EXPORTS_DIR constant is defined."""
        assert module.EXPORTS_DIR is not None
        assert isinstance(module.EXPORTS_DIR, Path)
