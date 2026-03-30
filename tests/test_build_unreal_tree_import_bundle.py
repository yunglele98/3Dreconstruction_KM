"""Unit tests for build_unreal_tree_import_bundle.py"""

import pytest
from pathlib import Path
import sys

sys.path.append(str(Path(__file__).parent.parent / "scripts"))

from build_unreal_tree_import_bundle import (
    resolve_asset_path,
    build_manifest,
    ALIAS_TO_MASTER,
    GENUS_TO_MASTER,
)


class TestResolveAssetPath:
    """Test the resolve_asset_path function."""

    def test_resolve_exact_master_exists(self, tmp_path):
        # Create a temporary masters directory with a test file
        masters_dir = tmp_path / "masters"
        masters_dir.mkdir()
        test_fbx = masters_dir / "SM_blue_spruce_A_mature.fbx"
        test_fbx.write_text("dummy")

        # Mock the MASTERS_DIR in the module
        import build_unreal_tree_import_bundle as module
        old_masters = module.MASTERS_DIR
        module.MASTERS_DIR = masters_dir

        try:
            asset_path, fbx_name, status = resolve_asset_path("blue_spruce")
            assert status == "exact_master"
            assert "blue_spruce" in asset_path
            assert fbx_name == "SM_blue_spruce_A_mature.fbx"
        finally:
            module.MASTERS_DIR = old_masters

    def test_resolve_alias_master(self, tmp_path):
        masters_dir = tmp_path / "masters"
        masters_dir.mkdir()
        # Create the specific tilia master for the alias
        test_fbx = masters_dir / "SM_tilia_A_mature.fbx"
        test_fbx.write_text("dummy")

        import build_unreal_tree_import_bundle as module
        old_masters = module.MASTERS_DIR
        module.MASTERS_DIR = masters_dir

        try:
            # tilia_cordata should resolve to tilia (alias)
            asset_path, fbx_name, status = resolve_asset_path("tilia_cordata")
            assert status == "alias_master"
            assert "tilia" in asset_path
        finally:
            module.MASTERS_DIR = old_masters

    def test_resolve_genus_fallback(self, tmp_path):
        masters_dir = tmp_path / "masters"
        masters_dir.mkdir()
        # Create the acer master for genus fallback
        test_fbx = masters_dir / "SM_acer_platanoides_A_mature.fbx"
        test_fbx.write_text("dummy")

        import build_unreal_tree_import_bundle as module
        old_masters = module.MASTERS_DIR
        module.MASTERS_DIR = masters_dir

        try:
            # Test genus-based fallback (no exact match)
            asset_path, fbx_name, status = resolve_asset_path("acer_saccharum")
            assert status == "alias_genus"
            assert "acer" in asset_path
        finally:
            module.MASTERS_DIR = old_masters

    def test_resolve_evergreen_fallback(self):
        # Spruce should fall into evergreen fallback
        asset_path, fbx_name, status = resolve_asset_path("picea_unknown")
        assert status == "alias_genus"
        assert "spruce" in asset_path.lower()

    def test_resolve_deciduous_fallback(self):
        # Maple should fall into deciduous fallback
        asset_path, fbx_name, status = resolve_asset_path("unknown_maple_species")
        assert status == "fallback_deciduous"
        assert "acer" in asset_path.lower()

    def test_resolve_pine_fallback_evergreen(self):
        # Pine should be evergreen fallback (via genus matching)
        asset_path, fbx_name, status = resolve_asset_path("pinus_unknown")
        assert status == "alias_genus"

    def test_resolve_cedar_fallback_evergreen(self):
        # Cedar matches fallback evergreen path directly
        asset_path, fbx_name, status = resolve_asset_path("cedar_unknown")
        assert status == "fallback_evergreen"

    def test_resolve_fir_fallback_deciduous(self):
        # Fir doesn't match evergreen keywords, falls back to deciduous
        asset_path, fbx_name, status = resolve_asset_path("abies_unknown")
        assert status == "fallback_deciduous"
        assert "acer" in asset_path.lower()  # Falls back to acer


class TestBuildManifest:
    """Test the build_manifest function."""

    def test_build_manifest_empty_list(self):
        manifest = build_manifest([])
        assert manifest == []

    def test_build_manifest_single_species(self, tmp_path):
        masters_dir = tmp_path / "masters"
        masters_dir.mkdir()
        # Create a fallback master
        fbx = masters_dir / "SM_acer_A_mature.fbx"
        fbx.write_text("dummy")

        import build_unreal_tree_import_bundle as module
        old_masters = module.MASTERS_DIR
        module.MASTERS_DIR = masters_dir

        try:
            manifest = build_manifest(["blue_spruce"])
            assert len(manifest) == 1
            assert manifest[0]["species_key"] == "blue_spruce"
            assert "resolved_asset_path" in manifest[0]
            assert "resolution_status" in manifest[0]
        finally:
            module.MASTERS_DIR = old_masters

    def test_build_manifest_multiple_species(self, tmp_path):
        masters_dir = tmp_path / "masters"
        masters_dir.mkdir()
        fbx = masters_dir / "SM_acer_A_mature.fbx"
        fbx.write_text("dummy")

        import build_unreal_tree_import_bundle as module
        old_masters = module.MASTERS_DIR
        module.MASTERS_DIR = masters_dir

        try:
            manifest = build_manifest(
                ["blue_spruce", "white_cedar", "eastern_white_pine"]
            )
            assert len(manifest) == 3
            # Check they are sorted
            keys = [m["species_key"] for m in manifest]
            assert keys == sorted(keys)
        finally:
            module.MASTERS_DIR = old_masters

    def test_build_manifest_deduplicates(self, tmp_path):
        masters_dir = tmp_path / "masters"
        masters_dir.mkdir()
        fbx = masters_dir / "SM_acer_A_mature.fbx"
        fbx.write_text("dummy")

        import build_unreal_tree_import_bundle as module
        old_masters = module.MASTERS_DIR
        module.MASTERS_DIR = masters_dir

        try:
            # Pass duplicate species keys
            manifest = build_manifest(
                ["blue_spruce", "blue_spruce", "blue_spruce", "white_cedar"]
            )
            assert len(manifest) == 2
            species_keys = [m["species_key"] for m in manifest]
            assert "blue_spruce" in species_keys
            assert "white_cedar" in species_keys
        finally:
            module.MASTERS_DIR = old_masters

    def test_build_manifest_includes_source_fbx_path(self, tmp_path):
        masters_dir = tmp_path / "masters"
        masters_dir.mkdir()
        fbx = masters_dir / "SM_acer_A_mature.fbx"
        fbx.write_text("dummy")

        import build_unreal_tree_import_bundle as module
        old_masters = module.MASTERS_DIR
        module.MASTERS_DIR = masters_dir

        try:
            manifest = build_manifest(["blue_spruce"])
            assert manifest[0]["source_fbx"]
            assert "SM_" in manifest[0]["source_fbx"]
        finally:
            module.MASTERS_DIR = old_masters


class TestAliasToMasterMapping:
    """Test the ALIAS_TO_MASTER mapping."""

    def test_alias_to_master_tilia_cordata(self):
        assert ALIAS_TO_MASTER["tilia_cordata"] == "tilia"

    def test_alias_to_master_acer_variants(self):
        assert ALIAS_TO_MASTER["acer_platanoides_crimson_king"] == "acer_platanoides"
        assert ALIAS_TO_MASTER["acer_platanoides_emerald_queen"] == "acer_platanoides"

    def test_alias_to_master_pinus_nigra(self):
        assert ALIAS_TO_MASTER["pinus_nigra"] == "eastern_white_pine"

    def test_alias_to_master_ulmus(self):
        assert ALIAS_TO_MASTER["ulmus_americana"] == "ulmus"
        assert ALIAS_TO_MASTER["ulmus_pumila"] == "ulmus"


class TestGenusToMasterMapping:
    """Test the GENUS_TO_MASTER mapping."""

    def test_genus_to_master_acer(self):
        assert GENUS_TO_MASTER["acer_"] == "acer_platanoides"

    def test_genus_to_master_picea(self):
        assert GENUS_TO_MASTER["picea_"] == "white_spruce"

    def test_genus_to_master_pinus(self):
        assert GENUS_TO_MASTER["pinus_"] == "eastern_white_pine"

    def test_genus_to_master_thuja(self):
        assert GENUS_TO_MASTER["thuja_"] == "white_cedar"

    def test_genus_to_master_all_have_masters(self):
        # Each genus should map to a valid master key
        for genus, master in GENUS_TO_MASTER.items():
            assert isinstance(master, str)
            assert len(master) > 0


class TestResolveAssetPathFallbacks:
    """Test fallback behavior when masters don't exist."""

    def test_resolve_fallback_missing_source_creates_fallback(self, tmp_path):
        masters_dir = tmp_path / "masters"
        masters_dir.mkdir()
        # Create only the fallback master
        fbx = masters_dir / "SM_acer_A_mature.fbx"
        fbx.write_text("dummy")

        import build_unreal_tree_import_bundle as module
        old_masters = module.MASTERS_DIR
        module.MASTERS_DIR = masters_dir

        try:
            # Request a species that doesn't have a master
            asset_path, fbx_name, status = resolve_asset_path("unknown_tree")
            assert "acer" in asset_path.lower()  # Falls back to acer
        finally:
            module.MASTERS_DIR = old_masters

    def test_resolve_conifer_vs_deciduous(self):
        # Conifers should get evergreen fallback
        conifer_keys = ["spruce_unknown", "pine_unknown", "fir_unknown"]
        for key in conifer_keys:
            asset_path, fbx_name, status = resolve_asset_path(key)
            assert status == "fallback_evergreen"
            assert "spruce" in asset_path.lower()


class TestResolveAssetPathAssetPathFormat:
    """Test asset path format consistency."""

    def test_asset_path_starts_with_game(self):
        asset_path, _, _ = resolve_asset_path("blue_spruce")
        assert asset_path.startswith("/Game/")

    def test_asset_path_includes_foliage_trees(self):
        asset_path, _, _ = resolve_asset_path("blue_spruce")
        assert "Foliage/Trees" in asset_path

    def test_fbx_name_ends_with_fbx(self):
        _, fbx_name, _ = resolve_asset_path("blue_spruce")
        assert fbx_name.endswith(".fbx")

    def test_fbx_name_starts_with_sm(self):
        _, fbx_name, _ = resolve_asset_path("blue_spruce")
        assert fbx_name.startswith("SM_")
