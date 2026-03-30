#!/usr/bin/env python3
"""Compute SSIM for two images."""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
from PIL import Image


def load_gray(path: Path) -> np.ndarray:
    img = Image.open(path).convert("L")
    return np.asarray(img, dtype=np.float64)


def compute_ssim(a: np.ndarray, b: np.ndarray) -> float:
    if a.shape != b.shape:
        raise ValueError(f"Image shape mismatch: {a.shape} vs {b.shape}")
    c1 = (0.01 * 255) ** 2
    c2 = (0.03 * 255) ** 2
    mu_a = a.mean()
    mu_b = b.mean()
    var_a = ((a - mu_a) ** 2).mean()
    var_b = ((b - mu_b) ** 2).mean()
    cov = ((a - mu_a) * (b - mu_b)).mean()
    num = (2 * mu_a * mu_b + c1) * (2 * cov + c2)
    den = (mu_a**2 + mu_b**2 + c1) * (var_a + var_b + c2)
    if den == 0:
        return 1.0
    return float(num / den)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare two images with SSIM.")
    parser.add_argument("reference")
    parser.add_argument("candidate")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    a = load_gray(Path(args.reference))
    b = load_gray(Path(args.candidate))
    score = compute_ssim(a, b)
    print(f"SSIM: {score:.6f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
