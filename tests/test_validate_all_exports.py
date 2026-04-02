"""Tests for validate_all_exports.py — export validation checks."""

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import validate_all_exports


class TestCheckFunctions:
    """Each check function returns a dict with 'pass' and 'detail' keys."""

    def test_check_fbx_count_returns_dict(self):
        result = validate_all_exports.check_fbx_count()
        assert "pass" in result
        assert "detail" in result

    def test_check_lods_returns_dict(self):
        result = validate_all_exports.check_lods()
        assert "pass" in result
        assert "detail" in result

    def test_check_collision_returns_dict(self):
        result = validate_all_exports.check_collision()
        assert "pass" in result
        assert "detail" in result

    def test_check_citygml_returns_dict(self):
        result = validate_all_exports.check_citygml()
        assert "pass" in result
        assert "detail" in result

    def test_check_3dtiles_returns_dict(self):
        result = validate_all_exports.check_3dtiles()
        assert "pass" in result
        assert "detail" in result

    def test_check_datasmith_returns_dict(self):
        result = validate_all_exports.check_datasmith()
        assert "pass" in result
        assert "detail" in result

    def test_check_unity_returns_dict(self):
        result = validate_all_exports.check_unity()
        assert "pass" in result
        assert "detail" in result


class TestChecksMissingDirs:
    """Checks should handle missing directories gracefully."""

    def test_fbx_missing_dir(self, tmp_path):
        with patch.object(validate_all_exports, "EXPORTS_DIR", tmp_path / "nope"):
            result = validate_all_exports.check_fbx_count()
        assert result["pass"] is False

    def test_citygml_missing(self, tmp_path):
        with patch.object(validate_all_exports, "REPO", tmp_path):
            result = validate_all_exports.check_citygml()
        assert result["pass"] is False

    def test_3dtiles_missing(self, tmp_path):
        with patch.object(validate_all_exports, "REPO", tmp_path):
            result = validate_all_exports.check_3dtiles()
        assert result["pass"] is False


class TestChecksIntegration:
    """Integration tests against actual export data."""

    def test_all_checks_pass(self):
        """All 7 checks should pass with current data."""
        if not validate_all_exports.EXPORTS_DIR.exists():
            pytest.skip("exports dir not found")
        for name, fn in validate_all_exports.CHECKS:
            result = fn()
            assert result["pass"], f"{name} failed: {result['detail']}"

    def test_checks_list_has_7_items(self):
        assert len(validate_all_exports.CHECKS) == 7
