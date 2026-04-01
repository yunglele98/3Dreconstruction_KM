"""Unit tests for analyze_streetscape_rhythm.py"""

import json
from pathlib import Path
import pytest
import statistics
from analyze_streetscape_rhythm import (
    extract_street_number,
    safe_get,
    compute_longest_material_run,
    compute_era_coherence,
    compute_storefront_density,
    analyze_street,
)


class TestExtractStreetNumber:
    """Test extract_street_number function."""

    def test_simple_address(self):
        """Should extract number and street."""
        num, street = extract_street_number("10 Nassau St")
        assert num == 10
        assert street == "Nassau St"

    def test_address_with_suffix(self):
        """Should handle suffix."""
        num, street = extract_street_number("10A Nassau St")
        assert num == 10

    def test_no_number(self):
        """Should return None for no number."""
        num, street = extract_street_number("Nassau St")
        assert num is None

    def test_large_number(self):
        """Should handle large numbers."""
        num, street = extract_street_number("1234 Spadina Ave")
        assert num == 1234

    def test_empty_string(self):
        """Should handle empty string."""
        num, street = extract_street_number("")
        assert num is None


class TestSafeGet:
    """Test safe_get function."""

    def test_simple_key(self):
        """Should get simple key."""
        obj = {"value": 42}
        assert safe_get(obj, "value") == 42

    def test_nested_keys(self):
        """Should traverse nested keys."""
        obj = {"a": {"b": {"c": "found"}}}
        assert safe_get(obj, "a", "b", "c") == "found"

    def test_missing_key_default(self):
        """Should return default for missing key."""
        obj = {"value": 42}
        assert safe_get(obj, "missing", default=0) == 0

    def test_none_in_chain(self):
        """Should return default if chain breaks."""
        obj = {"a": None}
        assert safe_get(obj, "a", "b", default="default") == "default"

    def test_non_dict_in_chain(self):
        """Should return default for non-dict in chain."""
        obj = {"a": "string"}
        assert safe_get(obj, "a", "b", default=None) is None


class TestComputeLongestMaterialRun:
    """Test compute_longest_material_run function."""

    def test_empty_list(self):
        """Empty list should return 0."""
        result = compute_longest_material_run([])
        assert result == 0

    def test_single_building(self):
        """Single building should return 1."""
        buildings = [{"facade_material": "brick"}]
        result = compute_longest_material_run(buildings)
        assert result == 1

    def test_all_same_material(self):
        """All same material should return length."""
        buildings = [
            {"facade_material": "brick"},
            {"facade_material": "brick"},
            {"facade_material": "brick"},
        ]
        result = compute_longest_material_run(buildings)
        assert result == 3

    def test_all_different_materials(self):
        """All different materials should return 1."""
        buildings = [
            {"facade_material": "brick"},
            {"facade_material": "stone"},
            {"facade_material": "wood"},
        ]
        result = compute_longest_material_run(buildings)
        assert result == 1

    def test_run_in_middle(self):
        """Should find longest run in middle."""
        buildings = [
            {"facade_material": "brick"},
            {"facade_material": "stone"},
            {"facade_material": "stone"},
            {"facade_material": "stone"},
            {"facade_material": "brick"},
        ]
        result = compute_longest_material_run(buildings)
        assert result == 3

    def test_missing_material_ends_run(self):
        """Missing material should end run."""
        buildings = [
            {"facade_material": "brick"},
            {"facade_material": "brick"},
            {},
            {"facade_material": "brick"},
            {"facade_material": "brick"},
        ]
        result = compute_longest_material_run(buildings)
        assert result == 2

    def test_multiple_same_runs_returns_longest(self):
        """Should return longest run when multiple exist."""
        buildings = [
            {"facade_material": "brick"},
            {"facade_material": "brick"},
            {"facade_material": "stone"},
            {"facade_material": "stone"},
            {"facade_material": "stone"},
            {"facade_material": "stone"},
        ]
        result = compute_longest_material_run(buildings)
        assert result == 4


class TestComputeEraCoherence:
    """Test compute_era_coherence function."""

    def test_single_building(self):
        """Single building should return 1.0."""
        buildings = [{"hcd_data": {"construction_date": "1904-1913"}}]
        result = compute_era_coherence(buildings)
        assert result == 1.0

    def test_all_same_era(self):
        """All same era should return 1.0."""
        buildings = [
            {"hcd_data": {"construction_date": "1904-1913"}},
            {"hcd_data": {"construction_date": "1904-1913"}},
            {"hcd_data": {"construction_date": "1904-1913"}},
        ]
        result = compute_era_coherence(buildings)
        assert result == 1.0

    def test_all_different_eras(self):
        """All different eras should return 0.0."""
        buildings = [
            {"hcd_data": {"construction_date": "1890-1903"}},
            {"hcd_data": {"construction_date": "1904-1913"}},
            {"hcd_data": {"construction_date": "1920-1930"}},
        ]
        result = compute_era_coherence(buildings)
        assert result == 0.0

    def test_half_coherence(self):
        """Half matching should return 0.5."""
        buildings = [
            {"hcd_data": {"construction_date": "1904-1913"}},
            {"hcd_data": {"construction_date": "1904-1913"}},
            {"hcd_data": {"construction_date": "1920-1930"}},
        ]
        result = compute_era_coherence(buildings)
        assert result == pytest.approx(0.5, rel=0.01)

    def test_missing_era_ignored(self):
        """Buildings without era shouldn't be counted."""
        buildings = [
            {"hcd_data": {"construction_date": "1904-1913"}},
            {"hcd_data": {}},
            {"hcd_data": {"construction_date": "1904-1913"}},
        ]
        result = compute_era_coherence(buildings)
        # Pairs: (0,1) - skip because 1 missing; (1,2) - skip because 1 missing
        # So 0 pairs are counted, returns 0.0
        assert result == 0.0

    def test_empty_list(self):
        """Empty list should return 1.0."""
        result = compute_era_coherence([])
        assert result == 1.0

    def test_all_missing_eras(self):
        """All missing eras should return 0.0."""
        buildings = [
            {"hcd_data": {}},
            {"hcd_data": {}},
        ]
        result = compute_era_coherence(buildings)
        assert result == 0.0


class TestComputeStorefrontDensity:
    """Test compute_storefront_density function."""

    def test_empty_list(self):
        """Empty list should return 0.0."""
        result = compute_storefront_density([])
        assert result == 0.0

    def test_no_storefronts(self):
        """No storefronts should return 0.0."""
        buildings = [
            {"has_storefront": False},
            {"has_storefront": False},
            {"has_storefront": False},
        ]
        result = compute_storefront_density(buildings)
        assert result == 0.0

    def test_all_storefronts(self):
        """All storefronts should return 1.0."""
        buildings = [
            {"has_storefront": True},
            {"has_storefront": True},
            {"has_storefront": True},
        ]
        result = compute_storefront_density(buildings)
        assert result == 1.0

    def test_half_storefronts(self):
        """Half storefronts should return 0.5."""
        buildings = [
            {"has_storefront": True},
            {"has_storefront": False},
            {"has_storefront": True},
            {"has_storefront": False},
        ]
        result = compute_storefront_density(buildings)
        assert result == pytest.approx(0.5, rel=0.01)

    def test_missing_storefront_treated_false(self):
        """Missing has_storefront should be treated as False."""
        buildings = [
            {"has_storefront": True},
            {},
            {"has_storefront": True},
        ]
        result = compute_storefront_density(buildings)
        # 2 out of 3
        assert result == pytest.approx(0.667, rel=0.01)

    def test_single_building_with_storefront(self):
        """Single building with storefront should return 1.0."""
        buildings = [{"has_storefront": True}]
        result = compute_storefront_density(buildings)
        assert result == 1.0


class TestAnalyzeStreet:
    """Test analyze_street function."""

    def test_empty_street(self):
        """Empty street should return zeros."""
        result = analyze_street([])
        assert result["building_count"] == 0
        assert result["heritage_quality_score"] == 0

    def test_single_building(self):
        """Single building analysis."""
        street_buildings = [
            (10, "10 Nassau St", {
                "site": {"street": "Nassau St", "setback_m": 2.0},
                "facade_width_m": 5,
                "total_height_m": 12,
                "hcd_data": {"construction_date": "1904-1913"},
                "has_storefront": False,
            })
        ]
        result = analyze_street(street_buildings)
        assert result["building_count"] == 1
        assert len(result["frontage_widths"]) == 1
        assert len(result["height_profile"]) == 1

    def test_multiple_buildings_metrics(self):
        """Multiple buildings should compute all metrics."""
        street_buildings = [
            (10, "10 Nassau St", {
                "site": {"street": "Nassau St", "setback_m": 2.0},
                "facade_width_m": 5,
                "total_height_m": 12,
                "facade_material": "brick",
                "hcd_data": {"construction_date": "1904-1913"},
                "has_storefront": False,
            }),
            (12, "12 Nassau St", {
                "site": {"street": "Nassau St", "setback_m": 2.0},
                "facade_width_m": 6,
                "total_height_m": 12,
                "facade_material": "brick",
                "hcd_data": {"construction_date": "1904-1913"},
                "has_storefront": False,
            }),
            (14, "14 Nassau St", {
                "site": {"street": "Nassau St", "setback_m": 2.0},
                "facade_width_m": 5.5,
                "total_height_m": 12,
                "facade_material": "brick",
                "hcd_data": {"construction_date": "1904-1913"},
                "has_storefront": False,
            }),
        ]
        result = analyze_street(street_buildings)
        assert result["building_count"] == 3
        assert result["height_regularity"] == 0.0  # All same height
        assert result["era_coherence"] == 1.0  # All same era
        assert result["material_runs"] == 3  # All same material
        assert result["storefront_density"] == 0.0  # No storefronts

    def test_heritage_quality_score_computed(self):
        """Heritage quality score should be between 0-100."""
        street_buildings = [
            (10, "10 Nassau St", {
                "site": {"street": "Nassau St", "setback_m": 2.0},
                "facade_width_m": 5,
                "total_height_m": 12,
                "facade_material": "brick",
                "hcd_data": {"construction_date": "1904-1913"},
                "has_storefront": False,
            }),
            (12, "12 Nassau St", {
                "site": {"street": "Nassau St", "setback_m": 2.0},
                "facade_width_m": 6,
                "total_height_m": 12,
                "facade_material": "brick",
                "hcd_data": {"construction_date": "1904-1913"},
                "has_storefront": False,
            }),
        ]
        result = analyze_street(street_buildings)
        assert 0 <= result["heritage_quality_score"] <= 100

    def test_high_coherence_high_score(self):
        """High coherence should yield high score."""
        street_buildings = [
            (10, f"{10+i} Nassau St", {
                "site": {"street": "Nassau St", "setback_m": 2.0},
                "facade_width_m": 5,
                "total_height_m": 12,
                "facade_material": "brick",
                "hcd_data": {"construction_date": "1904-1913"},
                "has_storefront": False,
            })
            for i in range(5)
        ]
        result = analyze_street(street_buildings)
        # All uniform should score high
        assert result["heritage_quality_score"] > 50

    def test_height_regularity_computed(self):
        """Height regularity should be standard deviation."""
        street_buildings = [
            (10, "10 Nassau St", {
                "site": {"street": "Nassau St"},
                "total_height_m": 12,
            }),
            (12, "12 Nassau St", {
                "site": {"street": "Nassau St"},
                "total_height_m": 14,
            }),
            (14, "14 Nassau St", {
                "site": {"street": "Nassau St"},
                "total_height_m": 13,
            }),
        ]
        result = analyze_street(street_buildings)
        expected_stdev = statistics.stdev([12, 14, 13])
        assert result["height_regularity"] == pytest.approx(expected_stdev, rel=0.01)

    def test_width_regularity_computed(self):
        """Width regularity should be standard deviation."""
        street_buildings = [
            (10, "10 Nassau St", {
                "site": {"street": "Nassau St"},
                "facade_width_m": 5,
            }),
            (12, "12 Nassau St", {
                "site": {"street": "Nassau St"},
                "facade_width_m": 7,
            }),
            (14, "14 Nassau St", {
                "site": {"street": "Nassau St"},
                "facade_width_m": 6,
            }),
        ]
        result = analyze_street(street_buildings)
        expected_stdev = statistics.stdev([5, 7, 6])
        assert result["width_regularity"] == pytest.approx(expected_stdev, rel=0.01)

    def test_setback_uniformity_computed(self):
        """Setback uniformity should be standard deviation."""
        street_buildings = [
            (10, "10 Nassau St", {
                "site": {"street": "Nassau St", "setback_m": 2.0},
            }),
            (12, "12 Nassau St", {
                "site": {"street": "Nassau St", "setback_m": 2.5},
            }),
            (14, "14 Nassau St", {
                "site": {"street": "Nassau St", "setback_m": 2.2},
            }),
        ]
        result = analyze_street(street_buildings)
        expected_stdev = statistics.stdev([2.0, 2.5, 2.2])
        assert result["setback_uniformity"] == pytest.approx(expected_stdev, rel=0.01)

    def test_missing_values_excluded_from_arrays(self):
        """Missing values should be excluded from arrays."""
        street_buildings = [
            (10, "10 Nassau St", {
                "site": {"street": "Nassau St"},
                "facade_width_m": 5,
                "total_height_m": 12,
            }),
            (12, "12 Nassau St", {
                "site": {"street": "Nassau St"},
                # missing facade_width_m and total_height_m
            }),
        ]
        result = analyze_street(street_buildings)
        assert len(result["frontage_widths"]) == 1
        assert len(result["height_profile"]) == 1

    def test_arrays_rounded(self):
        """Arrays should be rounded to 2 decimal places."""
        street_buildings = [
            (10, "10 Nassau St", {
                "site": {"street": "Nassau St"},
                "facade_width_m": 5.123456,
                "total_height_m": 12.789012,
            }),
        ]
        result = analyze_street(street_buildings)
        assert result["frontage_widths"][0] == pytest.approx(5.12, rel=0.01)
        assert result["height_profile"][0] == pytest.approx(12.79, rel=0.01)

    def test_mixed_coherence_and_density(self):
        """Street with mixed coherence and storefronts."""
        street_buildings = [
            (10, "10 Nassau St", {
                "site": {"street": "Nassau St", "setback_m": 2.0},
                "facade_width_m": 5,
                "total_height_m": 12,
                "facade_material": "brick",
                "hcd_data": {"construction_date": "1904-1913"},
                "has_storefront": True,
            }),
            (12, "12 Nassau St", {
                "site": {"street": "Nassau St", "setback_m": 2.0},
                "facade_width_m": 6,
                "total_height_m": 14,
                "facade_material": "stone",
                "hcd_data": {"construction_date": "1890-1903"},
                "has_storefront": False,
            }),
        ]
        result = analyze_street(street_buildings)
        assert result["storefront_density"] == pytest.approx(0.5, rel=0.01)
        assert result["era_coherence"] == 0.0
        assert result["material_runs"] == 1
