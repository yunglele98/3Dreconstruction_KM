#!/usr/bin/env python3
"""Phase 0, Stage 2: Compute similarity metrics between render and photo.

For each paired render-photo, computes SSIM, colour histogram correlation,
LAB colour distance, edge similarity, aspect ratio difference, and rough
window count difference.

Usage:
    python scripts/visual_audit/compare_render_to_photo.py --pairs outputs/visual_audit/pairs.json
    python scripts/visual_audit/compare_render_to_photo.py --pairs outputs/visual_audit/pairs.json --limit 10
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import cv2
import numpy as np
from skimage.metrics import structural_similarity as ssim

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).parent.parent.parent
TARGET_HEIGHT = 512


def load_and_resize(path: str, target_height: int = TARGET_HEIGHT) -> np.ndarray | None:
    """Load image and resize to target height, preserving aspect ratio."""
    img = cv2.imread(path)
    if img is None:
        return None
    img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    h, w = img.shape[:2]
    if h == 0:
        return None
    scale = target_height / h
    new_w = int(w * scale)
    return cv2.resize(img, (new_w, target_height))


def make_same_size(a: np.ndarray, b: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Resize both images to the same dimensions (min of each axis)."""
    h = min(a.shape[0], b.shape[0])
    w = min(a.shape[1], b.shape[1])
    return cv2.resize(a, (w, h)), cv2.resize(b, (w, h))


def compute_ssim(render_grey: np.ndarray, photo_grey: np.ndarray) -> float:
    """Structural similarity index."""
    # win_size must be odd and <= min dimension
    min_dim = min(render_grey.shape[0], render_grey.shape[1])
    win = min(7, min_dim)
    if win % 2 == 0:
        win -= 1
    if win < 3:
        return 0.0
    return float(ssim(render_grey, photo_grey, win_size=win))


def compute_histogram_correlation(render: np.ndarray, photo: np.ndarray) -> dict:
    """Colour histogram correlation per channel."""
    results = {}
    for channel, name in enumerate(["red", "green", "blue"]):
        hist_r = cv2.calcHist([render], [channel], None, [64], [0, 256])
        hist_p = cv2.calcHist([photo], [channel], None, [64], [0, 256])
        cv2.normalize(hist_r, hist_r)
        cv2.normalize(hist_p, hist_p)
        results[f"hist_{name}"] = float(cv2.compareHist(hist_r, hist_p, cv2.HISTCMP_CORREL))
    results["hist_avg"] = float(np.mean([results["hist_red"],
                                          results["hist_green"],
                                          results["hist_blue"]]))
    return results


def compute_lab_distance(render: np.ndarray, photo: np.ndarray) -> float:
    """Mean LAB colour distance in central facade region."""
    render_lab = cv2.cvtColor(render, cv2.COLOR_RGB2LAB).astype(np.float32)
    photo_lab = cv2.cvtColor(photo, cv2.COLOR_RGB2LAB).astype(np.float32)

    h, w = render.shape[:2]
    y1, y2 = int(h * 0.2), int(h * 0.8)
    x1, x2 = int(w * 0.2), int(w * 0.8)

    if y2 <= y1 or x2 <= x1:
        return 0.0

    region_r = render_lab[y1:y2, x1:x2]
    region_p = photo_lab[y1:y2, x1:x2]

    return float(np.mean(np.sqrt(np.sum((region_r - region_p) ** 2, axis=2))))


def compute_edge_similarity(render_grey: np.ndarray, photo_grey: np.ndarray) -> float:
    """Edge overlap between Canny edges."""
    edges_r = cv2.Canny(render_grey, 50, 150)
    edges_p = cv2.Canny(photo_grey, 50, 150)
    union = np.sum(edges_r | edges_p)
    if union == 0:
        return 1.0
    return float(np.sum(edges_r & edges_p) / union)


def estimate_sky_ratio(img: np.ndarray) -> float:
    """Estimate proportion of image that is sky (top bright/blue region)."""
    # Check top 30% of image
    h = img.shape[0]
    top = img[:int(h * 0.3)]
    if top.size == 0:
        return 0.0
    # Sky: high brightness + high blue relative to red
    grey = cv2.cvtColor(top, cv2.COLOR_RGB2GRAY) if len(top.shape) == 3 else top
    bright = np.mean(grey > 160)
    return float(bright)


def count_rectangular_regions(grey: np.ndarray, min_area: int = 200,
                               max_area: int = 5000) -> int:
    """Rough window count by detecting rectangular contours."""
    edges = cv2.Canny(grey, 50, 150)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    edges = cv2.dilate(edges, kernel, iterations=1)

    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    count = 0
    for cnt in contours:
        area = cv2.contourArea(cnt)
        if min_area <= area <= max_area:
            x, y, w, h = cv2.boundingRect(cnt)
            aspect = w / max(h, 1)
            # Windows are roughly portrait or square
            if 0.3 < aspect < 2.5:
                count += 1
    return count


def compare_pair(render_path: str, photo_path: str) -> dict:
    """Compute all similarity metrics between render and photo."""
    render = load_and_resize(render_path)
    photo = load_and_resize(photo_path)

    if render is None or photo is None:
        return {"error": "failed_to_load", "ssim": 0.0, "hist_avg": 0.0,
                "lab_distance": 100.0, "edge_similarity": 0.0}

    render, photo = make_same_size(render, photo)

    render_grey = cv2.cvtColor(render, cv2.COLOR_RGB2GRAY)
    photo_grey = cv2.cvtColor(photo, cv2.COLOR_RGB2GRAY)

    metrics = {}

    # 1. SSIM
    metrics["ssim"] = compute_ssim(render_grey, photo_grey)

    # 2. Colour histogram
    metrics.update(compute_histogram_correlation(render, photo))

    # 3. LAB distance
    metrics["lab_distance"] = compute_lab_distance(render, photo)

    # 4. Edge similarity
    metrics["edge_similarity"] = compute_edge_similarity(render_grey, photo_grey)

    # 5. Aspect ratio
    render_h, render_w = render.shape[:2]
    photo_h, photo_w = photo.shape[:2]
    render_aspect = render_w / max(render_h, 1)
    photo_aspect = photo_w / max(photo_h, 1)
    metrics["aspect_ratio_diff"] = abs(render_aspect - photo_aspect)

    # 6. Window count
    metrics["render_window_count"] = count_rectangular_regions(render_grey)
    metrics["photo_window_count"] = count_rectangular_regions(photo_grey)
    metrics["window_count_diff"] = abs(metrics["render_window_count"] -
                                        metrics["photo_window_count"])

    # 7. Sky ratio
    metrics["render_sky_ratio"] = estimate_sky_ratio(render)
    metrics["photo_sky_ratio"] = estimate_sky_ratio(photo)

    return metrics


def compare_all(pairs: list[dict], limit: int = 0) -> list[dict]:
    """Run comparison on all paired render-photo entries."""
    results = []
    to_process = [p for p in pairs if p["match_status"] == "matched"]
    if limit > 0:
        to_process = to_process[:limit]

    for i, pair in enumerate(to_process):
        metrics = compare_pair(pair["render"], pair["photo_path"])
        pair["metrics"] = metrics
        results.append(pair)

        if (i + 1) % 50 == 0:
            logger.info("  Compared %d/%d", i + 1, len(to_process))

    # Also include unmatched (no_photo) entries with null metrics
    for pair in pairs:
        if pair["match_status"] != "matched":
            pair["metrics"] = None
            results.append(pair)

    return results


def main():
    parser = argparse.ArgumentParser(description="Phase 0: Compare render vs photo")
    parser.add_argument("--pairs", type=Path,
                        default=REPO_ROOT / "outputs" / "visual_audit" / "pairs.json")
    parser.add_argument("--output", type=Path,
                        default=REPO_ROOT / "outputs" / "visual_audit" / "comparisons.json")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    pairs = json.loads(args.pairs.read_text(encoding="utf-8"))
    logger.info("Loaded %d pairs", len(pairs))

    results = compare_all(pairs, limit=args.limit)

    matched = [r for r in results if r.get("metrics") is not None]
    if matched:
        avg_ssim = np.mean([r["metrics"]["ssim"] for r in matched])
        avg_lab = np.mean([r["metrics"]["lab_distance"] for r in matched])
        logger.info("Average SSIM: %.3f, Average LAB distance: %.1f", avg_ssim, avg_lab)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(results, indent=2), encoding="utf-8")
    logger.info("Saved → %s", args.output)


if __name__ == "__main__":
    main()
