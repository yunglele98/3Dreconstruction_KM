#!/usr/bin/env python3
"""Render quality analysis for building renders.

Comprehensive quality scoring for rendered building images including
resolution, dynamic range, color diversity, edge sharpness, symmetry,
and artifact detection.

Usage:
    python scripts/analyze/render_quality.py
    python scripts/analyze/render_quality.py --renders outputs/buildings_renders_v1/ --output outputs/render_quality/
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PIL import Image

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_RENDERS_DIR = REPO_ROOT / "outputs" / "buildings_renders_v1"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "outputs" / "render_quality"

MIN_WIDTH = 1920
MIN_HEIGHT = 1080

# Weights for overall quality score (sum to 1.0)
WEIGHTS = {
    "resolution": 0.10,
    "dynamic_range": 0.15,
    "color_diversity": 0.15,
    "edge_sharpness": 0.20,
    "sky_ratio": 0.10,
    "symmetry": 0.10,
    "artifact_free": 0.20,
}


def _luminance(rgb: np.ndarray) -> np.ndarray:
    """Convert RGB array (H, W, 3) to luminance (H, W) using Rec. 709."""
    return 0.2126 * rgb[:, :, 0] + 0.7152 * rgb[:, :, 1] + 0.0722 * rgb[:, :, 2]


def check_resolution(width: int, height: int) -> dict:
    """Check if render meets minimum resolution requirements."""
    meets_min = width >= MIN_WIDTH and height >= MIN_HEIGHT
    # Score: 1.0 if meets minimum, scaled down proportionally otherwise
    ratio = min(width / MIN_WIDTH, height / MIN_HEIGHT, 1.0)
    return {
        "width": width,
        "height": height,
        "meets_minimum": meets_min,
        "score": round(ratio, 3),
    }


def check_dynamic_range(lum: np.ndarray) -> dict:
    """Compute luminance statistics and flag flat renders."""
    lum_min = float(np.min(lum))
    lum_max = float(np.max(lum))
    lum_std = float(np.std(lum))
    lum_mean = float(np.mean(lum))
    # A good render has std > 30 on 0-255 scale
    # Score based on standard deviation (0-80 mapped to 0-1)
    score = min(lum_std / 80.0, 1.0)
    flat = lum_std < 15.0
    return {
        "luminance_min": round(lum_min, 2),
        "luminance_max": round(lum_max, 2),
        "luminance_mean": round(lum_mean, 2),
        "luminance_std": round(lum_std, 2),
        "is_flat": flat,
        "score": round(score, 3),
    }


def check_color_diversity(rgb: np.ndarray, n_clusters: int = 32) -> dict:
    """Count unique color clusters via quantization.

    Downsamples the image and quantizes to a grid, then counts distinct
    clusters.  >10 clusters = good variety.
    """
    # Subsample for speed: take every 4th pixel
    sub = rgb[::4, ::4, :].reshape(-1, 3)
    # Quantize to bins of 32 levels (8 bins per channel)
    quantized = (sub // 32).astype(np.uint8)
    # Pack into single int for unique counting
    packed = quantized[:, 0].astype(np.uint32) * 10000 + quantized[:, 1].astype(np.uint32) * 100 + quantized[:, 2].astype(np.uint32)
    unique_clusters = int(len(np.unique(packed)))
    # Score: 10+ clusters is good (1.0), fewer scales down
    score = min(unique_clusters / 10.0, 1.0)
    return {
        "unique_clusters": unique_clusters,
        "good_variety": unique_clusters >= 10,
        "score": round(score, 3),
    }


def check_edge_sharpness(lum: np.ndarray) -> dict:
    """Average Sobel gradient magnitude as sharpness proxy."""
    # Sobel-like gradient using numpy (avoid scipy dependency)
    # Horizontal gradient
    gx = np.zeros_like(lum)
    gx[:, 1:-1] = lum[:, 2:] - lum[:, :-2]
    # Vertical gradient
    gy = np.zeros_like(lum)
    gy[1:-1, :] = lum[2:, :] - lum[:-2, :]
    magnitude = np.sqrt(gx ** 2 + gy ** 2)
    avg_mag = float(np.mean(magnitude))
    # Score: avg gradient of 15+ on 0-255 scale is sharp detail
    score = min(avg_mag / 15.0, 1.0)
    return {
        "avg_gradient_magnitude": round(avg_mag, 3),
        "score": round(score, 3),
    }


def check_sky_ratio(rgb: np.ndarray) -> dict:
    """Estimate sky/background ratio from upper region brightness and uniformity."""
    h = rgb.shape[0]
    upper_third = rgb[: h // 3, :, :]
    # Sky pixels: bright (mean > 200) or very uniform (std < 10 per pixel)
    pixel_mean = np.mean(upper_third, axis=2)
    pixel_std = np.std(upper_third.astype(float), axis=2)
    sky_mask = (pixel_mean > 200) | (pixel_std < 10)
    sky_ratio = float(np.sum(sky_mask)) / sky_mask.size
    total_ratio = sky_ratio * (1 / 3)  # fraction of total image
    # Score: penalize if sky > 50% of image (too much empty space)
    if total_ratio > 0.5:
        score = max(0.0, 1.0 - (total_ratio - 0.5) * 2)
    elif total_ratio < 0.05:
        score = 0.8  # very little sky is fine but slightly unusual
    else:
        score = 1.0
    return {
        "upper_third_sky_pct": round(sky_ratio * 100, 1),
        "total_sky_pct": round(total_ratio * 100, 1),
        "score": round(score, 3),
    }


def check_symmetry(rgb: np.ndarray) -> dict:
    """Compare left half vs right half for facade symmetry."""
    h, w = rgb.shape[:2]
    mid = w // 2
    left = rgb[:, :mid, :].astype(float)
    right = np.flip(rgb[:, w - mid :, :], axis=1).astype(float)
    # Truncate to same size
    min_w = min(left.shape[1], right.shape[1])
    left = left[:, :min_w, :]
    right = right[:, :min_w, :]
    # Mean absolute difference normalized to 0-255
    diff = np.mean(np.abs(left - right))
    # Perfect symmetry = 0 diff, score inversely proportional
    # diff of 30 or less is reasonably symmetric
    score = max(0.0, 1.0 - diff / 60.0)
    return {
        "mean_lr_difference": round(float(diff), 2),
        "score": round(score, 3),
    }


def check_artifacts(rgb: np.ndarray) -> dict:
    """Detect large uniform patches that may indicate flat/missing geometry."""
    h, w = rgb.shape[:2]
    total_pixels = h * w
    # Divide image into 16x16 blocks, check uniformity of each
    block_h, block_w = 16, 16
    uniform_pixels = 0
    blocks_checked = 0
    for y in range(0, h - block_h, block_h):
        for x in range(0, w - block_w, block_w):
            block = rgb[y : y + block_h, x : x + block_w, :]
            block_std = np.std(block.astype(float))
            if block_std < 3.0:  # nearly uniform block
                uniform_pixels += block_h * block_w
            blocks_checked += 1
    uniform_ratio = uniform_pixels / total_pixels if total_pixels > 0 else 0.0
    has_artifact = uniform_ratio > 0.20
    # Score: 1.0 if uniform < 10%, drops to 0 at 40%
    score = max(0.0, min(1.0, 1.0 - (uniform_ratio - 0.10) / 0.30)) if uniform_ratio > 0.10 else 1.0
    return {
        "uniform_patch_pct": round(uniform_ratio * 100, 1),
        "has_potential_artifact": has_artifact,
        "blocks_checked": blocks_checked,
        "score": round(score, 3),
    }


def compute_overall_score(metrics: dict) -> float:
    """Weighted combination of individual metric scores."""
    total = 0.0
    for key, weight in WEIGHTS.items():
        sub = metrics.get(key, {})
        total += sub.get("score", 0.0) * weight
    return round(total, 3)


def classify_tier(score: float) -> str:
    """Classify render into quality tier."""
    if score >= 0.85:
        return "excellent"
    elif score >= 0.70:
        return "good"
    elif score >= 0.50:
        return "acceptable"
    elif score >= 0.30:
        return "poor"
    return "critical"


def analyze_render(image_path: Path) -> dict:
    """Run all quality checks on a single render image."""
    img = Image.open(image_path).convert("RGB")
    rgb = np.array(img, dtype=np.uint8)
    lum = _luminance(rgb.astype(float))

    metrics = {
        "file": image_path.name,
        "resolution": check_resolution(img.width, img.height),
        "dynamic_range": check_dynamic_range(lum),
        "color_diversity": check_color_diversity(rgb),
        "edge_sharpness": check_edge_sharpness(lum),
        "sky_ratio": check_sky_ratio(rgb),
        "symmetry": check_symmetry(rgb),
        "artifact_free": check_artifacts(rgb),
    }
    metrics["overall_score"] = compute_overall_score(metrics)
    metrics["tier"] = classify_tier(metrics["overall_score"])
    return metrics


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Render quality analysis for building images"
    )
    parser.add_argument(
        "--renders",
        type=Path,
        default=DEFAULT_RENDERS_DIR,
        help="Directory containing rendered .png images",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Output directory for quality report",
    )
    args = parser.parse_args()

    renders_dir: Path = args.renders
    output_dir: Path = args.output

    if not renders_dir.is_dir():
        print(f"Renders directory not found: {renders_dir}")
        return

    output_dir.mkdir(parents=True, exist_ok=True)

    png_files = sorted(renders_dir.glob("*.png"))
    if not png_files:
        print(f"No .png files found in {renders_dir}")
        return

    print(f"Analyzing {len(png_files)} render images ...")
    results = []
    for i, png in enumerate(png_files, 1):
        try:
            metrics = analyze_render(png)
            results.append(metrics)
            tier_tag = metrics["tier"].upper()
            print(f"  [{i}/{len(png_files)}] {png.name}: {metrics['overall_score']:.3f} ({tier_tag})")
        except Exception as exc:
            print(f"  [{i}/{len(png_files)}] {png.name}: ERROR - {exc}")
            results.append({"file": png.name, "error": str(exc)})

    # Sort by overall score descending
    results.sort(key=lambda r: r.get("overall_score", 0), reverse=True)

    # Tier distribution
    tier_counts: dict[str, int] = {}
    scores = []
    for r in results:
        tier = r.get("tier", "error")
        tier_counts[tier] = tier_counts.get(tier, 0) + 1
        if "overall_score" in r:
            scores.append(r["overall_score"])

    report = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "renders_dir": str(renders_dir),
        "total_renders": len(results),
        "avg_quality_score": round(float(np.mean(scores)), 3) if scores else 0.0,
        "min_quality_score": round(float(np.min(scores)), 3) if scores else 0.0,
        "max_quality_score": round(float(np.max(scores)), 3) if scores else 0.0,
        "tier_distribution": tier_counts,
        "renders": results,
    }

    report_path = output_dir / "render_quality_report.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nReport written to {report_path}")
    print(f"  Total: {len(results)}, Avg score: {report['avg_quality_score']}")
    for tier, count in sorted(tier_counts.items()):
        print(f"  {tier}: {count}")


if __name__ == "__main__":
    main()
