"""Unit tests for build_unreal_sign_import_bundle.py"""

import pytest
from pathlib import Path
import sys

sys.path.append(str(Path(__file__).parent.parent / "scripts"))

from build_unreal_sign_import_bundle import (
    resolve,
)


class TestResolve:
    """Test the resolve function for sign asset resolution."""

    def test_resolve_exact_master_exists(self, tmp_path):
        masters_dir = tmp_path / "masters"
        masters_dir.mkdir()
        fbx = masters_dir / "SM_speed_sign_A_standard.fbx"
        fbx.write_text("dummy")

        import build_unreal_sign_import_bundle as module
        old_masters = module.MASTERS
        module.MASTERS = masters_dir

        try:
            asset_path, fbx_name, status = resolve("speed_sign")
            assert status == "exact_master"
            assert "speed_sign" in asset_path
            assert fbx_name == "SM_speed_sign_A_standard.fbx"
        finally:
            module.MASTERS = old_masters

    def test_resolve_fallback_generic_sign(self, tmp_path):
        masters_dir = tmp_path / "masters"
        masters_dir.mkdir()
        fbx = masters_dir / "SM_generic_sign_A_standard.fbx"
        fbx.write_text("dummy")

        import build_unreal_sign_import_bundle as module
        old_masters = module.MASTERS
        module.MASTERS = masters_dir

        try:
            asset_path, fbx_name, status = resolve("warning_sign")
            assert status == "fallback"
            assert "generic_sign" in asset_path
            assert "generic_sign" in fbx_name
        finally:
            module.MASTERS = old_masters

    def test_resolve_asset_path_format_speed_sign(self, tmp_path):
        masters_dir = tmp_path / "masters"
        masters_dir.mkdir()
        fbx = masters_dir / "SM_speed_sign_A_standard.fbx"
        fbx.write_text("dummy")

        import build_unreal_sign_import_bundle as module
        old_masters = module.MASTERS
        module.MASTERS = masters_dir

        try:
            asset_path, _, _ = resolve("speed_sign")
            assert asset_path.startswith("/Game/Street/Signs/")
            assert "SM_" in asset_path
            assert "_A_standard" in asset_path
        finally:
            module.MASTERS = old_masters

    def test_resolve_fbx_name_format(self, tmp_path):
        masters_dir = tmp_path / "masters"
        masters_dir.mkdir()
        fbx = masters_dir / "SM_warning_sign_A_standard.fbx"
        fbx.write_text("dummy")

        import build_unreal_sign_import_bundle as module
        old_masters = module.MASTERS
        module.MASTERS = masters_dir

        try:
            _, fbx_name, _ = resolve("warning_sign")
            assert fbx_name.startswith("SM_")
            assert fbx_name.endswith(".fbx")
            assert "warning_sign" in fbx_name
        finally:
            module.MASTERS = old_masters


class TestResolveSignTypes:
    """Test resolution for various sign types."""

    def test_resolve_speed_sign(self, tmp_path):
        masters_dir = tmp_path / "masters"
        masters_dir.mkdir()
        fbx = masters_dir / "SM_speed_sign_A_standard.fbx"
        fbx.write_text("dummy")

        import build_unreal_sign_import_bundle as module
        old_masters = module.MASTERS
        module.MASTERS = masters_dir

        try:
            asset_path, fbx_name, status = resolve("speed_sign")
            assert status == "exact_master"
            assert "speed_sign" in asset_path
        finally:
            module.MASTERS = old_masters

    def test_resolve_restriction_sign(self, tmp_path):
        masters_dir = tmp_path / "masters"
        masters_dir.mkdir()
        fbx = masters_dir / "SM_restriction_sign_A_standard.fbx"
        fbx.write_text("dummy")

        import build_unreal_sign_import_bundle as module
        old_masters = module.MASTERS
        module.MASTERS = masters_dir

        try:
            asset_path, fbx_name, status = resolve("restriction_sign")
            assert status == "exact_master"
            assert "restriction_sign" in asset_path
        finally:
            module.MASTERS = old_masters

    def test_resolve_warning_sign(self, tmp_path):
        masters_dir = tmp_path / "masters"
        masters_dir.mkdir()
        fbx = masters_dir / "SM_warning_sign_A_standard.fbx"
        fbx.write_text("dummy")

        import build_unreal_sign_import_bundle as module
        old_masters = module.MASTERS
        module.MASTERS = masters_dir

        try:
            asset_path, fbx_name, status = resolve("warning_sign")
            assert status == "exact_master"
            assert "warning_sign" in asset_path
        finally:
            module.MASTERS = old_masters

    def test_resolve_oneway_sign(self, tmp_path):
        masters_dir = tmp_path / "masters"
        masters_dir.mkdir()
        fbx = masters_dir / "SM_oneway_sign_A_standard.fbx"
        fbx.write_text("dummy")

        import build_unreal_sign_import_bundle as module
        old_masters = module.MASTERS
        module.MASTERS = masters_dir

        try:
            asset_path, fbx_name, status = resolve("oneway_sign")
            assert status == "exact_master"
            assert "oneway_sign" in asset_path
        finally:
            module.MASTERS = old_masters

    def test_resolve_info_sign(self, tmp_path):
        masters_dir = tmp_path / "masters"
        masters_dir.mkdir()
        fbx = masters_dir / "SM_info_sign_A_standard.fbx"
        fbx.write_text("dummy")

        import build_unreal_sign_import_bundle as module
        old_masters = module.MASTERS
        module.MASTERS = masters_dir

        try:
            asset_path, fbx_name, status = resolve("info_sign")
            assert status == "exact_master"
            assert "info_sign" in asset_path
        finally:
            module.MASTERS = old_masters

    def test_resolve_generic_sign(self, tmp_path):
        masters_dir = tmp_path / "masters"
        masters_dir.mkdir()
        fbx = masters_dir / "SM_generic_sign_A_standard.fbx"
        fbx.write_text("dummy")

        import build_unreal_sign_import_bundle as module
        old_masters = module.MASTERS
        module.MASTERS = masters_dir

        try:
            asset_path, fbx_name, status = resolve("generic_sign")
            assert status == "exact_master"
            assert "generic_sign" in asset_path
        finally:
            module.MASTERS = old_masters


class TestResolveFallbackBehavior:
    """Test fallback behavior for missing sign types."""

    def test_resolve_falls_back_to_generic_sign(self, tmp_path):
        masters_dir = tmp_path / "masters"
        masters_dir.mkdir()
        fbx = masters_dir / "SM_generic_sign_A_standard.fbx"
        fbx.write_text("dummy")

        import build_unreal_sign_import_bundle as module
        old_masters = module.MASTERS
        module.MASTERS = masters_dir

        try:
            asset_path, fbx_name, status = resolve("unknown_sign_type")
            assert status == "fallback"
            assert "generic_sign" in asset_path
            assert "generic_sign" in fbx_name
        finally:
            module.MASTERS = old_masters

    def test_resolve_all_missing_types_use_generic(self, tmp_path):
        # All types that don't exist should fall back to generic_sign
        masters_dir = tmp_path / "masters"
        masters_dir.mkdir()
        fbx = masters_dir / "SM_generic_sign_A_standard.fbx"
        fbx.write_text("dummy")

        import build_unreal_sign_import_bundle as module
        old_masters = module.MASTERS
        module.MASTERS = masters_dir

        try:
            missing_types = [
                "unknown_type1",
                "custom_sign",
                "special_sign",
            ]

            results = [resolve(t) for t in missing_types]
            for asset_path, fbx_name, status in results:
                assert status == "fallback"
                assert "generic_sign" in asset_path
        finally:
            module.MASTERS = old_masters


class TestResolveReturnTuple:
    """Test the return tuple structure."""

    def test_resolve_returns_3_tuple(self, tmp_path):
        masters_dir = tmp_path / "masters"
        masters_dir.mkdir()
        fbx = masters_dir / "SM_speed_sign_A_standard.fbx"
        fbx.write_text("dummy")

        import build_unreal_sign_import_bundle as module
        old_masters = module.MASTERS
        module.MASTERS = masters_dir

        try:
            result = resolve("speed_sign")
            assert isinstance(result, tuple)
            assert len(result) == 3
            asset_path, fbx_name, status = result
            assert isinstance(asset_path, str)
            assert isinstance(fbx_name, str)
            assert isinstance(status, str)
        finally:
            module.MASTERS = old_masters

    def test_resolve_status_is_exact_or_fallback(self, tmp_path):
        masters_dir = tmp_path / "masters"
        masters_dir.mkdir()
        fbx1 = masters_dir / "SM_speed_sign_A_standard.fbx"
        fbx1.write_text("dummy")
        fbx2 = masters_dir / "SM_generic_sign_A_standard.fbx"
        fbx2.write_text("dummy")

        import build_unreal_sign_import_bundle as module
        old_masters = module.MASTERS
        module.MASTERS = masters_dir

        try:
            _, _, status_exact = resolve("speed_sign")
            assert status_exact == "exact_master"

            _, _, status_fallback = resolve("unknown_type")
            assert status_fallback == "fallback"
        finally:
            module.MASTERS = old_masters


class TestResolveAssetPathPrefix:
    """Test asset path prefix consistency."""

    def test_resolve_asset_path_game_prefix(self, tmp_path):
        masters_dir = tmp_path / "masters"
        masters_dir.mkdir()
        fbx = masters_dir / "SM_speed_sign_A_standard.fbx"
        fbx.write_text("dummy")

        import build_unreal_sign_import_bundle as module
        old_masters = module.MASTERS
        module.MASTERS = masters_dir

        try:
            asset_path, _, _ = resolve("speed_sign")
            assert asset_path.startswith("/Game/Street/Signs/")
        finally:
            module.MASTERS = old_masters

    def test_resolve_asset_path_suffix(self, tmp_path):
        masters_dir = tmp_path / "masters"
        masters_dir.mkdir()
        fbx = masters_dir / "SM_warning_sign_A_standard.fbx"
        fbx.write_text("dummy")

        import build_unreal_sign_import_bundle as module
        old_masters = module.MASTERS
        module.MASTERS = masters_dir

        try:
            asset_path, _, _ = resolve("warning_sign")
            assert asset_path.endswith("_A_standard")
        finally:
            module.MASTERS = old_masters


class TestResolveMultipleCalls:
    """Test consistency across multiple calls."""

    def test_resolve_multiple_calls_consistent(self, tmp_path):
        masters_dir = tmp_path / "masters"
        masters_dir.mkdir()
        fbx = masters_dir / "SM_speed_sign_A_standard.fbx"
        fbx.write_text("dummy")

        import build_unreal_sign_import_bundle as module
        old_masters = module.MASTERS
        module.MASTERS = masters_dir

        try:
            result1 = resolve("speed_sign")
            result2 = resolve("speed_sign")
            result3 = resolve("speed_sign")
            assert result1 == result2 == result3
        finally:
            module.MASTERS = old_masters

    def test_resolve_different_types_different_results(self, tmp_path):
        masters_dir = tmp_path / "masters"
        masters_dir.mkdir()
        fbx1 = masters_dir / "SM_speed_sign_A_standard.fbx"
        fbx1.write_text("dummy")
        fbx2 = masters_dir / "SM_warning_sign_A_standard.fbx"
        fbx2.write_text("dummy")

        import build_unreal_sign_import_bundle as module
        old_masters = module.MASTERS
        module.MASTERS = masters_dir

        try:
            result_speed = resolve("speed_sign")
            result_warning = resolve("warning_sign")
            assert result_speed != result_warning
            assert "speed_sign" in result_speed[0]
            assert "warning_sign" in result_warning[0]
        finally:
            module.MASTERS = old_masters
