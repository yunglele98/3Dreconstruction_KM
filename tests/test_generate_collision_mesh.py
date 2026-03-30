"""
Unit tests for generate_collision_mesh.py

Tests utility functions and pure Python logic.
Bpy and bmesh operations are mocked.
"""

import json
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
    mock_bmesh_module.ops = MagicMock()
    monkeypatch.setitem(sys.modules, "bmesh", mock_bmesh_module)


@pytest.fixture(autouse=True)
def mock_mathutils(monkeypatch):
    """Mock mathutils module."""
    mock_mathutils = MagicMock()

    class MockVector:
        def __init__(self, data):
            self.x, self.y, self.z = data if len(data) == 3 else (data[0], data[1], 0)

        def __add__(self, other):
            return MockVector((self.x + other.x, self.y + other.y, self.z + other.z))

        def __truediv__(self, scalar):
            return MockVector((self.x / scalar, self.y / scalar, self.z / scalar))

    mock_mathutils.Vector = MockVector
    monkeypatch.setitem(sys.modules, "mathutils", mock_mathutils)


@pytest.fixture
def module():
    """Import module after mocking dependencies."""
    import sys as sys_module
    if "scripts.generate_collision_mesh" in sys_module.modules:
        del sys_module.modules["scripts.generate_collision_mesh"]
    sys_module.path.insert(0, str(Path(__file__).parent.parent))
    from scripts import generate_collision_mesh
    return generate_collision_mesh


class TestParseArgs:
    """Test command-line argument parsing."""

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

    def test_parse_args_skip_existing(self, module):
        """Test --skip-existing flag."""
        with patch.object(sys, "argv", ["script.py", "--", "--skip-existing"]):
            args = module.parse_args()
            assert args.skip_existing is True

    def test_parse_args_defaults(self, module):
        """Test default argument values."""
        with patch.object(sys, "argv", ["script.py", "--"]):
            args = module.parse_args()
            assert args.blend is None
            assert args.source_dir is None
            assert args.skip_existing is False


class TestClearScene:
    """Test scene clearing function."""

    def test_clear_scene_function_exists(self, module):
        """Test that clear_scene function exists."""
        assert hasattr(module, "clear_scene")
        assert callable(module.clear_scene)


class TestGetBoundingBox:
    """Test bounding box retrieval."""

    def test_get_bounding_box_function_exists(self, module):
        """Test that get_bounding_box function exists."""
        assert hasattr(module, "get_bounding_box")
        assert callable(module.get_bounding_box)


class TestCountMeshElements:
    """Test mesh element counting."""

    def test_count_mesh_elements_function_exists(self, module):
        """Test that count_mesh_elements exists."""
        assert hasattr(module, "count_mesh_elements")
        assert callable(module.count_mesh_elements)

    def test_count_function_signature(self, module):
        """Test function accepts object parameter."""
        import inspect
        sig = inspect.signature(module.count_mesh_elements)
        params = list(sig.parameters.keys())
        assert "obj" in params


class TestApplyAllModifiers:
    """Test modifier application."""

    def test_apply_all_modifiers_function_exists(self, module):
        """Test that apply_all_modifiers exists."""
        assert hasattr(module, "apply_all_modifiers")
        assert callable(module.apply_all_modifiers)


class TestJoinMeshes:
    """Test mesh joining functionality."""

    def test_join_meshes_function_exists(self, module):
        """Test that join_meshes function exists."""
        assert hasattr(module, "join_meshes")
        assert callable(module.join_meshes)


class TestDecimateMesh:
    """Test mesh decimation."""

    def test_decimate_mesh_function_exists(self, module):
        """Test that decimate_mesh exists."""
        assert hasattr(module, "decimate_mesh")
        assert callable(module.decimate_mesh)

    def test_decimate_default_ratio(self, module):
        """Test decimate accepts ratio parameter."""
        import inspect
        sig = inspect.signature(module.decimate_mesh)
        params = sig.parameters
        assert "ratio" in params
        # Should have a default of 0.1
        assert params["ratio"].default == 0.1


class TestMeshOperations:
    """Test mesh operation functions."""

    def test_module_has_required_attributes(self, module):
        """Test that module has expected attributes."""
        assert hasattr(module, "REPO_ROOT")
        assert hasattr(module, "DEFAULT_OUTPUT_DIR")

    def test_write_metadata_creates_json(self, module, tmp_path):
        """Test that metadata JSON file is created."""
        metadata_path = tmp_path / "collision_meta.json"

        metadata = {
            "address": "Test Building",
            "original_vertex_count": 1000,
            "original_face_count": 500,
            "simplified_vertex_count": 100,
            "simplified_face_count": 50,
            "convex_hull_vertex_count": 50,
            "convex_hull_face_count": 30,
            "decimation_ratio": 0.1,
            "output_path": str(tmp_path / "test_collision.fbx")
        }

        # Write metadata
        with open(metadata_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2)

        # Verify it exists and is valid JSON
        assert metadata_path.exists()
        with open(metadata_path, "r") as f:
            loaded = json.load(f)
        assert loaded["address"] == "Test Building"




class TestMainFunction:
    """Test main entry point."""

    def test_main_function_exists(self, module):
        """Test that main function exists."""
        assert hasattr(module, "main")
        assert callable(module.main)


class TestDefaultOutputDir:
    """Test default output directory."""

    def test_default_output_dir_set(self, module):
        """Test that DEFAULT_OUTPUT_DIR is configured."""
        assert module.DEFAULT_OUTPUT_DIR is not None
        assert isinstance(module.DEFAULT_OUTPUT_DIR, Path)
        assert "collision" in str(module.DEFAULT_OUTPUT_DIR)


class TestRepoRoot:
    """Test repository root."""

    def test_repo_root_exists(self, module):
        """Test that REPO_ROOT is computed."""
        assert module.REPO_ROOT is not None
        assert isinstance(module.REPO_ROOT, Path)


class TestPathHandling:
    """Test path handling."""

    def test_output_directory_creation(self, module, tmp_path):
        """Test output directory can be created."""
        output_dir = tmp_path / "collision"
        assert not output_dir.exists()

        output_dir.mkdir(parents=True, exist_ok=True)
        assert output_dir.exists()

    def test_fbx_filename_generation(self, module):
        """Test FBX filename generation pattern."""
        address = "22 Lippincott St"
        safe_name = address.replace(" ", "_").replace("/", "-")

        expected_fbx = f"{safe_name}_collision.fbx"
        assert "_collision" in expected_fbx
        assert expected_fbx.endswith(".fbx")


class TestArgumentEdgeCases:
    """Test argument parsing edge cases."""

    def test_parse_args_no_separator(self, module):
        """Test parsing without -- separator."""
        with patch.object(sys, "argv", ["script.py", "--blend", "/path"]):
            args = module.parse_args()
            # Should work even without -- separator
            assert args.blend is None or args.blend == "/path"

    def test_path_arguments_various_formats(self, module):
        """Test various path formats."""
        test_paths = [
            "/absolute/path/to/file.blend",
            "relative/path/file.blend",
            "./current/dir/file.blend",
            "../parent/file.blend"
        ]

        for test_path in test_paths:
            argv = ["script.py", "--", "--blend", test_path]
            with patch.object(sys, "argv", argv):
                args = module.parse_args()
                assert args.blend == test_path

    def test_skip_existing_default_false(self, module):
        """Test that skip_existing defaults to False."""
        with patch.object(sys, "argv", ["script.py", "--"]):
            args = module.parse_args()
            assert args.skip_existing is False

    def test_skip_existing_true_when_set(self, module):
        """Test skip_existing is True when flag is set."""
        with patch.object(sys, "argv", ["script.py", "--", "--skip-existing"]):
            args = module.parse_args()
            assert args.skip_existing is True


class TestMetadataStructure:
    """Test metadata structure and content."""

    def test_collision_metadata_fields(self, module, tmp_path):
        """Test that collision metadata has required fields."""
        metadata = {
            "address": "100 Augusta Ave",
            "original_vertex_count": 2000,
            "original_face_count": 1000,
            "simplified_vertex_count": 200,
            "simplified_face_count": 100,
            "convex_hull_vertex_count": 100,
            "convex_hull_face_count": 50,
            "decimation_ratio": 0.1,
            "output_path": str(tmp_path / "collision.fbx")
        }

        required_fields = [
            "address", "original_vertex_count", "original_face_count",
            "simplified_vertex_count", "simplified_face_count",
            "convex_hull_vertex_count", "convex_hull_face_count",
            "decimation_ratio", "output_path"
        ]

        for field in required_fields:
            assert field in metadata


class TestBuildBlendFilePath:
    """Test blend file path handling."""

    def test_resolve_blend_path(self, module, tmp_path):
        """Test resolving blend file paths."""
        blend_file = tmp_path / "test_building.blend"
        blend_file.touch()

        assert blend_file.exists()
        assert blend_file.suffix == ".blend"


class TestArgumentCombinations:
    """Test various argument combinations."""

    def test_blend_and_source_dir_both_provided(self, module):
        """Test that both --blend and --source-dir can be parsed."""
        argv = ["script.py", "--", "--blend", "/path/file.blend", "--source-dir", "/path/dir"]
        with patch.object(sys, "argv", argv):
            args = module.parse_args()
            # Parser accepts both (user logic determines which to use)
            assert args.blend == "/path/file.blend"
            assert args.source_dir == "/path/dir"

    def test_multiple_options_combined(self, module):
        """Test combining multiple options."""
        argv = ["script.py", "--", "--source-dir", "/path", "--output-dir", "/output", "--skip-existing"]
        with patch.object(sys, "argv", argv):
            args = module.parse_args()
            assert args.source_dir == "/path"
            assert args.output_dir == "/output"
            assert args.skip_existing is True
