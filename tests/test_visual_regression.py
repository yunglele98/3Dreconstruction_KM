"""Tests for scripts/verify/visual_regression.py."""

import sys
from pathlib import Path

import numpy as np
import pytest

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts" / "verify"))

from visual_regression import compute_ssim, compute_perceptual_hash, hamming_distance


def test_ssim_identical():
    img = np.random.randint(0, 255, (100, 100, 3), dtype=np.uint8)
    score = compute_ssim(img, img)
    assert score > 0.99


def test_ssim_different():
    img_a = np.zeros((100, 100, 3), dtype=np.uint8)
    img_b = np.full((100, 100, 3), 255, dtype=np.uint8)
    score = compute_ssim(img_a, img_b)
    assert score < 0.1


def test_ssim_different_sizes():
    img_a = np.random.randint(0, 255, (100, 100, 3), dtype=np.uint8)
    img_b = np.random.randint(0, 255, (120, 110, 3), dtype=np.uint8)
    score = compute_ssim(img_a, img_b)
    assert -1 <= score <= 1  # SSIM range is [-1, 1]


def test_perceptual_hash_length():
    img = np.random.randint(0, 255, (64, 64, 3), dtype=np.uint8)
    h = compute_perceptual_hash(img)
    assert len(h) == 64  # 8x8 hash


def test_perceptual_hash_identical():
    img = np.random.randint(0, 255, (64, 64, 3), dtype=np.uint8)
    h1 = compute_perceptual_hash(img)
    h2 = compute_perceptual_hash(img)
    assert h1 == h2


def test_hamming_distance():
    assert hamming_distance("0000", "0000") == 0
    assert hamming_distance("0000", "1111") == 4
    assert hamming_distance("1010", "1001") == 2
