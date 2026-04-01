#!/usr/bin/env python3
"""
Tests for scripts/match_photos_to_params.py

Tests address normalization and photo matching strategies using progressive
matching (exact, normalized, composite, variants, substring, fuzzy).
"""

from __future__ import annotations

import csv
import json
import tempfile
from pathlib import Path

import pytest

# Import the functions to test
from match_photos_to_params import (
    find_photo,
    load_photo_index,
    normalize_address,
)


class TestNormalizeAddress:
    """Tests for normalize_address()"""

    def test_exact_match_simple(self):
        """Exact addresses should normalize to same value"""
        result = normalize_address("100 Oxford St")
        assert result == "100 oxford"  # "St" suffix is stripped

    def test_remove_punctuation(self):
        """Punctuation should be removed"""
        # Note: "St." becomes " st" after period removal, so "st" is not stripped
        assert normalize_address("100 Oxford St.") == "100 oxford st"
        assert normalize_address("100-Oxford-St") == "100 oxford"
        assert normalize_address("100,Oxford,St") == "100 oxford"

    def test_remove_parens(self):
        """Parentheses should be removed"""
        assert normalize_address("100 Oxford St (North)") == "100 oxford st north"

    def test_strip_street_suffix_st(self):
        """Street suffix 'st' should be removed"""
        assert normalize_address("100 Oxford St") == "100 oxford"
        assert normalize_address("100 Oxford Street") == "100 oxford"

    def test_strip_street_suffix_ave(self):
        """Street suffix 'ave' should be removed"""
        assert normalize_address("100 Oxford Ave") == "100 oxford"
        assert normalize_address("100 Oxford Avenue") == "100 oxford"

    def test_strip_street_suffix_pl(self):
        """Street suffix 'pl' should be removed"""
        assert normalize_address("100 Oxford Pl") == "100 oxford"
        assert normalize_address("100 Oxford Place") == "100 oxford"

    def test_strip_street_suffix_rd(self):
        """Street suffix 'rd' should be removed"""
        assert normalize_address("100 Oxford Rd") == "100 oxford"
        assert normalize_address("100 Oxford Road") == "100 oxford"

    def test_strip_street_suffix_dr(self):
        """Street suffix 'dr' should be removed"""
        assert normalize_address("100 Oxford Dr") == "100 oxford"
        assert normalize_address("100 Oxford Drive") == "100 oxford"

    def test_strip_street_suffix_ln(self):
        """Street suffix 'ln' should be removed"""
        assert normalize_address("100 Oxford Ln") == "100 oxford"
        assert normalize_address("100 Oxford Lane") == "100 oxford"

    def test_strip_street_suffix_ct(self):
        """Street suffix 'ct' should be removed"""
        assert normalize_address("100 Oxford Ct") == "100 oxford"
        assert normalize_address("100 Oxford Court") == "100 oxford"

    def test_collapse_whitespace(self):
        """Multiple spaces should collapse to single space"""
        assert normalize_address("100   Oxford   St") == "100 oxford"

    def test_case_insensitive(self):
        """Case should be normalized to lowercase"""
        assert normalize_address("100 OXFORD ST") == "100 oxford"
        assert normalize_address("100 Oxford ST") == "100 oxford"
        assert normalize_address("100 oxford st") == "100 oxford"

    def test_empty_string(self):
        """Empty string should return empty"""
        assert normalize_address("") == ""
        assert normalize_address(None) == ""

    def test_number_with_suffix_preserved(self):
        """Number suffixes like 10A should be preserved during normalization"""
        result = normalize_address("10A Oxford St")
        assert "10a" in result or "10 a" in result

    def test_complex_address(self):
        """Complex address with multiple elements"""
        result = normalize_address("100-B Oxford Street (North Side)")
        assert "100" in result
        assert "oxford" in result
        assert "north" in result


class TestLoadPhotoIndex:
    """Tests for load_photo_index()"""

    def test_load_valid_index(self):
        """Load a valid photo index CSV"""
        with tempfile.TemporaryDirectory() as tmpdir:
            index_path = Path(tmpdir) / "photo_index.csv"

            # Create a simple CSV
            with open(index_path, "w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=["filename", "address_or_location", "source"])
                writer.writeheader()
                writer.writerow({"filename": "photo_001.jpg", "address_or_location": "100 Oxford St", "source": "field"})
                writer.writerow({"filename": "photo_002.jpg", "address_or_location": "22 Lippincott St", "source": "field"})

            result = load_photo_index(index_path)

            # Check that addresses were normalized
            assert "100 oxford" in result
            assert "22 lippincott" in result
            assert result["100 oxford"] == ["photo_001.jpg"]
            assert result["22 lippincott"] == ["photo_002.jpg"]

    def test_load_index_with_duplicates(self):
        """Multiple photos with same address should be grouped"""
        with tempfile.TemporaryDirectory() as tmpdir:
            index_path = Path(tmpdir) / "photo_index.csv"

            with open(index_path, "w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=["filename", "address_or_location", "source"])
                writer.writeheader()
                writer.writerow({"filename": "photo_001.jpg", "address_or_location": "100 Oxford St", "source": "field"})
                writer.writerow({"filename": "photo_002.jpg", "address_or_location": "100 Oxford Street", "source": "field"})

            result = load_photo_index(index_path)

            # Both should normalize to same address
            assert "100 oxford" in result
            assert len(result["100 oxford"]) == 2
            assert "photo_001.jpg" in result["100 oxford"]
            assert "photo_002.jpg" in result["100 oxford"]

    def test_load_index_skip_empty_rows(self):
        """Skip rows with missing filename or address"""
        with tempfile.TemporaryDirectory() as tmpdir:
            index_path = Path(tmpdir) / "photo_index.csv"

            with open(index_path, "w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=["filename", "address_or_location", "source"])
                writer.writeheader()
                writer.writerow({"filename": "photo_001.jpg", "address_or_location": "100 Oxford St", "source": "field"})
                writer.writerow({"filename": "", "address_or_location": "100 Blank St", "source": "field"})
                writer.writerow({"filename": "photo_003.jpg", "address_or_location": "", "source": "field"})

            result = load_photo_index(index_path)

            # Only valid row should be included
            assert len(result) == 1
            assert "100 oxford" in result

    def test_load_empty_index(self):
        """Load an empty CSV should return empty dict"""
        with tempfile.TemporaryDirectory() as tmpdir:
            index_path = Path(tmpdir) / "photo_index.csv"

            with open(index_path, "w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=["filename", "address_or_location", "source"])
                writer.writeheader()

            result = load_photo_index(index_path)
            assert result == {}


class TestExactMatch:
    """Tests for Strategy 1: exact match on building_name"""

    def test_exact_match(self):
        """Exact match on building_name"""
        photos_by_addr = {
            "100 oxford": ["photo_001.jpg"],
        }

        result_photo, result_method = find_photo(
            building_name="100 Oxford St",
            site_street_number=None,
            site_street=None,
            photos_by_addr=photos_by_addr,
        )

        assert result_photo == "photo_001.jpg"
        assert result_method == "exact"


class TestNormalizedMatch:
    """Tests for Strategy 2: normalized match on building_name"""

    def test_normalized_match_with_suffix(self):
        """Normalized match handles street suffixes"""
        photos_by_addr = {
            "100 oxford": ["photo_001.jpg"],
        }

        result_photo, result_method = find_photo(
            building_name="100 Oxford Street",
            site_street_number=None,
            site_street=None,
            photos_by_addr=photos_by_addr,
        )

        assert result_photo == "photo_001.jpg"
        assert result_method in ["exact", "normalized"]


class TestCompositeMatch:
    """Tests for Strategy 3: composite match (street_number + space + street)"""

    def test_composite_match(self):
        """Composite match builds address from number and street"""
        photos_by_addr = {
            "100 oxford": ["photo_001.jpg"],
        }

        result_photo, result_method = find_photo(
            building_name="Unknown Building",
            site_street_number=100,
            site_street="Oxford St",
            photos_by_addr=photos_by_addr,
        )

        assert result_photo == "photo_001.jpg"
        assert result_method == "composite"

    def test_composite_match_string_number(self):
        """Composite match works with string street numbers"""
        photos_by_addr = {
            "100a oxford": ["photo_001.jpg"],
        }

        result_photo, result_method = find_photo(
            building_name="Unknown",
            site_street_number="100A",
            site_street="Oxford St",
            photos_by_addr=photos_by_addr,
        )

        assert result_photo == "photo_001.jpg"
        assert result_method == "composite"


class TestNumberVariantMatch:
    """Tests for Strategy 4: number variants (10A ↔ 10a)"""

    def test_number_variant_uppercase_to_lowercase(self):
        """Number variant matches 10A to 10a"""
        photos_by_addr = {
            "10a oxford": ["photo_001.jpg"],
        }

        result_photo, result_method = find_photo(
            building_name="Unknown",
            site_street_number="10A",
            site_street="Oxford St",
            photos_by_addr=photos_by_addr,
        )

        assert result_photo == "photo_001.jpg"
        # Composite match should work first (faster than number_variant)
        assert result_method in ["number_variant", "composite"]

    def test_number_variant_lowercase_to_uppercase(self):
        """Number variant matches 10a to 10A"""
        photos_by_addr = {
            "10a oxford": ["photo_001.jpg"],
        }

        result_photo, result_method = find_photo(
            building_name="Unknown",
            site_street_number="10a",
            site_street="Oxford St",
            photos_by_addr=photos_by_addr,
        )

        assert result_photo == "photo_001.jpg"
        assert result_method in ["number_variant", "composite"]


class TestSubstringMatch:
    """Tests for Strategy 5: substring match (both number and street appear)"""

    def test_substring_match_with_punctuation(self):
        """Substring match finds number and street in photo address"""
        photos_by_addr = {
            "100 oxford north side": ["photo_001.jpg"],
        }

        result_photo, result_method = find_photo(
            building_name="Unknown",
            site_street_number=100,
            site_street="Oxford",
            photos_by_addr=photos_by_addr,
        )

        assert result_photo == "photo_001.jpg"
        # Could match via composite or number_variant, both are fine
        assert result_method in ["substring", "number_variant", "composite"]


class TestFuzzyMatch:
    """Tests for Strategy 6: fuzzy match (word overlap and SequenceMatcher)"""

    def test_fuzzy_match_word_overlap(self):
        """Fuzzy match using word overlap"""
        photos_by_addr = {
            "100 oxford street corner": ["photo_001.jpg"],
        }

        result_photo, result_method = find_photo(
            building_name="100 Oxford St",
            site_street_number=None,
            site_street=None,
            photos_by_addr=photos_by_addr,
        )

        assert result_photo == "photo_001.jpg"
        # Could be fuzzy or substring depending on word overlap scoring
        assert result_method in ["fuzzy", "substring"]

    def test_fuzzy_match_sequence_matcher(self):
        """Fuzzy match using SequenceMatcher when word overlap fails"""
        photos_by_addr = {
            "100 oxfords": ["photo_001.jpg"],
        }

        result_photo, result_method = find_photo(
            building_name="100 Oxford",
            site_street_number=None,
            site_street=None,
            photos_by_addr=photos_by_addr,
        )

        assert result_photo == "photo_001.jpg"
        assert result_method == "fuzzy"

    def test_fuzzy_match_below_threshold_excluded(self):
        """Fuzzy match below threshold should return no match"""
        photos_by_addr = {
            "50 maple ave": ["photo_999.jpg"],
        }

        result_photo, result_method = find_photo(
            building_name="100 Oxford St",
            site_street_number=None,
            site_street=None,
            photos_by_addr=photos_by_addr,
        )

        assert result_photo is None
        assert result_method == ""


class TestNoMatch:
    """Tests for when no match is found"""

    def test_no_match_empty_index(self):
        """No match when photo index is empty"""
        photos_by_addr = {}

        result_photo, result_method = find_photo(
            building_name="100 Oxford St",
            site_street_number=100,
            site_street="Oxford",
            photos_by_addr=photos_by_addr,
        )

        assert result_photo is None
        assert result_method == ""

    def test_no_match_dissimilar_address(self):
        """No match when address is very different"""
        photos_by_addr = {
            "200 maple ave": ["photo_999.jpg"],
            "300 elm street": ["photo_888.jpg"],
        }

        result_photo, result_method = find_photo(
            building_name="100 Oxford St",
            site_street_number=None,
            site_street=None,
            photos_by_addr=photos_by_addr,
        )

        assert result_photo is None
        assert result_method == ""

    def test_no_match_missing_site_info(self):
        """No match when building_name is empty and site info is None"""
        photos_by_addr = {
            "100 oxford": ["photo_001.jpg"],
        }

        result_photo, result_method = find_photo(
            building_name="",
            site_street_number=None,
            site_street=None,
            photos_by_addr=photos_by_addr,
        )

        assert result_photo is None
        assert result_method == ""


class TestStrategyPriority:
    """Tests that strategies are tried in order"""

    def test_exact_wins_over_fuzzy(self):
        """Exact match should win over fuzzy match"""
        photos_by_addr = {
            "100 oxford": ["exact_match.jpg"],
            "100 oxfords": ["fuzzy_match.jpg"],
        }

        result_photo, result_method = find_photo(
            building_name="100 Oxford St",
            site_street_number=None,
            site_street=None,
            photos_by_addr=photos_by_addr,
        )

        assert result_photo == "exact_match.jpg"
        assert result_method in ["exact", "normalized"]

    def test_composite_before_fuzzy(self):
        """Composite match should be found before fuzzy"""
        photos_by_addr = {
            "100 oxford": ["composite.jpg"],
            "99 oxford": ["fuzzy.jpg"],
        }

        result_photo, result_method = find_photo(
            building_name="Different Name",
            site_street_number=100,
            site_street="Oxford",
            photos_by_addr=photos_by_addr,
        )

        assert result_photo == "composite.jpg"
        assert result_method == "composite"


class TestMultiplePhotosPerAddress:
    """Tests that first photo is returned when multiple exist"""

    def test_returns_first_photo_of_many(self):
        """Should return first photo from list when multiple exist"""
        photos_by_addr = {
            "100 oxford": ["photo_001.jpg", "photo_002.jpg", "photo_003.jpg"],
        }

        result_photo, result_method = find_photo(
            building_name="100 Oxford St",
            site_street_number=None,
            site_street=None,
            photos_by_addr=photos_by_addr,
        )

        assert result_photo == "photo_001.jpg"
        assert result_method == "exact"


class TestIntegrationScenarios:
    """Integration tests with realistic scenarios"""

    def test_hyphenated_building_number(self):
        """Building with hyphenated number like 10-12"""
        photos_by_addr = {
            "10 oxford": ["photo_001.jpg"],
        }

        result_photo, result_method = find_photo(
            building_name="10-12 Oxford Street",
            site_street_number="10-12",
            site_street="Oxford",
            photos_by_addr=photos_by_addr,
        )

        # Should find via substring or fuzzy
        assert result_photo is not None

    def test_corner_building_address(self):
        """Corner building with "Corner of" format"""
        photos_by_addr = {
            "100 oxford 50 spalding": ["photo_001.jpg"],
        }

        result_photo, result_method = find_photo(
            building_name="Corner of Oxford and Spalding",
            site_street_number=100,
            site_street="Oxford",
            photos_by_addr=photos_by_addr,
        )

        # Should find via substring or fuzzy
        assert result_photo is not None

    def test_building_with_proper_name(self):
        """Building with proper name"""
        photos_by_addr = {
            "15 bellevue": ["photo_001.jpg"],
        }

        result_photo, result_method = find_photo(
            building_name="15 Bellevue Ave (Historic Hall)",
            site_street_number=15,
            site_street="Bellevue",
            photos_by_addr=photos_by_addr,
        )

        assert result_photo == "photo_001.jpg"

    def test_real_world_address_variations(self):
        """Test with various real-world address formats"""
        photos_by_addr = {
            "22 lippincott": ["photo_lippincott.jpg"],
            "10 oxford": ["photo_oxford.jpg"],
            "132 bellevue": ["photo_bellevue.jpg"],
        }

        # Try different building_name formats
        test_cases = [
            ("22 Lippincott St", None, None, "photo_lippincott.jpg"),
            ("22 Lippincott Street", None, None, "photo_lippincott.jpg"),
            ("22 LIPPINCOTT ST", None, None, "photo_lippincott.jpg"),
            (None, 10, "Oxford", "photo_oxford.jpg"),
            (None, 132, "Bellevue Ave", "photo_bellevue.jpg"),
        ]

        for building_name, num, street, expected_photo in test_cases:
            photo, method = find_photo(building_name, num, street, photos_by_addr)
            if expected_photo:
                assert photo == expected_photo, f"Failed for {building_name}/{num} {street}"
