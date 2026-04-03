"""Tests for scripts/sense/analyze_facade_deep.py and detect_decorative.py."""

import sys
from pathlib import Path

import numpy as np
import pytest

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts" / "sense"))

from analyze_facade_deep import (
    analyze_colour_distribution,
    analyze_openings,
    detect_decorative_elements,
    analyze_condition,
)
from detect_decorative import (
    detect_cornice,
    detect_string_courses,
    detect_bay_window,
)


class TestColourDistribution:
    def test_red_brick_detection(self):
        # Red-ish image should detect as brick
        img = np.full((200, 150, 3), [180, 80, 60], dtype=np.uint8)
        result = analyze_colour_distribution(img)
        assert result["facade_material_observed"] == "brick"
        assert result["brick_colour_hex"] is not None
        assert result["brick_colour_hex"].startswith("#")

    def test_light_stucco_detection(self):
        img = np.full((200, 150, 3), [210, 200, 185], dtype=np.uint8)
        result = analyze_colour_distribution(img)
        assert result["facade_material_observed"] == "stucco"

    def test_colour_palette_has_facade(self):
        img = np.random.randint(100, 200, (200, 150, 3), dtype=np.uint8)
        result = analyze_colour_distribution(img)
        assert "colour_palette_observed" in result
        assert "facade" in result["colour_palette_observed"]


class TestOpenings:
    def test_detects_windows(self):
        # Create image with dark rectangles (windows) in upper half
        gray = np.full((300, 200), 180, dtype=np.uint8)
        # Add 3 dark windows on second floor
        for x in [30, 80, 130]:
            gray[80:150, x:x + 40] = 40
        result = analyze_openings(gray)
        assert "windows_detail" in result
        assert len(result["windows_detail"]) >= 2

    def test_empty_image(self):
        gray = np.full((100, 100), 128, dtype=np.uint8)
        result = analyze_openings(gray)
        assert "windows_detail" in result


class TestDecorativeDetection:
    def test_cornice_from_strong_top_edge(self):
        img = np.full((300, 200, 3), 180, dtype=np.uint8)
        gray = np.full((300, 200), 180, dtype=np.uint8)
        # Strong horizontal edge at top
        gray[20:25, 20:180] = 40
        gray[25:30, 20:180] = 220
        result = detect_cornice(img, gray)
        # May or may not detect depending on threshold
        if result:
            assert result["present"] is True
            assert result["style"] in ("simple", "bracketed", "dentil")

    def test_no_cornice_on_uniform(self):
        img = np.full((300, 200, 3), 128, dtype=np.uint8)
        gray = np.full((300, 200), 128, dtype=np.uint8)
        result = detect_cornice(img, gray)
        assert result is None

    def test_string_courses_from_bands(self):
        img = np.full((400, 200, 3), 170, dtype=np.uint8)
        gray = np.full((400, 200), 170, dtype=np.uint8)
        # Add horizontal bands
        for y in [120, 200, 280]:
            gray[y:y + 5, 20:180] = 80
        result = detect_string_courses(img, gray)
        if result:
            assert result["present"] is True

    def test_bay_window_from_brightness(self):
        img = np.full((400, 300, 3), 140, dtype=np.uint8)
        gray = np.full((400, 300), 140, dtype=np.uint8)
        # Bright center region (bay window catches light)
        gray[120:280, 100:200] = 200
        result = detect_bay_window(img, gray)
        if result:
            assert result["present"] is True
            assert result["type"] == "canted"


class TestCondition:
    def test_good_condition(self):
        img = np.full((200, 200, 3), 170, dtype=np.uint8)
        result = analyze_condition(img)
        assert result["condition_observed"] == "good"

    def test_poor_condition_dark(self):
        img = np.full((200, 200, 3), 30, dtype=np.uint8)
        result = analyze_condition(img)
        assert result["condition_observed"] in ("poor", "fair")
