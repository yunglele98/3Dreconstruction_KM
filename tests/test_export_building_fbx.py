"""
Unit tests for export_building_fbx.py

Tests utility functions that don't depend on bpy or bmesh.
Bpy-dependent functions are tested via mocking.
"""

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch, mock_open

import pytest


# Mock bpy before importing the module
@pytest.fixture(autouse=True)
def mock_bpy(monkeypatch):
    """Create mock bpy module before importing export_building_fbx."""
    mock_bpy_module = MagicMock()
    mock_bpy_module.data = MagicMock()
    mock_bpy_module.ops = MagicMock()
    mock_bpy_module.context = MagicMock()
    monkeypatch.setitem(sys.modules, "bpy", mock_bpy_module)


@pytest.fixture(autouse=True)
def mock_bmesh(monkeypatch):
    """Create mock bmesh module."""
    mock_bmesh_module = MagicMock()
    monkeypatch.setitem(sys.modules, "bmesh", mock_bmesh_module)


@pytest.fixture
def module():
    """Import the module after mocking bpy and bmesh."""
    import sys as sys_module
    # Clear cached modules to force re-import with mocks
    for mod_name in list(sys_module.modules):
        if "export_building_fbx" in mod_name or "bake_utils" in mod_name:
            del sys_module.modules[mod_name]
    sys_module.path.insert(0, str(Path(__file__).parent.parent))
    import export_building_fbx
    return export_building_fbx


@pytest.fixture
def bake_utils_module():
    """Import bake_utils after mocking bpy."""
    import sys as sys_module
    sys_module.path.insert(0, str(Path(__file__).parent.parent))
    import bake_utils
    return bake_utils


class TestParseArgs:
    """Test parse_args function."""

    def test_parse_args_with_address(self, module):
        """Test parsing --address argument."""
        with patch.object(sys, "argv", ["script.py", "--", "--address", "22 Lippincott St"]):
            args = module.parse_args()
            assert args.address == "22 Lippincott St"

    def test_parse_args_with_blend(self, module):
        """Test parsing --blend argument."""
        with patch.object(sys, "argv", ["script.py", "--", "--blend", "/path/to/file.blend"]):
            args = module.parse_args()
            assert args.blend == "/path/to/file.blend"

    def test_parse_args_texture_size(self, module):
        """Test parsing --texture-size argument."""
        with patch.object(sys, "argv", ["script.py", "--", "--texture-size", "4096"]):
            args = module.parse_args()
            assert args.texture_size == 4096

    def test_parse_args_defaults(self, module):
        """Test default argument values."""
        with patch.object(sys, "argv", ["script.py", "--"]):
            args = module.parse_args()
            assert args.address is None
            assert args.blend is None
            assert args.texture_size == 2048
            assert args.skip_glb is False

    def test_parse_args_skip_glb_flag(self, module):
        """Test parsing --skip-glb argument."""
        with patch.object(sys, "argv", ["script.py", "--", "--skip-glb"]):
            args = module.parse_args()
            assert args.skip_glb is True

    def test_parse_args_no_separator(self, module):
        """Test parsing without -- separator."""
        with patch.object(sys, "argv", ["script.py", "arg1", "arg2"]):
            args = module.parse_args()
            # Should parse empty list when -- not present
            assert args.texture_size == 2048


class TestSanitizeAddress:
    """Test sanitize_address function."""

    def test_spaces_to_underscores(self, module):
        """Test that spaces are converted to underscores."""
        result = module.sanitize_address("22 Lippincott St")
        assert result == "22_Lippincott_St"

    def test_slashes_to_hyphens(self, module):
        """Test that slashes are converted to hyphens."""
        result = module.sanitize_address("100/102 Augusta Ave")
        assert result == "100-102_Augusta_Ave"

    def test_multiple_spaces(self, module):
        """Test multiple consecutive spaces."""
        result = module.sanitize_address("100  Bellevue  Ave")
        assert result == "100__Bellevue__Ave"

    def test_no_special_chars(self, module):
        """Test address without special characters."""
        result = module.sanitize_address("Baldwin_Lane")
        assert result == "Baldwin_Lane"


class TestExtractAddressFromBlend:
    """Test extract_address_from_blend function."""

    def test_simple_address(self, module):
        """Test extracting simple address from blend filename."""
        result = module.extract_address_from_blend("22_Lippincott_St.blend")
        assert result == "22 Lippincott St"

    def test_path_with_directories(self, module):
        """Test extracting address from full path."""
        result = module.extract_address_from_blend("/path/to/100_Augusta_Ave.blend")
        assert result == "100 Augusta Ave"

    def test_address_with_slashes(self, module):
        """Test address with slashes represented as hyphens."""
        result = module.extract_address_from_blend("100-102_Kensington_Ave.blend")
        assert result == "100-102 Kensington Ave"

    def test_pathlib_path_object(self, module):
        """Test with Path object input."""
        path = Path("outputs/full/22_Lippincott_St.blend")
        result = module.extract_address_from_blend(str(path))
        assert result == "22 Lippincott St"


class TestGetMeshStats:
    """Test get_mesh_stats function (now in bake_utils)."""

    def test_get_mesh_stats_importable(self, bake_utils_module):
        """Test that get_mesh_stats is available in bake_utils."""
        assert hasattr(bake_utils_module, "get_mesh_stats")
        assert callable(bake_utils_module.get_mesh_stats)


class TestWriteMetadata:
    """Test metadata writing functions (now in bake_utils)."""

    def test_write_metadata_creates_json(self, bake_utils_module, tmp_path):
        """Test that write_export_metadata creates a JSON file."""
        export_dir = tmp_path / "exports"
        export_dir.mkdir(parents=True)
        fbx_path = export_dir / "test.fbx"

        # Create mock material object
        mock_mat = MagicMock()
        mock_mat.name = "Material1"

        with patch.object(bake_utils_module, "get_mesh_stats") as mock_stats, \
             patch.object(bake_utils_module, "get_unique_materials") as mock_mats:
            mock_stats.return_value = {
                "mesh_count": 5,
                "vertex_count": 1000,
                "face_count": 500,
                "bbox_min": [0.0, 0.0, 0.0],
                "bbox_max": [10.0, 10.0, 15.0]
            }
            mock_mats.return_value = [mock_mat]

            with patch.object(sys.modules["bpy"], "data") as mock_bpy_data:
                mock_bpy_data.filepath = "/path/to/scene.blend"
                bake_utils_module.write_export_metadata("22 Lippincott St", export_dir, fbx_path, 2048)

            # Check that metadata file was created
            meta_path = export_dir / "export_meta.json"
            assert meta_path.exists()

            # Verify metadata content
            with open(meta_path, "r") as f:
                metadata = json.load(f)

            assert metadata["address"] == "22 Lippincott St"
            assert metadata["safe_address"] == "22_Lippincott_St"
            assert metadata["texture_size"] == 2048
            assert metadata["mesh_count"] == 5
            assert metadata["vertex_count"] == 1000
            assert metadata["face_count"] == 500
            assert "export_timestamp" in metadata

    def test_metadata_bbox_calculation(self, bake_utils_module, tmp_path):
        """Test that bounding box dimensions are calculated correctly."""
        export_dir = tmp_path / "exports"
        export_dir.mkdir(parents=True)
        fbx_path = export_dir / "test.fbx"

        with patch.object(bake_utils_module, "get_mesh_stats") as mock_stats, \
             patch.object(bake_utils_module, "get_unique_materials") as mock_mats:
            mock_stats.return_value = {
                "mesh_count": 1,
                "vertex_count": 100,
                "face_count": 50,
                "bbox_min": [0.0, 0.0, 0.0],
                "bbox_max": [10.0, 20.0, 15.0]
            }
            mock_mats.return_value = []

            with patch.object(sys.modules["bpy"], "data") as mock_bpy_data:
                mock_bpy_data.filepath = "/path/to/scene.blend"
                bake_utils_module.write_export_metadata("Test", export_dir, fbx_path, 2048)

            meta_path = export_dir / "export_meta.json"
            with open(meta_path, "r") as f:
                metadata = json.load(f)

            bbox = metadata["bounding_box"]
            assert bbox["width"] == pytest.approx(10.0)
            assert bbox["height"] == pytest.approx(20.0)
            assert bbox["depth"] == pytest.approx(15.0)


class TestConstantsAndPaths:
    """Test module constants and path setup."""

    def test_repo_root_exists(self, module):
        """Test that REPO_ROOT is properly computed."""
        assert module.REPO_ROOT is not None
        assert isinstance(module.REPO_ROOT, Path)

    def test_exports_dir_path(self, module):
        """Test that EXPORTS_DIR is properly set."""
        assert module.EXPORTS_DIR is not None
        assert "exports" in str(module.EXPORTS_DIR)


class TestArgumentParsing:
    """Test argument parsing edge cases."""

    def test_parse_args_combined_flags(self, module):
        """Test parsing multiple combined arguments."""
        argv = [
            "script.py", "--",
            "--address", "100 Bellevue Ave",
            "--texture-size", "1024",
            "--blend", "/path/file.blend"
        ]
        with patch.object(sys, "argv", argv):
            args = module.parse_args()
            assert args.address == "100 Bellevue Ave"
            assert args.texture_size == 1024
            assert args.blend == "/path/file.blend"

    def test_parse_args_integer_parsing(self, module):
        """Test that texture-size is parsed as integer."""
        with patch.object(sys, "argv", ["script.py", "--", "--texture-size", "8192"]):
            args = module.parse_args()
            assert isinstance(args.texture_size, int)
            assert args.texture_size == 8192


class TestAddressNormalization:
    """Test address normalization consistency."""

    def test_sanitize_and_extract_roundtrip(self, module):
        """Test that sanitize/extract can work together."""
        original = "22 Lippincott St"
        sanitized = module.sanitize_address(original)
        # Sanitized version is "22_Lippincott_St"
        extracted = module.extract_address_from_blend(sanitized + ".blend")
        # Extracted should restore spaces
        assert extracted == original

    def test_complex_address_handling(self, module):
        """Test handling of complex addresses with multiple special chars."""
        address = "100/102 Bellevue Ave"
        sanitized = module.sanitize_address(address)
        assert "100-102_Bellevue_Ave" == sanitized

    def test_double_slash_handling(self, module):
        """Test double slashes are converted to double hyphens."""
        result = module.sanitize_address("100//102 Street")
        assert result == "100--102_Street"


class TestTexturePathHandling:
    """Test texture file path handling."""

    def test_texture_directory_creation(self, bake_utils_module, tmp_path):
        """Test that metadata file is created."""
        export_dir = tmp_path / "exports"
        export_dir.mkdir(parents=True)

        with patch.object(bake_utils_module, "get_mesh_stats") as mock_stats, \
             patch.object(bake_utils_module, "get_unique_materials") as mock_mats:
            mock_stats.return_value = {
                "mesh_count": 0,
                "vertex_count": 0,
                "face_count": 0,
                "bbox_min": [0.0, 0.0, 0.0],
                "bbox_max": [0.0, 0.0, 0.0]
            }
            mock_mats.return_value = []

            with patch.object(sys.modules["bpy"], "data") as mock_bpy_data:
                mock_bpy_data.filepath = "/path/to/scene.blend"
                bake_utils_module.write_export_metadata("Test", export_dir, export_dir / "test.fbx", 2048)

            # Check directory structure
            assert (export_dir / "export_meta.json").exists()


class TestMetadataTimestamp:
    """Test metadata timestamp generation."""

    def test_metadata_has_iso_timestamp(self, bake_utils_module, tmp_path):
        """Test that metadata includes ISO 8601 timestamp."""
        export_dir = tmp_path / "exports"
        export_dir.mkdir(parents=True)
        fbx_path = export_dir / "test.fbx"

        with patch.object(bake_utils_module, "get_mesh_stats") as mock_stats, \
             patch.object(bake_utils_module, "get_unique_materials") as mock_mats:
            mock_stats.return_value = {
                "mesh_count": 0,
                "vertex_count": 0,
                "face_count": 0,
                "bbox_min": [0.0, 0.0, 0.0],
                "bbox_max": [0.0, 0.0, 0.0]
            }
            mock_mats.return_value = []

            with patch.object(sys.modules["bpy"], "data") as mock_bpy_data:
                mock_bpy_data.filepath = "/path/to/scene.blend"
                bake_utils_module.write_export_metadata("Test", export_dir, fbx_path, 2048)

            meta_path = export_dir / "export_meta.json"
            with open(meta_path, "r") as f:
                metadata = json.load(f)

            # Validate ISO timestamp format
            timestamp = metadata["export_timestamp"]
            try:
                datetime.fromisoformat(timestamp)
            except ValueError:
                pytest.fail(f"Invalid ISO timestamp: {timestamp}")
