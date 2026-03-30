"""Unit tests for build_unreal_alley_import_bundle.py"""

import pytest
from pathlib import Path
import sys

sys.path.append(str(Path(__file__).parent.parent / "scripts"))

from build_unreal_alley_import_bundle import (
    resolve,
    FALLBACK_KEY,
)


class TestResolve:
    """Test the resolve function for alley asset resolution."""

    def test_resolve_exact_master_exists(self, tmp_path):
        masters_dir = tmp_path / "masters"
        masters_dir.mkdir()
        fbx = masters_dir / "SM_alley_pedestrian_A_standard.fbx"
        fbx.write_text("dummy")

        import build_unreal_alley_import_bundle as module
        old_masters = module.MASTERS
        module.MASTERS = masters_dir

        try:
            asset_path, fbx_name, status = resolve("alley_pedestrian")
            assert status == "exact_master"
            assert "alley_pedestrian" in asset_path
            assert fbx_name == "SM_alley_pedestrian_A_standard.fbx"
        finally:
            module.MASTERS = old_masters

    def test_resolve_fallback_when_not_exists(self, tmp_path):
        masters_dir = tmp_path / "masters"
        masters_dir.mkdir()
        # Create only fallback
        fbx = masters_dir / f"SM_{FALLBACK_KEY}_A_standard.fbx"
        fbx.write_text("dummy")

        import build_unreal_alley_import_bundle as module
        old_masters = module.MASTERS
        module.MASTERS = masters_dir

        try:
            asset_path, fbx_name, status = resolve("alley_pedestrian")
            assert status == "fallback"
            assert FALLBACK_KEY in asset_path
            assert FALLBACK_KEY in fbx_name
        finally:
            module.MASTERS = old_masters

    def test_resolve_asset_path_format(self, tmp_path):
        masters_dir = tmp_path / "masters"
        masters_dir.mkdir()
        fbx = masters_dir / "SM_alley_service_A_standard.fbx"
        fbx.write_text("dummy")

        import build_unreal_alley_import_bundle as module
        old_masters = module.MASTERS
        module.MASTERS = masters_dir

        try:
            asset_path, _, _ = resolve("alley_service")
            assert asset_path.startswith("/Game/Street/Alleys/")
            assert "SM_" in asset_path
            assert "_A_standard" in asset_path
        finally:
            module.MASTERS = old_masters

    def test_resolve_fbx_name_format(self, tmp_path):
        masters_dir = tmp_path / "masters"
        masters_dir.mkdir()
        fbx = masters_dir / "SM_alley_shared_A_standard.fbx"
        fbx.write_text("dummy")

        import build_unreal_alley_import_bundle as module
        old_masters = module.MASTERS
        module.MASTERS = masters_dir

        try:
            _, fbx_name, _ = resolve("alley_shared")
            assert fbx_name.startswith("SM_")
            assert fbx_name.endswith(".fbx")
            assert "alley_shared" in fbx_name
        finally:
            module.MASTERS = old_masters


class TestFallbackKey:
    """Test the FALLBACK_KEY constant."""

    def test_fallback_key_is_vehicle_asphalt(self):
        assert FALLBACK_KEY == "alley_vehicle_asphalt"

    def test_fallback_key_is_string(self):
        assert isinstance(FALLBACK_KEY, str)


class TestResolveAllAlleyTypes:
    """Test resolution for all alley types."""

    def test_resolve_all_alley_types(self, tmp_path):
        masters_dir = tmp_path / "masters"
        masters_dir.mkdir()

        alley_types = [
            "alley_pedestrian",
            "alley_service",
            "alley_shared_green",
            "alley_shared",
            "alley_vehicle_gravel",
            "alley_vehicle_concrete",
            "alley_vehicle_asphalt",
            "alley_degraded",
        ]

        # Create masters for all types
        for alley_type in alley_types:
            fbx = masters_dir / f"SM_{alley_type}_A_standard.fbx"
            fbx.write_text("dummy")

        import build_unreal_alley_import_bundle as module
        old_masters = module.MASTERS
        module.MASTERS = masters_dir

        try:
            for alley_type in alley_types:
                asset_path, fbx_name, status = resolve(alley_type)
                assert status == "exact_master"
                assert alley_type in asset_path
                assert alley_type in fbx_name
        finally:
            module.MASTERS = old_masters


class TestResolveFallbackBehavior:
    """Test fallback behavior."""

    def test_resolve_falls_back_to_vehicle_asphalt(self, tmp_path):
        masters_dir = tmp_path / "masters"
        masters_dir.mkdir()
        # Create only vehicle_asphalt master
        fbx = masters_dir / "SM_alley_vehicle_asphalt_A_standard.fbx"
        fbx.write_text("dummy")

        import build_unreal_alley_import_bundle as module
        old_masters = module.MASTERS
        module.MASTERS = masters_dir

        try:
            # Request a missing type
            asset_path, fbx_name, status = resolve("alley_unknown_type")
            assert status == "fallback"
            assert "alley_vehicle_asphalt" in asset_path
            assert "alley_vehicle_asphalt" in fbx_name
        finally:
            module.MASTERS = old_masters

    def test_resolve_multiple_calls_consistent(self, tmp_path):
        masters_dir = tmp_path / "masters"
        masters_dir.mkdir()
        fbx = masters_dir / "SM_alley_pedestrian_A_standard.fbx"
        fbx.write_text("dummy")

        import build_unreal_alley_import_bundle as module
        old_masters = module.MASTERS
        module.MASTERS = masters_dir

        try:
            result1 = resolve("alley_pedestrian")
            result2 = resolve("alley_pedestrian")
            assert result1 == result2
        finally:
            module.MASTERS = old_masters


class TestResolveReturnTuple:
    """Test the return tuple structure."""

    def test_resolve_returns_3_tuple(self, tmp_path):
        masters_dir = tmp_path / "masters"
        masters_dir.mkdir()
        fbx = masters_dir / "SM_alley_service_A_standard.fbx"
        fbx.write_text("dummy")

        import build_unreal_alley_import_bundle as module
        old_masters = module.MASTERS
        module.MASTERS = masters_dir

        try:
            result = resolve("alley_service")
            assert isinstance(result, tuple)
            assert len(result) == 3
            asset_path, fbx_name, status = result
            assert isinstance(asset_path, str)
            assert isinstance(fbx_name, str)
            assert isinstance(status, str)
        finally:
            module.MASTERS = old_masters

    def test_resolve_status_values(self, tmp_path):
        masters_dir = tmp_path / "masters"
        masters_dir.mkdir()
        fbx1 = masters_dir / "SM_alley_pedestrian_A_standard.fbx"
        fbx1.write_text("dummy")
        fbx2 = masters_dir / "SM_alley_vehicle_asphalt_A_standard.fbx"
        fbx2.write_text("dummy")

        import build_unreal_alley_import_bundle as module
        old_masters = module.MASTERS
        module.MASTERS = masters_dir

        try:
            _, _, status_exact = resolve("alley_pedestrian")
            assert status_exact == "exact_master"

            _, _, status_fallback = resolve("alley_unknown")
            assert status_fallback == "fallback"
        finally:
            module.MASTERS = old_masters


class TestResolveAssetPathPrefix:
    """Test asset path prefix consistency."""

    def test_resolve_asset_path_game_prefix(self, tmp_path):
        masters_dir = tmp_path / "masters"
        masters_dir.mkdir()
        fbx = masters_dir / "SM_alley_pedestrian_A_standard.fbx"
        fbx.write_text("dummy")

        import build_unreal_alley_import_bundle as module
        old_masters = module.MASTERS
        module.MASTERS = masters_dir

        try:
            asset_path, _, _ = resolve("alley_pedestrian")
            assert asset_path.startswith("/Game/Street/Alleys/")
        finally:
            module.MASTERS = old_masters
