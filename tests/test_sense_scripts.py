"""Tests for scripts/sense/ pipeline scripts."""

import json
import sys
from pathlib import Path

import numpy as np
import pytest

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts" / "sense"))
sys.path.insert(0, str(REPO_ROOT / "scripts" / "enrich"))

from extract_depth import estimate_depth_fallback, save_depth_viz
from segment_facades import segment_facade_fallback
from fuse_signage import extract_business_info


# ── extract_depth ────────────────────────────────────────────────────

def test_depth_fallback_shape(tmp_path):
    """Fallback depth produces correct shape."""
    from PIL import Image
    img = Image.new("RGB", (100, 80), color=(128, 128, 128))
    img_path = tmp_path / "test.jpg"
    img.save(img_path)
    depth = estimate_depth_fallback(img_path)
    assert depth.shape == (80, 100)
    assert depth.dtype == np.float32
    assert depth.min() >= 0.0
    assert depth.max() <= 1.0


def test_depth_viz_saves_png(tmp_path):
    depth = np.random.rand(50, 50).astype(np.float32)
    out = tmp_path / "viz.png"
    save_depth_viz(depth, out)
    assert out.exists()
    assert out.stat().st_size > 0


# ── segment_facades ──────────────────────────────────────────────────

def test_segment_fallback_returns_elements(tmp_path):
    from PIL import Image
    img = Image.new("RGB", (200, 300), color=(180, 120, 90))
    img_path = tmp_path / "facade.jpg"
    img.save(img_path)
    result = segment_facade_fallback(img_path)
    assert "elements" in result
    assert len(result["elements"]) >= 2
    assert result["width"] == 200
    assert result["height"] == 300
    for elem in result["elements"]:
        assert "class" in elem
        assert "bbox" in elem


# ── extract_signage ──────────────────────────────────────────────────

def test_extract_business_info_filters():
    detections = [
        {"text": "KENSINGTON MARKET BAKERY", "confidence": 0.95},
        {"text": "OPEN", "confidence": 0.9},
        {"text": "42", "confidence": 0.99},  # pure numeric, skip
        {"text": "Hi", "confidence": 0.8},   # too short, skip
    ]
    info = extract_business_info(detections)
    assert info["business_name"] == "KENSINGTON MARKET BAKERY"
    assert "42" not in info["signage_texts"]


def test_extract_business_info_empty():
    assert extract_business_info([]) == {}


def test_extract_business_info_low_confidence():
    detections = [{"text": "Faint Sign", "confidence": 0.3}]
    assert extract_business_info(detections) == {}
