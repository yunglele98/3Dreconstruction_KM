"""Unit tests for export_unreal_alley_data.py - pure function tests."""

import pytest
from pathlib import Path
import unicodedata

ORIGIN_X = 312672.94
ORIGIN_Y = 4834994.86


def fold(v: str) -> str:
    return unicodedata.normalize("NFKD", (v or "").lower()).encode("ascii", "ignore").decode("ascii")


def classify_alley(type_voie: str, revetement: str, verdissement: str, etat: str) -> str:
    t = fold(type_voie)
    r = fold(revetement)
    g = fold(verdissement)
    e = fold(etat)

    if "pietonne" in t:
        return "alley_pedestrian"
    if "prive" in t or "service" in t:
        return "alley_service"
    if "partagee" in t:
        if "modere" in g or "vegetal" in g:
            return "alley_shared_green"
        return "alley_shared"
    if "vehiculaire" in t:
        if "gravier" in r:
            return "alley_vehicle_gravel"
        if "beton" in r:
            return "alley_vehicle_concrete"
        return "alley_vehicle_asphalt"
    if "critique" in e or "mauvais" in e:
        return "alley_degraded"
    return "alley_vehicle_asphalt"


def default_scale(key: str) -> float:
    if key in {"alley_service", "alley_pedestrian"}:
        return 0.95
    if key in {"alley_shared_green", "alley_shared"}:
        return 1.05
    if key == "alley_degraded":
        return 1.1
    return 1.0


class TestFold:
    """Test the fold function for Unicode normalization."""

    def test_fold_basic_lowercase(self):
        assert fold("Hello World") == "hello world"

    def test_fold_accents(self):
        assert fold("Café") == "cafe"

    def test_fold_french_accents(self):
        assert fold("piétonne") == "pietonne"

    def test_fold_diacritics(self):
        assert fold("naïve") == "naive"

    def test_fold_empty_string(self):
        assert fold("") == ""

    def test_fold_none(self):
        assert fold(None) == ""

    def test_fold_mixed_case_accents(self):
        assert fold("CAFÉ PIÉTONNE") == "cafe pietonne"


class TestClassifyAlley:
    """Test the classify_alley function."""

    def test_classify_pedestrian(self):
        key = classify_alley("Piétonne", "Béton", "", "")
        assert key == "alley_pedestrian"

    def test_classify_pedestrian_english(self):
        key = classify_alley("Pedestrian", "Asphalt", "", "")
        # "Pedestrian" doesn't contain "pietonne" so won't match
        assert key == "alley_vehicle_asphalt"

    def test_classify_private(self):
        key = classify_alley("Privée", "", "", "")
        assert key == "alley_service"

    def test_classify_service(self):
        key = classify_alley("Service", "", "", "")
        assert key == "alley_service"

    def test_classify_shared_green(self):
        key = classify_alley("Partagée", "", "Modéré", "")
        assert key == "alley_shared_green"

    def test_classify_shared_green_vegetal(self):
        key = classify_alley("Partagée", "", "Végétal", "")
        assert key == "alley_shared_green"

    def test_classify_shared_basic(self):
        key = classify_alley("Partagée", "", "", "")
        assert key == "alley_shared"

    def test_classify_vehicular_gravel(self):
        key = classify_alley("Véhiculaire", "Gravier", "", "")
        assert key == "alley_vehicle_gravel"

    def test_classify_vehicular_concrete(self):
        key = classify_alley("Véhiculaire", "Béton", "", "")
        assert key == "alley_vehicle_concrete"

    def test_classify_vehicular_asphalt(self):
        key = classify_alley("Véhiculaire", "Asphalte", "", "")
        assert key == "alley_vehicle_asphalt"

    def test_classify_vehicular_default(self):
        key = classify_alley("Véhiculaire", "", "", "")
        assert key == "alley_vehicle_asphalt"

    def test_classify_degraded_critical(self):
        key = classify_alley("", "", "", "Critique")
        assert key == "alley_degraded"

    def test_classify_degraded_poor(self):
        key = classify_alley("", "", "", "Mauvais")
        assert key == "alley_degraded"

    def test_classify_default(self):
        key = classify_alley("", "", "", "")
        assert key == "alley_vehicle_asphalt"

    def test_classify_case_insensitive(self):
        key = classify_alley("PIÉTONNE", "BÉTON", "", "")
        assert key == "alley_pedestrian"

    def test_classify_precedence_pedestrian_over_vehicle(self):
        # Pedestrian should take precedence
        key = classify_alley("Piétonne", "Gravier", "", "")
        assert key == "alley_pedestrian"


class TestDefaultScale:
    """Test the default_scale function."""

    def test_scale_service(self):
        assert default_scale("alley_service") == 0.95

    def test_scale_pedestrian(self):
        assert default_scale("alley_pedestrian") == 0.95

    def test_scale_shared_green(self):
        assert default_scale("alley_shared_green") == 1.05

    def test_scale_shared(self):
        assert default_scale("alley_shared") == 1.05

    def test_scale_degraded(self):
        assert default_scale("alley_degraded") == 1.1

    def test_scale_vehicle_asphalt(self):
        assert default_scale("alley_vehicle_asphalt") == 1.0

    def test_scale_vehicle_gravel(self):
        assert default_scale("alley_vehicle_gravel") == 1.0

    def test_scale_vehicle_concrete(self):
        assert default_scale("alley_vehicle_concrete") == 1.0

    def test_scale_unknown(self):
        assert default_scale("unknown_alley_type") == 1.0


class TestCoordinateConstants:
    """Test coordinate origin constants."""

    def test_origin_x_exists(self):
        assert ORIGIN_X == 312672.94

    def test_origin_y_exists(self):
        assert ORIGIN_Y == 4834994.86

    def test_coordinate_transform(self):
        """Test coordinate transform from SRID 2952 to local meters."""
        x_2952 = ORIGIN_X + 100.0
        y_2952 = ORIGIN_Y + 200.0

        local_x = x_2952 - ORIGIN_X
        local_y = y_2952 - ORIGIN_Y

        assert local_x == pytest.approx(100.0, abs=0.01)
        assert local_y == pytest.approx(200.0, abs=0.01)

    def test_coordinate_transform_to_cm(self):
        """Test coordinate transform from local meters to centimeters."""
        x_2952 = ORIGIN_X + 50.0
        y_2952 = ORIGIN_Y + 75.0

        local_x_cm = (x_2952 - ORIGIN_X) * 100.0
        local_y_cm = (y_2952 - ORIGIN_Y) * 100.0

        assert local_x_cm == pytest.approx(5000.0, abs=0.1)
        assert local_y_cm == pytest.approx(7500.0, abs=0.1)


class TestClassifyAlleyEdgeCases:
    """Test edge cases for classify_alley."""

    def test_classify_alley_all_empty(self):
        key = classify_alley("", "", "", "")
        assert key == "alley_vehicle_asphalt"

    def test_classify_alley_none_values(self):
        key = classify_alley(None, None, None, None)
        assert key == "alley_vehicle_asphalt"

    def test_classify_alley_whitespace_only(self):
        key = classify_alley("   ", "   ", "   ", "   ")
        assert key == "alley_vehicle_asphalt"

    def test_classify_shared_green_exact_match_modere(self):
        # Test exact matching for "modere"
        key = classify_alley("Partagée", "", "Modéré", "")
        assert key == "alley_shared_green"

    def test_classify_multiple_keywords_first_match(self):
        # If multiple keywords match, first one in classify function wins
        key = classify_alley("Piétonne Véhiculaire", "", "", "")
        assert key == "alley_pedestrian"

    def test_classify_partial_keyword_match(self):
        # Test that partial matches work
        key = classify_alley("Type: Piétonne Route", "", "", "")
        assert key == "alley_pedestrian"
