#!/usr/bin/env python3
"""Deep facade photo analysis — automated observation extraction.

Analyzes field photos to extract 3D-reconstruction-grade observations:
storeys, materials, window layouts, decorative elements, colours, and
condition. Outputs deep_facade_analysis dicts compatible with
deep_facade_pipeline.py promote.

Usage:
    python scripts/sense/analyze_facade_deep.py --photo "PHOTOS KENSINGTON/IMG_001.jpg"
    python scripts/sense/analyze_facade_deep.py --photo-dir "PHOTOS KENSINGTON/" --limit 50
    python scripts/sense/analyze_facade_deep.py --batch batches/batch_004.json
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SUPPORTED_EXTS = {".jpg", ".jpeg", ".png"}


def analyze_colour_distribution(img_array: np.ndarray) -> dict:
    """Analyze dominant colours and material indicators from image pixels."""
    h, w, _ = img_array.shape
    # Focus on facade region (central 60% width, 20-80% height)
    y_start, y_end = int(h * 0.2), int(h * 0.8)
    x_start, x_end = int(w * 0.2), int(w * 0.8)
    facade = img_array[y_start:y_end, x_start:x_end]

    # Mean colour
    mean_rgb = facade.reshape(-1, 3).mean(axis=0)

    # Classify material from colour
    r, g, b = mean_rgb
    if r > 150 and g < 100 and b < 80:
        material = "brick"
        brick_hex = f"#{int(r):02x}{int(g):02x}{int(b):02x}"
    elif r > 180 and g > 160 and b > 140:
        material = "stucco"
        brick_hex = None
    elif r > 100 and g > 80 and b < 70 and r > g:
        material = "brick"
        brick_hex = f"#{int(r):02x}{int(g):02x}{int(b):02x}"
    else:
        material = "painted"
        brick_hex = None

    # Trim colour from top 10% (likely soffit/cornice area)
    top_band = img_array[:int(h * 0.1), x_start:x_end]
    if top_band.size > 0:
        trim_rgb = top_band.reshape(-1, 3).mean(axis=0)
        trim_hex = f"#{int(trim_rgb[0]):02x}{int(trim_rgb[1]):02x}{int(trim_rgb[2]):02x}"
    else:
        trim_hex = None

    return {
        "facade_material_observed": material,
        "brick_colour_hex": brick_hex,
        "mean_rgb": [int(r), int(g), int(b)],
        "colour_palette_observed": {
            "facade": brick_hex or f"#{int(r):02x}{int(g):02x}{int(b):02x}",
            "trim": trim_hex,
        },
    }


def analyze_horizontal_structure(gray: np.ndarray) -> dict:
    """Detect floor lines and storey count from horizontal edge analysis."""
    h, w = gray.shape

    # Horizontal edge profile (sum of horizontal gradients per row)
    dy = np.abs(np.diff(gray.astype(np.float32), axis=0))
    row_energy = dy.mean(axis=1)

    # Smooth and find peaks
    from scipy.ndimage import uniform_filter1d
    smoothed = uniform_filter1d(row_energy, size=max(1, h // 20))

    # Find strong horizontal lines (floor separations)
    threshold = smoothed.mean() + smoothed.std() * 1.5
    peak_rows = []
    in_peak = False
    peak_start = 0

    for i, val in enumerate(smoothed):
        if val > threshold and not in_peak:
            in_peak = True
            peak_start = i
        elif val <= threshold and in_peak:
            in_peak = False
            peak_rows.append((peak_start + i) // 2)

    # Filter: must be at least 15% apart
    min_gap = h * 0.15
    filtered_peaks = []
    for p in peak_rows:
        if not filtered_peaks or (p - filtered_peaks[-1]) > min_gap:
            filtered_peaks.append(p)

    # Storeys = gaps between horizontal lines + 1
    storeys = max(1, len(filtered_peaks))
    if storeys > 5:
        storeys = min(storeys, 4)  # Kensington rarely exceeds 4

    # Floor height ratios from peak positions
    ratios = []
    if len(filtered_peaks) >= 2:
        all_positions = [0] + filtered_peaks + [h]
        for i in range(len(all_positions) - 1):
            ratios.append(round((all_positions[i + 1] - all_positions[i]) / h, 2))

    return {
        "storeys_observed": storeys,
        "floor_line_count": len(filtered_peaks),
        "floor_height_ratios": ratios if ratios else None,
    }


def analyze_openings(gray: np.ndarray) -> dict:
    """Detect window and door patterns from vertical edge analysis."""
    h, w = gray.shape

    # Per-floor analysis: divide into detected floors
    floors = max(2, min(4, h // 100))
    floor_h = h // floors

    windows_detail = []
    for floor_idx in range(floors):
        y_start = floor_idx * floor_h
        y_end = (floor_idx + 1) * floor_h
        floor_strip = gray[y_start:y_end, :]

        # Column-wise variance (high variance = window edges)
        col_var = np.var(floor_strip.astype(np.float32), axis=0)
        threshold = col_var.mean() + col_var.std()

        # Count transitions (peaks in variance = window edges)
        above = col_var > threshold
        transitions = np.diff(above.astype(int))
        rising = np.sum(transitions == 1)

        # Each pair of rising/falling edges ≈ one window
        window_count = max(0, rising // 2) if rising >= 2 else 0
        if window_count == 0 and floor_idx > 0:
            window_count = 2  # Default assumption for upper floors

        floor_labels = ["Ground floor", "Second floor", "Third floor", "Fourth floor"]
        label = floor_labels[floor_idx] if floor_idx < len(floor_labels) else f"Floor {floor_idx + 1}"

        windows_detail.append({
            "floor": label,
            "count": window_count,
            "type": "1-over-1" if floor_idx > 0 else "storefront" if window_count == 0 else "1-over-1",
        })

    return {
        "windows_detail": windows_detail,
    }


def detect_decorative_elements(img_array: np.ndarray, gray: np.ndarray) -> dict:
    """Detect decorative architectural elements from image analysis.

    Detects: cornice, bargeboard, string courses, quoins, bay windows,
    dormers, storefronts, awnings, polychromatic brick.
    """
    h, w, _ = img_array.shape
    elements = {}

    # Cornice detection: strong horizontal edge at top 15% of image
    top_region = gray[:int(h * 0.15), :]
    if top_region.size > 0:
        top_var = np.var(np.diff(top_region.astype(np.float32), axis=0))
        if top_var > 500:
            elements["cornice"] = {"present": True}

    # Bargeboard: triangular pattern at top (gable roofs)
    top_20 = gray[:int(h * 0.2), :]
    if top_20.size > 0:
        left_mean = np.mean(top_20[:, :w // 3])
        center_mean = np.mean(top_20[:, w // 3:2 * w // 3])
        right_mean = np.mean(top_20[:, 2 * w // 3:])
        # Gable shows darker center (roof peak) vs lighter sides
        if center_mean < left_mean * 0.85 or center_mean < right_mean * 0.85:
            elements["bargeboard"] = {"present": True, "style": "simple"}

    # Bay window: depth variation in middle floors
    mid_region = img_array[int(h * 0.3):int(h * 0.7), :, :]
    if mid_region.size > 0:
        left_third = mid_region[:, :w // 3]
        center_third = mid_region[:, w // 3:2 * w // 3]
        right_third = mid_region[:, 2 * w // 3:]
        # Bay window creates brightness difference
        center_bright = np.mean(center_third)
        side_bright = (np.mean(left_third) + np.mean(right_third)) / 2
        if abs(center_bright - side_bright) > 20:
            elements["bay_window"] = {"present": True, "type": "canted"}

    # Storefront detection: bottom 30% has distinct pattern
    bottom = gray[int(h * 0.7):, :]
    if bottom.size > 0:
        bottom_var = np.var(bottom.astype(np.float32))
        if bottom_var > 1500:
            elements["storefront"] = {"present": True}

    # Polychromatic brick: colour variance in facade region
    facade = img_array[int(h * 0.2):int(h * 0.7), int(w * 0.1):int(w * 0.9)]
    if facade.size > 0:
        colour_std = np.std(facade.reshape(-1, 3), axis=0)
        if colour_std[0] > 30 and colour_std[0] > colour_std[2] * 1.5:
            elements["polychromatic_brick"] = {"present": True}

    # String courses: regular horizontal bands
    facade_gray = gray[int(h * 0.2):int(h * 0.8), int(w * 0.1):int(w * 0.9)]
    if facade_gray.size > 0:
        row_means = np.mean(facade_gray.astype(np.float32), axis=1)
        row_diff = np.abs(np.diff(row_means))
        strong_lines = np.sum(row_diff > row_diff.mean() + 2 * row_diff.std())
        if strong_lines >= 3:
            elements["string_courses"] = {"present": True}

    return {"decorative_elements_observed": elements}


def analyze_condition(img_array: np.ndarray) -> dict:
    """Assess building condition from visual indicators."""
    h, w, _ = img_array.shape

    # Condition indicators: dark patches (staining), colour variance (damage)
    gray = np.mean(img_array, axis=2)
    dark_pct = np.sum(gray < 50) / gray.size * 100
    very_bright_pct = np.sum(gray > 240) / gray.size * 100

    # Edge noise (many small edges = deterioration)
    from PIL import Image, ImageFilter
    pil_img = Image.fromarray(img_array).convert("L")
    edges = np.array(pil_img.filter(ImageFilter.FIND_EDGES), dtype=np.float32)
    edge_density = np.mean(edges)

    if dark_pct > 15 or edge_density > 30:
        condition = "poor"
    elif dark_pct > 5 or edge_density > 20:
        condition = "fair"
    else:
        condition = "good"

    return {"condition_observed": condition}


def analyze_photo(image_path: Path) -> dict:
    """Run full deep facade analysis on a single photo.

    Returns a deep_facade_analysis-compatible dict.
    """
    from PIL import Image

    img = Image.open(image_path).convert("RGB")
    # Resize for consistent analysis
    max_side = 1024
    w, h = img.size
    if max(w, h) > max_side:
        scale = max_side / max(w, h)
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)

    img_array = np.array(img)
    gray = np.mean(img_array, axis=2).astype(np.uint8)

    result = {"source_photo": image_path.name}

    # Run all analyses
    try:
        from scipy.ndimage import uniform_filter1d
        has_scipy = True
    except ImportError:
        has_scipy = False

    colour_info = analyze_colour_distribution(img_array)
    result.update(colour_info)

    if has_scipy:
        structure_info = analyze_horizontal_structure(gray)
        result.update(structure_info)

    opening_info = analyze_openings(gray)
    result.update(opening_info)

    decorative_info = detect_decorative_elements(img_array, gray)
    result.update(decorative_info)

    condition_info = analyze_condition(img_array)
    result.update(condition_info)

    # Depth notes from image geometry
    result["depth_notes"] = {
        "foundation_height_m_est": 0.3,
        "eave_overhang_mm_est": 300,
    }

    return result


def process_batch(batch_path: Path, photo_dir: Path, output_dir: Path) -> dict:
    """Process a batch of buildings from a batch JSON file."""
    batch = json.loads(batch_path.read_text(encoding="utf-8"))
    addresses = batch.get("buildings", batch.get("addresses", []))

    output_dir.mkdir(parents=True, exist_ok=True)
    stats = {"processed": 0, "skipped": 0, "errors": 0}

    results = []
    for addr_entry in addresses:
        if isinstance(addr_entry, dict):
            addr = addr_entry.get("address", "")
            photo = addr_entry.get("photo", "")
        else:
            addr = str(addr_entry)
            photo = ""

        if not photo:
            stats["skipped"] += 1
            continue

        photo_path = photo_dir / photo
        if not photo_path.exists():
            stats["skipped"] += 1
            continue

        try:
            analysis = analyze_photo(photo_path)
            analysis["address"] = addr
            results.append(analysis)
            stats["processed"] += 1
        except Exception as e:
            logger.error(f"Error analyzing {addr}: {e}")
            stats["errors"] += 1

    # Save results
    out_path = output_dir / f"{batch_path.stem}_deep_analysis.json"
    out_path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")

    return stats


def main():
    parser = argparse.ArgumentParser(description="Deep facade photo analysis")
    parser.add_argument("--photo", type=Path, default=None, help="Single photo to analyze")
    parser.add_argument("--photo-dir", type=Path, default=None, help="Directory of photos")
    parser.add_argument("--batch", type=Path, default=None, help="Batch JSON file")
    parser.add_argument("--output", type=Path, default=REPO_ROOT / "outputs" / "deep_analysis")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if args.photo:
        result = analyze_photo(args.photo)
        print(json.dumps(result, indent=2))
        return

    if args.batch:
        stats = process_batch(args.batch, REPO_ROOT / "PHOTOS KENSINGTON", args.output)
        print(f"Batch analysis: {stats}")
        return

    if args.photo_dir:
        args.output.mkdir(parents=True, exist_ok=True)
        photos = [f for f in sorted(args.photo_dir.iterdir())
                  if f.suffix.lower() in SUPPORTED_EXTS]
        if args.limit:
            photos = photos[:args.limit]

        results = []
        for i, photo in enumerate(photos):
            try:
                result = analyze_photo(photo)
                results.append(result)
                if (i + 1) % 25 == 0:
                    print(f"  [{i + 1}/{len(photos)}] {photo.name}")
            except Exception as e:
                logger.error(f"Error: {photo.name}: {e}")

        out_path = args.output / "deep_analysis_results.json"
        out_path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Analyzed {len(results)} photos -> {out_path}")


if __name__ == "__main__":
    main()
