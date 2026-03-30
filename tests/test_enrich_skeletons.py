import json
import pytest
import shutil
from pathlib import Path

# Adjust the import path to make enrich_skeletons accessible
import sys
sys.path.append(str(Path(__file__).parent.parent / "scripts"))
from enrich_skeletons import enrich_file

# Define a temporary directory for test parameter files
@pytest.fixture
def temp_params_dir(tmp_path):
    temp_dir = tmp_path / "params"
    temp_dir.mkdir()
    return temp_dir

def create_test_param_file(temp_dir, filename, content):
    filepath = temp_dir / filename
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(content, f, indent=2)
    return filepath

def test_enrich_simple_skeleton(temp_params_dir):
    # Test case: a very minimal skeleton file, expect many defaults to be filled
    initial_content = {
        "building_name": "Minimal Skeleton",
        "hcd_data": {
            "typology": "House-form, Semi-detached",
            "construction_date": "Pre-1889"
        },
        "_meta": {}
    }
    filepath = create_test_param_file(temp_params_dir, "minimal_skeleton.json", initial_content)

    changed, msg = enrich_file(filepath)
    assert changed is True
    assert "party_walls" in msg # Expect party walls to be inferred

    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)
    assert data["party_wall_left"] is True
    assert data["party_wall_right"] is False  # For semi-detached
    assert data["_meta"]["enriched"] is True
    assert "party_walls" in data["_meta"]["enrichments_applied"]

def test_enrich_only_missing_fields(temp_params_dir):
    # Test case: a file with some fields already present, ensure they are not overwritten
    initial_content = {
        "building_name": "Partial Skeleton",
        "hcd_data": {
            "typology": "House-form, Detached",
            "construction_date": "1890-1903"
        },
        "floors": 3, # This should NOT be overwritten by template (2.5)
        "facade_width_m": 7.0, # This should NOT be overwritten by template (6.0)
        "party_wall_left": False, # This should NOT be overwritten by template (False)
        "roof_type": "Mansard", # This should NOT be overwritten
        "_meta": {}
    }
    filepath = create_test_param_file(temp_params_dir, "partial_skeleton.json", initial_content)

    changed, msg = enrich_file(filepath)
    assert changed is True # Should still make some enrichments

    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)
    assert data["floors"] == 3 # Should remain as original
    assert data["facade_width_m"] == 7.0 # Should remain as original
    assert data["roof_type"] == "Mansard" # Should remain as original
    assert data["party_wall_left"] is False # Should remain as original
    assert "party_wall_right" in data # Should be enriched
    assert data["party_wall_right"] is False # For detached
    assert data["_meta"]["enriched"] is True
    assert "party_walls" in data["_meta"]["enrichments_applied"] # party_wall_right should be inferred

def test_idempotency(temp_params_dir):
    # Test case: run enrichment twice, second run should not change
    initial_content = {
        "building_name": "Idempotent Test",
        "hcd_data": {
            "typology": "House-form, Detached",
            "construction_date": "Pre-1889"
        },
        "floors": 2.5,
        "facade_width_m": 6.0,
        "roof_type": "Cross-gable",
        "facade_material": "Red brick",
        "windows_per_floor": [2, 2, 1],
        "party_wall_left": False,
        "party_wall_right": False,
        "_meta": {"enriched": True} # Already enriched
    }
    filepath = create_test_param_file(temp_params_dir, "idempotent.json", initial_content)

    # First run on an already enriched file
    changed, msg = enrich_file(filepath)
    assert changed is False
    assert "already enriched" in msg

    # Run on a file that needs enrichment, then run again
    initial_content_needs_enrich = {
        "building_name": "Needs Enrich",
        "hcd_data": {
            "typology": "House-form, Detached",
            "construction_date": "Pre-1889"
        },
        "_meta": {}
    }
    filepath_needs_enrich = create_test_param_file(temp_params_dir, "test_needs_enrich.json", initial_content_needs_enrich)

    changed_1, msg_1 = enrich_file(filepath_needs_enrich)
    assert changed_1 is True
    assert "party_walls" in msg_1 # Check for a known enrichment

    with open(filepath_needs_enrich, 'r', encoding='utf-8') as f:
        state_after_first_run = json.load(f)

    changed_2, msg_2 = enrich_file(filepath_needs_enrich)
    assert changed_2 is False
    assert "already enriched" in msg_2

    with open(filepath_needs_enrich, 'r', encoding='utf-8') as f:
        state_after_second_run = json.load(f)
    assert state_after_first_run == state_after_second_run

def test_skipped_file(temp_params_dir):
    # Test case: file explicitly marked as skipped
    initial_content = {
        "building_name": "Skipped Building",
        "skipped": True,
        "hcd_data": {
            "typology": "House-form, Detached",
            "construction_date": "Pre-1889"
        },
        "_meta": {}
    }
    filepath = create_test_param_file(temp_params_dir, "skipped_skeleton.json", initial_content)

    changed, msg = enrich_file(filepath)
    assert changed is False
    assert "non-building (skipped)" in msg

    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)
    assert "floors" not in data # Should remain un-enriched
