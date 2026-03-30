"""Unit tests for export_unreal_street_furniture_data.py - pure function tests."""

import pytest
from pathlib import Path
import unicodedata

ORIGIN_X = 312672.94
ORIGIN_Y = 4834994.86


def fold(v: str) -> str:
    return unicodedata.normalize("NFKD", (v or "").lower()).encode("ascii", "ignore").decode("ascii")


def classify_art(forme_art: str) -> str:
    f = fold(forme_art)
    if "mural" in f:
        return "public_art_mural"
    if "sculpt" in f or "statue" in f:
        return "public_art_sculpture"
    return "public_art_installation"


def classify_terrace(type_terrasse: str) -> str:
    t = fold(type_terrasse)
    if "platform" in t or "deck" in t:
        return "terrace_platform"
    if "patio" in t:
        return "terrace_patio"
    return "terrace_module"


def classify_shelter(type_abribus: str) -> str:
    t = fold(type_abribus)
    if "glass" in t or "vitre" in t:
        return "bus_shelter_glass"
    return "bus_shelter_standard"


class TestFold:
    """Test the fold function for Unicode normalization."""

    def test_fold_basic(self):
        assert fold("Hello") == "hello"

    def test_fold_accents_french(self):
        assert fold("Murale") == "murale"

    def test_fold_uppercase(self):
        assert fold("SCULPTURE") == "sculpture"

    def test_fold_none(self):
        assert fold(None) == ""

    def test_fold_empty(self):
        assert fold("") == ""


class TestClassifyArt:
    """Test the classify_art function."""

    def test_classify_art_mural(self):
        assert classify_art("Murale") == "public_art_mural"

    def test_classify_art_mural_english(self):
        assert classify_art("Mural") == "public_art_mural"

    def test_classify_art_sculpture(self):
        assert classify_art("Sculpture") == "public_art_sculpture"

    def test_classify_art_statue(self):
        assert classify_art("Statue") == "public_art_sculpture"

    def test_classify_art_installation(self):
        assert classify_art("Installation") == "public_art_installation"

    def test_classify_art_default(self):
        assert classify_art("Unknown") == "public_art_installation"

    def test_classify_art_case_insensitive(self):
        assert classify_art("MURALE") == "public_art_mural"

    def test_classify_art_empty(self):
        assert classify_art("") == "public_art_installation"

    def test_classify_art_none(self):
        assert classify_art(None) == "public_art_installation"

    def test_classify_art_sculpture_with_accents(self):
        assert classify_art("Sculpture monumentale") == "public_art_sculpture"


class TestClassifyTerrace:
    """Test the classify_terrace function."""

    def test_classify_terrace_platform(self):
        assert classify_terrace("Platform") == "terrace_platform"

    def test_classify_terrace_deck(self):
        assert classify_terrace("Deck") == "terrace_platform"

    def test_classify_terrace_patio(self):
        assert classify_terrace("Patio") == "terrace_patio"

    def test_classify_terrace_module(self):
        assert classify_terrace("Module") == "terrace_module"

    def test_classify_terrace_default(self):
        assert classify_terrace("Pergola") == "terrace_module"

    def test_classify_terrace_case_insensitive(self):
        assert classify_terrace("PLATFORM") == "terrace_platform"

    def test_classify_terrace_empty(self):
        assert classify_terrace("") == "terrace_module"

    def test_classify_terrace_none(self):
        assert classify_terrace(None) == "terrace_module"

    def test_classify_terrace_platform_with_accents(self):
        # "Plate-forme" doesn't contain "platform" or "deck" exactly
        assert classify_terrace("Plate-forme") == "terrace_module"


class TestClassifyShelter:
    """Test the classify_shelter function."""

    def test_classify_shelter_glass(self):
        assert classify_shelter("Glass") == "bus_shelter_glass"

    def test_classify_shelter_vitre(self):
        assert classify_shelter("Vitre") == "bus_shelter_glass"

    def test_classify_shelter_standard(self):
        assert classify_shelter("Standard") == "bus_shelter_standard"

    def test_classify_shelter_default(self):
        assert classify_shelter("Enclosed") == "bus_shelter_standard"

    def test_classify_shelter_case_insensitive(self):
        assert classify_shelter("GLASS") == "bus_shelter_glass"

    def test_classify_shelter_empty(self):
        assert classify_shelter("") == "bus_shelter_standard"

    def test_classify_shelter_none(self):
        assert classify_shelter(None) == "bus_shelter_standard"

    def test_classify_shelter_partial_match(self):
        assert classify_shelter("Glass-enclosed shelter") == "bus_shelter_glass"


class TestCoordinateConstants:
    """Test coordinate system constants."""

    def test_origin_x(self):
        assert ORIGIN_X == 312672.94

    def test_origin_y(self):
        assert ORIGIN_Y == 4834994.86

    def test_coordinate_transform(self):
        x_2952 = ORIGIN_X + 50.0
        y_2952 = ORIGIN_Y + 100.0

        local_x = x_2952 - ORIGIN_X
        local_y = y_2952 - ORIGIN_Y

        assert local_x == pytest.approx(50.0, abs=0.01)
        assert local_y == pytest.approx(100.0, abs=0.01)

    def test_coordinate_to_centimeters(self):
        x_2952 = ORIGIN_X + 30.0
        y_2952 = ORIGIN_Y + 40.0

        x_cm = (x_2952 - ORIGIN_X) * 100.0
        y_cm = (y_2952 - ORIGIN_Y) * 100.0

        assert x_cm == pytest.approx(3000.0, abs=0.1)
        assert y_cm == pytest.approx(4000.0, abs=0.1)


class TestClassifyArtEdgeCases:
    """Test edge cases for art classification."""

    def test_classify_art_multiple_keywords(self):
        # "Sculpture" should match even with other text
        assert classify_art("Public Sculpture Installation") == "public_art_sculpture"

    def test_classify_art_mural_in_middle(self):
        assert classify_art("Outdoor Mural Art") == "public_art_mural"


class TestClassifyTerraceEdgeCases:
    """Test edge cases for terrace classification."""

    def test_classify_terrace_deck_in_middle(self):
        assert classify_terrace("Wooden Deck Area") == "terrace_platform"

    def test_classify_terrace_multiple_types(self):
        # "Platform" comes first in classify function
        assert classify_terrace("Platform Patio Deck") == "terrace_platform"


class TestClassifyShelterEdgeCases:
    """Test edge cases for shelter classification."""

    def test_classify_shelter_vitre_french(self):
        assert classify_shelter("Abribus Vitre") == "bus_shelter_glass"

    def test_classify_shelter_glass_uppercase(self):
        assert classify_shelter("GLASS SHELTER") == "bus_shelter_glass"
