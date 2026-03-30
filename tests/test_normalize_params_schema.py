import json
import pytest
import shutil
from pathlib import Path

# Adjust the import path to make normalize_params_schema accessible
import sys
sys.path.append(str(Path(__file__).parent.parent / "scripts"))
from normalize_params_schema import normalize_file

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

def test_normalize_boolean_decorative_elements(temp_params_dir):
    # Test case: boolean decorative element to structured dict
    initial_content = {
        "building_name": "Boolean Test",
        "decorative_elements": {
            "bargeboard": True,
            "string_courses": False,
            "cornice": "ornate" # Should be converted to dict
        },
        "_meta": {}
    }
    filepath = create_test_param_file(temp_params_dir, "test_boolean.json", initial_content)

    changed, msg = normalize_file(filepath)
    assert changed is True
    assert "bargeboard" in msg
    assert "string_courses" in msg
    assert "cornice" in msg

    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)
    assert isinstance(data["decorative_elements"]["bargeboard"], dict)
    assert data["decorative_elements"]["bargeboard"]["present"] is True
    assert isinstance(data["decorative_elements"]["string_courses"], dict)
    assert data["decorative_elements"]["string_courses"]["present"] is False
    assert isinstance(data["decorative_elements"]["cornice"], dict)
    assert data["decorative_elements"]["cornice"]["type"] == "ornate"
    assert data["decorative_elements"]["cornice"]["present"] is True
    assert data["_meta"]["normalized"] is True

def test_normalize_bay_window_floors_spanned(temp_params_dir):
    # Test case: bay_window floors_spanned to floors list
    initial_content = {
        "building_name": "Bay Window Test",
        "bay_window": {
            "present": True,
            "floors_spanned": 2, # Should be converted to [0,1] or similar
            "floors": [0] # Pre-existing floors should be merged/updated
        },
        "floors": 3,
        "_meta": {}
    }
    filepath = create_test_param_file(temp_params_dir, "test_bay_window.json", initial_content)

    changed, msg = normalize_file(filepath)
    assert changed is True
    assert "bay_window_floors" in msg

    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)
    assert "floors_spanned" not in data["bay_window"]
    assert isinstance(data["bay_window"]["floors"], list)
    assert data["bay_window"]["floors"] == [0, 1] # Assuming default floors from 0 upwards
    assert data["_meta"]["normalized"] is True

def test_normalize_roof_features_string(temp_params_dir):
    # Test case: roof_features string to structured dict
    initial_content = {
        "building_name": "Roof Feature Test",
        "roof_features": "oculus",
        "_meta": {}
    }
    filepath = create_test_param_file(temp_params_dir, "test_roof_feature.json", initial_content)

    changed, msg = normalize_file(filepath)
    assert changed is True
    assert "roof_features" in msg

    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)
    assert isinstance(data["roof_features"], list)
    assert len(data["roof_features"]) == 1
    assert isinstance(data["roof_features"][0], dict)
    assert data["roof_features"][0]["type"] == "oculus_window"
    assert data["_meta"]["normalized"] is True

def test_move_top_level_cornice(temp_params_dir):
    # Test case: top-level cornice to decorative_elements
    initial_content = {
        "building_name": "Top Level Cornice Test",
        "cornice": {"present": True, "type": "simple"},
        "_meta": {}
    }
    filepath = create_test_param_file(temp_params_dir, "test_top_cornice.json", initial_content)

    changed, msg = normalize_file(filepath)
    assert changed is True
    assert "top_level_cornice" in msg

    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)
    assert "cornice" not in data # Should be moved
    assert "decorative_elements" in data
    assert isinstance(data["decorative_elements"]["cornice"], dict)
    assert data["decorative_elements"]["cornice"]["type"] == "simple"
    assert data["_meta"]["normalized"] is True

def test_idempotency(temp_params_dir):
    # Test case: run normalization twice, second run should not change
    initial_content = {
        "building_name": "Idempotent Test",
        "decorative_elements": {
            "bargeboard": {"present": True, "type": "simple"}
        },
        "_meta": {"normalized": True} # Already normalized
    }
    filepath = create_test_param_file(temp_params_dir, "test_idempotent.json", initial_content)

    # First run on an already normalized file
    changed, msg = normalize_file(filepath)
    assert changed is False
    assert "already normalized" in msg

    # Run on a file that needs normalization, then run again
    initial_content_needs_norm = {
        "building_name": "Needs Norm",
        "decorative_elements": {"bargeboard": True},
        "_meta": {}
    }
    filepath_needs_norm = create_test_param_file(temp_params_dir, "test_needs_norm.json", initial_content_needs_norm)

    changed_1, msg_1 = normalize_file(filepath_needs_norm)
    assert changed_1 is True
    assert "bargeboard" in msg_1

    with open(filepath_needs_norm, 'r', encoding='utf-8') as f:
        state_after_first_run = json.load(f)

    changed_2, msg_2 = normalize_file(filepath_needs_norm)
    assert changed_2 is False
    assert "already normalized" in msg_2

    with open(filepath_needs_norm, 'r', encoding='utf-8') as f:
        state_after_second_run = json.load(f)
    assert state_after_first_run == state_after_second_run

def test_skipped_file(temp_params_dir):
    # Test case: file explicitly marked as skipped
    initial_content = {
        "building_name": "Skipped Building",
        "skipped": True,
        "decorative_elements": {"bargeboard": True},
        "_meta": {}
    }
    filepath = create_test_param_file(temp_params_dir, "skipped_building.json", initial_content)

    changed, msg = normalize_file(filepath)
    assert changed is False
    assert "non-building (skipped)" in msg

    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)
    assert "bargeboard" in data["decorative_elements"] # Should remain un-normalized
    assert data["decorative_elements"]["bargeboard"] is True
