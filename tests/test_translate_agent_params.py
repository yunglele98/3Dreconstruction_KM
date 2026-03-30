import json
import pytest
import shutil
from pathlib import Path

# Adjust the import path to make translate_agent_params accessible
# Assuming the test is run from blender_buildings/tests
import sys
sys.path.append(str(Path(__file__).parent.parent / "scripts"))
from translate_agent_params import translate_file

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

def test_translate_cornice_string_to_dict(temp_params_dir):
    # Test case: flat cornice string to structured dict
    initial_content = {
        "building_name": "Test Building 1",
        "cornice": "decorative",
        "_meta": {}
    }
    filepath = create_test_param_file(temp_params_dir, "test_building_1.json", initial_content)

    # Run translation
    changed, msg = translate_file(filepath)
    assert changed is True
    assert "cornice" in msg

    # Verify content
    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)
    assert isinstance(data["cornice"], dict)
    assert data["cornice"]["type"] == "decorative"
    assert data["cornice"]["present"] is True
    assert data["_meta"]["translated"] is True
    assert "cornice" in data["_meta"]["translations_applied"]

def test_translate_bay_windows_int_to_dict(temp_params_dir):
    # Test case: int bay_windows count to structured dict
    initial_content = {
        "building_name": "Test Building 2",
        "bay_windows": 1,
        "facade_width_m": 5.0,
        "floors": 3,
        "_meta": {}
    }
    filepath = create_test_param_file(temp_params_dir, "test_building_2.json", initial_content)

    # Run translation
    changed, msg = translate_file(filepath)
    assert changed is True
    assert "bay_window" in msg

    # Verify content
    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)
    assert isinstance(data["bay_window"], dict)
    assert data["bay_window"]["count"] == 1
    assert data["bay_window"]["type"] == "Three-sided projecting bay"
    assert data["bay_window"]["floors"] == [0, 1] # Defaults to first two floors if more
    assert data["_meta"]["translated"] is True
    assert "bay_window" in data["_meta"]["translations_applied"]

def test_idempotency(temp_params_dir):
    # Test case: run translation twice, second run should not change
    initial_content = {
        "building_name": "Test Building 3",
        "cornice": "simple",
        "bay_windows": 1,
        "facade_width_m": 5.0,
        "floors": 2,
        "_meta": {}
    }
    filepath = create_test_param_file(temp_params_dir, "test_building_3.json", initial_content)

    # First run
    changed_1, msg_1 = translate_file(filepath)
    assert changed_1 is True

    # Capture state after first run
    with open(filepath, 'r', encoding='utf-8') as f:
        state_after_first_run = json.load(f)

    # Second run
    changed_2, msg_2 = translate_file(filepath)
    assert changed_2 is False # Should not change on second run
    assert "already translated" in msg_2

    # Verify content remains the same
    with open(filepath, 'r', encoding='utf-8') as f:
        state_after_second_run = json.load(f)
    assert state_after_first_run == state_after_second_run

def test_skipped_file(temp_params_dir):
    # Test case: file explicitly marked as skipped
    initial_content = {
        "building_name": "Skipped Building",
        "skipped": True,
        "cornice": "simple",
        "_meta": {}
    }
    filepath = create_test_param_file(temp_params_dir, "skipped_building.json", initial_content)

    changed, msg = translate_file(filepath)
    assert changed is False
    assert "non-building (skipped)" in msg

    # Verify no changes were made
    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)
    assert data.get("cornice") == "simple" # Still untranslated
    assert data["_meta"] == {} # No _meta.translated added

def test_already_translated_file(temp_params_dir):
    # Test case: file already marked as translated
    initial_content = {
        "building_name": "Already Translated",
        "cornice": {"present": True, "type": "simple"}, # Already structured
        "_meta": {"translated": True, "translations_applied": ["cornice"]}
    }
    filepath = create_test_param_file(temp_params_dir, "already_translated.json", initial_content)

    changed, msg = translate_file(filepath)
    assert changed is False
    assert "already translated" in msg

    # Verify no changes were made
    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)
    assert data["_meta"]["translated"] is True # Still true, not re-added
