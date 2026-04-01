"""Unit tests for generate_qa_report.py"""

from __future__ import annotations

import json
import pytest
from pathlib import Path
from typing import Any

from generate_qa_report import (
    QAIssue,
    _extract_street_from_name,
    _check_building,
)


class TestQAIssueDataclass:
    """Tests for QAIssue dataclass."""

    def test_create_qa_issue(self):
        """Test creating a QAIssue instance."""
        issue = QAIssue(
            category="missing_windows_detail",
            severity="error",
            message="Test message"
        )
        assert issue.category == "missing_windows_detail"
        assert issue.severity == "error"
        assert issue.message == "Test message"

    def test_qa_issue_as_dict(self):
        """Test converting QAIssue to dict."""
        issue = QAIssue(
            category="missing_roof_type",
            severity="warning",
            message="No roof type"
        )
        result = issue.as_dict()
        assert isinstance(result, dict)
        assert result["category"] == "missing_roof_type"
        assert result["severity"] == "warning"
        assert result["message"] == "No roof type"

    def test_qa_issue_with_empty_message(self):
        """Test QAIssue with empty message."""
        issue = QAIssue(
            category="test",
            severity="info",
            message=""
        )
        assert issue.message == ""
        assert issue.as_dict()["message"] == ""

    def test_qa_issue_severity_types(self):
        """Test QAIssue with different severity levels."""
        for severity in ["error", "warning", "info"]:
            issue = QAIssue(category="test", severity=severity, message="msg")
            assert issue.severity == severity


class TestExtractStreetFromName:
    """Tests for _extract_street_from_name function."""

    def test_extract_street_simple(self):
        """Test extracting street from simple building name."""
        result = _extract_street_from_name("22 Lippincott St")
        assert result == "Lippincott St"

    def test_extract_street_with_number_prefix(self):
        """Test extracting street with leading number."""
        result = _extract_street_from_name("128 Augusta Ave")
        assert result == "Augusta Ave"

    def test_extract_street_three_part_name(self):
        """Test extracting street from three-part name."""
        result = _extract_street_from_name("22 Lippincott Street")
        assert result == "Lippincott Street"

    def test_extract_street_no_number(self):
        """Test when building name has no number prefix."""
        # With no number, it splits by space and returns the second part
        result = _extract_street_from_name("Lippincott St")
        assert result == "St"

    def test_extract_street_single_word(self):
        """Test with single-word street name."""
        result = _extract_street_from_name("22 Dundas")
        assert result == "Dundas"

    def test_extract_street_empty_string(self):
        """Test with empty string."""
        result = _extract_street_from_name("")
        assert result == ""

    def test_extract_street_whitespace_only(self):
        """Test with whitespace-only string - causes IndexError."""
        # Whitespace-only string will cause IndexError due to empty split result
        with pytest.raises(IndexError):
            _extract_street_from_name("   ")

    def test_extract_street_leading_trailing_spaces(self):
        """Test extraction with leading/trailing spaces."""
        result = _extract_street_from_name("  22 Lippincott St  ")
        assert result == "Lippincott St"

    def test_extract_street_complex_name(self):
        """Test with complex street name."""
        result = _extract_street_from_name("1 College Street West")
        assert result == "College Street West"

    def test_extract_street_all_digits(self):
        """Test when entire string is digits."""
        # Single digit group returns as is
        result = _extract_street_from_name("123")
        assert result == "123"


class TestCheckBuilding:
    """Tests for _check_building function."""

    def test_check_building_no_issues(self, tmp_path):
        """Test building with no issues."""
        params = {
            "building_name": "22 Lippincott St",
            "windows_detail": [{"floor": "Ground floor"}],
            "doors_detail": [{"id": "door1"}],
            "roof_type": "gable",
            "total_height_m": 10.0,
            "decorative_elements": {"cornice": {}},
            "deep_facade_analysis": {"analysis": "data"},
            "photo_observations": {"observation": "data"},
            "storefront": None,
            "has_storefront": False,
            "floors": 2,
            "floor_heights_m": [3.0, 3.0],
        }
        building_path = tmp_path / "test_building.json"
        issues, score = _check_building(params, building_path)
        assert len(issues) == 0
        assert score == 100.0

    def test_check_building_missing_windows_detail(self, tmp_path):
        """Test detection of missing windows_detail."""
        params = {
            "building_name": "Test",
            "windows_detail": [],
            "roof_type": "flat",
        }
        building_path = tmp_path / "test.json"
        issues, score = _check_building(params, building_path)
        assert any(i.category == "missing_windows_detail" for i in issues)
        assert any(i.severity == "error" for i in issues)

    def test_check_building_missing_roof_type(self, tmp_path):
        """Test detection of missing roof_type."""
        params = {
            "building_name": "Test",
            "windows_detail": [{"floor": "Ground"}],
        }
        building_path = tmp_path / "test.json"
        issues, score = _check_building(params, building_path)
        assert any(i.category == "missing_roof_type" for i in issues)

    def test_check_building_missing_doors_detail(self, tmp_path):
        """Test detection of missing doors_detail."""
        params = {
            "building_name": "Test",
            "windows_detail": [{"floor": "Ground"}],
            "roof_type": "flat",
        }
        building_path = tmp_path / "test.json"
        issues, score = _check_building(params, building_path)
        assert any(i.category == "missing_doors_detail" for i in issues)
        assert any(i.severity == "warning" for i in issues)

    def test_check_building_height_mismatch(self, tmp_path):
        """Test detection of height mismatch."""
        params = {
            "building_name": "Test",
            "windows_detail": [{"floor": "Ground"}],
            "roof_type": "flat",
            "doors_detail": [],
            "total_height_m": 15.0,
            "city_data": {"height_avg_m": 8.0},
        }
        building_path = tmp_path / "test.json"
        issues, score = _check_building(params, building_path)
        assert any(i.category == "height_mismatch" for i in issues)

    def test_check_building_missing_brick_colour(self, tmp_path):
        """Test detection of missing brick colour for brick buildings."""
        params = {
            "building_name": "Test",
            "windows_detail": [{"floor": "Ground"}],
            "roof_type": "flat",
            "doors_detail": [],
            "facade_material": "brick",
            "facade_detail": {},
        }
        building_path = tmp_path / "test.json"
        issues, score = _check_building(params, building_path)
        assert any(i.category == "missing_brick_colour" for i in issues)

    def test_check_building_storefront_conflict(self, tmp_path):
        """Test detection of storefront conflict."""
        params = {
            "building_name": "Test",
            "windows_detail": [{"floor": "Ground"}],
            "roof_type": "flat",
            "doors_detail": [],
            "storefront": {"type": "modern"},
            "has_storefront": False,
        }
        building_path = tmp_path / "test.json"
        issues, score = _check_building(params, building_path)
        assert any(i.category == "storefront_conflict" for i in issues)

    def test_check_building_floor_heights_mismatch(self, tmp_path):
        """Test detection of floor_heights_m mismatch."""
        params = {
            "building_name": "Test",
            "windows_detail": [{"floor": "Ground"}],
            "roof_type": "flat",
            "doors_detail": [],
            "floors": 3,
            "floor_heights_m": [3.0, 3.0],
        }
        building_path = tmp_path / "test.json"
        issues, score = _check_building(params, building_path)
        assert any(i.category == "floor_heights_mismatch" for i in issues)

    def test_check_building_missing_floor_heights(self, tmp_path):
        """Test detection of missing floor_heights_m."""
        params = {
            "building_name": "Test",
            "windows_detail": [{"floor": "Ground"}],
            "roof_type": "flat",
            "doors_detail": [],
            "floors": 2,
            "floor_heights_m": [],
        }
        building_path = tmp_path / "test.json"
        issues, score = _check_building(params, building_path)
        assert any(i.category == "missing_floor_heights" for i in issues)

    def test_check_building_missing_decorative_elements(self, tmp_path):
        """Test detection of missing decorative_elements."""
        params = {
            "building_name": "Test",
            "windows_detail": [{"floor": "Ground"}],
            "roof_type": "flat",
            "doors_detail": [],
        }
        building_path = tmp_path / "test.json"
        issues, score = _check_building(params, building_path)
        assert any(i.category == "missing_decorative_elements" for i in issues)

    def test_check_building_missing_deep_facade_analysis(self, tmp_path):
        """Test detection of missing deep_facade_analysis."""
        params = {
            "building_name": "Test",
            "windows_detail": [{"floor": "Ground"}],
            "roof_type": "flat",
            "doors_detail": [],
            "decorative_elements": {},
        }
        building_path = tmp_path / "test.json"
        issues, score = _check_building(params, building_path)
        assert any(i.category == "missing_deep_facade_analysis" for i in issues)

    def test_check_building_missing_photo_observations(self, tmp_path):
        """Test detection of missing photo_observations."""
        params = {
            "building_name": "Test",
            "windows_detail": [{"floor": "Ground"}],
            "roof_type": "flat",
            "doors_detail": [],
            "decorative_elements": {},
            "deep_facade_analysis": {},
        }
        building_path = tmp_path / "test.json"
        issues, score = _check_building(params, building_path)
        assert any(i.category == "missing_photo_observations" for i in issues)

    def test_check_building_score_calculation_single_error(self, tmp_path):
        """Test quality score calculation with single error."""
        params = {
            "building_name": "Test",
            "roof_type": None,  # This causes an error
            "windows_detail": [{"floor": "Ground"}],
            "doors_detail": [],
        }
        building_path = tmp_path / "test.json"
        issues, score = _check_building(params, building_path)
        # Missing roof_type is one error (-15), 3 info issues (-6 total)
        # 100 - 15 - 6 = 79
        assert score == 79.0

    def test_check_building_score_calculation_multiple_issues(self, tmp_path):
        """Test quality score with multiple issues."""
        params = {
            "building_name": "Test",
            "windows_detail": [],  # error: -15
            "roof_type": None,  # error: -15
            "doors_detail": None,  # warning: -8
        }
        building_path = tmp_path / "test.json"
        issues, score = _check_building(params, building_path)
        # 2 errors (-30), 1 warning (-8), 3 info issues (-6 total)
        # 100 - 30 - 8 - 6 = 56
        assert score == 56.0

    def test_check_building_score_minimum_zero(self, tmp_path):
        """Test that score doesn't go below 0."""
        params = {
            "building_name": "Test",
        }
        building_path = tmp_path / "test.json"
        issues, score = _check_building(params, building_path)
        assert score >= 0.0

    def test_check_building_invalid_height_values(self, tmp_path):
        """Test handling of invalid (non-numeric) height values."""
        params = {
            "building_name": "Test",
            "windows_detail": [{"floor": "Ground"}],
            "roof_type": "flat",
            "doors_detail": [],
            "total_height_m": "not_a_number",
            "city_data": {"height_avg_m": "also_not_a_number"},
        }
        building_path = tmp_path / "test.json"
        issues, score = _check_building(params, building_path)
        # Should not raise an error
        assert isinstance(score, float)

    def test_check_building_invalid_floor_count(self, tmp_path):
        """Test handling of invalid floor count."""
        params = {
            "building_name": "Test",
            "windows_detail": [{"floor": "Ground"}],
            "roof_type": "flat",
            "doors_detail": [],
            "floors": "invalid",
            "floor_heights_m": [3.0],
        }
        building_path = tmp_path / "test.json"
        issues, score = _check_building(params, building_path)
        # Should not raise an error
        assert isinstance(score, float)

    def test_check_building_brick_building_no_facade_detail(self, tmp_path):
        """Test brick building without facade_detail."""
        params = {
            "building_name": "Test",
            "windows_detail": [{"floor": "Ground"}],
            "roof_type": "flat",
            "doors_detail": [],
            "facade_material": "brick",
        }
        building_path = tmp_path / "test.json"
        issues, score = _check_building(params, building_path)
        assert any(i.category == "missing_brick_colour" for i in issues)

    def test_check_building_non_brick_material_no_colour_check(self, tmp_path):
        """Test that non-brick materials don't trigger brick colour check."""
        params = {
            "building_name": "Test",
            "windows_detail": [{"floor": "Ground"}],
            "roof_type": "flat",
            "doors_detail": [],
            "facade_material": "painted",
            "facade_detail": {},
        }
        building_path = tmp_path / "test.json"
        issues, score = _check_building(params, building_path)
        # Should not check for brick_colour_hex
        assert not any(i.category == "missing_brick_colour" for i in issues)

    def test_check_building_returns_tuple(self, tmp_path):
        """Test that _check_building returns a tuple."""
        params = {
            "building_name": "Test",
            "windows_detail": [{"floor": "Ground"}],
            "roof_type": "flat",
            "doors_detail": [],
        }
        building_path = tmp_path / "test.json"
        result = _check_building(params, building_path)
        assert isinstance(result, tuple)
        assert len(result) == 2
        assert isinstance(result[0], list)
        assert isinstance(result[1], float)

    def test_check_building_issue_message_includes_name(self, tmp_path):
        """Test that issue messages include building name."""
        params = {
            "building_name": "Test Building 123",
            "windows_detail": [],
            "roof_type": "flat",
        }
        building_path = tmp_path / "test.json"
        issues, score = _check_building(params, building_path)
        # At least one issue should mention the building name
        assert any("Test Building 123" in issue.message for issue in issues)

    def test_check_building_uses_stem_as_fallback_name(self, tmp_path):
        """Test that building_path.stem is used as fallback name."""
        params = {
            "windows_detail": [],
            "roof_type": "flat",
        }
        building_path = tmp_path / "my_test_building.json"
        issues, score = _check_building(params, building_path)
        # At least one issue should use stem name
        assert any("my_test_building" in issue.message for issue in issues)

    def test_check_building_empty_params_dict(self, tmp_path):
        """Test checking building with minimal params."""
        params = {}
        building_path = tmp_path / "empty.json"
        issues, score = _check_building(params, building_path)
        # Should detect many missing fields
        assert len(issues) > 0
        assert score < 100.0

    def test_check_building_none_values_handled(self, tmp_path):
        """Test that None values are handled gracefully."""
        params = {
            "building_name": None,
            "windows_detail": None,
            "doors_detail": None,
            "roof_type": None,
            "decorative_elements": None,
            "deep_facade_analysis": None,
            "photo_observations": None,
        }
        building_path = tmp_path / "test.json"
        issues, score = _check_building(params, building_path)
        # Should not raise an error
        assert isinstance(score, float)
        assert len(issues) > 0
