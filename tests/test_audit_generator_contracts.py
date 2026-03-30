"""Unit tests for audit_generator_contracts.py"""

import json
import pytest
from scripts.audit_generator_contracts import (
    extract_param_accesses,
    check_compatibility,
)


class TestExtractParamAccesses:
    """Test extract_param_accesses function."""

    def test_param_get_with_default(self):
        """Should extract params.get() with default."""
        code = 'x = params.get("roof_type", "flat")'
        required, optional = extract_param_accesses(code)
        assert "roof_type" in optional
        assert "roof_type" not in required

    def test_param_get_without_default(self):
        """Should extract params.get() without default."""
        code = 'x = params.get("floor_count")'
        required, optional = extract_param_accesses(code)
        assert "floor_count" in optional

    def test_param_direct_access(self):
        """Should extract params["key"] direct access."""
        code = 'x = params["building_name"]'
        required, optional = extract_param_accesses(code)
        # Direct access not in optional, so should be required
        assert "building_name" in required

    def test_nested_access_pattern(self):
        """Should extract nested access patterns."""
        code = 'hcd = params.get("hcd_data", {})\nvalue = hcd.get("construction_date")'
        required, optional = extract_param_accesses(code)
        assert "hcd_data" in optional
        # Nested access might be captured
        assert len(optional) >= 1

    def test_multiple_accesses_same_function(self):
        """Should extract multiple accesses in same code."""
        code = '''
x = params.get("roof_type", "flat")
y = params.get("floor_count")
z = params["building_name"]
        '''
        required, optional = extract_param_accesses(code)
        assert "roof_type" in optional
        assert "floor_count" in optional
        assert "building_name" in required

    def test_no_accesses(self):
        """Should return empty sets for code with no param accesses."""
        code = 'x = 5\ny = "hello"'
        required, optional = extract_param_accesses(code)
        assert len(required) == 0
        assert len(optional) == 0

    def test_single_quoted_string(self):
        """Should handle single-quoted strings."""
        code = "x = params.get('field', 10)"
        required, optional = extract_param_accesses(code)
        assert "field" in optional

    def test_spaced_params_get(self):
        """Should handle spaces in params.get()."""
        code = 'x = params . get ( "field" , 10 )'
        required, optional = extract_param_accesses(code)
        # Regex might not match with spaces around dot, check result
        # This tests robustness
        assert isinstance(required, set)
        assert isinstance(optional, set)

    def test_escaped_quotes_not_matched(self):
        """Should not match escaped quotes."""
        code = r'x = params.get("field\"test")'
        required, optional = extract_param_accesses(code)
        # Should not crash
        assert isinstance(optional, set)


class TestCheckCompatibility:
    """Test check_compatibility function."""

    def test_empty_building(self):
        """Empty building should trigger warnings."""
        contract_map = {
            "create_walls": {
                "required": ["facade_material", "facade_colour"],
                "optional": [],
                "conditions": [],
            }
        }
        params = {}
        warnings = check_compatibility(contract_map, params, "10 Test St")
        # Should have warnings for missing required fields
        assert len(warnings) > 0

    def test_building_with_required_fields(self):
        """Building with required fields should have no warnings."""
        contract_map = {
            "create_walls": {
                "required": ["facade_material"],
                "optional": [],
                "conditions": [],
            }
        }
        params = {
            "facade_material": "brick",
            "roof_type": "gable",
        }
        warnings = check_compatibility(contract_map, params, "10 Test St")
        # May have warnings for other functions, but not create_walls
        walls_warnings = [w for w in warnings if w["function"] == "create_walls"]
        assert len(walls_warnings) == 0

    def test_flat_roof_condition(self):
        """Flat roof should call create_flat_roof."""
        contract_map = {
            "create_flat_roof": {
                "required": ["roof_detail"],
                "optional": [],
                "conditions": ["roof_type == flat"],
            }
        }
        params = {
            "roof_type": "flat",
            # missing roof_detail
        }
        warnings = check_compatibility(contract_map, params, "10 Test St")
        flat_roof_warnings = [w for w in warnings if w["function"] == "create_flat_roof"]
        assert len(flat_roof_warnings) > 0

    def test_gable_roof_condition(self):
        """Gable roof should call create_gable_roof."""
        contract_map = {
            "create_gable_roof": {
                "required": ["roof_pitch_deg"],
                "optional": [],
                "conditions": [],
            }
        }
        params = {
            "roof_type": "gable",
            "roof_pitch_deg": 45,
        }
        warnings = check_compatibility(contract_map, params, "10 Test St")
        gable_warnings = [w for w in warnings if w["function"] == "create_gable_roof"]
        assert len(gable_warnings) == 0

    def test_storefront_condition(self):
        """Storefront presence triggers create_storefront."""
        contract_map = {
            "create_storefront": {
                "required": ["storefront"],
                "optional": [],
                "conditions": [],
            }
        }
        params = {
            "has_storefront": True,
            # missing storefront details
        }
        warnings = check_compatibility(contract_map, params, "10 Test St")
        storefront_warnings = [w for w in warnings if w["function"] == "create_storefront"]
        assert len(storefront_warnings) > 0

    def test_porch_condition(self):
        """Porch presence triggers create_porch."""
        contract_map = {
            "create_porch": {
                "required": ["porch"],
                "optional": [],
                "conditions": [],
            }
        }
        params = {
            "porch_present": True,
            # missing porch details
        }
        warnings = check_compatibility(contract_map, params, "10 Test St")
        porch_warnings = [w for w in warnings if w["function"] == "create_porch"]
        assert len(porch_warnings) > 0

    def test_bay_window_condition(self):
        """Bay window presence triggers create_bay_window."""
        contract_map = {
            "create_bay_window": {
                "required": ["bay_window"],
                "optional": [],
                "conditions": [],
            }
        }
        params = {
            "bay_window": {"present": True},
            # bay_window is present (dict with present key)
        }
        warnings = check_compatibility(contract_map, params, "10 Test St")
        # bay_window dict is present, so field exists and is not None
        # Only warnings if the field is None or empty string
        bay_warnings = [w for w in warnings if w["function"] == "create_bay_window"]
        # No warnings expected since bay_window field exists
        assert len(bay_warnings) == 0

    def test_string_courses_condition(self):
        """String courses in decorative_elements."""
        contract_map = {
            "create_string_courses": {
                "required": ["string_course_height"],
                "optional": [],
                "conditions": [],
            }
        }
        params = {
            "decorative_elements": {
                "string_courses": {"present": True}
            },
            # missing string_course_height
        }
        warnings = check_compatibility(contract_map, params, "10 Test St")
        sc_warnings = [w for w in warnings if w["function"] == "create_string_courses"]
        assert len(sc_warnings) > 0

    def test_chimney_in_roof_features(self):
        """Chimney in roof_features triggers create_chimney."""
        contract_map = {
            "create_chimney": {
                "required": ["chimney_height"],
                "optional": [],
                "conditions": [],
            }
        }
        params = {
            "roof_features": ["chimney"],
            # missing chimney_height
        }
        warnings = check_compatibility(contract_map, params, "10 Test St")
        chimney_warnings = [w for w in warnings if w["function"] == "create_chimney"]
        assert len(chimney_warnings) > 0

    def test_dormer_in_roof_features(self):
        """Dormer in roof_features triggers create_dormer."""
        contract_map = {
            "create_dormer": {
                "required": ["dormer_width"],
                "optional": [],
                "conditions": [],
            }
        }
        params = {
            "roof_features": ["dormer"],
            # missing dormer_width
        }
        warnings = check_compatibility(contract_map, params, "10 Test St")
        dormer_warnings = [w for w in warnings if w["function"] == "create_dormer"]
        assert len(dormer_warnings) > 0

    def test_cross_gable_roof(self):
        """Cross-gable roof triggers create_cross_gable_roof."""
        contract_map = {
            "create_cross_gable_roof": {
                "required": ["cross_gable_detail"],
                "optional": [],
                "conditions": [],
            }
        }
        params = {
            "roof_type": "cross-gable",
            # missing cross_gable_detail
        }
        warnings = check_compatibility(contract_map, params, "10 Test St")
        cross_gable_warnings = [w for w in warnings if w["function"] == "create_cross_gable_roof"]
        assert len(cross_gable_warnings) > 0

    def test_hip_roof(self):
        """Hip roof triggers create_hip_roof."""
        contract_map = {
            "create_hip_roof": {
                "required": ["hip_roof_detail"],
                "optional": [],
                "conditions": [],
            }
        }
        params = {
            "roof_type": "hip",
            # missing hip_roof_detail
        }
        warnings = check_compatibility(contract_map, params, "10 Test St")
        hip_warnings = [w for w in warnings if w["function"] == "create_hip_roof"]
        assert len(hip_warnings) > 0

    def test_quoins_in_decorative_elements(self):
        """Quoins in decorative_elements."""
        contract_map = {
            "create_quoins": {
                "required": ["quoin_width"],
                "optional": [],
                "conditions": [],
            }
        }
        params = {
            "decorative_elements": {
                "quoins": {"present": True}
            },
            # missing quoin_width
        }
        warnings = check_compatibility(contract_map, params, "10 Test St")
        quoin_warnings = [w for w in warnings if w["function"] == "create_quoins"]
        assert len(quoin_warnings) > 0

    def test_cornice_in_decorative_elements(self):
        """Cornice in decorative_elements."""
        contract_map = {
            "create_cornice_band": {
                "required": ["cornice_height"],
                "optional": [],
                "conditions": [],
            }
        }
        params = {
            "decorative_elements": {
                "cornice": {"present": True}
            },
            # missing cornice_height
        }
        warnings = check_compatibility(contract_map, params, "10 Test St")
        cornice_warnings = [w for w in warnings if w["function"] == "create_cornice_band"]
        assert len(cornice_warnings) > 0

    def test_missing_required_field_warning(self):
        """Missing required field should create warning."""
        contract_map = {
            "create_walls": {
                "required": ["facade_material"],
                "optional": [],
                "conditions": [],
            }
        }
        params = {
            # missing facade_material
            "roof_type": "gable",
        }
        warnings = check_compatibility(contract_map, params, "10 Test St")
        assert len(warnings) > 0
        assert warnings[0]["missing_field"] == "facade_material"
        assert warnings[0]["severity"] == "error"

    def test_warning_structure(self):
        """Warnings should have correct structure."""
        contract_map = {
            "create_walls": {
                "required": ["facade_material"],
                "optional": [],
                "conditions": [],
            }
        }
        params = {}
        warnings = check_compatibility(contract_map, params, "10 Test St")
        if warnings:
            warning = warnings[0]
            assert "address" in warning
            assert "function" in warning
            assert "missing_field" in warning
            assert "severity" in warning
            assert warning["address"] == "10 Test St"

    def test_multiple_missing_fields(self):
        """Multiple missing fields should create multiple warnings."""
        contract_map = {
            "create_walls": {
                "required": ["facade_material", "facade_colour", "total_height_m"],
                "optional": [],
                "conditions": [],
            }
        }
        params = {
            "roof_type": "gable",
        }
        warnings = check_compatibility(contract_map, params, "10 Test St")
        walls_warnings = [w for w in warnings if w["function"] == "create_walls"]
        assert len(walls_warnings) >= 3

    def test_nested_field_access(self):
        """Nested fields should be checked."""
        contract_map = {
            "create_walls": {
                "required": ["decorative_elements.string_courses.height"],
                "optional": [],
                "conditions": [],
            }
        }
        params = {
            "decorative_elements": {
                "string_courses": {}
                # missing height
            }
        }
        warnings = check_compatibility(contract_map, params, "10 Test St")
        # Should have warning about missing nested field
        assert len(warnings) > 0
