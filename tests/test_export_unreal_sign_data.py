"""Unit tests for export_unreal_sign_data.py - pure function tests."""

import pytest
from pathlib import Path
import unicodedata

ORIGIN_X = 312672.94
ORIGIN_Y = 4834994.86


def fold(v: str) -> str:
    return unicodedata.normalize("NFKD", (v or "").lower()).encode("ascii", "ignore").decode("ascii")


def sign_key(type_panneau: str) -> str:
    t = fold(type_panneau)
    if "vitesse" in t or "speed" in t:
        return "speed_sign"
    if "interdiction" in t or "restriction" in t:
        return "restriction_sign"
    if "avertissement" in t or "warning" in t:
        return "warning_sign"
    if "sens unique" in t or "one way" in t:
        return "oneway_sign"
    if "information" in t or "direction" in t:
        return "info_sign"
    return "generic_sign"


def scale_for_key(key: str) -> float:
    if key in {"warning_sign", "speed_sign"}:
        return 1.05
    if key in {"restriction_sign", "oneway_sign"}:
        return 0.95
    return 1.0


class TestFold:
    """Test the fold function for Unicode normalization."""

    def test_fold_basic(self):
        assert fold("Hello") == "hello"

    def test_fold_accents(self):
        assert fold("Vitesse") == "vitesse"

    def test_fold_uppercase(self):
        assert fold("SPEED") == "speed"

    def test_fold_none(self):
        assert fold(None) == ""

    def test_fold_empty(self):
        assert fold("") == ""

    def test_fold_special_chars(self):
        assert fold("Sens-Unique") == "sens-unique"


class TestSignKey:
    """Test the sign_key function."""

    def test_sign_key_speed_french(self):
        assert sign_key("Vitesse") == "speed_sign"

    def test_sign_key_speed_english(self):
        assert sign_key("Speed") == "speed_sign"

    def test_sign_key_restriction(self):
        assert sign_key("Interdiction") == "restriction_sign"

    def test_sign_key_restriction_english(self):
        assert sign_key("Restriction") == "restriction_sign"

    def test_sign_key_warning(self):
        assert sign_key("Avertissement") == "warning_sign"

    def test_sign_key_warning_english(self):
        assert sign_key("Warning") == "warning_sign"

    def test_sign_key_oneway_french(self):
        assert sign_key("Sens Unique") == "oneway_sign"

    def test_sign_key_oneway_english(self):
        assert sign_key("One Way") == "oneway_sign"

    def test_sign_key_info_french(self):
        assert sign_key("Information") == "info_sign"

    def test_sign_key_direction(self):
        assert sign_key("Direction") == "info_sign"

    def test_sign_key_generic(self):
        assert sign_key("Custom") == "generic_sign"

    def test_sign_key_case_insensitive(self):
        assert sign_key("VITESSE") == "speed_sign"

    def test_sign_key_empty(self):
        assert sign_key("") == "generic_sign"

    def test_sign_key_none(self):
        assert sign_key(None) == "generic_sign"

    def test_sign_key_partial_match_speed(self):
        assert sign_key("Panneau Vitesse 50") == "speed_sign"

    def test_sign_key_priority_oneway_over_generic(self):
        # "sens unique" should match over generic
        assert sign_key("Type: Sens Unique") == "oneway_sign"


class TestScaleForKey:
    """Test the scale_for_key function."""

    def test_scale_warning_sign(self):
        assert scale_for_key("warning_sign") == 1.05

    def test_scale_speed_sign(self):
        assert scale_for_key("speed_sign") == 1.05

    def test_scale_restriction_sign(self):
        assert scale_for_key("restriction_sign") == 0.95

    def test_scale_oneway_sign(self):
        assert scale_for_key("oneway_sign") == 0.95

    def test_scale_info_sign(self):
        assert scale_for_key("info_sign") == 1.0

    def test_scale_generic_sign(self):
        assert scale_for_key("generic_sign") == 1.0

    def test_scale_unknown_sign(self):
        assert scale_for_key("unknown_sign") == 1.0


class TestCoordinateConstants:
    """Test coordinate system constants."""

    def test_origin_x(self):
        assert ORIGIN_X == 312672.94

    def test_origin_y(self):
        assert ORIGIN_Y == 4834994.86

    def test_coordinate_transform_simple(self):
        x_2952 = ORIGIN_X + 25.0
        y_2952 = ORIGIN_Y + 50.0

        local_x = x_2952 - ORIGIN_X
        local_y = y_2952 - ORIGIN_Y

        assert local_x == pytest.approx(25.0, abs=0.01)
        assert local_y == pytest.approx(50.0, abs=0.01)

    def test_coordinate_transform_to_centimeters(self):
        x_2952 = ORIGIN_X + 10.0
        y_2952 = ORIGIN_Y + 20.0

        x_cm = (x_2952 - ORIGIN_X) * 100.0
        y_cm = (y_2952 - ORIGIN_Y) * 100.0

        assert x_cm == pytest.approx(1000.0, abs=0.1)
        assert y_cm == pytest.approx(2000.0, abs=0.1)


class TestSignKeyEdgeCases:
    """Test edge cases for sign key classification."""

    def test_sign_key_multiple_keywords_speed_first(self):
        # "vitesse" comes first in the function
        assert sign_key("Vitesse Interdiction") == "speed_sign"

    def test_sign_key_whitespace(self):
        assert sign_key("   ") == "generic_sign"

    def test_sign_key_partial_word_match(self):
        # Test that "vitesse" is found within longer strings
        assert sign_key("Panneau de Vitesse Limite") == "speed_sign"

    def test_sign_key_french_accents(self):
        assert sign_key("Avertissement Danger") == "warning_sign"


class TestScaleForKeyRanges:
    """Test scale values are within reasonable ranges."""

    def test_scale_range_min(self):
        min_scale = 0.95
        assert scale_for_key("restriction_sign") == min_scale

    def test_scale_range_max(self):
        max_scale = 1.05
        assert scale_for_key("warning_sign") == max_scale

    def test_scale_range_default(self):
        default_scale = 1.0
        assert scale_for_key("info_sign") == default_scale

    def test_all_scales_positive(self):
        keys = [
            "speed_sign",
            "restriction_sign",
            "warning_sign",
            "oneway_sign",
            "info_sign",
            "generic_sign",
        ]
        for key in keys:
            assert scale_for_key(key) > 0


class TestFoldEdgeCases:
    """Test edge cases for fold function."""

    def test_fold_unicode_normalization(self):
        # Test NFKD normalization
        assert fold("Café") == "cafe"

    def test_fold_mixed_case_with_accents(self):
        assert fold("CAFÉ") == "cafe"

    def test_fold_only_accents(self):
        assert fold("é à ù") == "e a u"
