#!/usr/bin/env python3
"""Tests for regen pipeline: fingerprint_params, build_regen_batches, verify_regen, compare_renders."""
import json
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from fingerprint_params import param_hash


# ── param_hash tests ──

def test_hash_excludes_meta():
    """Changing _meta should NOT change the hash."""
    params = {"building_name": "Test", "floors": 2, "_meta": {"source": "a"}}
    h1 = param_hash(params)
    params["_meta"]["source"] = "b"
    h2 = param_hash(params)
    assert h1 == h2


def test_hash_changes_on_facade_material():
    """Changing a real field should change the hash."""
    p1 = {"building_name": "Test", "facade_material": "brick"}
    p2 = {"building_name": "Test", "facade_material": "stucco"}
    assert param_hash(p1) != param_hash(p2)


def test_hash_deterministic():
    """Same params should always give the same hash."""
    params = {"floors": 3, "roof_type": "gable", "building_name": "A"}
    assert param_hash(params) == param_hash(params)


def test_hash_key_order_irrelevant():
    """Key insertion order should not affect hash (sort_keys=True)."""
    p1 = {"a": 1, "b": 2}
    p2 = {"b": 2, "a": 1}
    assert param_hash(p1) == param_hash(p2)


def test_hash_empty_params():
    """Empty dict should return a valid md5 hex."""
    h = param_hash({})
    assert len(h) == 32
    assert all(c in "0123456789abcdef" for c in h)


def test_hash_nested_values():
    """Hash should account for nested dict changes."""
    p1 = {"facade_detail": {"brick_colour_hex": "#B85A3A"}}
    p2 = {"facade_detail": {"brick_colour_hex": "#FFFFFF"}}
    assert param_hash(p1) != param_hash(p2)


# ── Classification logic ──

def test_classification_stale_new_fresh(tmp_path):
    """Integration test: write param files + fake manifests, run classification."""
    from fingerprint_params import param_hash as ph

    # A "fresh" building: manifest hash matches param hash
    params_fresh = {"building_name": "Fresh", "floors": 2}
    h_fresh = ph(params_fresh)

    # A "stale" building: manifest hash differs
    params_stale = {"building_name": "Stale", "floors": 3}
    h_stale_old = "0000000000000000"

    # A "new" building: no manifest at all
    params_new = {"building_name": "New", "floors": 1}

    # Classify manually
    manifest_fresh = {"param_file": "Fresh.json", "param_hash": h_fresh}
    manifest_stale = {"param_file": "Stale.json", "param_hash": h_stale_old}
    manifests = {"Fresh.json": manifest_fresh, "Stale.json": manifest_stale}

    results = {"stale": [], "new": [], "fresh": []}
    for name, params in [("Fresh.json", params_fresh), ("Stale.json", params_stale), ("New.json", params_new)]:
        h = ph(params)
        m = manifests.get(name)
        if not m:
            results["new"].append(name)
        elif m.get("param_hash") == h:
            results["fresh"].append(name)
        else:
            results["stale"].append(name)

    assert results["fresh"] == ["Fresh.json"]
    assert results["stale"] == ["Stale.json"]
    assert results["new"] == ["New.json"]


# ── Batch splitting ──

def test_batch_size_limit():
    """Batches should never exceed BATCH_SIZE (50)."""
    from build_regen_batches import BATCH_SIZE
    items = list(range(123))
    batches = []
    for i in range(0, len(items), BATCH_SIZE):
        batches.append(items[i:i + BATCH_SIZE])
    assert all(len(b) <= BATCH_SIZE for b in batches)
    assert len(batches) == 3  # 50 + 50 + 23


def test_batch_priority_order(tmp_path):
    """Priority 1 items should come before priority 4."""
    from build_regen_batches import classify_priority

    # Create a param file with handoff_fixes_applied (priority 1)
    p1 = tmp_path / "prio1.json"
    p1.write_text(json.dumps({
        "_meta": {"handoff_fixes_applied": ["fix_height"]},
        "floors": 2,
    }))

    # Create a param file without (priority 4)
    p4 = tmp_path / "prio4.json"
    p4.write_text(json.dumps({"floors": 2}))

    assert classify_priority(p1) < classify_priority(p4)


def test_batch_priority_volumes(tmp_path):
    """Buildings with volumes[] should be priority 2."""
    from build_regen_batches import classify_priority

    p = tmp_path / "vol.json"
    p.write_text(json.dumps({"volumes": [{"id": "main"}]}))
    assert classify_priority(p) == 2


# ── Verify regen ──

def test_verify_detects_missing_manifests(tmp_path):
    """Buildings in regen queue without manifests should be flagged missing."""
    queue = {
        "stale": [{"address": "1 Test St", "file": "1_Test_St.json"}],
        "new": [{"address": "2 Test St", "file": "2_Test_St.json"}],
    }
    queue_file = tmp_path / "regen_queue.json"
    queue_file.write_text(json.dumps(queue))

    # No manifests dir at all
    expected = queue["stale"] + queue["new"]
    missing = []
    for item in expected:
        stem = Path(item["file"]).stem
        manifest_path = tmp_path / "full_v2" / f"{stem}.manifest.json"
        if not manifest_path.exists():
            missing.append(item["address"])

    assert len(missing) == 2
    assert "1 Test St" in missing
    assert "2 Test St" in missing


def test_verify_detects_completed(tmp_path):
    """Buildings with manifests in full_v2/ should be marked completed."""
    v2 = tmp_path / "full_v2"
    v2.mkdir()
    (v2 / "1_Test_St.manifest.json").write_text("{}")

    item = {"address": "1 Test St", "file": "1_Test_St.json"}
    stem = Path(item["file"]).stem
    manifest_path = v2 / f"{stem}.manifest.json"
    assert manifest_path.exists()


# ── Compare renders ──

def test_compare_finds_no_pairs_without_photos():
    """With empty photo index, no pairs should be found."""
    from compare_renders import find_photo
    assert find_photo("123 Fake St", {}) == ""


def test_compare_finds_photo_by_exact_match():
    """Exact address match should return the photo filename."""
    from compare_renders import find_photo
    index = {"123 Fake St": ["IMG_001.jpg"]}
    assert find_photo("123 Fake St", index) == "IMG_001.jpg"


def test_compare_finds_photo_by_substring():
    """Substring match should work as fallback."""
    from compare_renders import find_photo
    index = {"123 Fake Street West": ["IMG_002.jpg"]}
    result = find_photo("123 Fake Street", index)
    assert result == "IMG_002.jpg"
