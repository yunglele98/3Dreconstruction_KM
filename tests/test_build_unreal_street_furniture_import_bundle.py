"""Unit tests for build_unreal_street_furniture_import_bundle.py"""

import pytest
from pathlib import Path
import sys

sys.path.append(str(Path(__file__).parent.parent / "scripts"))

from build_unreal_street_furniture_import_bundle import (
    resolve,
)


class TestResolve:
    """Test the resolve function for street furniture asset resolution."""

    def test_resolve_exact_master_exists(self, tmp_path):
        masters_dir = tmp_path / "masters"
        masters_dir.mkdir()
        fbx = masters_dir / "SM_bus_shelter_glass_A_standard.fbx"
        fbx.write_text("dummy")

        import build_unreal_street_furniture_import_bundle as module
        old_masters = module.MASTERS
        module.MASTERS = masters_dir

        try:
            asset_path, fbx_name, status = resolve("bus_shelter_glass")
            assert status == "exact_master"
            assert "bus_shelter_glass" in asset_path
            assert fbx_name == "SM_bus_shelter_glass_A_standard.fbx"
        finally:
            module.MASTERS = old_masters

    def test_resolve_fallback_terrace_module(self, tmp_path):
        masters_dir = tmp_path / "masters"
        masters_dir.mkdir()
        fbx = masters_dir / "SM_terrace_module_A_standard.fbx"
        fbx.write_text("dummy")

        import build_unreal_street_furniture_import_bundle as module
        old_masters = module.MASTERS
        module.MASTERS = masters_dir

        try:
            asset_path, fbx_name, status = resolve("public_art_mural")
            assert status == "fallback"
            assert "terrace_module" in asset_path
            assert "terrace_module" in fbx_name
        finally:
            module.MASTERS = old_masters

    def test_resolve_asset_path_format_bus_shelter(self, tmp_path):
        masters_dir = tmp_path / "masters"
        masters_dir.mkdir()
        fbx = masters_dir / "SM_bus_shelter_standard_A_standard.fbx"
        fbx.write_text("dummy")

        import build_unreal_street_furniture_import_bundle as module
        old_masters = module.MASTERS
        module.MASTERS = masters_dir

        try:
            asset_path, _, _ = resolve("bus_shelter_standard")
            assert asset_path.startswith("/Game/Street/Furniture/")
            assert "SM_" in asset_path
            assert "_A_standard" in asset_path
        finally:
            module.MASTERS = old_masters

    def test_resolve_fbx_name_format(self, tmp_path):
        masters_dir = tmp_path / "masters"
        masters_dir.mkdir()
        fbx = masters_dir / "SM_public_art_sculpture_A_standard.fbx"
        fbx.write_text("dummy")

        import build_unreal_street_furniture_import_bundle as module
        old_masters = module.MASTERS
        module.MASTERS = masters_dir

        try:
            _, fbx_name, _ = resolve("public_art_sculpture")
            assert fbx_name.startswith("SM_")
            assert fbx_name.endswith(".fbx")
            assert "public_art_sculpture" in fbx_name
        finally:
            module.MASTERS = old_masters


class TestResolveFurnitureTypes:
    """Test resolution for various furniture types."""

    def test_resolve_bus_shelter_glass(self, tmp_path):
        masters_dir = tmp_path / "masters"
        masters_dir.mkdir()
        fbx = masters_dir / "SM_bus_shelter_glass_A_standard.fbx"
        fbx.write_text("dummy")

        import build_unreal_street_furniture_import_bundle as module
        old_masters = module.MASTERS
        module.MASTERS = masters_dir

        try:
            asset_path, fbx_name, status = resolve("bus_shelter_glass")
            assert status == "exact_master"
            assert "bus_shelter_glass" in asset_path
        finally:
            module.MASTERS = old_masters

    def test_resolve_bus_shelter_standard(self, tmp_path):
        masters_dir = tmp_path / "masters"
        masters_dir.mkdir()
        fbx = masters_dir / "SM_bus_shelter_standard_A_standard.fbx"
        fbx.write_text("dummy")

        import build_unreal_street_furniture_import_bundle as module
        old_masters = module.MASTERS
        module.MASTERS = masters_dir

        try:
            asset_path, fbx_name, status = resolve("bus_shelter_standard")
            assert status == "exact_master"
            assert "bus_shelter_standard" in asset_path
        finally:
            module.MASTERS = old_masters

    def test_resolve_public_art_mural(self, tmp_path):
        masters_dir = tmp_path / "masters"
        masters_dir.mkdir()
        fbx = masters_dir / "SM_public_art_mural_A_standard.fbx"
        fbx.write_text("dummy")

        import build_unreal_street_furniture_import_bundle as module
        old_masters = module.MASTERS
        module.MASTERS = masters_dir

        try:
            asset_path, fbx_name, status = resolve("public_art_mural")
            assert status == "exact_master"
            assert "public_art_mural" in asset_path
        finally:
            module.MASTERS = old_masters

    def test_resolve_public_art_sculpture(self, tmp_path):
        masters_dir = tmp_path / "masters"
        masters_dir.mkdir()
        fbx = masters_dir / "SM_public_art_sculpture_A_standard.fbx"
        fbx.write_text("dummy")

        import build_unreal_street_furniture_import_bundle as module
        old_masters = module.MASTERS
        module.MASTERS = masters_dir

        try:
            asset_path, fbx_name, status = resolve("public_art_sculpture")
            assert status == "exact_master"
            assert "public_art_sculpture" in asset_path
        finally:
            module.MASTERS = old_masters

    def test_resolve_terrace_types(self, tmp_path):
        masters_dir = tmp_path / "masters"
        masters_dir.mkdir()

        terrace_types = [
            "terrace_platform",
            "terrace_patio",
            "terrace_module",
        ]

        for terrace_type in terrace_types:
            fbx = masters_dir / f"SM_{terrace_type}_A_standard.fbx"
            fbx.write_text("dummy")

        import build_unreal_street_furniture_import_bundle as module
        old_masters = module.MASTERS
        module.MASTERS = masters_dir

        try:
            for terrace_type in terrace_types:
                asset_path, fbx_name, status = resolve(terrace_type)
                assert status == "exact_master"
                assert terrace_type in asset_path
        finally:
            module.MASTERS = old_masters


class TestResolveFallbackBehavior:
    """Test fallback behavior for missing furniture types."""

    def test_resolve_falls_back_to_terrace_module(self, tmp_path):
        masters_dir = tmp_path / "masters"
        masters_dir.mkdir()
        fbx = masters_dir / "SM_terrace_module_A_standard.fbx"
        fbx.write_text("dummy")

        import build_unreal_street_furniture_import_bundle as module
        old_masters = module.MASTERS
        module.MASTERS = masters_dir

        try:
            asset_path, fbx_name, status = resolve("unknown_furniture_type")
            assert status == "fallback"
            assert "terrace_module" in asset_path
            assert "terrace_module" in fbx_name
        finally:
            module.MASTERS = old_masters

    def test_resolve_all_types_fallback_same(self, tmp_path):
        # All types that don't exist should fall back to terrace_module
        masters_dir = tmp_path / "masters"
        masters_dir.mkdir()
        fbx = masters_dir / "SM_terrace_module_A_standard.fbx"
        fbx.write_text("dummy")

        import build_unreal_street_furniture_import_bundle as module
        old_masters = module.MASTERS
        module.MASTERS = masters_dir

        try:
            missing_types = [
                "unknown_type1",
                "unknown_type2",
                "custom_furniture",
            ]

            results = [resolve(t) for t in missing_types]
            for asset_path, fbx_name, status in results:
                assert status == "fallback"
                assert "terrace_module" in asset_path
        finally:
            module.MASTERS = old_masters


class TestResolveReturnTuple:
    """Test the return tuple structure."""

    def test_resolve_returns_3_tuple(self, tmp_path):
        masters_dir = tmp_path / "masters"
        masters_dir.mkdir()
        fbx = masters_dir / "SM_bus_shelter_glass_A_standard.fbx"
        fbx.write_text("dummy")

        import build_unreal_street_furniture_import_bundle as module
        old_masters = module.MASTERS
        module.MASTERS = masters_dir

        try:
            result = resolve("bus_shelter_glass")
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
        fbx1 = masters_dir / "SM_bus_shelter_glass_A_standard.fbx"
        fbx1.write_text("dummy")
        fbx2 = masters_dir / "SM_terrace_module_A_standard.fbx"
        fbx2.write_text("dummy")

        import build_unreal_street_furniture_import_bundle as module
        old_masters = module.MASTERS
        module.MASTERS = masters_dir

        try:
            _, _, status_exact = resolve("bus_shelter_glass")
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
        fbx = masters_dir / "SM_bus_shelter_glass_A_standard.fbx"
        fbx.write_text("dummy")

        import build_unreal_street_furniture_import_bundle as module
        old_masters = module.MASTERS
        module.MASTERS = masters_dir

        try:
            asset_path, _, _ = resolve("bus_shelter_glass")
            assert asset_path.startswith("/Game/Street/Furniture/")
        finally:
            module.MASTERS = old_masters

    def test_resolve_asset_path_suffix(self, tmp_path):
        masters_dir = tmp_path / "masters"
        masters_dir.mkdir()
        fbx = masters_dir / "SM_public_art_mural_A_standard.fbx"
        fbx.write_text("dummy")

        import build_unreal_street_furniture_import_bundle as module
        old_masters = module.MASTERS
        module.MASTERS = masters_dir

        try:
            asset_path, _, _ = resolve("public_art_mural")
            assert asset_path.endswith("_A_standard")
        finally:
            module.MASTERS = old_masters


class TestResolveMultipleCalls:
    """Test consistency across multiple calls."""

    def test_resolve_multiple_calls_consistent(self, tmp_path):
        masters_dir = tmp_path / "masters"
        masters_dir.mkdir()
        fbx = masters_dir / "SM_bus_shelter_glass_A_standard.fbx"
        fbx.write_text("dummy")

        import build_unreal_street_furniture_import_bundle as module
        old_masters = module.MASTERS
        module.MASTERS = masters_dir

        try:
            result1 = resolve("bus_shelter_glass")
            result2 = resolve("bus_shelter_glass")
            result3 = resolve("bus_shelter_glass")
            assert result1 == result2 == result3
        finally:
            module.MASTERS = old_masters
