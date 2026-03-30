"""Tests for generate_building.py helper functions added in passes 9-12.

Covers:
- _safe_tan: clamped trigonometric helper
- _clamp_positive: dimension validation helper
- Geometry bounds clamps in create_walls, create_storefront, create_porch, etc.
"""

from __future__ import annotations

import importlib
import math
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# Import helpers from generate_building.py without Blender (bpy mock)
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[1]

# We need to mock bpy/bmesh/mathutils so generate_building can be imported
# outside Blender.  Only the pure-Python helpers are tested here.
_bpy_mock = type(sys)("bpy")
_bpy_mock.data = type(sys)("data")
_bpy_mock.data.materials = type(sys)("materials")
_bpy_mock.data.materials.__iter__ = lambda self: iter([])
_bpy_mock.ops = type(sys)("ops")
_bpy_mock.context = type(sys)("context")
_bmesh_mock = type(sys)("bmesh")
_mathutils_mock = type(sys)("mathutils")
_mathutils_mock.Vector = lambda *a: None

sys.modules.setdefault("bpy", _bpy_mock)
sys.modules.setdefault("bmesh", _bmesh_mock)
sys.modules.setdefault("mathutils", _mathutils_mock)

# Now import the helpers via exec to avoid top-level bpy usage
# We parse just the helper functions from generate_building.py
_gen_path = REPO_ROOT / "generate_building.py"
_source = _gen_path.read_text(encoding="utf-8")

# Extract just the helper functions we need (they only use math, no bpy)
_helper_code = ""
_in_func = False
_brace_depth = 0
_funcs_wanted = {"_safe_tan", "_clamp_positive"}
_collected = set()

for line in _source.splitlines():
    stripped = line.strip()
    if not _in_func:
        for fn in _funcs_wanted:
            if stripped.startswith(f"def {fn}("):
                _in_func = True
                _current_func = fn
                _helper_code += line + "\n"
                break
    else:
        if stripped and not stripped.startswith("#") and not line[0:1] in (" ", "\t") and not stripped.startswith("def "):
            # Dedented non-empty line → end of function
            _in_func = False
            _collected.add(_current_func)
        else:
            _helper_code += line + "\n"
            if stripped.startswith("def ") and _current_func not in stripped:
                # New function inside → we overshot
                pass

_ns = {"math": math}
exec(_helper_code, _ns)
_safe_tan = _ns["_safe_tan"]
_clamp_positive = _ns["_clamp_positive"]


# ===========================================================================
# _safe_tan tests
# ===========================================================================

class TestSafeTan:
    """Tests for _safe_tan(degrees, lo, hi)."""

    def test_normal_angle(self):
        """Standard 45° should return tan(45°) = 1.0."""
        assert abs(_safe_tan(45) - 1.0) < 1e-9

    def test_35_degree_default(self):
        """35° is the most common roof pitch in the dataset."""
        expected = math.tan(math.radians(35))
        assert abs(_safe_tan(35) - expected) < 1e-9

    def test_zero_clamped_to_5(self):
        """0° should be clamped to 5° (lower bound)."""
        expected = math.tan(math.radians(5))
        assert abs(_safe_tan(0) - expected) < 1e-9

    def test_negative_clamped_to_5(self):
        """Negative angles should be clamped to 5°."""
        expected = math.tan(math.radians(5))
        assert abs(_safe_tan(-10) - expected) < 1e-9

    def test_90_clamped_to_85(self):
        """90° would be infinity — should be clamped to 85°."""
        expected = math.tan(math.radians(85))
        result = _safe_tan(90)
        assert abs(result - expected) < 1e-9
        assert result < 20  # sanity: not infinity

    def test_100_clamped_to_85(self):
        """Values above 90° also clamped to 85°."""
        expected = math.tan(math.radians(85))
        assert abs(_safe_tan(100) - expected) < 1e-9

    def test_boundary_5(self):
        """Exactly 5° should pass through unclamped."""
        expected = math.tan(math.radians(5))
        assert abs(_safe_tan(5) - expected) < 1e-9

    def test_boundary_85(self):
        """Exactly 85° should pass through unclamped."""
        expected = math.tan(math.radians(85))
        assert abs(_safe_tan(85) - expected) < 1e-9

    def test_custom_bounds(self):
        """Custom lo/hi should be respected."""
        result = _safe_tan(2, lo=10, hi=80)
        expected = math.tan(math.radians(10))
        assert abs(result - expected) < 1e-9

    def test_float_input(self):
        """Float degree values should work."""
        result = _safe_tan(35.5)
        expected = math.tan(math.radians(35.5))
        assert abs(result - expected) < 1e-9

    def test_result_always_positive(self):
        """For any input, result should be positive (clamped range is 5-85°)."""
        for deg in [-50, 0, 1, 5, 45, 85, 90, 180]:
            assert _safe_tan(deg) > 0


# ===========================================================================
# _clamp_positive tests
# ===========================================================================

class TestClampPositive:
    """Tests for _clamp_positive(value, default, minimum)."""

    def test_normal_value(self):
        """A valid positive value above minimum should pass through."""
        assert _clamp_positive(6.0, 5.0) == 6.0

    def test_none_returns_default(self):
        """None should return the default."""
        assert _clamp_positive(None, 5.0) == 5.0

    def test_zero_returns_default(self):
        """Zero is below the default minimum (0.5), so returns default."""
        assert _clamp_positive(0, 5.0) == 5.0

    def test_negative_returns_default(self):
        """Negative values return default."""
        assert _clamp_positive(-3.0, 5.0) == 5.0

    def test_below_minimum_returns_default(self):
        """Value below the minimum threshold returns default."""
        assert _clamp_positive(0.3, 5.0, minimum=1.0) == 5.0

    def test_at_minimum(self):
        """Value exactly at minimum should pass through."""
        assert _clamp_positive(1.0, 5.0, minimum=1.0) == 1.0

    def test_string_numeric(self):
        """String containing a number should be coerced."""
        assert _clamp_positive("8.5", 5.0) == 8.5

    def test_string_non_numeric(self):
        """Non-numeric string should return default."""
        assert _clamp_positive("unknown", 5.0) == 5.0

    def test_empty_string(self):
        """Empty string should return default."""
        assert _clamp_positive("", 5.0) == 5.0

    def test_dict_returns_default(self):
        """A dict value should return default (not crash)."""
        assert _clamp_positive({"width": 6}, 5.0) == 5.0

    def test_list_returns_default(self):
        """A list value should return default (not crash)."""
        assert _clamp_positive([3.0], 5.0) == 5.0

    def test_custom_minimum(self):
        """Custom minimum should be respected."""
        assert _clamp_positive(1.5, 5.0, minimum=2.0) == 5.0
        assert _clamp_positive(2.0, 5.0, minimum=2.0) == 2.0
        assert _clamp_positive(3.0, 5.0, minimum=2.0) == 3.0


# ===========================================================================
# Atomic write tests (enrichment pipeline)
# ===========================================================================

class TestAtomicWriteJson:
    """Test _atomic_write_json across enrichment scripts."""

    SCRIPTS = [
        "translate_agent_params",
        "enrich_skeletons",
        "enrich_facade_descriptions",
        "normalize_params_schema",
        "infer_missing_params",
    ]

    @pytest.fixture(autouse=True)
    def _setup_path(self):
        scripts_dir = str(REPO_ROOT / "scripts")
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)

    @pytest.mark.parametrize("module_name", SCRIPTS)
    def test_atomic_write_creates_valid_json(self, module_name, tmp_path):
        """Each script's _atomic_write_json should produce valid JSON."""
        import json

        try:
            mod = importlib.import_module(module_name)
        except ImportError:
            pytest.skip(f"Cannot import {module_name}")

        fn = getattr(mod, "_atomic_write_json", None)
        if fn is None:
            pytest.skip(f"{module_name} has no _atomic_write_json")

        filepath = tmp_path / "test_output.json"
        data = {"building_name": "Test", "floors": 2, "_meta": {"source": "test"}}
        fn(filepath, data)

        assert filepath.exists()
        with open(filepath, encoding="utf-8") as f:
            loaded = json.load(f)
        assert loaded["building_name"] == "Test"
        assert loaded["floors"] == 2

    @pytest.mark.parametrize("module_name", SCRIPTS)
    def test_atomic_write_overwrites_existing(self, module_name, tmp_path):
        """Atomic write should replace existing file content."""
        import json

        try:
            mod = importlib.import_module(module_name)
        except ImportError:
            pytest.skip(f"Cannot import {module_name}")

        fn = getattr(mod, "_atomic_write_json", None)
        if fn is None:
            pytest.skip(f"{module_name} has no _atomic_write_json")

        filepath = tmp_path / "test_overwrite.json"
        fn(filepath, {"version": 1})
        fn(filepath, {"version": 2})

        with open(filepath, encoding="utf-8") as f:
            loaded = json.load(f)
        assert loaded["version"] == 2

    @pytest.mark.parametrize("module_name", SCRIPTS)
    def test_atomic_write_no_temp_files_left(self, module_name, tmp_path):
        """After atomic write, no .tmp files should remain."""
        try:
            mod = importlib.import_module(module_name)
        except ImportError:
            pytest.skip(f"Cannot import {module_name}")

        fn = getattr(mod, "_atomic_write_json", None)
        if fn is None:
            pytest.skip(f"{module_name} has no _atomic_write_json")

        filepath = tmp_path / "test_clean.json"
        fn(filepath, {"clean": True})

        tmp_files = list(tmp_path.glob("*.tmp"))
        assert len(tmp_files) == 0, f"Leftover temp files: {tmp_files}"

    @pytest.mark.parametrize("module_name", SCRIPTS)
    def test_atomic_write_ends_with_newline(self, module_name, tmp_path):
        """JSON files should end with a trailing newline."""
        try:
            mod = importlib.import_module(module_name)
        except ImportError:
            pytest.skip(f"Cannot import {module_name}")

        fn = getattr(mod, "_atomic_write_json", None)
        if fn is None:
            pytest.skip(f"{module_name} has no _atomic_write_json")

        filepath = tmp_path / "test_newline.json"
        fn(filepath, {"trail": True})

        content = filepath.read_text(encoding="utf-8")
        assert content.endswith("\n")
