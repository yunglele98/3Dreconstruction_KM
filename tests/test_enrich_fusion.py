"""Tests for scripts/enrich/ fusion scripts."""

import json
import sys
from pathlib import Path

import numpy as np
import pytest

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts" / "enrich"))

from fuse_depth import analyze_depth_map
from fuse_segmentation import analyze_segmentation


# ── fuse_depth ───────────────────────────────────────────────────────

def test_analyze_depth_map(tmp_path):
    """Depth analysis returns expected keys."""
    depth = np.random.rand(100, 80).astype(np.float32)
    npy_path = tmp_path / "test.npy"
    np.save(npy_path, depth)
    result = analyze_depth_map(npy_path)
    assert "setback_m_est" in result
    assert "foundation_height_m_est" in result
    assert "eave_overhang_mm_est" in result
    assert isinstance(result["setback_m_est"], float)
    assert result["eave_overhang_mm_est"] >= 150


# ── fuse_segmentation ───────────────────────────────────────────────

def test_analyze_segmentation(tmp_path):
    """Segmentation analysis extracts element counts."""
    seg = {
        "elements": [
            {"class": "window", "bbox": [10, 50, 50, 100], "confidence": 0.9},
            {"class": "window", "bbox": [60, 50, 100, 100], "confidence": 0.85},
            {"class": "door", "bbox": [30, 200, 70, 300], "confidence": 0.8},
            {"class": "storefront", "bbox": [0, 250, 200, 350], "confidence": 0.7},
        ],
        "height": 400,
        "width": 200,
    }
    seg_path = tmp_path / "test_segments.json"
    seg_path.write_text(json.dumps(seg), encoding="utf-8")
    result = analyze_segmentation(seg_path)
    assert result["element_counts"]["window"] == 2
    assert result["element_counts"]["door"] == 1
    assert result["has_storefront"] is True
    assert result["door_count"] == 1
    assert result["total_elements"] == 4


def test_analyze_segmentation_empty(tmp_path):
    seg = {"elements": [], "height": 100, "width": 100}
    seg_path = tmp_path / "empty_segments.json"
    seg_path.write_text(json.dumps(seg), encoding="utf-8")
    result = analyze_segmentation(seg_path)
    assert result["total_elements"] == 0
    assert result["has_storefront"] is False
