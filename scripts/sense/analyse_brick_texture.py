#!/usr/bin/env python3
"""
Brick Texture Analyser for Kensington Market 3D Reconstruction
--------------------------------------------------------------
Analyses field photos of brick buildings to extract:
  - Dominant mortar line spacing (courses per metre estimate)
  - Brick colour palette (dominant, secondary, mortar colour)
  - Colour variance classification
  - Horizontal/vertical edge density (proxy for coursing regularity)
  - Texture roughness estimate
  - Mortar joint width estimate (relative to brick height)

Usage:
    python3 analyse_brick_texture.py <image_path> [--output json_path]
    python3 analyse_brick_texture.py --batch <directory> [--output-dir dir]
"""

import sys
import os
import json
import csv
import numpy as np
from PIL import Image, ImageStat, ImageFilter, ExifTags
from collections import Counter
import colorsys


def load_and_orient(path, max_dim=1600):
    """Load image, apply EXIF orientation, resize for processing."""
    img = Image.open(path)
    # Apply EXIF rotation
    try:
        for k, v in (img._getexif() or {}).items():
            if ExifTags.TAGS.get(k) == 'Orientation':
                if v == 3:
                    img = img.rotate(180, expand=True)
                elif v == 6:
                    img = img.rotate(270, expand=True)
                elif v == 8:
                    img = img.rotate(90, expand=True)
                break
    except (AttributeError, TypeError):
        pass
    # Resize for speed
    w, h = img.size
    if max(w, h) > max_dim:
        scale = max_dim / max(w, h)
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
    return img


def extract_dominant_colours(img, n_colours=8, sample_size=10000):
    """Extract dominant colours from the image using quantization."""
    # Sample pixels for speed
    pixels = np.array(img.convert('RGB'))
    h, w, _ = pixels.shape
    flat = pixels.reshape(-1, 3)
    if len(flat) > sample_size:
        indices = np.random.choice(len(flat), sample_size, replace=False)
        flat = flat[indices]

    # Quantize using PIL
    small = img.convert('RGB').quantize(colors=n_colours, method=Image.Quantize.MEDIANCUT)
    palette = small.getpalette()[:n_colours * 3]
    colours = []
    for i in range(0, len(palette), 3):
        r, g, b = palette[i], palette[i+1], palette[i+2]
        hex_col = f"#{r:02X}{g:02X}{b:02X}"
        colours.append({"rgb": [r, g, b], "hex": hex_col})

    return colours


def classify_brick_colour(colours):
    """Classify the dominant brick colour and variance."""
    if not colours:
        return {"base_hex": "#000000", "variance": "unknown"}

    # Find the most "brick-like" colour (warm, medium luminance)
    brick_candidates = []
    mortar_candidates = []
    for c in colours:
        r, g, b = c['rgb']
        h_val, s, v = colorsys.rgb_to_hsv(r/255, g/255, b/255)
        hue_deg = h_val * 360
        # Brick hues: red-orange-brown range (0-40 deg, 340-360 deg)
        is_warm = (0 <= hue_deg <= 45) or (330 <= hue_deg <= 360)
        is_mid_value = 0.15 < v < 0.85
        is_saturated = s > 0.1
        # Mortar: low saturation, lighter
        is_mortar = s < 0.15 and v > 0.4

        if is_warm and is_mid_value and is_saturated:
            brick_candidates.append(c)
        if is_mortar:
            mortar_candidates.append(c)

    base = brick_candidates[0] if brick_candidates else colours[0]

    # Calculate colour variance among brick candidates
    if len(brick_candidates) >= 2:
        rgbs = np.array([c['rgb'] for c in brick_candidates])
        std = np.std(rgbs, axis=0).mean()
        if std < 15:
            variance = "low"
        elif std < 30:
            variance = "medium"
        else:
            variance = "high"
    else:
        variance = "low"

    mortar_hex = mortar_candidates[0]['hex'] if mortar_candidates else "#C0C0C0"

    return {
        "base_hex": base['hex'],
        "variance": variance,
        "all_brick_colours": [c['hex'] for c in brick_candidates[:4]],
        "mortar_colour_hex": mortar_hex,
        "palette": [c['hex'] for c in colours]
    }


def detect_mortar_lines(img, region='centre'):
    """
    Detect horizontal mortar lines using edge detection.
    Returns estimated courses per metre and line spacing stats.
    """
    grey = np.array(img.convert('L'))
    h, w = grey.shape

    # Crop to centre 60% to avoid edges/sky/ground
    if region == 'centre':
        y1, y2 = int(h * 0.2), int(h * 0.8)
        x1, x2 = int(w * 0.2), int(w * 0.8)
        grey = grey[y1:y2, x1:x2]
        h, w = grey.shape

    # Horizontal edge detection (Sobel-like)
    # Mortar lines create horizontal edges
    kernel_h = np.array([[-1, -1, -1],
                         [ 0,  0,  0],
                         [ 1,  1,  1]], dtype=np.float64)

    # Manual convolution via PIL
    pil_crop = Image.fromarray(grey)
    edges_h = pil_crop.filter(ImageFilter.Kernel(
        size=(3, 3),
        kernel=[-1, -1, -1, 0, 0, 0, 1, 1, 1],
        scale=1, offset=128
    ))
    edges_arr = np.array(edges_h).astype(np.float64) - 128
    edges_abs = np.abs(edges_arr)

    # Sum horizontal edges across each row to find mortar line positions
    row_energy = edges_abs.mean(axis=1)

    # Smooth and find peaks
    kernel_size = max(3, h // 100)
    smoothed = np.convolve(row_energy, np.ones(kernel_size)/kernel_size, mode='same')

    # Find local maxima (mortar line positions)
    threshold = np.percentile(smoothed, 75)
    peaks = []
    min_gap = max(3, h // 80)  # Minimum gap between peaks

    for i in range(1, len(smoothed) - 1):
        if smoothed[i] > threshold and smoothed[i] > smoothed[i-1] and smoothed[i] >= smoothed[i+1]:
            if not peaks or (i - peaks[-1]) >= min_gap:
                peaks.append(i)

    # Calculate spacings between consecutive peaks
    spacings = np.diff(peaks) if len(peaks) > 1 else np.array([])

    if len(spacings) > 2:
        # Remove outliers (> 2 std from median)
        median_sp = np.median(spacings)
        std_sp = np.std(spacings)
        filtered = spacings[np.abs(spacings - median_sp) < 2 * std_sp]
        if len(filtered) > 0:
            spacings = filtered

    result = {
        "num_lines_detected": len(peaks),
        "mean_spacing_px": float(np.mean(spacings)) if len(spacings) > 0 else 0,
        "median_spacing_px": float(np.median(spacings)) if len(spacings) > 0 else 0,
        "std_spacing_px": float(np.std(spacings)) if len(spacings) > 0 else 0,
        "spacing_regularity": 0,
        "region_height_px": h,
        "region_width_px": w,
    }

    if result["mean_spacing_px"] > 0:
        result["spacing_regularity"] = round(
            1.0 - min(1.0, result["std_spacing_px"] / result["mean_spacing_px"]), 3
        )

    return result


def detect_vertical_lines(img):
    """Detect vertical mortar lines (head joints) similarly."""
    grey = np.array(img.convert('L'))
    h, w = grey.shape
    y1, y2 = int(h * 0.2), int(h * 0.8)
    x1, x2 = int(w * 0.2), int(w * 0.8)
    grey = grey[y1:y2, x1:x2]
    h, w = grey.shape

    pil_crop = Image.fromarray(grey)
    edges_v = pil_crop.filter(ImageFilter.Kernel(
        size=(3, 3),
        kernel=[-1, 0, 1, -1, 0, 1, -1, 0, 1],
        scale=1, offset=128
    ))
    edges_arr = np.array(edges_v).astype(np.float64) - 128
    edges_abs = np.abs(edges_arr)

    col_energy = edges_abs.mean(axis=0)
    kernel_size = max(3, w // 100)
    smoothed = np.convolve(col_energy, np.ones(kernel_size)/kernel_size, mode='same')
    threshold = np.percentile(smoothed, 75)

    peaks = []
    min_gap = max(3, w // 60)
    for i in range(1, len(smoothed) - 1):
        if smoothed[i] > threshold and smoothed[i] > smoothed[i-1] and smoothed[i] >= smoothed[i+1]:
            if not peaks or (i - peaks[-1]) >= min_gap:
                peaks.append(i)

    spacings = np.diff(peaks) if len(peaks) > 1 else np.array([])
    if len(spacings) > 2:
        median_sp = np.median(spacings)
        std_sp = np.std(spacings)
        filtered = spacings[np.abs(spacings - median_sp) < 2 * std_sp]
        if len(filtered) > 0:
            spacings = filtered

    return {
        "num_vertical_lines": len(peaks),
        "mean_spacing_px": float(np.mean(spacings)) if len(spacings) > 0 else 0,
        "median_spacing_px": float(np.median(spacings)) if len(spacings) > 0 else 0,
    }


def estimate_texture_roughness(img):
    """
    Estimate surface roughness from local variance.
    Higher values = rougher texture (hand-pressed brick).
    Lower values = smoother (machine-pressed).
    """
    grey = np.array(img.convert('L'), dtype=np.float64)
    h, w = grey.shape
    # Centre crop
    y1, y2 = int(h * 0.25), int(h * 0.75)
    x1, x2 = int(w * 0.25), int(w * 0.75)
    crop = grey[y1:y2, x1:x2]

    # Local variance in 8x8 blocks
    bh, bw = 8, 8
    variances = []
    for y in range(0, crop.shape[0] - bh, bh):
        for x in range(0, crop.shape[1] - bw, bw):
            block = crop[y:y+bh, x:x+bw]
            variances.append(np.var(block))

    if not variances:
        return {"roughness": 0, "classification": "unknown"}

    mean_var = np.mean(variances)
    if mean_var < 200:
        classification = "smooth (machine-pressed)"
    elif mean_var < 600:
        classification = "medium"
    elif mean_var < 1200:
        classification = "rough (hand-pressed)"
    else:
        classification = "very rough (weathered/salvage)"

    return {
        "roughness_score": round(float(mean_var), 1),
        "classification": classification
    }


def estimate_mortar_ratio(horiz_data, vert_data):
    """
    Estimate mortar joint width as a ratio of course height.
    Based on horizontal vs vertical line detection characteristics.
    """
    if horiz_data["mean_spacing_px"] == 0:
        return {"mortar_ratio": 0, "estimated_joint_mm": 0, "classification": "unknown"}

    # Course height in px
    course_px = horiz_data["mean_spacing_px"]

    # Mortar joints create sharper, narrower edge peaks
    # The width of detected edge peaks relative to spacing indicates joint width
    # Use regularity as a proxy
    regularity = horiz_data["spacing_regularity"]

    # Standard course height is 74mm
    # Estimate mortar proportion from edge sharpness
    if regularity > 0.85:
        mortar_ratio = 0.13  # ~10mm of 74mm
        est_mm = 10
        classification = "medium (9-11mm)"
    elif regularity > 0.7:
        mortar_ratio = 0.16  # ~12mm
        est_mm = 12
        classification = "medium-wide (11-13mm)"
    elif regularity > 0.5:
        mortar_ratio = 0.20  # ~15mm
        est_mm = 15
        classification = "wide (13-16mm)"
    else:
        mortar_ratio = 0.22  # ~17mm
        est_mm = 17
        classification = "very wide (>15mm)"

    return {
        "mortar_ratio": round(mortar_ratio, 3),
        "estimated_joint_mm": est_mm,
        "classification": classification
    }


def analyse_image(path):
    """Run full brick texture analysis on a single image."""
    img = load_and_orient(path)
    w, h = img.size

    colours = extract_dominant_colours(img)
    colour_class = classify_brick_colour(colours)
    horiz = detect_mortar_lines(img)
    vert = detect_vertical_lines(img)
    roughness = estimate_texture_roughness(img)
    mortar = estimate_mortar_ratio(horiz, vert)

    # Estimate courses per metre
    # If we assume the centre 60% of the image height spans ~2m (rough assumption for facade photos)
    # then we can estimate courses per metre
    visible_height_m = 2.0  # rough assumption
    centre_height_px = h * 0.6
    if horiz["mean_spacing_px"] > 0:
        courses_in_region = centre_height_px / horiz["mean_spacing_px"]
        courses_per_m = courses_in_region / visible_height_m
    else:
        courses_per_m = 0

    # Aspect ratio to detect close-up vs facade
    aspect = w / h if h > 0 else 1
    if max(w, h) < 800:
        photo_type = "low_resolution"
    elif horiz["num_lines_detected"] < 5:
        photo_type = "non_brick_or_obscured"
    elif horiz["num_lines_detected"] > 40:
        photo_type = "close_up"
    else:
        photo_type = "facade"

    return {
        "file": os.path.basename(path),
        "image_size": [w, h],
        "photo_type": photo_type,
        "colour": colour_class,
        "horizontal_lines": horiz,
        "vertical_lines": vert,
        "texture": roughness,
        "mortar": mortar,
        "estimated_courses_per_m": round(courses_per_m, 1),
    }


def batch_analyse(directory, output_path=None):
    """Analyse all images in a directory."""
    results = []
    extensions = {'.jpg', '.jpeg', '.png', '.tif', '.tiff'}

    files = sorted([
        f for f in os.listdir(directory)
        if os.path.splitext(f)[1].lower() in extensions
    ])

    print(f"Analysing {len(files)} images in {directory}...")

    for i, fname in enumerate(files):
        path = os.path.join(directory, fname)
        try:
            result = analyse_image(path)
            results.append(result)
            if (i + 1) % 10 == 0:
                print(f"  [{i+1}/{len(files)}] {fname} — {result['photo_type']}, "
                      f"lines={result['horizontal_lines']['num_lines_detected']}, "
                      f"colour={result['colour']['base_hex']}")
        except Exception as e:
            results.append({"file": fname, "error": str(e)})
            print(f"  [{i+1}/{len(files)}] {fname} — ERROR: {e}")

    if output_path:
        with open(output_path, 'w') as f:
            json.dump(results, f, indent=2)
        print(f"\nResults written to {output_path}")

    # Summary
    brick_count = sum(1 for r in results if r.get('photo_type') in ('facade', 'close_up'))
    print(f"\nSummary: {len(results)} images, {brick_count} with detected brick texture")
    return results


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    if sys.argv[1] == '--batch':
        directory = sys.argv[2] if len(sys.argv) > 2 else '.'
        output = None
        if '--output' in sys.argv:
            output = sys.argv[sys.argv.index('--output') + 1]
        batch_analyse(directory, output)
    else:
        result = analyse_image(sys.argv[1])
        print(json.dumps(result, indent=2))
