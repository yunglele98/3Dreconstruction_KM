import json
import pytest
import shutil
from pathlib import Path

# Adjust the import path to make infer_missing_params accessible
import sys
sys.path.append(str(Path(__file__).parent.parent / "scripts"))
from infer_missing_params import infer_file

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

def test_infer_colour_palette(temp_params_dir):
    # Test case: infer missing colour_palette
    initial_content = {
        "building_name": "Colourful Building",
        "facade_material": "Red brick",
        "roof_material": "Grey asphalt shingles",
        "overall_style": "Victorian",
        "year_built_approx": "Pre-1889",
        "_meta": {}
    }
    filepath = create_test_param_file(temp_params_dir, "test_colour.json", initial_content)

    changed, msg = infer_file(filepath)
    assert changed is True
    assert "colour_palette" in msg

    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)
    assert "colour_palette" in data
    assert "facade_hex" in data["colour_palette"]
    assert data["_meta"]["gaps_filled"] is True
    assert "colour_palette" in data["_meta"]["inferences_applied"]

def test_infer_dormer_and_eave_overhang(temp_params_dir):
    # Test case: infer dormer and eave_overhang_mm
    initial_content = {
        "building_name": "Roof Building",
        "roof_type": "Cross-gable with dormer",
        "roof_features": ["dormer"],
        "_meta": {}
    }
    filepath = create_test_param_file(temp_params_dir, "test_roof.json", initial_content)

    changed, msg = infer_file(filepath)
    assert changed is True
    assert "dormer" in msg
    assert "eave_overhang" in msg # Corrected: msg reports "eave_overhang", not "eave_overhang_mm"

    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)
    assert "dormer" in data
    assert "eave_overhang_mm" in data
    assert data["_meta"]["gaps_filled"] is True
    assert "dormer" in data["_meta"]["inferences_applied"]
    assert "eave_overhang" in data["_meta"]["inferences_applied"] # Corrected: list contains "eave_overhang"

def test_infer_ground_floor_arches(temp_params_dir):
    # Test case: infer ground_floor_arches
    initial_content = {
        "building_name": "Arched Building",
        "window_type": "Round arch windows",
        "door_type": "Round arch door",
        "windows_per_floor": [2], # Added to provide more complete context
        "floors": 1, # Added
        "_meta": {}
    }
    filepath = create_test_param_file(temp_params_dir, "test_arches.json", initial_content)

    changed, msg = infer_file(filepath)
    assert changed is True
    assert "ground_floor_arches" in msg

    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)
    assert "ground_floor_arches" in data
    assert data["_meta"]["gaps_filled"] is True
    assert "ground_floor_arches" in data["_meta"]["inferences_applied"]

def test_infer_hcd_data_stub(temp_params_dir):
    # Test case: infer hcd_data stub
    initial_content = {
        "building_name": "HCD Stub Building",
        "overall_style": "Victorian",
        "_meta": {}
    }
    filepath = create_test_param_file(temp_params_dir, "test_hcd_stub.json", initial_content)

    changed, msg = infer_file(filepath)
    assert changed is True
    assert "hcd_data_stub" in msg # Corrected: msg reports "hcd_data_stub"

    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)
    assert "hcd_data" in data
    assert "typology" in data["hcd_data"]
    assert data["_meta"]["gaps_filled"] is True
    assert "hcd_data_stub" in data["_meta"]["inferences_applied"] # Corrected: list contains "hcd_data_stub"

def test_idempotency(temp_params_dir):
    # Test case: run inference twice, second run should not change
    initial_content = {
        "building_name": "Idempotent Building",
        "facade_material": "Red brick",
        "roof_material": "Grey asphalt shingles",
        "overall_style": "Victorian",
        "year_built_approx": "Pre-1889",
        "_meta": {}
    }
    filepath = create_test_param_file(temp_params_dir, "test_idempotent.json", initial_content)

    # First run
    changed_1, msg_1 = infer_file(filepath)
    assert changed_1 is True
    assert "colour_palette" in msg_1 # Ensure some change

    # Capture state after first run
    with open(filepath, 'r', encoding='utf-8') as f:
        state_after_first_run = json.load(f)

    # Second run
    changed_2, msg_2 = infer_file(filepath)
    assert changed_2 is False # Should not change on second run
    assert "already processed" in msg_2 # Corrected: message is "already processed"

    # Verify content remains the same
    with open(filepath, 'r', encoding='utf-8') as f:
        state_after_second_run = json.load(f)
    assert state_after_first_run == state_after_second_run

def test_skipped_file(temp_params_dir):
    # Test case: file explicitly marked as skipped
    initial_content = {
        "building_name": "Skipped Building",
        "skipped": True,
        "_meta": {}
    }
    filepath = create_test_param_file(temp_params_dir, "skipped_building.json", initial_content)

    changed, msg = infer_file(filepath)
    assert changed is False
    assert "non-building (skipped)" in msg

    # Verify no changes were made
    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)
    assert data.get("_meta", {}).get("gaps_filled") is None # Should not have been set

def test_already_gaps_filled_file(temp_params_dir):
    # Test case: file already marked as gaps_filled
    initial_content = {
        "building_name": "Already Gaps Filled",
        "colour_palette": {"facade_hex": "#ABCDEF"},
        "_meta": {"gaps_filled": True}
    }
    filepath = create_test_param_file(temp_params_dir, "already_filled.json", initial_content)

    changed, msg = infer_file(filepath)
    assert changed is False
    assert "already processed" in msg # Corrected: message is "already processed"

    # Verify no changes were made
    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)
    assert data["_meta"]["gaps_filled"] is True # Still true


# New standalone test for infer_ground_floor_arches
from infer_missing_params import infer_ground_floor_arches # Import the specific function

def test_infer_ground_floor_arches_standalone():
    data = {
        "building_name": "Arched Building Standalone",
        "window_type": "Round arch windows",
        "door_type": "Round arch door",
        "_meta": {}
    }
    
    changed = infer_ground_floor_arches(data)
    assert changed is True
    assert "ground_floor_arches" in data
    assert data["ground_floor_arches"]["arch_type"] == "round"
    assert data["ground_floor_arches"]["present"] is True

