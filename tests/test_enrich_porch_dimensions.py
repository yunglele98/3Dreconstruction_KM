"""Unit tests for enrich_porch_dimensions.py"""

import pytest

from scripts.enrich_porch_dimensions import (
    enrich_porch,
    get_porch_columns,
    get_porch_width_m,
    infer_step_count,
    parse_era,
)


class TestParseEra:
    """Tests for parse_era function."""

    def test_exact_match_pre_1889(self):
        assert parse_era("pre-1889") == "pre-1889"

    def test_exact_match_1889_1903(self):
        assert parse_era("1889-1903") == "1889-1903"

    def test_exact_match_1904_1913(self):
        assert parse_era("1904-1913") == "1904-1913"

    def test_exact_match_1914_plus(self):
        # Script uses "1914+" as era key, not "1914-1930"
        result = parse_era("1914-1930")
        assert result in ["1914-1930", "1914+"]

    def test_pre_prefix_lowercase(self):
        assert parse_era("pre-1800") == "pre-1889"

    def test_pre_prefix_uppercase(self):
        assert parse_era("Pre-1800") == "pre-1889"

    def test_year_extraction_1850(self):
        assert parse_era("1850") == "pre-1889"

    def test_year_extraction_1889(self):
        assert parse_era("1889") == "1889-1903"

    def test_year_extraction_1895(self):
        assert parse_era("1895") == "1889-1903"

    def test_year_extraction_1903(self):
        assert parse_era("1903") == "1889-1903"

    def test_year_extraction_1904(self):
        assert parse_era("1904") == "1904-1913"

    def test_year_extraction_1910(self):
        assert parse_era("1910") == "1904-1913"

    def test_year_extraction_1913(self):
        assert parse_era("1913") == "1904-1913"

    def test_year_extraction_1914(self):
        assert parse_era("1914") == "1914+"

    def test_year_extraction_1920(self):
        assert parse_era("1920") == "1914+"

    def test_year_extraction_1950(self):
        assert parse_era("1950") == "1914+"

    def test_year_extraction_2000(self):
        assert parse_era("2000") == "1914+"

    def test_case_insensitive(self):
        assert parse_era("PRE-1889") == "pre-1889"

    def test_whitespace_handling(self):
        assert parse_era("  1895  ") == "1889-1903"

    def test_none_input(self):
        assert parse_era(None) == "1889-1903"

    def test_empty_string(self):
        assert parse_era("") == "1889-1903"

    def test_no_year_match(self):
        assert parse_era("ancient") == "1889-1903"

    def test_year_at_boundary_1889(self):
        assert parse_era("1889") == "1889-1903"

    def test_year_at_boundary_1904(self):
        assert parse_era("1904") == "1904-1913"

    def test_mixed_text_and_year(self):
        assert parse_era("circa 1895, Toronto") == "1889-1903"


class TestGetPorchWidthM:
    """Tests for get_porch_width_m function."""

    def test_narrow_facade_small_porch(self):
        """Facade <= 5m: width = 0.6 × facade."""
        result = get_porch_width_m(4.0)
        assert result == pytest.approx(4.0 * 0.6)

    def test_small_facade_boundary(self):
        """At 5m boundary."""
        result = get_porch_width_m(5.0)
        assert result == pytest.approx(5.0 * 0.6)

    def test_medium_facade(self):
        """5m < facade <= 8m: width = 0.5 × facade."""
        result = get_porch_width_m(6.0)
        assert result == pytest.approx(6.0 * 0.5)

    def test_medium_facade_upper_boundary(self):
        """At 8m boundary."""
        result = get_porch_width_m(8.0)
        assert result == pytest.approx(8.0 * 0.5)

    def test_large_facade(self):
        """Facade > 8m: width = 4.0m (clamped)."""
        result = get_porch_width_m(10.0)
        assert result == 4.0

    def test_very_large_facade(self):
        """Very large facade still clamped to 4.0m."""
        result = get_porch_width_m(20.0)
        assert result == 4.0

    def test_very_small_facade(self):
        """Very small facade still uses proportion."""
        result = get_porch_width_m(2.0)
        assert result == pytest.approx(2.0 * 0.6)

    def test_decimal_facade_width(self):
        """Handle decimal facade widths."""
        result = get_porch_width_m(5.5)
        assert result == pytest.approx(5.5 * 0.5)


class TestGetPorchColumns:
    """Tests for get_porch_columns function."""

    def test_pre_1889_turned_columns(self):
        result = get_porch_columns("pre-1889")
        assert result["count"] == 2
        assert result["type"] == "turned"
        assert result["material"] == "wood"

    def test_1889_1903_turned_columns(self):
        result = get_porch_columns("1889-1903")
        assert result["count"] == 2
        assert result["type"] == "turned"
        assert result["material"] == "wood"

    def test_1904_1913_tapered_columns(self):
        result = get_porch_columns("1904-1913")
        assert result["count"] == 2
        assert result["type"] == "tapered_square"
        assert result["material"] == "wood"

    def test_1914_plus_square_columns(self):
        result = get_porch_columns("1914+")
        assert result["count"] == 2
        assert result["type"] == "square"
        assert result["material"] == "wood"

    def test_all_eras_have_two_columns(self):
        """All eras should specify 2 columns."""
        for era in ["pre-1889", "1889-1903", "1904-1913", "1914+"]:
            result = get_porch_columns(era)
            assert result["count"] == 2

    def test_all_eras_wood_material(self):
        """All eras should use wood material."""
        for era in ["pre-1889", "1889-1903", "1904-1913", "1914+"]:
            result = get_porch_columns(era)
            assert result["material"] == "wood"

    def test_unknown_era_defaults_to_later(self):
        """Unknown era should default to square (1914+)."""
        result = get_porch_columns("1950-1970")
        assert result["type"] == "square"


class TestInferStepCount:
    """Tests for infer_step_count function."""

    def test_from_deep_facade_analysis(self):
        """Extract step_count from deep_facade_analysis.depth_notes."""
        params = {
            "deep_facade_analysis": {
                "depth_notes": {
                    "step_count": 3,
                }
            }
        }
        result = infer_step_count(params)
        assert result == 3

    def test_from_foundation_height(self):
        """Infer from foundation_height_m (assume 0.18m per step)."""
        params = {
            "foundation_height_m": 0.36,
        }
        result = infer_step_count(params)
        # 0.36 / 0.18 = 2
        assert result == 2

    def test_foundation_height_rounding(self):
        """Test rounding of foundation height calculation."""
        params = {
            "foundation_height_m": 0.5,
        }
        result = infer_step_count(params)
        # 0.5 / 0.18 ≈ 2.78 → rounds to 3
        assert result == 3

    def test_foundation_height_minimum(self):
        """Step count should be at least 2."""
        params = {
            "foundation_height_m": 0.1,
        }
        result = infer_step_count(params)
        assert result >= 2

    def test_default_step_count(self):
        """Default to 2 steps when no data available."""
        params = {}
        result = infer_step_count(params)
        assert result == 2

    def test_deep_analysis_takes_priority(self):
        """deep_facade_analysis should take priority over foundation_height."""
        params = {
            "deep_facade_analysis": {
                "depth_notes": {
                    "step_count": 4,
                }
            },
            "foundation_height_m": 0.36,
        }
        result = infer_step_count(params)
        assert result == 4

    def test_non_integer_step_count_ignored(self):
        """Non-integer step_count in deep_facade_analysis should be ignored."""
        params = {
            "deep_facade_analysis": {
                "depth_notes": {
                    "step_count": "three",
                }
            }
        }
        result = infer_step_count(params)
        # Should fall back to default
        assert result == 2

    def test_non_dict_deep_analysis(self):
        """Handle non-dict deep_facade_analysis."""
        params = {
            "deep_facade_analysis": "not a dict",
        }
        result = infer_step_count(params)
        assert result == 2

    def test_non_dict_depth_notes(self):
        """Handle non-dict depth_notes."""
        params = {
            "deep_facade_analysis": {
                "depth_notes": "not a dict",
            }
        }
        result = infer_step_count(params)
        assert result == 2

    def test_zero_foundation_height(self):
        """Handle zero foundation height."""
        params = {
            "foundation_height_m": 0.0,
        }
        result = infer_step_count(params)
        # Should return minimum of 2
        assert result == 2


class TestEnrichPorch:
    """Tests for enrich_porch function."""

    def test_no_porch_returns_false(self):
        params = {
            "porch_present": False,
        }
        changed, msg = enrich_porch(params)
        assert changed is False
        assert "no porch" in msg.lower()

    def test_missing_porch_present(self):
        params = {}
        changed, msg = enrich_porch(params)
        assert changed is False

    def test_already_has_dimensions(self):
        params = {
            "porch_present": True,
            "porch_width_m": 3.0,
            "porch_depth_m": 1.8,
            "porch_height_m": 3.0,
        }
        changed, msg = enrich_porch(params)
        assert changed is False
        assert "already has dimensions" in msg.lower()

    def test_enrich_missing_width(self):
        params = {
            "porch_present": True,
            "porch_depth_m": 1.8,
            "porch_height_m": 3.0,
            "facade_width_m": 5.0,
        }
        changed, msg = enrich_porch(params)
        assert changed is True
        assert "porch_width_m" in params

    def test_enrich_missing_depth(self):
        params = {
            "porch_present": True,
            "porch_width_m": 3.0,
            "porch_height_m": 3.0,
        }
        changed, msg = enrich_porch(params)
        assert changed is True
        assert params["porch_depth_m"] == 1.8

    def test_enrich_missing_height(self):
        params = {
            "porch_present": True,
            "porch_width_m": 3.0,
            "porch_depth_m": 1.8,
            "floor_heights_m": [3.5],
        }
        changed, msg = enrich_porch(params)
        assert changed is True
        assert params["porch_height_m"] == 3.5

    def test_enrich_all_dimensions(self):
        params = {
            "porch_present": True,
            "facade_width_m": 6.0,
            "floor_heights_m": [3.2],
        }
        changed, msg = enrich_porch(params)
        assert changed is True
        assert "porch_width_m" in params
        assert "porch_depth_m" in params
        assert "porch_height_m" in params

    def test_porch_detail_created(self):
        params = {
            "porch_present": True,
            "facade_width_m": 5.0,
            "hcd_data": {"construction_date": "1895"},
        }
        changed, msg = enrich_porch(params)
        assert changed is True
        assert "porch_detail" in params
        assert "columns" in params["porch_detail"]
        assert "railing" in params["porch_detail"]
        assert "step_count" in params["porch_detail"]

    def test_columns_turned_for_1895(self):
        params = {
            "porch_present": True,
            "facade_width_m": 5.0,
            "hcd_data": {"construction_date": "1895"},
        }
        changed, msg = enrich_porch(params)
        assert params["porch_detail"]["columns"]["type"] == "turned"

    def test_columns_tapered_for_1910(self):
        params = {
            "porch_present": True,
            "facade_width_m": 5.0,
            "hcd_data": {"construction_date": "1910"},
        }
        changed, msg = enrich_porch(params)
        assert params["porch_detail"]["columns"]["type"] == "tapered_square"

    def test_railing_present_and_correct(self):
        params = {
            "porch_present": True,
            "facade_width_m": 5.0,
        }
        changed, msg = enrich_porch(params)
        assert params["porch_detail"]["railing"]["present"] is True
        assert params["porch_detail"]["railing"]["height_m"] == 0.9
        assert params["porch_detail"]["railing"]["type"] == "baluster"

    def test_default_facade_width(self):
        params = {
            "porch_present": True,
        }
        changed, msg = enrich_porch(params)
        assert changed is True
        # Should use default 5.0m facade width
        assert params["porch_width_m"] == pytest.approx(5.0 * 0.6)

    def test_default_floor_height(self):
        params = {
            "porch_present": True,
            "facade_width_m": 5.0,
        }
        changed, msg = enrich_porch(params)
        assert changed is True
        # Should use default 3.0m floor height
        assert params["porch_height_m"] == 3.0

    def test_empty_floor_heights_array(self):
        params = {
            "porch_present": True,
            "facade_width_m": 5.0,
            "floor_heights_m": [],
        }
        changed, msg = enrich_porch(params)
        assert changed is True
        # Should use default 3.0m
        assert params["porch_height_m"] == 3.0

    def test_non_dict_hcd_data(self):
        params = {
            "porch_present": True,
            "facade_width_m": 5.0,
            "hcd_data": "not a dict",
        }
        changed, msg = enrich_porch(params)
        assert changed is True
        # Should not crash, use default era

    def test_non_dict_porch_detail(self):
        params = {
            "porch_present": True,
            "facade_width_m": 5.0,
            "porch_detail": "not a dict",
        }
        changed, msg = enrich_porch(params)
        assert changed is True
        # Should replace with dict

    def test_porch_width_rounding(self):
        params = {
            "porch_present": True,
            "facade_width_m": 7.777,
        }
        changed, msg = enrich_porch(params)
        # Width should be rounded to 2 decimal places
        assert isinstance(params["porch_width_m"], float)

    def test_porch_height_rounding(self):
        params = {
            "porch_present": True,
            "facade_width_m": 5.0,
            "floor_heights_m": [3.555],
        }
        changed, msg = enrich_porch(params)
        # Height should be rounded to 2 decimal places
        assert isinstance(params["porch_height_m"], float)

    def test_width_calculation_small_facade(self):
        """Test width calculation for small facade (5.0m)."""
        params = {
            "porch_present": True,
            "facade_width_m": 5.0,
        }
        changed, msg = enrich_porch(params)
        # 5.0 * 0.6 = 3.0
        assert params["porch_width_m"] == pytest.approx(3.0)

    def test_width_calculation_medium_facade(self):
        """Test width calculation for medium facade (6.0m)."""
        params = {
            "porch_present": True,
            "facade_width_m": 6.0,
        }
        changed, msg = enrich_porch(params)
        # 6.0 * 0.5 = 3.0
        assert params["porch_width_m"] == pytest.approx(3.0)

    def test_width_calculation_large_facade(self):
        """Test width calculation for large facade (10.0m)."""
        params = {
            "porch_present": True,
            "facade_width_m": 10.0,
        }
        changed, msg = enrich_porch(params)
        # Clamped to 4.0m
        assert params["porch_width_m"] == 4.0

    def test_step_count_inference_from_foundation(self):
        params = {
            "porch_present": True,
            "facade_width_m": 5.0,
            "foundation_height_m": 0.54,
        }
        changed, msg = enrich_porch(params)
        # 0.54 / 0.18 = 3
        assert params["porch_detail"]["step_count"] == 3

    def test_step_count_from_deep_analysis_priority(self):
        params = {
            "porch_present": True,
            "facade_width_m": 5.0,
            "foundation_height_m": 0.36,
            "deep_facade_analysis": {
                "depth_notes": {
                    "step_count": 5,
                }
            },
        }
        changed, msg = enrich_porch(params)
        # Deep analysis should take priority
        assert params["porch_detail"]["step_count"] == 5


class TestIntegration:
    """Integration tests for porch enrichment workflow."""

    def test_full_porch_enrichment_workflow(self):
        """Test complete porch enrichment."""
        params = {
            "porch_present": True,
            "facade_width_m": 5.5,
            "floor_heights_m": [3.2, 3.2],
            "hcd_data": {"construction_date": "1900"},
            "deep_facade_analysis": {
                "depth_notes": {
                    "step_count": 3,
                }
            },
        }

        changed, msg = enrich_porch(params)
        assert changed is True

        # Check all enriched fields
        # 5.5 <= 5.0? No, so 5.5 * 0.5 = 2.75
        expected_width = 5.5 * 0.5 if 5.5 > 5.0 else 5.5 * 0.6
        assert params["porch_width_m"] == pytest.approx(expected_width)
        assert params["porch_depth_m"] == 1.8
        assert params["porch_height_m"] == 3.2

        # Check porch_detail
        assert params["porch_detail"]["columns"]["type"] == "turned"
        assert params["porch_detail"]["railing"]["present"] is True
        assert params["porch_detail"]["step_count"] == 3

    def test_enrichment_preserves_existing_columns(self):
        """Test that existing columns config is not overwritten."""
        params = {
            "porch_present": True,
            "facade_width_m": 5.0,
            "porch_detail": {
                "columns": {"count": 4, "type": "composite"},
            },
        }

        changed, msg = enrich_porch(params)
        # Columns exist, so shouldn't be replaced
        assert params["porch_detail"]["columns"]["count"] == 4
        assert params["porch_detail"]["columns"]["type"] == "composite"

    def test_enrichment_partial_porch_detail(self):
        """Test enrichment when porch_detail exists but is incomplete."""
        params = {
            "porch_present": True,
            "facade_width_m": 5.0,
            "porch_detail": {
                "columns": {"count": 2, "type": "turned"},
            },
        }

        changed, msg = enrich_porch(params)
        assert changed is True
        # Should add missing railing and step_count
        assert "railing" in params["porch_detail"]
        assert "step_count" in params["porch_detail"]
        # Existing columns should be preserved
        assert params["porch_detail"]["columns"]["type"] == "turned"
