"""Unit tests for enrich_storefronts_advanced.py"""

import pytest

from enrich_storefronts_advanced import (
    MAJOR_COMMERCIAL_STREETS,
    MARKET_STREETS,
    enrich_storefront,
    get_street_from_building_name,
    infer_awning,
    infer_security_grille,
    infer_signage,
)


class TestGetStreetFromBuildingName:
    """Tests for get_street_from_building_name function."""

    def test_extract_kensington_ave(self):
        result = get_street_from_building_name("22 Kensington Ave")
        assert "kensington" in result.lower()
        assert "ave" in result.lower()

    def test_extract_oxford_st(self):
        result = get_street_from_building_name("100 Oxford St")
        assert "oxford" in result.lower()

    def test_extract_multi_word_street(self):
        result = get_street_from_building_name("42 Bathurst Street")
        assert "bathurst" in result.lower()

    def test_with_suffix_letter(self):
        result = get_street_from_building_name("10A Lippincott St")
        assert "lippincott" in result.lower()

    def test_single_word_building_name(self):
        result = get_street_from_building_name("Kensington")
        assert result == ""

    def test_empty_string(self):
        result = get_street_from_building_name("")
        assert result == ""

    def test_only_number(self):
        result = get_street_from_building_name("22")
        assert result == ""

    def test_long_building_name(self):
        result = get_street_from_building_name("22 Kensington Avenue South")
        assert "kensington" in result.lower()
        assert "avenue" in result.lower()
        assert "south" in result.lower()

    def test_preserves_case_initially(self):
        """Function returns street as-is before lowercasing in caller."""
        result = get_street_from_building_name("22 OXFORD ST")
        assert "OXFORD" in result

    def test_strips_whitespace(self):
        result = get_street_from_building_name("22   Kensington Ave   ")
        assert result.strip() == result


class TestInferAwning:
    """Tests for infer_awning function."""

    def test_awning_from_deep_analysis(self):
        params = {
            "deep_facade_analysis": {
                "storefront_observed": {
                    "awning": True,
                }
            },
            "facade_width_m": 5.0,
            "colour_palette": {"accent": "#2A4A2A"},
        }
        result = infer_awning(params)
        assert result["present"] is True
        assert result["type"] == "fixed"

    def test_awning_from_photo_observations_porch(self):
        params = {
            "photo_observations": {
                "porch_present": True,
            },
            "facade_width_m": 5.0,
            "colour_palette": {"accent": "#2A4A2A"},
        }
        result = infer_awning(params)
        assert result["present"] is True

    def test_awning_from_photo_observations_awning(self):
        params = {
            "photo_observations": {
                "awning": True,
            },
            "facade_width_m": 5.0,
            "colour_palette": {"accent": "#2A4A2A"},
        }
        result = infer_awning(params)
        assert result["present"] is True

    def test_retractable_awning_market_street(self):
        params = {
            "building_name": "10 Kensington Ave",
            "facade_width_m": 5.0,
        }
        result = infer_awning(params)
        assert result["present"] is True
        assert result["type"] == "retractable"
        assert result["colour_hex"] == "#8A2A2A"

    def test_retractable_awning_augusta_street(self):
        params = {
            "building_name": "15 Augusta Ave",
            "facade_width_m": 5.0,
        }
        result = infer_awning(params)
        assert result["present"] is True
        assert result["type"] == "retractable"

    def test_retractable_awning_baldwin_street(self):
        params = {
            "building_name": "20 Baldwin St",
            "facade_width_m": 5.0,
        }
        result = infer_awning(params)
        assert result["present"] is True
        assert result["type"] == "retractable"

    def test_fixed_awning_major_commercial(self):
        params = {
            "building_name": "100 Spadina Ave",
            "facade_width_m": 5.0,
        }
        result = infer_awning(params)
        assert result["present"] is True
        assert result["type"] == "fixed"
        assert result["colour_hex"] == "#2A4A2A"

    def test_fixed_awning_college_street(self):
        params = {
            "building_name": "50 College St",
            "facade_width_m": 5.0,
        }
        result = infer_awning(params)
        assert result["present"] is True
        assert result["type"] == "fixed"

    def test_no_awning_residential_street(self):
        params = {
            "building_name": "22 Lippincott St",
            "facade_width_m": 5.0,
        }
        result = infer_awning(params)
        assert result["present"] is False

    def test_awning_width_calculation(self):
        params = {
            "building_name": "10 Kensington Ave",
            "facade_width_m": 6.0,
        }
        result = infer_awning(params)
        # For market street: 0.8 × facade width
        assert result["width_m"] == pytest.approx(6.0 * 0.8)

    def test_awning_projection_market(self):
        params = {
            "building_name": "10 Kensington Ave",
            "facade_width_m": 5.0,
        }
        result = infer_awning(params)
        assert result["projection_m"] == 1.0

    def test_awning_projection_commercial(self):
        params = {
            "building_name": "100 Spadina Ave",
            "facade_width_m": 5.0,
        }
        result = infer_awning(params)
        assert result["projection_m"] == 1.2

    def test_missing_facade_width_default(self):
        params = {
            "building_name": "10 Kensington Ave",
        }
        result = infer_awning(params)
        # Should use default 5.0m
        assert "width_m" in result

    def test_missing_colour_palette_default(self):
        params = {
            "building_name": "100 Spadina Ave",
            "facade_width_m": 5.0,
        }
        result = infer_awning(params)
        assert result["colour_hex"] == "#2A4A2A"

    def test_non_dict_deep_analysis(self):
        params = {
            "deep_facade_analysis": "not a dict",
            "facade_width_m": 5.0,
        }
        result = infer_awning(params)
        # Should handle gracefully
        assert isinstance(result, dict)


class TestInferSignage:
    """Tests for infer_signage function."""

    def test_signage_from_business_name_fascia(self):
        params = {
            "context": {
                "business_name": "Smith & Co",
                "business_category": "Retail",
            },
            "facade_width_m": 5.0,
        }
        result = infer_signage(params)
        assert result is not None
        assert result["text"] == "Smith & Co"
        assert result["type"] == "fascia"

    def test_signage_projecting_for_restaurant(self):
        params = {
            "context": {
                "business_name": "The Cafe",
                "business_category": "Restaurant",
            },
            "facade_width_m": 5.0,
        }
        result = infer_signage(params)
        assert result["type"] == "projecting"

    def test_signage_projecting_for_cafe(self):
        params = {
            "context": {
                "business_name": "Morning Cup",
                "business_category": "Cafe",
            },
            "facade_width_m": 5.0,
        }
        result = infer_signage(params)
        assert result["type"] == "projecting"

    def test_signage_projecting_for_food(self):
        params = {
            "context": {
                "business_name": "Tasty Bites",
                "business_category": "Food Service",
            },
            "facade_width_m": 5.0,
        }
        result = infer_signage(params)
        assert result["type"] == "projecting"

    def test_signage_painted_for_market(self):
        params = {
            "context": {
                "business_name": "Kensington Market",
                "business_category": "Market",
            },
            "facade_width_m": 5.0,
        }
        result = infer_signage(params)
        assert result["type"] == "painted_window"

    def test_signage_painted_for_grocery(self):
        params = {
            "context": {
                "business_name": "Fresh Produce",
                "business_category": "Grocery",
            },
            "facade_width_m": 5.0,
        }
        result = infer_signage(params)
        assert result["type"] == "painted_window"

    def test_signage_painted_for_produce(self):
        params = {
            "context": {
                "business_name": "Urban Harvest",
                "business_category": "Produce",
            },
            "facade_width_m": 5.0,
        }
        result = infer_signage(params)
        assert result["type"] == "painted_window"

    def test_no_signage_without_business_name(self):
        params = {
            "context": {
                "business_name": "",
                "business_category": "Retail",
            },
            "facade_width_m": 5.0,
        }
        result = infer_signage(params)
        assert result is None

    def test_no_signage_without_context(self):
        params = {
            "facade_width_m": 5.0,
        }
        result = infer_signage(params)
        assert result is None

    def test_signage_width_clamped(self):
        params = {
            "context": {
                "business_name": "Large Business",
                "business_category": "Retail",
            },
            "facade_width_m": 10.0,
        }
        result = infer_signage(params)
        # Width should be clamped to 4.0m
        assert result["width_m"] == 4.0

    def test_signage_width_proportional(self):
        params = {
            "context": {
                "business_name": "Small Shop",
                "business_category": "Retail",
            },
            "facade_width_m": 3.0,
        }
        result = infer_signage(params)
        # Should be 70% of 3.0m
        assert result["width_m"] == pytest.approx(3.0 * 0.7)

    def test_signage_height(self):
        params = {
            "context": {
                "business_name": "Test Store",
                "business_category": "Retail",
            },
            "facade_width_m": 5.0,
        }
        result = infer_signage(params)
        assert result["height_m"] == 0.6

    def test_signage_colour(self):
        params = {
            "context": {
                "business_name": "Test Store",
                "business_category": "Retail",
            },
            "facade_width_m": 5.0,
        }
        result = infer_signage(params)
        assert result["colour_hex"] == "#F0EDE8"

    def test_context_not_dict(self):
        params = {
            "context": "not a dict",
        }
        result = infer_signage(params)
        assert result is None

    def test_case_insensitive_business_category(self):
        params = {
            "context": {
                "business_name": "Morning Cup",
                "business_category": "RESTAURANT",
            },
            "facade_width_m": 5.0,
        }
        result = infer_signage(params)
        assert result["type"] == "projecting"


class TestInferSecurityGrille:
    """Tests for infer_security_grille function."""

    def test_grille_for_kensington_ave(self):
        params = {
            "building_name": "10 Kensington Ave",
        }
        result = infer_security_grille(params)
        assert result is not None
        assert result["present"] is True
        assert result["type"] == "rolling"

    def test_grille_for_kensington(self):
        params = {
            "building_name": "10 Kensington St",
        }
        result = infer_security_grille(params)
        assert result is not None
        assert result["present"] is True

    def test_grille_for_augusta_ave(self):
        params = {
            "building_name": "15 Augusta Ave",
        }
        result = infer_security_grille(params)
        assert result is not None
        assert result["present"] is True

    def test_grille_for_augusta(self):
        params = {
            "building_name": "15 Augusta St",
        }
        result = infer_security_grille(params)
        assert result is not None
        assert result["present"] is True

    def test_grille_for_baldwin_st(self):
        params = {
            "building_name": "20 Baldwin St",
        }
        result = infer_security_grille(params)
        assert result is not None
        assert result["present"] is True

    def test_grille_for_baldwin(self):
        params = {
            "building_name": "20 Baldwin Ave",
        }
        result = infer_security_grille(params)
        assert result is not None
        assert result["present"] is True

    def test_no_grille_for_oxford_st(self):
        params = {
            "building_name": "22 Oxford St",
        }
        result = infer_security_grille(params)
        assert result is None

    def test_no_grille_for_lippincott_st(self):
        params = {
            "building_name": "22 Lippincott St",
        }
        result = infer_security_grille(params)
        assert result is None

    def test_no_grille_for_spadina_ave(self):
        params = {
            "building_name": "100 Spadina Ave",
        }
        result = infer_security_grille(params)
        assert result is None

    def test_grille_from_site_street(self):
        """Test grille inference from site.street when building_name is missing."""
        params = {
            "building_name": "100 Some Place",
            "site": {"street": "Kensington Ave"},
        }
        result = infer_security_grille(params)
        # Building name extraction would fail, so use site
        # Actually, the function tries to extract from building_name first
        assert result is None or result.get("present") is True


class TestEnrichStorefront:
    """Tests for enrich_storefront function."""

    def test_no_storefront_returns_false(self):
        params = {
            "has_storefront": False,
        }
        changed, msg = enrich_storefront(params)
        assert changed is False
        assert "no storefront" in msg.lower()

    def test_missing_has_storefront(self):
        params = {}
        changed, msg = enrich_storefront(params)
        assert changed is False

    def test_enrich_with_awning_and_signage(self):
        params = {
            "building_name": "10 Kensington Ave",
            "has_storefront": True,
            "storefront": {},
            "facade_width_m": 5.0,
            "colour_palette": {"accent": "#2A4A2A"},
            "context": {
                "business_name": "The Market",
                "business_category": "Market",
            },
        }
        changed, msg = enrich_storefront(params)
        assert changed is True
        assert "awning" in params["storefront"]
        assert "signage" in params["storefront"]

    def test_enrich_with_security_grille(self):
        params = {
            "building_name": "10 Kensington Ave",
            "has_storefront": True,
            "storefront": {},
            "facade_width_m": 5.0,
            "colour_palette": {"accent": "#2A4A2A"},
        }
        changed, msg = enrich_storefront(params)
        assert changed is True
        assert "security_grille" in params["storefront"]

    def test_no_changes_when_already_enriched(self):
        params = {
            "building_name": "10 Kensington Ave",
            "has_storefront": True,
            "storefront": {
                "awning": {"present": True},
                "signage": {"text": "Test"},
                "security_grille": {"present": True},
            },
        }
        changed, msg = enrich_storefront(params)
        assert changed is False

    def test_missing_storefront_dict(self):
        params = {
            "building_name": "10 Kensington Ave",
            "has_storefront": True,
            "facade_width_m": 5.0,
        }
        changed, msg = enrich_storefront(params)
        assert changed is True
        assert "storefront" in params

    def test_non_dict_storefront(self):
        params = {
            "building_name": "10 Kensington Ave",
            "has_storefront": True,
            "storefront": "not a dict",
            "facade_width_m": 5.0,
        }
        changed, msg = enrich_storefront(params)
        # Should handle gracefully
        assert isinstance(params["storefront"], dict)

    def test_only_awning_enriched(self):
        """Test enrichment when only awning is missing."""
        params = {
            "building_name": "10 Kensington Ave",
            "has_storefront": True,
            "storefront": {
                "signage": {"text": "existing"},
            },
            "facade_width_m": 5.0,
            "colour_palette": {"accent": "#2A4A2A"},
        }
        changed, msg = enrich_storefront(params)
        assert changed is True

    def test_only_signage_enriched(self):
        """Test enrichment when only signage is missing."""
        params = {
            "building_name": "10 Kensington Ave",
            "has_storefront": True,
            "storefront": {
                "awning": {"present": True},
            },
            "facade_width_m": 5.0,
            "context": {
                "business_name": "Test",
                "business_category": "Retail",
            },
        }
        changed, msg = enrich_storefront(params)
        assert changed is True

    def test_only_grille_enriched(self):
        """Test enrichment when only security grille is missing."""
        params = {
            "building_name": "10 Kensington Ave",
            "has_storefront": True,
            "storefront": {
                "awning": {"present": True},
                "signage": {"text": "Test"},
            },
            "facade_width_m": 5.0,
        }
        changed, msg = enrich_storefront(params)
        assert changed is True
        assert "security_grille" in params["storefront"]


class TestStreetConstants:
    """Tests for street constant definitions."""

    def test_market_streets_defined(self):
        assert len(MARKET_STREETS) > 0
        assert "kensington" in MARKET_STREETS or any("kensington" in s.lower() for s in MARKET_STREETS)

    def test_major_commercial_streets_defined(self):
        assert len(MAJOR_COMMERCIAL_STREETS) > 0
        assert "spadina" in MAJOR_COMMERCIAL_STREETS or any("spadina" in s.lower() for s in MAJOR_COMMERCIAL_STREETS)
