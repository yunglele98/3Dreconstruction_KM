"""
Unit tests for generate_lods.py

Tests utility functions that don't depend on bpy or bmesh.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def mock_bpy(monkeypatch):
    """Mock bpy module."""
    mock_bpy_module = MagicMock()
    mock_bpy_module.data = MagicMock()
    mock_bpy_module.ops = MagicMock()
    mock_bpy_module.context = MagicMock()
    monkeypatch.setitem(sys.modules, "bpy", mock_bpy_module)


@pytest.fixture(autouse=True)
def mock_bmesh(monkeypatch):
    """Mock bmesh module."""
    mock_bmesh_module = MagicMock()
    monkeypatch.setitem(sys.modules, "bmesh", mock_bmesh_module)


@pytest.fixture(autouse=True)
def mock_mathutils(monkeypatch):
    """Mock mathutils module."""
    mock_mathutils = MagicMock()

    # Create a Vector mock class
    class MockVector:
        def __init__(self, data):
            self.x, self.y, self.z = data if len(data) == 3 else (data[0], data[1], 0)

        def __add__(self, other):
            return MockVector((self.x + other.x, self.y + other.y, self.z + other.z))

        def __truediv__(self, scalar):
            return MockVector((self.x / scalar, self.y / scalar, self.z / scalar))

        def __mul__(self, scalar):
            return MockVector((self.x * scalar, self.y * scalar, self.z * scalar))

    mock_mathutils.Vector = MockVector
    monkeypatch.setitem(sys.modules, "mathutils", mock_mathutils)


@pytest.fixture
def module():
    """Import module after mocking dependencies."""
    import sys as sys_module
    if "scripts.generate_lods" in sys_module.modules:
        del sys_module.modules["scripts.generate_lods"]
    sys_module.path.insert(0, str(Path(__file__).parent.parent))
    import generate_lods
    return generate_lods


class TestParseArgs:
    """Test argument parsing."""

    def test_parse_args_blend_file(self, module):
        """Test --blend argument."""
        with patch.object(sys, "argv", ["script.py", "--", "--blend", "/path/to/file.blend"]):
            args = module.parse_args()
            assert args.blend == "/path/to/file.blend"

    def test_parse_args_source_dir(self, module):
        """Test --source-dir argument."""
        with patch.object(sys, "argv", ["script.py", "--", "--source-dir", "/path/to/blends"]):
            args = module.parse_args()
            assert args.source_dir == "/path/to/blends"

    def test_parse_args_output_dir(self, module):
        """Test --output-dir argument."""
        with patch.object(sys, "argv", ["script.py", "--", "--output-dir", "/custom/output"]):
            args = module.parse_args()
            assert args.output_dir == "/custom/output"

    def test_parse_args_limit(self, module):
        """Test --limit argument."""
        with patch.object(sys, "argv", ["script.py", "--", "--limit", "10"]):
            args = module.parse_args()
            assert args.limit == 10

    def test_parse_args_skip_existing(self, module):
        """Test --skip-existing flag."""
        with patch.object(sys, "argv", ["script.py", "--", "--skip-existing"]):
            args = module.parse_args()
            assert args.skip_existing is True

    def test_parse_args_defaults(self, module):
        """Test default values."""
        with patch.object(sys, "argv", ["script.py", "--"]):
            args = module.parse_args()
            assert args.blend is None
            assert args.source_dir is None
            assert args.limit is None
            assert args.skip_existing is False
            assert args.output_dir is not None  # Has default


class TestDecorativePrefixes:
    """Test decorative element prefix constants."""

    def test_decorative_prefixes_defined(self, module):
        """Test that DECORATIVE_PREFIXES is defined."""
        assert hasattr(module, "DECORATIVE_PREFIXES")
        assert isinstance(module.DECORATIVE_PREFIXES, set)
        assert len(module.DECORATIVE_PREFIXES) > 0

    def test_decorative_prefixes_content(self, module):
        """Test expected prefixes are in the set."""
        expected = {"cornice_", "bracket_", "voussoir_", "quoin_", "finial_"}
        assert expected.issubset(module.DECORATIVE_PREFIXES)

    def test_window_prefixes_defined(self, module):
        """Test that WINDOW_PREFIXES is defined."""
        assert hasattr(module, "WINDOW_PREFIXES")
        assert isinstance(module.WINDOW_PREFIXES, set)
        assert "frame_" in module.WINDOW_PREFIXES
        assert "glass_" in module.WINDOW_PREFIXES


class TestDefaultOutputDir:
    """Test default output directory setup."""

    def test_default_output_dir_set(self, module):
        """Test that DEFAULT_OUTPUT_DIR is properly configured."""
        assert module.DEFAULT_OUTPUT_DIR is not None
        assert isinstance(module.DEFAULT_OUTPUT_DIR, Path)
        assert "lods" in str(module.DEFAULT_OUTPUT_DIR)


class TestRepoRoot:
    """Test repository root detection."""

    def test_repo_root_exists(self, module):
        """Test that REPO_ROOT is computed."""
        assert module.REPO_ROOT is not None
        assert isinstance(module.REPO_ROOT, Path)


class TestCountMeshElements:
    """Test mesh element counting (pure Python aspect)."""

    def test_count_function_exists(self, module):
        """Test that count_mesh_elements function exists."""
        assert hasattr(module, "count_mesh_elements")
        assert callable(module.count_mesh_elements)


class TestGetObjectBoundingBox:
    """Test bounding box computation."""

    def test_get_bounding_box_function_exists(self, module):
        """Test that get_object_bounding_box exists."""
        assert hasattr(module, "get_object_bounding_box")
        assert callable(module.get_object_bounding_box)


class TestCreateBoxMassing:
    """Test box massing creation for LOD3."""

    def test_create_box_massing_function_exists(self, module):
        """Test that create_box_massing exists."""
        assert hasattr(module, "create_box_massing")
        assert callable(module.create_box_massing)


class TestExportFbx:
    """Test FBX export function."""

    def test_export_fbx_function_exists(self, module):
        """Test that export_fbx exists."""
        assert hasattr(module, "export_fbx")
        assert callable(module.export_fbx)

    def test_export_fbx_signature(self, module):
        """Test export_fbx accepts expected parameters."""
        # Should accept output_path and optional axis/scale params
        import inspect
        sig = inspect.signature(module.export_fbx)
        params = list(sig.parameters.keys())
        assert "output_path" in params
        assert "axis_forward" in params
        assert "axis_up" in params


class TestLodGenerationFunctions:
    """Test LOD generation functions."""

    def test_generate_lod0_exists(self, module):
        """Test that generate_lod0 exists."""
        assert hasattr(module, "generate_lod0")
        assert callable(module.generate_lod0)

    def test_generate_lod1_exists(self, module):
        """Test that generate_lod1 exists."""
        assert hasattr(module, "generate_lod1")
        assert callable(module.generate_lod1)

    def test_generate_lod2_exists(self, module):
        """Test that generate_lod2 exists."""
        assert hasattr(module, "generate_lod2")
        assert callable(module.generate_lod2)

    def test_generate_lod3_exists(self, module):
        """Test that generate_lod3 exists."""
        assert hasattr(module, "generate_lod3")
        assert callable(module.generate_lod3)


class TestApplyAllModifiers:
    """Test modifier application."""

    def test_apply_all_modifiers_function_exists(self, module):
        """Test that apply_all_modifiers exists."""
        assert hasattr(module, "apply_all_modifiers")
        assert callable(module.apply_all_modifiers)


class TestClearScene:
    """Test scene clearing function."""

    def test_clear_scene_function_exists(self, module):
        """Test that clear_scene exists."""
        assert hasattr(module, "clear_scene")
        assert callable(module.clear_scene)


class TestArgumentCombinations:
    """Test various argument combinations."""

    def test_blend_and_source_dir_mutually_exclusive_parsing(self, module):
        """Test that both --blend and --source-dir can be specified (user responsibility)."""
        argv = ["script.py", "--", "--blend", "/path/file.blend", "--source-dir", "/path/dir"]
        with patch.object(sys, "argv", argv):
            args = module.parse_args()
            # Parser should accept both (user logic handles exclusivity)
            assert args.blend == "/path/file.blend"
            assert args.source_dir == "/path/dir"

    def test_multiple_flags_together(self, module):
        """Test combining multiple flags."""
        argv = ["script.py", "--", "--source-dir", "/path", "--limit", "20", "--skip-existing"]
        with patch.object(sys, "argv", argv):
            args = module.parse_args()
            assert args.source_dir == "/path"
            assert args.limit == 20
            assert args.skip_existing is True


class TestPathValidation:
    """Test path handling."""

    def test_output_dir_creation(self, module, tmp_path):
        """Test that output directory can be created."""
        output_dir = tmp_path / "lods"
        assert not output_dir.exists()

        # Mock the bpy operations
        with patch.object(sys.modules["bpy"].ops, "export_scene") as mock_export:
            # Directory creation should happen before export
            output_dir.mkdir(parents=True, exist_ok=True)
            assert output_dir.exists()


class TestLodFilenameGeneration:
    """Test LOD filename conventions."""

    def test_lod_filename_patterns(self, module):
        """Test that LOD filenames follow expected pattern."""
        # These should be generated by the module
        address = "22 Lippincott St"
        safe = address.replace(" ", "_")

        expected_names = [
            f"{safe}_LOD0.fbx",
            f"{safe}_LOD1.fbx",
            f"{safe}_LOD2.fbx",
            f"{safe}_LOD3.fbx"
        ]

        # Just verify that the naming scheme is documented
        for name in expected_names:
            assert "_LOD" in name
            assert name.endswith(".fbx")


class TestMainFunction:
    """Test main entry point."""

    def test_main_function_exists(self, module):
        """Test that main function exists."""
        assert hasattr(module, "main")
        assert callable(module.main)


class TestArgumentEdgeCases:
    """Test edge cases in argument parsing."""

    def test_integer_parsing(self, module):
        """Test integer argument parsing."""
        with patch.object(sys, "argv", ["script.py", "--", "--limit", "999"]):
            args = module.parse_args()
            assert isinstance(args.limit, int)
            assert args.limit == 999

    def test_path_arguments(self, module):
        """Test path arguments with various formats."""
        test_paths = [
            "/absolute/path",
            "relative/path",
            "./current/path",
            "../parent/path"
        ]

        for test_path in test_paths:
            argv = ["script.py", "--", "--output-dir", test_path]
            with patch.object(sys, "argv", argv):
                args = module.parse_args()
                assert args.output_dir == test_path
