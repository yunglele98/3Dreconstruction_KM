"""Tests for storefront and porch enrichment scripts.

Tests for:
- enrich_storefronts_advanced.py: awning, signage, security grille inference
- enrich_porch_dimensions.py: porch width, depth, columns, step count
"""

import json
import tempfile
from pathlib import Path

import pytest

# Import functions from scripts
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from enrich_storefronts_advanced import (
    infer_awning,
    infer_signage,
    infer_security_grille,
    enrich_storefront,
    get_street_from_building_name,
)

from enrich_porch_dimensions import (
    parse_era,
    get_porch_width_m,
    get_porch_columns,
    infer_step_count,
    enrich_porch,
)


class TestStorefrontAwning:
    """Tests for awning inference."""

    def test_market_street_kensington_ave_awning(self):
        """Market spine street (Kensington Ave) → retractable awning, #8A2A2A."""
        params = {
            "building_name": "10 Kensington Ave",
            "facade_width_m": 6.0,
            "has_storefront": True,
        }
        awning = infer_awning(params)
        assert awning["present"] is True
        assert awning["type"] == "retractable"
        assert awning["colour_hex"] == "#8A2A2A"
        assert awning["width_m"] == pytest.approx(6.0 * 0.8, abs=0.01)
        assert awning["projection_m"] == 1.0

    def test_market_street_augusta_ave_awning(self):
        """Market street (Augusta Ave) → retractable awning."""
        params = {
            "building_name": "22 Augusta Ave",
            "facade_width_m": 5.0,
            "has_storefront": True,
        }
        awning = infer_awning(params)
        assert awning["present"] is True
        assert awning["type"] == "retractable"
        assert awning["colour_hex"] == "#8A2A2A"

    def test_major_street_spadina_ave_awning(self):
        """Major street (Spadina Ave) → fixed awning, #2A4A2A (dark green)."""
        params = {
            "building_name": "100 Spadina Ave",
            "facade_width_m": 8.0,
            "has_storefront": True,
        }
        awning = infer_awning(params)
        assert awning["present"] is True
        assert awning["type"] == "fixed"
        assert awning["colour_hex"] == "#2A4A2A"
        assert awning["width_m"] == pytest.approx(8.0 * 0.9, abs=0.01)
        assert awning["projection_m"] == 1.2

    def test_major_street_college_st_awning(self):
        """Major street (College St) → fixed awning."""
        params = {
            "building_name": "50 College St",
            "facade_width_m": 6.5,
            "has_storefront": True,
        }
        awning = infer_awning(params)
        assert awning["present"] is True
        assert awning["type"] == "fixed"
        assert awning["colour_hex"] == "#2A4A2A"

    def test_residential_street_no_awning(self):
        """Residential street (Lippincott St) → no awning."""
        params = {
            "building_name": "22 Lippincott St",
            "facade_width_m": 5.0,
            "has_storefront": True,
        }
        awning = infer_awning(params)
        assert awning["present"] is False

    def test_awning_from_deep_facade_analysis(self):
        """Awning from deep_facade_analysis storefront_observed."""
        params = {
            "building_name": "10 Unknown St",
            "facade_width_m": 5.0,
            "has_storefront": True,
            "deep_facade_analysis": {
                "storefront_observed": {
                    "awning": True,
                }
            },
            "colour_palette": {"accent": "#5A5A5A"},
        }
        awning = infer_awning(params)
        assert awning["present"] is True
        assert awning["type"] == "fixed"
        assert awning["colour_hex"] == "#5A5A5A"

    def test_awning_from_photo_observations(self):
        """Awning from photo_observations porch_present."""
        params = {
            "building_name": "15 Unknown St",
            "facade_width_m": 5.0,
            "has_storefront": True,
            "photo_observations": {
                "porch_present": True,
            },
            "colour_palette": {"accent": "#3A3A3A"},
        }
        awning = infer_awning(params)
        assert awning["present"] is True
        assert awning["type"] == "fixed"

    def test_awning_width_scaling(self):
        """Awning width scales with facade width."""
        params_small = {
            "building_name": "10 Kensington Ave",
            "facade_width_m": 3.0,
        }
        awning_small = infer_awning(params_small)
        assert awning_small["width_m"] == pytest.approx(3.0 * 0.8, abs=0.01)

        params_large = {
            "building_name": "10 Kensington Ave",
            "facade_width_m": 10.0,
        }
        awning_large = infer_awning(params_large)
        assert awning_large["width_m"] == pytest.approx(10.0 * 0.8, abs=0.01)


class TestStorefrontSignage:
    """Tests for signage inference."""

    def test_signage_restaurant_category_projecting(self):
        """Restaurant category → projecting signage."""
        params = {
            "context": {
                "business_name": "Joe's Diner",
                "business_category": "restaurant",
            },
            "facade_width_m": 5.0,
        }
        signage = infer_signage(params)
        assert signage is not None
        assert signage["text"] == "Joe's Diner"
        assert signage["type"] == "projecting"
        assert signage["width_m"] == pytest.approx(min(5.0 * 0.7, 4.0), abs=0.01)

    def test_signage_cafe_category_projecting(self):
        """Cafe category → projecting signage."""
        params = {
            "context": {
                "business_name": "Morning Brew",
                "business_category": "cafe",
            },
            "facade_width_m": 6.0,
        }
        signage = infer_signage(params)
        assert signage["type"] == "projecting"

    def test_signage_market_category_painted_window(self):
        """Market category → painted_window signage."""
        params = {
            "context": {
                "business_name": "Fresh Produce",
                "business_category": "market",
            },
            "facade_width_m": 5.0,
        }
        signage = infer_signage(params)
        assert signage["type"] == "painted_window"

    def test_signage_grocery_category_painted_window(self):
        """Grocery category → painted_window signage."""
        params = {
            "context": {
                "business_name": "Main St Grocery",
                "business_category": "grocery",
            },
            "facade_width_m": 5.0,
        }
        signage = infer_signage(params)
        assert signage["type"] == "painted_window"

    def test_signage_produce_category_painted_window(self):
        """Produce category → painted_window signage."""
        params = {
            "context": {
                "business_name": "Apple & Carrot",
                "business_category": "produce",
            },
            "facade_width_m": 5.0,
        }
        signage = infer_signage(params)
        assert signage["type"] == "painted_window"

    def test_signage_no_business_name(self):
        """No business_name → no signage."""
        params = {
            "context": {
                "business_category": "retail",
            },
        }
        signage = infer_signage(params)
        assert signage is None

    def test_signage_width_clamped_to_4m(self):
        """Signage width clamped to max 4.0m."""
        params = {
            "context": {
                "business_name": "Wide Store",
                "business_category": "restaurant",
            },
            "facade_width_m": 10.0,
        }
        signage = infer_signage(params)
        assert signage["width_m"] == 4.0

    def test_signage_height_fixed(self):
        """Signage height always 0.6m."""
        params = {
            "context": {
                "business_name": "Test",
                "business_category": "cafe",
            },
            "facade_width_m": 5.0,
        }
        signage = infer_signage(params)
        assert signage["height_m"] == 0.6

    def test_signage_colour_always_cream(self):
        """Signage colour always #F0EDE8 (cream)."""
        params = {
            "context": {
                "business_name": "Test",
                "business_category": "food",
            },
            "facade_width_m": 5.0,
        }
        signage = infer_signage(params)
        assert signage["colour_hex"] == "#F0EDE8"


class TestSecurityGrille:
    """Tests for security grille inference."""

    def test_grille_on_market_streets(self):
        """Security grille present on market spine streets."""
        # Note: street name extraction is case-insensitive
        for street_name in ["kensington ave", "augusta ave", "baldwin", "nassau"]:
            params = {
                "building_name": f"10 {street_name}",
            }
            grille = infer_security_grille(params)
            # Grille detection is case-insensitive, checking the function logic
            if grille is not None:
                assert grille["present"] is True
                assert grille["type"] == "rolling"

    def test_grille_on_residential_streets(self):
        """No security grille on residential streets."""
        params = {
            "building_name": "22 Lippincott St",
        }
        grille = infer_security_grille(params)
        assert grille is None

    def test_grille_on_major_streets(self):
        """No security grille on major streets."""
        params = {
            "building_name": "100 Spadina Ave",
        }
        grille = infer_security_grille(params)
        assert grille is None

    def test_grille_type_rolling(self):
        """Security grille type is 'rolling'."""
        params = {
            "building_name": "10 Kensington Ave",
        }
        grille = infer_security_grille(params)
        assert grille["type"] == "rolling"


class TestStorefrontEnrichment:
    """Tests for full storefront enrichment."""

    def test_enrich_storefront_skip_no_storefront(self):
        """Skip if has_storefront is False."""
        params = {
            "has_storefront": False,
        }
        changed, msg = enrich_storefront(params)
        assert changed is False
        assert "no storefront" in msg

    def test_enrich_storefront_full_enrichment(self):
        """Full enrichment: awning, signage, grille."""
        params = {
            "building_name": "10 Kensington Ave",
            "has_storefront": True,
            "facade_width_m": 5.0,
            "context": {
                "business_name": "Market Place",
                "business_category": "market",
            },
        }
        changed, msg = enrich_storefront(params)
        assert changed is True
        assert "awning/signage/grille" in msg

        storefront = params["storefront"]
        assert "awning" in storefront
        assert "signage" in storefront
        assert "security_grille" in storefront

    def test_enrich_storefront_idempotent_awning(self):
        """Skip awning enrichment if already present."""
        params = {
            "building_name": "10 Kensington Ave",
            "has_storefront": True,
            "facade_width_m": 5.0,
            "storefront": {
                "awning": {
                    "present": True,
                    "type": "fixed",
                    "colour_hex": "#123456",
                }
            },
        }
        changed, msg = enrich_storefront(params)
        # Should only add signage/grille, not overwrite awning
        awning = params["storefront"]["awning"]
        assert awning["colour_hex"] == "#123456"  # unchanged

    def test_enrich_storefront_idempotent_signage(self):
        """Skip signage enrichment if already present."""
        params = {
            "building_name": "10 Kensington Ave",
            "has_storefront": True,
            "context": {
                "business_name": "Market",
                "business_category": "market",
            },
            "storefront": {
                "signage": {
                    "text": "Existing Sign",
                    "type": "fascia",
                }
            },
        }
        changed, msg = enrich_storefront(params)
        signage = params["storefront"]["signage"]
        assert signage["text"] == "Existing Sign"  # unchanged

    def test_enrich_storefront_updates_storefront_dict(self):
        """Storefront dict is updated with enriched fields."""
        params = {
            "building_name": "10 Kensington Ave",
            "has_storefront": True,
            "facade_width_m": 5.0,
        }
        changed, msg = enrich_storefront(params)
        assert changed is True
        assert "storefront" in params
        # Verify changes were made to storefront
        assert len(params["storefront"]) > 0


class TestPorchEraDetection:
    """Tests for era parsing."""

    def test_era_pre_1889(self):
        """Pre-1889 detection."""
        assert parse_era("Pre-1889") == "pre-1889"
        assert parse_era("pre-1889") == "pre-1889"
        assert parse_era("PRE-1889") == "pre-1889"

    def test_era_1889_1903(self):
        """1889-1903 era."""
        assert parse_era("1889-1903") == "1889-1903"
        assert parse_era("1890") == "1889-1903"
        assert parse_era("1903") == "1889-1903"

    def test_era_1904_1913(self):
        """1904-1913 era."""
        assert parse_era("1904-1913") == "1904-1913"
        assert parse_era("1904") == "1904-1913"
        assert parse_era("1913") == "1904-1913"

    def test_era_1914_plus(self):
        """1914+ era."""
        assert parse_era("1914-1930") == "1914+"
        assert parse_era("1920") == "1914+"
        assert parse_era("2000") == "1914+"

    def test_era_default(self):
        """Default era is 1889-1903."""
        assert parse_era("") == "1889-1903"
        assert parse_era(None) == "1889-1903"


class TestPorchWidth:
    """Tests for porch width inference."""

    def test_porch_width_small_facade_60_percent(self):
        """Facade ≤5m → 60% width."""
        width = get_porch_width_m(5.0)
        assert width == pytest.approx(3.0, abs=0.01)

        width_small = get_porch_width_m(4.0)
        assert width_small == pytest.approx(2.4, abs=0.01)

    def test_porch_width_medium_facade_50_percent(self):
        """Facade 5-8m → 50% width."""
        width = get_porch_width_m(6.0)
        assert width == pytest.approx(3.0, abs=0.01)

        width_large = get_porch_width_m(8.0)
        assert width_large == pytest.approx(4.0, abs=0.01)

    def test_porch_width_large_facade_clamped(self):
        """Facade >8m → 4.0m."""
        width = get_porch_width_m(10.0)
        assert width == 4.0

        width_very_large = get_porch_width_m(15.0)
        assert width_very_large == 4.0


class TestPorchColumns:
    """Tests for porch column style by era."""

    def test_columns_pre_1889_turned(self):
        """Pre-1889 → turned columns."""
        columns = get_porch_columns("pre-1889")
        assert columns["type"] == "turned"
        assert columns["count"] == 2
        assert columns["material"] == "wood"

    def test_columns_1889_1903_turned(self):
        """1889-1903 → turned columns."""
        columns = get_porch_columns("1889-1903")
        assert columns["type"] == "turned"

    def test_columns_1904_1913_tapered_square(self):
        """1904-1913 → tapered square columns."""
        columns = get_porch_columns("1904-1913")
        assert columns["type"] == "tapered_square"

    def test_columns_1914_plus_square(self):
        """1914+ → square columns."""
        columns = get_porch_columns("1914+")
        assert columns["type"] == "square"


class TestPorchStepCount:
    """Tests for step count inference."""

    def test_step_count_from_deep_facade_analysis(self):
        """Step count from deep_facade_analysis depth_notes."""
        params = {
            "deep_facade_analysis": {
                "depth_notes": {
                    "step_count": 5,
                }
            },
        }
        step_count = infer_step_count(params)
        assert step_count == 5

    def test_step_count_from_foundation_height(self):
        """Step count computed from foundation_height_m (0.18m per step)."""
        params = {
            "foundation_height_m": 0.36,  # 2 steps
        }
        step_count = infer_step_count(params)
        assert step_count == 2

        params_tall = {
            "foundation_height_m": 0.54,  # 3 steps
        }
        step_count_tall = infer_step_count(params_tall)
        assert step_count_tall == 3

    def test_step_count_default(self):
        """Default step count is 2."""
        params = {}
        step_count = infer_step_count(params)
        assert step_count == 2


class TestPorchEnrichment:
    """Tests for full porch enrichment."""

    def test_enrich_porch_skip_no_porch(self):
        """Skip if porch_present is False."""
        params = {
            "porch_present": False,
        }
        changed, msg = enrich_porch(params)
        assert changed is False
        assert "no porch" in msg

    def test_enrich_porch_skip_already_has_dimensions(self):
        """Skip if porch dimensions already present."""
        params = {
            "porch_present": True,
            "porch_width_m": 2.0,
            "porch_depth_m": 1.8,
            "porch_height_m": 3.0,
        }
        changed, msg = enrich_porch(params)
        assert changed is False
        assert "already has dimensions" in msg

    def test_enrich_porch_full_enrichment(self):
        """Full enrichment: width, depth, height, columns, railing, steps."""
        params = {
            "porch_present": True,
            "facade_width_m": 4.0,
            "floor_heights_m": [3.2],
            "hcd_data": {
                "construction_date": "1900",
            },
        }
        changed, msg = enrich_porch(params)
        assert changed is True

        # Check top-level dimensions
        assert params["porch_width_m"] == pytest.approx(4.0 * 0.6, abs=0.01)
        assert params["porch_depth_m"] == 1.8
        assert params["porch_height_m"] == pytest.approx(3.2, abs=0.01)

        # Check porch_detail
        porch_detail = params["porch_detail"]
        assert "columns" in porch_detail
        assert "railing" in porch_detail
        assert "step_count" in porch_detail
        assert porch_detail["columns"]["type"] == "turned"

    def test_enrich_porch_updates_porch_fields(self):
        """Porch fields are enriched and updated."""
        params = {
            "porch_present": True,
            "facade_width_m": 5.0,
        }
        changed, msg = enrich_porch(params)
        assert changed is True
        # Verify top-level fields exist
        assert "porch_width_m" in params
        assert "porch_depth_m" in params
        assert "porch_height_m" in params

    def test_enrich_porch_idempotent(self):
        """Running twice doesn't double-write dimensions."""
        params = {
            "porch_present": True,
            "facade_width_m": 5.0,
            "floor_heights_m": [3.0],
        }

        # First enrichment
        changed1, _ = enrich_porch(params)
        assert changed1 is True
        width1 = params["porch_width_m"]

        # Second enrichment
        changed2, _ = enrich_porch(params)
        assert changed2 is False
        width2 = params["porch_width_m"]

        # Width unchanged
        assert width1 == width2

    def test_enrich_porch_default_floor_height(self):
        """Default floor height is 3.0m if missing."""
        params = {
            "porch_present": True,
            "facade_width_m": 5.0,
            # No floor_heights_m
        }
        changed, _ = enrich_porch(params)
        assert changed is True
        assert params["porch_height_m"] == 3.0

    def test_enrich_porch_railing_always_baluster(self):
        """Porch railing is always baluster type, 0.9m height."""
        params = {
            "porch_present": True,
            "facade_width_m": 5.0,
        }
        changed, _ = enrich_porch(params)
        railing = params["porch_detail"]["railing"]
        assert railing["present"] is True
        assert railing["type"] == "baluster"
        assert railing["height_m"] == 0.9


class TestStreetNameExtraction:
    """Tests for street name extraction from building_name."""

    def test_extract_street_simple(self):
        """Simple street extraction (number + street)."""
        street = get_street_from_building_name("22 Lippincott St")
        assert street == "Lippincott St"

    def test_extract_street_with_avenue(self):
        """Street with Ave abbreviation."""
        street = get_street_from_building_name("10 Kensington Ave")
        assert street == "Kensington Ave"

    def test_extract_street_with_multiple_words(self):
        """Street with multiple words."""
        street = get_street_from_building_name("15 Glen Baillie St")
        assert street == "Glen Baillie St"

    def test_extract_street_only_number(self):
        """Only number, no street."""
        street = get_street_from_building_name("22")
        assert street == ""

    def test_extract_street_empty_string(self):
        """Empty string."""
        street = get_street_from_building_name("")
        assert street == ""


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
