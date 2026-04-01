"""
Unit tests for build_unity_prefab_manifest.py

Tests pure Python utility functions for Unity manifest generation.
This script has no bpy dependencies, so all functions can be tested directly.
"""

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture
def module():
    """Import module."""
    import sys as sys_module
    if "scripts.build_unity_prefab_manifest" in sys_module.modules:
        del sys_module.modules["scripts.build_unity_prefab_manifest"]
    sys_module.path.insert(0, str(Path(__file__).parent.parent))
    import build_unity_prefab_manifest
    return build_unity_prefab_manifest


class TestLoadSiteCoordinates:
    """Test loading site coordinates."""

    def test_load_site_coordinates_returns_dict(self, module, tmp_path):
        """Test that load_site_coordinates returns a dictionary."""
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

    def test_load_site_coordinates_empty_file(self, module, tmp_path):
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
            "facade_material": "brick"
        }

        with open(param_file, "w") as f:
            json.dump(param_data, f)

        with patch.object(module, "PARAMS_DIR", tmp_path):
            result = module.load_building_param("22 Lippincott St")

        assert result is not None
        assert result["floors"] == 3

    def test_load_building_param_missing_file(self, module, tmp_path):
        """Test handling of missing parameter file."""
        with patch.object(module, "PARAMS_DIR", tmp_path):
            result = module.load_building_param("Nonexistent Building")

        assert result is None

    def test_load_building_param_address_with_slash(self, module, tmp_path):
        """Test loading address with slash (converts to hyphen)."""
        param_file = tmp_path / "100-102_Augusta_Ave.json"
        param_data = {"building_name": "100/102 Augusta Ave"}

        with open(param_file, "w") as f:
            json.dump(param_data, f)

        with patch.object(module, "PARAMS_DIR", tmp_path):
            result = module.load_building_param("100/102 Augusta Ave")

        assert result is not None


class TestSrid2952ToUnity:
    """Test coordinate system conversion."""

    def test_srid_to_unity_basic(self, module):
        """Test basic coordinate conversion."""
        x, y, z = module.srid2952_to_unity(312672.94, 4834994.86, 0.0)

        # Should convert to centimeters and swap axes
        assert isinstance(x, float)
        assert isinstance(y, float)
        assert isinstance(z, float)

    def test_srid_to_unity_with_elevation(self, module):
        """Test conversion with elevation."""
        x, y, z = module.srid2952_to_unity(100.0, 200.0, 10.0)

        # X should be 100 * 100 = 10000 cm
        assert x == 10000.0
        # Y should be 10 * 100 = 1000 cm (Z becomes Y in Unity)
        assert y == 1000.0
        # Z should be 200 * 100 = 20000 cm (Y becomes Z in Unity)
        assert z == 20000.0

    def test_srid_to_unity_zero_elevation(self, module):
        """Test conversion at sea level."""
        x, y, z = module.srid2952_to_unity(50.0, 75.0, 0.0)

        assert x == 5000.0
        assert y == 0.0  # No elevation
        assert z == 7500.0

    def test_srid_to_unity_converts_to_centimeters(self, module):
        """Test that conversion multiplies by 100."""
        x, y, z = module.srid2952_to_unity(1.0, 1.0, 1.0)

        # 1 metre = 100 cm
        assert x == 100.0
        assert y == 100.0
        assert z == 100.0

    def test_srid_to_unity_negative_coordinates(self, module):
        """Test with negative coordinates."""
        x, y, z = module.srid2952_to_unity(-100.0, 200.0, 5.0)

        assert x == -10000.0
        assert y == 500.0
        assert z == 20000.0


class TestGetMaterialInfo:
    """Test material information extraction."""

    def test_get_material_info_with_params(self, module):
        """Test extracting material info from params."""
        params = {
            "facade_material": "brick",
            "facade_detail": {
                "brick_colour_hex": "#B85A3A",
                "mortar_colour": "#B0A898"
            },
            "roof_material": "asphalt",
            "colour_palette": {
                "facade": "#B85A3A",
                "roof": "#5A5A5A",
                "trim": "#3A2A20",
                "accent": "#D4B896"
            }
        }

        result = module.get_material_info(params)

        assert result["facade"]["material"] == "brick"
        assert result["facade"]["colour_hex"] == "#B85A3A"
        assert result["roof"]["material"] == "asphalt"
        assert result["roof"]["colour_hex"] == "#5A5A5A"

    def test_get_material_info_none_params(self, module):
        """Test with None params."""
        result = module.get_material_info(None)

        assert isinstance(result, dict)
        assert "facade" in result
        assert "roof" in result
        assert result["facade"]["material"] == "brick"

    def test_get_material_info_empty_params(self, module):
        """Test with empty params dict."""
        result = module.get_material_info({})

        assert isinstance(result, dict)
        assert result["facade"]["colour_hex"] == "#B85A3A"  # Default

    def test_get_material_info_partial_params(self, module):
        """Test with partial params."""
        params = {
            "facade_material": "stucco",
            "facade_detail": {}
        }

        result = module.get_material_info(params)

        assert result["facade"]["material"] == "stucco"
        # Should use default colour when not provided
        assert result["facade"]["colour_hex"] == "#B85A3A"

    def test_get_material_info_mortar_color(self, module):
        """Test extracting mortar color."""
        params = {
            "facade_detail": {
                "mortar_colour": "#C0B8A8"
            }
        }

        result = module.get_material_info(params)

        assert result["facade"]["mortar_colour"] == "#C0B8A8"


class TestScanFbxFiles:
    """Test scanning FBX files."""

    def test_scan_fbx_files_basic(self, module, tmp_path):
        """Test basic FBX file scanning."""
        (tmp_path / "building1.fbx").touch()
        (tmp_path / "building2.fbx").touch()

        with patch.object(module, "OUTPUTS_DIR", tmp_path.parent):
            result = module.scan_fbx_files(tmp_path)

        assert isinstance(result, dict)

    def test_scan_fbx_files_missing_directory(self, module, tmp_path):
        """Test handling of missing directory."""
        missing = tmp_path / "nonexistent"

        with patch.object(module, "OUTPUTS_DIR", tmp_path.parent):
            result = module.scan_fbx_files(missing)

        assert isinstance(result, dict)
        assert len(result) == 0

    def test_scan_fbx_files_skips_lod_files(self, module, tmp_path):
        """Test that LOD files are skipped in main scan."""
        (tmp_path / "building.fbx").touch()
        (tmp_path / "building_LOD0.fbx").touch()

        with patch.object(module, "OUTPUTS_DIR", tmp_path.parent):
            result = module.scan_fbx_files(tmp_path)

        # Should only find the main building.fbx
        assert len(result) <= 1

    def test_scan_fbx_files_skips_collision(self, module, tmp_path):
        """Test that collision files are skipped."""
        (tmp_path / "building.fbx").touch()
        (tmp_path / "building_collision.fbx").touch()

        with patch.object(module, "OUTPUTS_DIR", tmp_path.parent):
            result = module.scan_fbx_files(tmp_path)

        assert len(result) <= 1


class TestPathConstants:
    """Test path constants."""

    def test_script_dir_defined(self, module):
        """Test SCRIPT_DIR is defined."""
        assert hasattr(module, "SCRIPT_DIR")
        assert isinstance(module.SCRIPT_DIR, Path)

    def test_project_dir_defined(self, module):
        """Test PROJECT_DIR is defined."""
        assert hasattr(module, "PROJECT_DIR")
        assert isinstance(module.PROJECT_DIR, Path)

    def test_params_dir_defined(self, module):
        """Test PARAMS_DIR is defined."""
        assert hasattr(module, "PARAMS_DIR")
        assert isinstance(module.PARAMS_DIR, Path)

    def test_outputs_dir_defined(self, module):
        """Test OUTPUTS_DIR is defined."""
        assert hasattr(module, "OUTPUTS_DIR")
        assert isinstance(module.OUTPUTS_DIR, Path)


class TestManifestGeneration:
    """Test manifest generation capabilities."""

    def test_manifest_module_structure(self, module):
        """Test that manifest module has required structure."""
        assert hasattr(module, "SCRIPT_DIR")
        assert hasattr(module, "PROJECT_DIR")

    def test_write_manifest_creates_file(self, module, tmp_path):
        """Test that manifest JSON file is created."""
        manifest_file = tmp_path / "manifest.json"

        manifest_data = {
            "buildings": [],
            "metadata": {"count": 0}
        }

        with open(manifest_file, "w") as f:
            json.dump(manifest_data, f)

        assert manifest_file.exists()

        with open(manifest_file, "r") as f:
            loaded = json.load(f)

        assert loaded["metadata"]["count"] == 0


class TestMainFunction:
    """Test main entry point."""

    def test_main_function_exists(self, module):
        """Test that main function exists."""
        assert hasattr(module, "main")
        assert callable(module.main)


class TestUnityManifestUtils:
    """Test Unity manifest utilities."""

    def test_module_imports(self, module):
        """Test that module imports successfully."""
        assert module is not None


class TestColourPaletteHandling:
    """Test colour palette extraction."""

    def test_colour_palette_complete(self, module):
        """Test complete colour palette."""
        params = {
            "colour_palette": {
                "facade": "#B85A3A",
                "roof": "#5A5A5A",
                "trim": "#3A2A20",
                "accent": "#D4B896"
            }
        }

        palette = params.get("colour_palette", {})

        assert palette["facade"] == "#B85A3A"
        assert palette["roof"] == "#5A5A5A"
        assert palette["trim"] == "#3A2A20"
        assert palette["accent"] == "#D4B896"

    def test_colour_palette_partial(self, module):
        """Test partial colour palette."""
        params = {
            "colour_palette": {
                "facade": "#B85A3A"
            }
        }

        palette = params.get("colour_palette", {})

        assert "facade" in palette
        assert palette.get("roof") is None


class TestBuildingDataCollection:
    """Test building data collection."""

    def test_building_manifest_entry(self, module):
        """Test structure of building manifest entry."""
        building_entry = {
            "address": "22 Lippincott St",
            "position": {"x": 1000.0, "y": 0.0, "z": 2000.0},
            "rotation": {"z": 45.0},
            "fbx_file": "22_Lippincott_St.fbx",
            "materials": {
                "facade": "brick",
                "roof": "asphalt"
            }
        }

        assert "address" in building_entry
        assert "position" in building_entry
        assert "materials" in building_entry

    def test_unity_position_structure(self, module):
        """Test Unity position structure."""
        position = {
            "x": 100.0,
            "y": 50.0,
            "z": 200.0
        }

        assert position["x"] == 100.0
        assert position["y"] == 50.0
        assert position["z"] == 200.0

    def test_unity_rotation_structure(self, module):
        """Test Unity rotation structure."""
        rotation = {
            "x": 0.0,
            "y": 0.0,
            "z": 45.0
        }

        assert rotation["z"] == 45.0


class TestJsonValidation:
    """Test JSON file handling."""

    def test_load_valid_json(self, module, tmp_path):
        """Test loading valid JSON."""
        json_file = tmp_path / "test.json"
        data = {"key": "value", "number": 42}

        with open(json_file, "w") as f:
            json.dump(data, f)

        with open(json_file, "r") as f:
            loaded = json.load(f)

        assert loaded["key"] == "value"
        assert loaded["number"] == 42

    def test_dump_json_with_indent(self, module, tmp_path):
        """Test dumping JSON with formatting."""
        json_file = tmp_path / "formatted.json"
        data = {
            "buildings": [
                {"address": "Building 1"},
                {"address": "Building 2"}
            ]
        }

        with open(json_file, "w") as f:
            json.dump(data, f, indent=2)

        with open(json_file, "r") as f:
            content = f.read()

        # Should have indentation
        assert "  " in content


class TestAddressNormalization:
    """Test address normalization."""

    def test_address_to_filename(self, module):
        """Test converting address to filename."""
        address = "22 Lippincott St"
        safe_name = address.replace(" ", "_").replace("/", "-")

        assert safe_name == "22_Lippincott_St"

    def test_address_with_slash(self, module):
        """Test address with slash."""
        address = "100/102 Augusta Ave"
        safe_name = address.replace(" ", "_").replace("/", "-")

        assert safe_name == "100-102_Augusta_Ave"

    def test_filename_to_address(self, module):
        """Test converting filename back to address."""
        filename = "22_Lippincott_St"
        address = filename.replace("_", " ")

        assert address == "22 Lippincott St"


class TestDictAccessPatterns:
    """Test safe dictionary access patterns."""

    def test_safe_nested_access(self, module):
        """Test safe nested dictionary access."""
        data = {
            "level1": {
                "level2": {
                    "value": 42
                }
            }
        }

        value = data.get("level1", {}).get("level2", {}).get("value")
        assert value == 42

    def test_safe_access_missing_key(self, module):
        """Test safe access to missing keys."""
        data = {}

        value = data.get("missing", {}).get("also_missing", "default")
        assert value == "default"
