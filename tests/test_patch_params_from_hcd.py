import json
import pytest
import shutil
from pathlib import Path

# Adjust the import path to make patch_params_from_hcd accessible
import sys
sys.path.append(str(Path(__file__).parent.parent / "scripts"))
from patch_params_from_hcd import patch_file # Assuming patch_file is the main entry

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

def test_patch_hcd_decorative_features(temp_params_dir):
    # Test case: a file that needs HCD decorative features merged
    initial_content = {
        "building_name": "HCD Patch Test",
        "hcd_data": {
            "typology": "Victorian",
            "building_features": ["Decorative brickwork", "Stone lintels"],
            "construction_date": "1890"
        },
        "decorative_elements": {}, # Empty, should be populated
        "_meta": {}
    }
    filepath = create_test_param_file(temp_params_dir, "test_hcd_patch.json", initial_content)

    changed, msg = patch_file(filepath)
    assert changed is True
    assert "decorative_elements" in msg

    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)
    assert "decorative_elements" in data
    assert "stone_lintels" in data["decorative_elements"]
    assert data["decorative_elements"]["stone_lintels"]["present"] is True

def test_idempotency(temp_params_dir):
    # Test case: run patch twice, second run should not change
    initial_content = {
        "building_name": "Idempotent HCD Test",
        "hcd_data": {
            "typology": "Victorian",
            "building_features": ["Stone lintels"],
            "construction_date": "1890"
        },
        "decorative_elements": {
            "stone_lintels": {"present": True}
        },
        "_meta": {"patched": True}  # Already patched
    }
    filepath = create_test_param_file(temp_params_dir, "test_idempotent_hcd.json", initial_content)

    # First run on an already patched file
    changed, msg = patch_file(filepath)
    assert changed is False
    assert "already patched" in msg

    # Run on a file that needs patching, then run again
    initial_content_needs_patch = {
        "building_name": "Needs Patch",
        "hcd_data": {
            "typology": "Victorian",
            "building_features": ["Stone lintels"],
            "construction_date": "1890"
        },
        "decorative_elements": {},
        "_meta": {}
    }
    filepath_needs_patch = create_test_param_file(temp_params_dir, "test_needs_patch.json", initial_content_needs_patch)

    changed_1, msg_1 = patch_file(filepath_needs_patch)
    assert changed_1 is True
    assert "decorative_elements" in msg_1

    with open(filepath_needs_patch, 'r', encoding='utf-8') as f:
        state_after_first_run = json.load(f)

    changed_2, msg_2 = patch_file(filepath_needs_patch)
    assert changed_2 is False
    assert "already patched" in msg_2

    with open(filepath_needs_patch, 'r', encoding='utf-8') as f:
        state_after_second_run = json.load(f)
    assert state_after_first_run == state_after_second_run

def test_skipped_file(temp_params_dir):
    # Test case: file explicitly marked as skipped
    initial_content = {
        "building_name": "Skipped Building",
        "skipped": True,
        "hcd_data": {
            "typology": "Victorian",
            "building_features": ["Decorative brickwork"],
        },
        "_meta": {}
    }
    filepath = create_test_param_file(temp_params_dir, "skipped_hcd.json", initial_content)

    changed, msg = patch_file(filepath)
    assert changed is False
    assert "non-building (skipped)" in msg

    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)
    assert "decorative_elements" not in data or not data["decorative_elements"] # Should remain unpatched


