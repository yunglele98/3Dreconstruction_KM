"""Unit tests for consolidate_depth_notes.py"""

import json
from pathlib import Path
import pytest
from scripts.consolidate_depth_notes import (
    infer_step_count,
    consolidate_depth_notes,
    process_params,
)


class TestInferStepCount:
    """Test infer_step_count function."""

    def test_commercial_no_foundation_returns_1(self):
        """Commercial at grade should return 1."""
        result = infer_step_count(None, None, False, True, {})
        assert result == 1

    def test_no_foundation_no_porch_returns_1(self):
        """No foundation and no porch should return 1."""
        result = infer_step_count(None, 2.0, False, False, {})
        assert result == 1

    def test_no_foundation_with_porch_returns_2(self):
        """No foundation with porch should return 2."""
        result = infer_step_count(None, 2.0, True, False, {})
        assert result == 2

    def test_foundation_height_0_3_returns_2(self):
        """Foundation height 0.3m should return 2."""
        result = infer_step_count(0.3, None, False, False, {})
        assert result == 2

    def test_foundation_height_0_36_returns_2(self):
        """Foundation height 0.36m should return 2."""
        result = infer_step_count(0.36, None, False, False, {})
        assert result == 2

    def test_foundation_height_0_54_returns_3(self):
        """Foundation height 0.54m should return 3."""
        result = infer_step_count(0.54, None, False, False, {})
        assert result == 3

    def test_foundation_with_setback_and_porch(self):
        """Foundation with setback and porch should increase count."""
        result = infer_step_count(0.3, 2.0, True, False, {})
        assert result >= 2

    def test_zero_foundation_height(self):
        """Zero foundation height should use default logic."""
        result = infer_step_count(0, None, False, False, {})
        assert result == 1

    def test_commercial_in_context(self):
        """Should recognize commercial in context building_type."""
        result = infer_step_count(None, None, False, False, {"building_type": "commercial"})
        assert result == 1

    def test_negative_foundation_height(self):
        """Should handle negative foundation height gracefully."""
        result = infer_step_count(-0.5, None, False, False, {})
        assert isinstance(result, int)


class TestConsolidateDepthNotes:
    """Test consolidate_depth_notes function."""

    def test_adds_setback_m_est_from_site(self):
        """Should add setback_m_est from site.setback_m."""
        params = {
            "site": {"setback_m": 2.5},
            "deep_facade_analysis": {},
        }
        result = consolidate_depth_notes(params)
        assert result["setback_m_est"] == 2.5

    def test_adds_setback_m_est_from_inferred(self):
        """Should add setback_m_est from inferred_setback_m if site missing."""
        params = {
            "site": {},
            "inferred_setback_m": 3.0,
            "deep_facade_analysis": {},
        }
        result = consolidate_depth_notes(params)
        assert result["setback_m_est"] == 3.0

    def test_setback_m_est_default(self):
        """Should default to 2.0 if no setback info."""
        params = {
            "site": {},
            "deep_facade_analysis": {},
        }
        result = consolidate_depth_notes(params)
        assert result["setback_m_est"] == 2.0

    def test_adds_foundation_height_m_est(self):
        """Should add foundation_height_m_est from foundation_height_m."""
        params = {
            "foundation_height_m": 0.45,
            "deep_facade_analysis": {},
        }
        result = consolidate_depth_notes(params)
        assert result["foundation_height_m_est"] == 0.45

    def test_foundation_height_m_est_default(self):
        """Should default to 0.3 if no foundation height."""
        params = {"deep_facade_analysis": {}}
        result = consolidate_depth_notes(params)
        assert result["foundation_height_m_est"] == 0.3

    def test_adds_step_count(self):
        """Should add step_count."""
        params = {
            "site": {"setback_m": 2.0},
            "foundation_height_m": 0.36,
            "porch_present": False,
            "has_storefront": False,
            "context": {},
            "deep_facade_analysis": {},
        }
        result = consolidate_depth_notes(params)
        assert "step_count" in result
        assert isinstance(result["step_count"], int)

    def test_adds_eave_overhang_mm_est(self):
        """Should add eave_overhang_mm_est from roof_detail."""
        params = {
            "roof_detail": {"eave_overhang_mm": 400},
            "deep_facade_analysis": {},
        }
        result = consolidate_depth_notes(params)
        assert result["eave_overhang_mm_est"] == 400

    def test_eave_overhang_mm_est_default(self):
        """Should default to 300 if not specified."""
        params = {"roof_detail": {}, "deep_facade_analysis": {}}
        result = consolidate_depth_notes(params)
        assert result["eave_overhang_mm_est"] == 300

    def test_adds_wall_thickness_m(self):
        """Should add wall_thickness_m = 0.3."""
        params = {"deep_facade_analysis": {}}
        result = consolidate_depth_notes(params)
        assert result["wall_thickness_m"] == 0.3

    def test_does_not_overwrite_existing_fields(self):
        """Should only add missing fields."""
        existing_depth_notes = {
            "setback_m_est": 1.0,
            "step_count": 5,
        }
        params = {
            "site": {"setback_m": 3.0},
            "inferred_setback_m": 2.5,
            "foundation_height_m": 0.36,
            "deep_facade_analysis": {"depth_notes": existing_depth_notes},
        }
        result = consolidate_depth_notes(params)
        # Should not include fields that already exist in depth_notes
        assert "setback_m_est" not in result or result["setback_m_est"] == 1.0
        assert "step_count" not in result or result["step_count"] == 5

    def test_handles_missing_deep_facade_analysis(self):
        """Should handle missing deep_facade_analysis."""
        params = {
            "site": {"setback_m": 2.0},
            "foundation_height_m": 0.3,
        }
        result = consolidate_depth_notes(params)
        assert "setback_m_est" in result
        assert "foundation_height_m_est" in result

    def test_handles_non_dict_deep_facade_analysis(self):
        """Should handle non-dict deep_facade_analysis."""
        params = {
            "deep_facade_analysis": "invalid",
            "site": {"setback_m": 2.0},
        }
        result = consolidate_depth_notes(params)
        assert "setback_m_est" in result

    def test_all_fields_added_complete_building(self):
        """Complete building should get all 5 fields."""
        params = {
            "site": {"setback_m": 2.0},
            "foundation_height_m": 0.36,
            "roof_detail": {"eave_overhang_mm": 350},
            "deep_facade_analysis": {},
        }
        result = consolidate_depth_notes(params)
        expected_keys = {"setback_m_est", "foundation_height_m_est", "step_count", "eave_overhang_mm_est", "wall_thickness_m"}
        assert set(result.keys()) == expected_keys


class TestProcessParams:
    """Test process_params function."""

    def test_process_empty_directory(self, tmp_path):
        """Should handle empty params directory."""
        result = process_params(tmp_path, apply=False, dry_run=True)
        assert result["processed"] == 0
        assert result["skipped"] == 0

    def test_process_skips_metadata_files(self, tmp_path):
        """Should skip files starting with underscore."""
        meta_file = tmp_path / "_site_coordinates.json"
        meta_file.write_text('{}', encoding="utf-8")

        result = process_params(tmp_path, apply=False, dry_run=True)
        assert result["skipped"] == 1

    def test_process_skips_marked_buildings(self, tmp_path):
        """Should skip buildings with skipped=true."""
        param_file = tmp_path / "10_Nassau_St.json"
        param_file.write_text(json.dumps({"skipped": True}), encoding="utf-8")

        result = process_params(tmp_path, apply=False, dry_run=True)
        assert result["skipped"] == 1

    def test_process_consolidates_single_building(self, tmp_path):
        """Should consolidate depth_notes for a single building."""
        param_file = tmp_path / "22_Lippincott_St.json"
        params = {
            "building_name": "22 Lippincott St",
            "site": {"setback_m": 2.5},
            "foundation_height_m": 0.36,
            "roof_detail": {"eave_overhang_mm": 300},
            "_meta": {},
        }
        param_file.write_text(json.dumps(params), encoding="utf-8")

        result = process_params(tmp_path, apply=False, dry_run=True)
        assert result["processed"] == 1
        assert result["consolidated"] == 1
        assert result["setback_m_est_added"] == 1
        assert result["foundation_height_m_est_added"] == 1
        assert result["step_count_added"] == 1
        assert result["eave_overhang_mm_est_added"] == 1
        assert result["wall_thickness_m_added"] == 1

    def test_process_apply_writes_files(self, tmp_path):
        """Should write files when apply=True."""
        param_file = tmp_path / "22_Lippincott_St.json"
        params = {
            "building_name": "22 Lippincott St",
            "site": {"setback_m": 2.0},
            "foundation_height_m": 0.36,
            "_meta": {},
        }
        param_file.write_text(json.dumps(params), encoding="utf-8")

        result = process_params(tmp_path, apply=True, dry_run=False)
        assert result["processed"] == 1

        # Verify file was written
        updated = json.loads(param_file.read_text(encoding="utf-8"))
        assert "deep_facade_analysis" in updated
        assert "depth_notes" in updated["deep_facade_analysis"]
        assert "setback_m_est" in updated["deep_facade_analysis"]["depth_notes"]

    def test_process_handles_invalid_json(self, tmp_path):
        """Should handle invalid JSON gracefully."""
        bad_file = tmp_path / "bad.json"
        bad_file.write_text("{ invalid json", encoding="utf-8")

        result = process_params(tmp_path, apply=False, dry_run=True)
        assert len(result["errors"]) > 0

    def test_process_partial_consolidation(self, tmp_path):
        """Should only add missing fields."""
        param_file = tmp_path / "22_Lippincott_St.json"
        existing_depth_notes = {
            "setback_m_est": 1.5,
            "step_count": 4,
        }
        params = {
            "building_name": "22 Lippincott St",
            "site": {"setback_m": 2.5},
            "foundation_height_m": 0.36,
            "deep_facade_analysis": {"depth_notes": existing_depth_notes},
            "_meta": {},
        }
        param_file.write_text(json.dumps(params), encoding="utf-8")

        result = process_params(tmp_path, apply=False, dry_run=True)
        assert result["consolidated"] == 1
        # These shouldn't be added since they already exist
        assert result["setback_m_est_added"] == 0
        assert result["step_count_added"] == 0

    def test_process_multiple_buildings(self, tmp_path):
        """Should process multiple buildings correctly."""
        for addr in ["22_Lippincott_St", "100_Spadina_Ave", "10_Nassau_St"]:
            param_file = tmp_path / f"{addr}.json"
            params = {
                "building_name": addr.replace("_", " "),
                "site": {"setback_m": 2.0},
                "foundation_height_m": 0.36,
                "_meta": {},
            }
            param_file.write_text(json.dumps(params), encoding="utf-8")

        result = process_params(tmp_path, apply=False, dry_run=True)
        assert result["processed"] == 3
        assert result["consolidated"] == 3

    def test_process_stamps_metadata(self, tmp_path):
        """Should add timestamp to _meta."""
        param_file = tmp_path / "22_Lippincott_St.json"
        params = {
            "building_name": "22 Lippincott St",
            "site": {"setback_m": 2.0},
            "_meta": {},
        }
        param_file.write_text(json.dumps(params), encoding="utf-8")

        result = process_params(tmp_path, apply=True, dry_run=False)

        updated = json.loads(param_file.read_text(encoding="utf-8"))
        assert "depth_notes_consolidated" in updated["_meta"]

    def test_process_handles_nested_depth_notes(self, tmp_path):
        """Should handle existing nested depth_notes structure."""
        param_file = tmp_path / "22_Lippincott_St.json"
        params = {
            "building_name": "22 Lippincott St",
            "site": {},
            "deep_facade_analysis": {
                "depth_notes": {
                    "foundation_height_m_est": 0.5,
                }
            },
            "_meta": {},
        }
        param_file.write_text(json.dumps(params), encoding="utf-8")

        result = process_params(tmp_path, apply=False, dry_run=True)
        assert result["processed"] == 1
        # foundation_height_m_est shouldn't be added since it exists
        assert result["foundation_height_m_est_added"] == 0

    def test_process_invalid_deep_facade_structure(self, tmp_path):
        """Should handle invalid deep_facade_analysis structure."""
        param_file = tmp_path / "22_Lippincott_St.json"
        params = {
            "building_name": "22 Lippincott St",
            "site": {"setback_m": 2.0},
            "deep_facade_analysis": "not a dict",
            "_meta": {},
        }
        param_file.write_text(json.dumps(params), encoding="utf-8")

        result = process_params(tmp_path, apply=False, dry_run=True)
        assert result["processed"] == 1
        assert result["consolidated"] == 1
