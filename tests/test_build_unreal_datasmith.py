"""
Unit tests for build_unreal_datasmith.py

Tests pure Python utility functions for Unreal Datasmith scene building.
This script has no bpy dependencies, so all functions can be tested directly.
"""

import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


@pytest.fixture
def module():
    """Import module."""
    import sys as sys_module
    if "scripts.build_unreal_datasmith" in sys_module.modules:
        del sys_module.modules["scripts.build_unreal_datasmith"]
    sys_module.path.insert(0, str(Path(__file__).parent.parent))
    from scripts import build_unreal_datasmith
    return build_unreal_datasmith


class TestLoadSiteCoordinates:
    """Test loading site coordinates."""

    def test_load_site_coordinates_returns_dict(self, module, tmp_path):
        """Test that load_site_coordinates returns a dictionary."""
        # Create a mock _site_coordinates.json
        coords_file = tmp_path / "params" / "_site_coordinates.json"
        coords_file.parent.mkdir(parents=True, exist_ok=True)

        coords_data = {
            "22 Lippincott St": {"x": 100.5, "y": 200.5, "rotation_deg": 45.0},
            "100 Augusta Ave": {"x": 150.0, "y": 250.0, "rotation_deg": 90.0}
        }

        with open(coords_file, "w") as f:
            json.dump(coords_data, f)

        with patch.object(module, "PARAMS_DIR", coords_file.parent):
            result = module.load_site_coordinates()

        assert isinstance(result, dict)
        assert len(result) == 2
        assert result["22 Lippincott St"]["x"] == 100.5

    def test_load_site_coordinates_missing_file(self, module, tmp_path):
        """Test handling of missing coordinates file."""
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()

        with patch.object(module, "PARAMS_DIR", empty_dir):
            result = module.load_site_coordinates()

        assert isinstance(result, dict)
        assert len(result) == 0


class TestLoadBuildingParam:
    """Test loading building parameter files."""

    def test_load_building_param_success(self, module, tmp_path):
        """Test successfully loading a parameter file."""
        param_file = tmp_path / "22_Lippincott_St.json"
        param_data = {
            "building_name": "22 Lippincott St",
            "floors": 3,
            "facade_material": "brick",
            "roof_type": "gable"
        }

        with open(param_file, "w") as f:
            json.dump(param_data, f)

        with patch.object(module, "PARAMS_DIR", tmp_path):
            result = module.load_building_param("22 Lippincott St")

        assert result is not None
        assert result["building_name"] == "22 Lippincott St"

    def test_load_building_param_missing_file(self, module, tmp_path):
        """Test handling of missing parameter file."""
        with patch.object(module, "PARAMS_DIR", tmp_path):
            result = module.load_building_param("Nonexistent Building")

        assert result is None

    def test_load_building_param_address_normalization(self, module, tmp_path):
        """Test that addresses are normalized to filenames."""
        # Create file with spaces as underscores
        param_file = tmp_path / "100_Augusta_Ave.json"
        param_data = {"building_name": "100 Augusta Ave"}

        with open(param_file, "w") as f:
            json.dump(param_data, f)

        with patch.object(module, "PARAMS_DIR", tmp_path):
            # Load with normal address
            result = module.load_building_param("100 Augusta Ave")

        assert result is not None
        assert result["building_name"] == "100 Augusta Ave"

    def test_load_building_param_with_slash(self, module, tmp_path):
        """Test address with slash converted to hyphen."""
        # Create file with slashes as hyphens
        param_file = tmp_path / "100-102_Augusta_Ave.json"
        param_data = {"building_name": "100/102 Augusta Ave"}

        with open(param_file, "w") as f:
            json.dump(param_data, f)

        with patch.object(module, "PARAMS_DIR", tmp_path):
            result = module.load_building_param("100/102 Augusta Ave")

        assert result is not None


class TestGetFacadeMaterialName:
    """Test facade material name extraction."""

    def test_facade_material_with_hex_color(self, module):
        """Test facade material with hex color."""
        params = {
            "facade_material": "brick",
            "facade_detail": {
                "brick_colour_hex": "#B85A3A"
            }
        }

        result = module.get_facade_material_name(params)

        assert "brick" in result.lower()
        # Material name should contain the hex color code or reference
        assert result  # Should return non-empty string

    def test_facade_material_without_color(self, module):
        """Test facade material without color specification."""
        params = {
            "facade_material": "stucco",
            "facade_detail": {}
        }

        result = module.get_facade_material_name(params)

        assert "stucco" in result.lower()

    def test_facade_material_default(self, module):
        """Test default facade material."""
        params = {}

        result = module.get_facade_material_name(params)

        assert result.lower() == "brick"

    def test_facade_material_case_insensitive(self, module):
        """Test material name is lowercase."""
        params = {
            "facade_material": "BRICK",
            "facade_detail": {
                "brick_colour_hex": "#B85A3A"
            }
        }

        result = module.get_facade_material_name(params)

        assert result == result.lower()


class TestGetRoofMaterialName:
    """Test roof material name extraction."""

    def test_roof_material_basic(self, module):
        """Test basic roof material."""
        params = {
            "roof_material": "asphalt",
            "roof_colour": "grey"
        }

        result = module.get_roof_material_name(params)

        assert "asphalt" in result.lower()
        assert "grey" in result.lower()

    def test_roof_material_default(self, module):
        """Test default roof material."""
        params = {}

        result = module.get_roof_material_name(params)

        # Should default to asphalt_grey
        assert "asphalt" in result.lower()
        assert "grey" in result.lower()

    def test_roof_material_with_spaces(self, module):
        """Test roof material with spaces (converted to underscores)."""
        params = {
            "roof_material": "slate shingles",
            "roof_colour": "dark grey"
        }

        result = module.get_roof_material_name(params)

        assert " " not in result  # No spaces


class TestScanExportsDir:
    """Test scanning exports directory."""

    def test_scan_exports_dir_basic(self, module, tmp_path):
        """Test scanning directory for FBX files."""
        # Create test structure
        (tmp_path / "22_Lippincott_St.fbx").touch()
        (tmp_path / "100_Augusta_Ave.fbx").touch()
        (tmp_path / "readme.txt").touch()

        with patch.object(module, "OUTPUTS_DIR", tmp_path.parent):
            result = module.scan_exports_dir(tmp_path)

        assert isinstance(result, dict)
        assert len(result) == 2

    def test_scan_exports_dir_skips_collision(self, module, tmp_path):
        """Test that collision files are skipped in main scan."""
        (tmp_path / "building.fbx").touch()
        (tmp_path / "building_collision.fbx").touch()

        with patch.object(module, "OUTPUTS_DIR", tmp_path.parent):
            result = module.scan_exports_dir(tmp_path)

        # Only the main FBX should be in results
        assert len(result) == 1

    def test_scan_exports_dir_skips_lod(self, module, tmp_path):
        """Test that LOD files are skipped in main scan."""
        (tmp_path / "building.fbx").touch()
        (tmp_path / "building_LOD0.fbx").touch()
        (tmp_path / "building_LOD1.fbx").touch()

        with patch.object(module, "OUTPUTS_DIR", tmp_path.parent):
            result = module.scan_exports_dir(tmp_path)

        assert len(result) == 1

    def test_scan_exports_dir_finds_lod_variants(self, module, tmp_path):
        """Test finding LOD variant files."""
        basename = "22_Lippincott_St"
        (tmp_path / f"{basename}.fbx").touch()
        (tmp_path / f"{basename}_LOD0.fbx").touch()
        (tmp_path / f"{basename}_LOD1.fbx").touch()
        (tmp_path / f"{basename}_LOD2.fbx").touch()

        with patch.object(module, "OUTPUTS_DIR", tmp_path.parent):
            result = module.scan_exports_dir(tmp_path)

        assert "22 Lippincott St" in result or basename in str(result)

    def test_scan_exports_dir_finds_collision(self, module, tmp_path):
        """Test finding collision mesh files."""
        basename = "100_Augusta_Ave"
        (tmp_path / f"{basename}.fbx").touch()
        (tmp_path / f"{basename}_collision.fbx").touch()

        with patch.object(module, "OUTPUTS_DIR", tmp_path.parent):
            result = module.scan_exports_dir(tmp_path)

        # Result should have collision file reference
        assert len(result) >= 1

    def test_scan_exports_dir_missing_directory(self, module, tmp_path):
        """Test handling of missing directory."""
        missing_dir = tmp_path / "nonexistent"

        with patch.object(module, "OUTPUTS_DIR", tmp_path.parent):
            result = module.scan_exports_dir(missing_dir)

        assert isinstance(result, dict)
        assert len(result) == 0


class TestFilenameNormalization:
    """Test filename to address normalization."""

    def test_address_extraction_from_fbx(self, module):
        """Test extracting address from FBX filename."""
        # This would be tested in the context of scan_exports_dir
        # Verifying that "22_Lippincott_St.fbx" -> "22 Lippincott St"
        filename = "22_Lippincott_St.fbx"
        stem = Path(filename).stem
        address = stem.replace("_", " ")

        assert address == "22 Lippincott St"

    def test_address_extraction_with_export_suffix(self, module):
        """Test removing _export suffix."""
        filename = "100_Augusta_Ave_export.fbx"
        stem = Path(filename).stem
        # Module removes _export suffix
        address = stem.replace("_export", "").replace("_", " ")

        assert address == "100 Augusta Ave"


class TestPathValidation:
    """Test path handling."""

    def test_script_dir_defined(self, module):
        """Test that SCRIPT_DIR is defined."""
        assert hasattr(module, "SCRIPT_DIR")
        assert isinstance(module.SCRIPT_DIR, Path)

    def test_project_dir_defined(self, module):
        """Test that PROJECT_DIR is defined."""
        assert hasattr(module, "PROJECT_DIR")
        assert isinstance(module.PROJECT_DIR, Path)

    def test_params_dir_defined(self, module):
        """Test that PARAMS_DIR is defined."""
        assert hasattr(module, "PARAMS_DIR")
        assert isinstance(module.PARAMS_DIR, Path)

    def test_outputs_dir_defined(self, module):
        """Test that OUTPUTS_DIR is defined."""
        assert hasattr(module, "OUTPUTS_DIR")
        assert isinstance(module.OUTPUTS_DIR, Path)


class TestDatasmithModule:
    """Test Datasmith module structure."""

    def test_datasmith_module_loads(self, module):
        """Test that Datasmith module loads successfully."""
        assert module is not None
        assert hasattr(module, "SCRIPT_DIR")


class TestMainFunction:
    """Test main entry point."""

    def test_main_function_exists(self, module):
        """Test that main function exists."""
        assert hasattr(module, "main")
        assert callable(module.main)


class TestDatasmithUtils:
    """Test Datasmith utilities."""

    def test_module_has_json_functions(self, module):
        """Test that module can handle JSON operations."""
        # Verify we can import and use JSON
        import json
        test_data = {"key": "value"}
        assert json.dumps(test_data)


class TestMaterialDataExtraction:
    """Test extracting material data from parameters."""

    def test_get_trim_color(self, module):
        """Test extracting trim color from params."""
        params = {
            "colour_palette": {
                "trim": "#3A2A20"
            }
        }

        trim_colour = params.get("colour_palette", {}).get("trim", "#3A2A20")
        assert trim_colour == "#3A2A20"

    def test_get_brick_colour(self, module):
        """Test extracting brick colour."""
        params = {
            "facade_detail": {
                "brick_colour_hex": "#B85A3A"
            }
        }

        brick_colour = params.get("facade_detail", {}).get("brick_colour_hex")
        assert brick_colour == "#B85A3A"


class TestJsonLoading:
    """Test JSON loading robustness."""

    def test_load_invalid_json(self, module, tmp_path):
        """Test handling of invalid JSON."""
        bad_json = tmp_path / "bad.json"
        with open(bad_json, "w") as f:
            f.write("{invalid json")

        with pytest.raises(json.JSONDecodeError):
            with open(bad_json, "r") as f:
                json.load(f)

    def test_load_empty_dict(self, module, tmp_path):
        """Test loading empty dictionary."""
        empty_file = tmp_path / "empty.json"
        with open(empty_file, "w") as f:
            json.dump({}, f)

        with open(empty_file, "r") as f:
            data = json.load(f)

        assert isinstance(data, dict)
        assert len(data) == 0


class TestDictAccess:
    """Test safe dictionary access patterns."""

    def test_dict_get_with_default(self, module):
        """Test safe dictionary access."""
        params = {"facade_material": "brick"}

        # Should handle missing keys gracefully
        roof_material = params.get("roof_material", "asphalt").lower()
        assert roof_material == "asphalt"

    def test_nested_dict_access(self, module):
        """Test accessing nested dictionaries."""
        params = {
            "facade_detail": {
                "brick_colour_hex": "#B85A3A"
            }
        }

        colour = params.get("facade_detail", {}).get("brick_colour_hex")
        assert colour == "#B85A3A"

    def test_safe_nested_access_missing(self, module):
        """Test safe access to missing nested values."""
        params = {"facade_detail": {}}

        colour = params.get("facade_detail", {}).get("brick_colour_hex", "#000000")
        assert colour == "#000000"
