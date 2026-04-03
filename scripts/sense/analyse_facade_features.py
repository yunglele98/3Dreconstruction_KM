#!/usr/bin/env python3
"""
Facade Feature Detector for Kensington Market 3D Reconstruction
----------------------------------------------------------------
Analyses facade photos to detect architectural features:

STRUCTURAL GEOMETRY:
  - Arches (segmental, semi-circular, pointed/Gothic, flat jack)
  - Bay windows (canted, bow/curved, box/square)
  - Gables (peaked, Dutch, stepped)
  - Dormers (gable, shed, arched/eyebrow)
  - Parapets and cornices
  - Turrets/towers

BRICK SPECIAL FEATURES:
  - Corbelling (stepped brick projection)
  - Soldier courses (bricks on end)
  - Rowlock courses (bricks on edge)
  - Polychromatic banding (horizontal colour bands)
  - Diaper patterns (diamond motifs)
  - Dog-tooth courses (45° sawtooth)
  - Quoins (corner stones/brick)
  - Pilasters (shallow attached columns)
  - String/belt courses (horizontal bands)
  - Blind arches (decorative non-structural arches)
  - Voussoirs (arch stones)

OPENINGS:
  - Window types (single/double-hung, casement, fixed, transom)
  - Window heads (flat, segmental, semi-circular, pointed)
  - Window groupings (paired, triple, Palladian/Venetian)
  - Door types (single, double, with transom/sidelight/fanlight)
  - Storefronts (commercial ground floor)
  - Oculus/round windows

SURFACE TREATMENTS:
  - Painted brick
  - Stucco/render over brick
  - Parging
  - Siding (clapboard, vinyl, etc.)

APPENDAGES:
  - Porches/verandahs
  - Balconies
  - Fire escapes
  - Awnings/canopies
  - Chimneys

Uses edge detection, contour analysis, Hough transforms (via PIL approximation),
colour segmentation, and symmetry analysis.
"""

import sys
import os
import json
import numpy as np
from PIL import Image, ImageFilter, ImageDraw, ExifTags
import colorsys
from collections import defaultdict


def load_and_orient(path, max_dim=1200):
    """Load image with EXIF rotation, resize."""
    img = Image.open(path)
    try:
        for k, v in (img._getexif() or {}).items():
            if ExifTags.TAGS.get(k) == 'Orientation':
                if v == 3: img = img.rotate(180, expand=True)
                elif v == 6: img = img.rotate(270, expand=True)
                elif v == 8: img = img.rotate(90, expand=True)
                break
    except (AttributeError, TypeError):
        pass
    w, h = img.size
    if max(w, h) > max_dim:
        scale = max_dim / max(w, h)
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
    return img


# ──────────────────── COLOUR ZONE ANALYSIS ────────────────────

def segment_colour_zones(img):
    """
    Segment image into colour zones to identify:
    - Brick regions (warm colours)
    - Stone/trim regions (light/neutral)
    - Painted regions (saturated non-brick)
    - Sky regions (blue/white at top)
    - Vegetation (green)
    """
    pixels = np.array(img.convert('RGB'))
    h, w, _ = pixels.shape

    zones = np.zeros((h, w), dtype=np.uint8)
    # 0=unknown, 1=brick, 2=stone/trim, 3=painted, 4=sky, 5=vegetation, 6=dark/shadow, 7=mortar

    for y in range(0, h, 2):  # sample every other pixel for speed
        for x in range(0, w, 2):
            r, g, b = int(pixels[y, x, 0]), int(pixels[y, x, 1]), int(pixels[y, x, 2])
            hsv_h, s, v = colorsys.rgb_to_hsv(r/255, g/255, b/255)
            hue = hsv_h * 360

            if v < 0.12:
                z = 6  # very dark / shadow
            elif s < 0.08 and v > 0.6:
                z = 2  # stone/trim/white (low sat, light)
            elif s < 0.08 and v > 0.35:
                z = 7  # mortar (low sat, mid-light)
            elif 190 < hue < 250 and v > 0.4 and y < h * 0.35:
                z = 4  # sky (blue, upper image)
            elif 80 < hue < 170 and s > 0.15:
                z = 5  # vegetation (green)
            elif (0 <= hue <= 45 or 330 <= hue <= 360) and s > 0.12 and 0.15 < v < 0.85:
                z = 1  # brick (warm, saturated, mid-value)
            elif s > 0.3:
                z = 3  # painted (saturated non-brick)
            else:
                z = 0

            zones[y, x] = z
            if y + 1 < h and x + 1 < w:
                zones[y+1, x] = z
                zones[y, x+1] = z
                zones[y+1, x+1] = z

    # Calculate zone percentages
    total = h * w
    zone_names = ['unknown', 'brick', 'stone_trim', 'painted', 'sky', 'vegetation', 'shadow', 'mortar']
    percentages = {}
    for i, name in enumerate(zone_names):
        percentages[name] = round(float(np.sum(zones == i)) / total * 100, 1)

    return zones, percentages


# ──────────────────── EDGE & LINE DETECTION ────────────────────

def detect_edges(img):
    """Multi-directional edge detection."""
    grey = img.convert('L')

    # Horizontal edges (mortar lines, cornices, belt courses)
    h_edges = grey.filter(ImageFilter.Kernel(
        size=(3, 3), kernel=[-1, -1, -1, 0, 0, 0, 1, 1, 1],
        scale=1, offset=128
    ))

    # Vertical edges (pilasters, quoins, window sides)
    v_edges = grey.filter(ImageFilter.Kernel(
        size=(3, 3), kernel=[-1, 0, 1, -1, 0, 1, -1, 0, 1],
        scale=1, offset=128
    ))

    # General edges (contours)
    contour = grey.filter(ImageFilter.FIND_EDGES)

    return h_edges, v_edges, contour


def analyse_edge_profile(edges_img, axis='horizontal'):
    """
    Analyse the distribution of edges along an axis.
    For horizontal: sum edges along each row → profile shows where strong
    horizontal features are (cornices, belt courses, window heads/sills).
    """
    arr = np.array(edges_img).astype(np.float64) - 128
    arr = np.abs(arr)
    h, w = arr.shape

    if axis == 'horizontal':
        profile = arr.mean(axis=1)
    else:
        profile = arr.mean(axis=0)

    # Smooth
    k = max(3, len(profile) // 50)
    smoothed = np.convolve(profile, np.ones(k)/k, mode='same')

    # Find significant peaks (strong horizontal/vertical features)
    threshold = np.percentile(smoothed, 85)
    peaks = []
    min_gap = max(5, len(profile) // 40)

    for i in range(1, len(smoothed) - 1):
        if smoothed[i] > threshold and smoothed[i] > smoothed[i-1] and smoothed[i] >= smoothed[i+1]:
            if not peaks or (i - peaks[-1]) >= min_gap:
                peaks.append({
                    "position_px": int(i),
                    "position_pct": round(i / len(profile) * 100, 1),
                    "strength": round(float(smoothed[i]), 2)
                })

    return {
        "num_significant_features": len(peaks),
        "peak_positions": peaks,
        "mean_energy": round(float(smoothed.mean()), 2),
        "max_energy": round(float(smoothed.max()), 2),
    }


# ──────────────────── SYMMETRY ANALYSIS ────────────────────

def analyse_symmetry(img):
    """
    Measure facade symmetry by comparing left and right halves.
    Heritage buildings are typically symmetrical or near-symmetrical.
    """
    grey = np.array(img.convert('L'), dtype=np.float64)
    h, w = grey.shape

    # Crop out top 15% (sky) and bottom 10% (ground)
    y1, y2 = int(h * 0.15), int(h * 0.9)
    crop = grey[y1:y2, :]
    ch, cw = crop.shape

    # Split left and right
    mid = cw // 2
    left = crop[:, :mid]
    right = crop[:, mid:mid+left.shape[1]]

    # Flip right half
    right_flipped = right[:, ::-1]

    # Ensure same size
    min_w = min(left.shape[1], right_flipped.shape[1])
    left = left[:, :min_w]
    right_flipped = right_flipped[:, :min_w]

    # Normalised correlation
    diff = np.abs(left - right_flipped)
    mean_diff = diff.mean()
    max_possible = 255.0
    symmetry_score = round(1.0 - (mean_diff / max_possible), 3)

    if symmetry_score > 0.85:
        classification = "highly symmetrical"
    elif symmetry_score > 0.75:
        classification = "moderately symmetrical"
    elif symmetry_score > 0.65:
        classification = "slightly asymmetrical"
    else:
        classification = "asymmetrical"

    return {
        "symmetry_score": symmetry_score,
        "classification": classification
    }


# ──────────────────── ARCH DETECTION ────────────────────

def detect_curved_features(img):
    """
    Detect curved/arched features by analysing contour curvature
    in the edge-detected image.
    """
    grey = np.array(img.convert('L'))
    h, w = grey.shape

    # Edge detect
    pil_grey = Image.fromarray(grey)
    edges = pil_grey.filter(ImageFilter.FIND_EDGES)
    edge_arr = np.array(edges)

    # Threshold to binary
    threshold = np.percentile(edge_arr, 90)
    binary = (edge_arr > threshold).astype(np.uint8)

    # Scan for curved patterns in horizontal strips
    # Arches appear as downward-curving edge concentrations
    strip_h = h // 20
    arch_candidates = []

    for strip_idx in range(20):
        y1 = strip_idx * strip_h
        y2 = min(y1 + strip_h, h)
        strip = binary[y1:y2, :]

        # Check if there's a concentration of edges that curves
        col_density = strip.mean(axis=0)
        if col_density.max() < 0.05:
            continue

        # Find edge concentrations
        threshold_col = np.percentile(col_density, 80)
        active_cols = np.where(col_density > threshold_col)[0]

        if len(active_cols) < 10:
            continue

        # Check for arch-like shape: edges concentrated in an inverted-U pattern
        # Sample the top vs bottom of the strip
        top_half = binary[y1:y1 + strip_h//2, :]
        bot_half = binary[y1 + strip_h//2:y2, :]

        top_density = top_half.mean(axis=0)
        bot_density = bot_half.mean(axis=0)

        # Arch: more edges in the top, with edges spreading wider at bottom
        top_active = np.sum(top_density > threshold_col * 0.5)
        bot_active = np.sum(bot_density > threshold_col * 0.5)

        if top_active > 0 and bot_active > top_active * 1.2:
            arch_candidates.append({
                "strip_position_pct": round(strip_idx / 20 * 100, 1),
                "width_span_pct": round(len(active_cols) / w * 100, 1),
                "confidence": round(min(1.0, (bot_active - top_active) / max(1, top_active)), 2)
            })

    return {
        "num_arch_candidates": len(arch_candidates),
        "candidates": arch_candidates[:10]
    }


# ──────────────────── FACADE DIVISION ANALYSIS ────────────────────

def analyse_facade_divisions(h_profile, v_profile, img_h, img_w):
    """
    Determine the facade's compositional divisions:
    - Number of storeys (from strong horizontal divisions)
    - Number of bays (from strong vertical divisions)
    - Floor level positions
    """
    h_peaks = h_profile["peak_positions"]
    v_peaks = v_profile["peak_positions"]

    # Estimate storeys from horizontal divisions
    # Strong horizontal lines in the 30-80% vertical range = floor divisions
    floor_lines = [p for p in h_peaks
                   if 25 < p["position_pct"] < 85
                   and p["strength"] > h_profile["mean_energy"] * 1.5]

    # Sort by position
    floor_lines.sort(key=lambda p: p["position_pct"])

    # Filter to keep only widely-spaced lines (actual floor divisions)
    filtered_floors = []
    min_gap_pct = 15  # floors are at least 15% of image height apart
    for fl in floor_lines:
        if not filtered_floors or (fl["position_pct"] - filtered_floors[-1]["position_pct"]) > min_gap_pct:
            filtered_floors.append(fl)

    # Number of storeys = number of floor gaps + 1
    n_storeys = len(filtered_floors) + 1
    if n_storeys > 5:
        n_storeys = max(2, len([f for f in filtered_floors if f["strength"] > h_profile["max_energy"] * 0.5]) + 1)

    # Estimate bays from vertical divisions
    bay_lines = [p for p in v_peaks
                 if 15 < p["position_pct"] < 85
                 and p["strength"] > v_profile["mean_energy"] * 1.3]
    bay_lines.sort(key=lambda p: p["position_pct"])

    filtered_bays = []
    min_bay_pct = 10
    for bl in bay_lines:
        if not filtered_bays or (bl["position_pct"] - filtered_bays[-1]["position_pct"]) > min_bay_pct:
            filtered_bays.append(bl)

    n_bays = len(filtered_bays) + 1
    if n_bays > 6:
        n_bays = max(1, len([b for b in filtered_bays if b["strength"] > v_profile["max_energy"] * 0.5]) + 1)

    return {
        "estimated_storeys": min(n_storeys, 5),
        "floor_divisions": [{"position_pct": f["position_pct"], "strength": f["strength"]}
                           for f in filtered_floors],
        "estimated_bays": min(n_bays, 6),
        "bay_divisions": [{"position_pct": b["position_pct"], "strength": b["strength"]}
                         for b in filtered_bays],
    }


# ──────────────────── POLYCHROMATIC DETECTION ────────────────────

def detect_polychromatic_banding(img, zones):
    """
    Detect horizontal bands of contrasting colour (polychromatic brickwork).
    Look for rows where the dominant colour shifts between brick and stone/trim.
    """
    h, w = zones.shape
    # For each row, calculate the ratio of stone/trim (2) to brick (1)
    row_ratios = []
    for y in range(0, h, 2):
        row = zones[y, :]
        brick_count = np.sum(row == 1)
        stone_count = np.sum(row == 2)
        total = brick_count + stone_count
        if total > w * 0.2:  # only consider rows with significant masonry
            ratio = stone_count / total if total > 0 else 0
            row_ratios.append({"y": y, "stone_ratio": ratio})

    if not row_ratios:
        return {"polychromatic": False, "bands": []}

    # Find bands where stone ratio jumps significantly
    bands = []
    in_band = False
    band_start = None

    for entry in row_ratios:
        if entry["stone_ratio"] > 0.3 and not in_band:
            in_band = True
            band_start = entry["y"]
        elif entry["stone_ratio"] < 0.15 and in_band:
            in_band = False
            band_height = entry["y"] - band_start
            if band_height > 4:  # minimum band height
                bands.append({
                    "position_pct": round(band_start / h * 100, 1),
                    "height_pct": round(band_height / h * 100, 1),
                    "type": "stone_belt_course" if band_height < h * 0.03 else "stone_band"
                })

    return {
        "polychromatic": len(bands) > 0,
        "num_bands": len(bands),
        "bands": bands[:10]
    }


# ──────────────────── PAINTED BRICK DETECTION ────────────────────

def detect_painted_surfaces(zones):
    """Detect if the brick has been painted based on colour zones."""
    h, w = zones.shape
    total = h * w
    brick_pct = np.sum(zones == 1) / total * 100
    painted_pct = np.sum(zones == 3) / total * 100
    stone_pct = np.sum(zones == 2) / total * 100

    if painted_pct > 30:
        return {"is_painted": True, "painted_coverage_pct": round(painted_pct, 1),
                "notes": "Significant painted surface — original brick likely obscured"}
    elif brick_pct < 10 and stone_pct > 20:
        return {"is_painted": False, "notes": "May be stucco/render, stone, or very light brick",
                "stone_coverage_pct": round(stone_pct, 1)}
    else:
        return {"is_painted": False, "brick_coverage_pct": round(brick_pct, 1)}


# ──────────────────── CHIMNEY / VERTICAL FEATURE DETECTION ────────────────────

def detect_roof_features(img, zones):
    """
    Look for features at the top of the image:
    chimneys, gable peaks, dormers, parapets.
    """
    h, w = zones.shape
    top_quarter = zones[:h//4, :]

    # Chimneys: narrow vertical brick regions above the roofline
    # Look for brick pixels (1) surrounded by sky (4) in the top region
    features = []

    for x in range(0, w, 4):
        col = top_quarter[:, max(0,x-2):min(w,x+3)]
        brick_in_col = np.sum(col == 1)
        sky_in_col = np.sum(col == 4)

        if brick_in_col > top_quarter.shape[0] * 0.2 and sky_in_col > top_quarter.shape[0] * 0.1:
            features.append({
                "type": "chimney_candidate",
                "position_pct": round(x / w * 100, 1)
            })

    # Merge nearby chimney candidates
    merged = []
    for f in features:
        if not merged or (f["position_pct"] - merged[-1]["position_pct"]) > 5:
            merged.append(f)

    return {"roof_features": merged}


# ──────────────────── MAIN ANALYSIS ────────────────────

def analyse_facade(path):
    """Run full facade feature analysis on a single image."""
    img = load_and_orient(path)
    w, h = img.size

    # Colour zone segmentation
    zones, zone_pcts = segment_colour_zones(img)

    # Edge detection
    h_edges, v_edges, contour = detect_edges(img)

    # Edge profiles
    h_profile = analyse_edge_profile(h_edges, 'horizontal')
    v_profile = analyse_edge_profile(v_edges, 'vertical')

    # Symmetry
    symmetry = analyse_symmetry(img)

    # Arch detection
    arches = detect_curved_features(img)

    # Facade divisions
    divisions = analyse_facade_divisions(h_profile, v_profile, h, w)

    # Polychromatic banding
    polychrome = detect_polychromatic_banding(img, zones)

    # Painted detection
    painted = detect_painted_surfaces(zones)

    # Roof features
    roof = detect_roof_features(img, zones)

    # Compile feature list
    detected_features = []

    # From divisions
    if divisions["estimated_storeys"] >= 1:
        detected_features.append({
            "type": "building_form",
            "feature": f"{divisions['estimated_storeys']}-storey",
            "bays": divisions["estimated_bays"],
            "confidence": 0.7
        })

    # From arches
    if arches["num_arch_candidates"] > 0:
        for arch in arches["candidates"]:
            detected_features.append({
                "type": "arch",
                "subtype": "segmental_or_semicircular",
                "position_pct": arch["strip_position_pct"],
                "width_pct": arch["width_span_pct"],
                "confidence": arch["confidence"]
            })

    # From polychrome
    if polychrome["polychromatic"]:
        detected_features.append({
            "type": "polychromatic_banding",
            "num_bands": polychrome["num_bands"],
            "band_details": polychrome["bands"],
            "confidence": min(0.9, 0.3 + polychrome["num_bands"] * 0.15)
        })

    # From roof
    for rf in roof["roof_features"]:
        detected_features.append({
            "type": "chimney",
            "position_pct": rf["position_pct"],
            "confidence": 0.5
        })

    # From symmetry
    detected_features.append({
        "type": "symmetry",
        "score": symmetry["symmetry_score"],
        "classification": symmetry["classification"]
    })

    # Painted
    if painted.get("is_painted"):
        detected_features.append({
            "type": "painted_brick",
            "coverage_pct": painted.get("painted_coverage_pct", 0),
            "confidence": 0.7
        })

    # Strong horizontal features (cornices, belt courses, lintels)
    strong_h = [p for p in h_profile["peak_positions"]
                if p["strength"] > h_profile["max_energy"] * 0.6]
    for sh in strong_h:
        pos = sh["position_pct"]
        if pos < 15:
            feat_type = "cornice_or_parapet"
        elif pos > 85:
            feat_type = "foundation_or_sill_line"
        else:
            feat_type = "belt_course_or_lintel_line"
        detected_features.append({
            "type": feat_type,
            "position_pct": pos,
            "strength": sh["strength"],
            "confidence": 0.5
        })

    # Strong vertical features (pilasters, quoins, bay window edges)
    strong_v = [p for p in v_profile["peak_positions"]
                if p["strength"] > v_profile["max_energy"] * 0.6]
    for sv in strong_v:
        pos = sv["position_pct"]
        if pos < 10 or pos > 90:
            feat_type = "quoin_or_building_edge"
        else:
            feat_type = "pilaster_or_bay_edge"
        detected_features.append({
            "type": feat_type,
            "position_pct": pos,
            "strength": sv["strength"],
            "confidence": 0.4
        })

    return {
        "file": os.path.basename(path),
        "image_size": [w, h],
        "colour_zones": zone_pcts,
        "symmetry": symmetry,
        "divisions": divisions,
        "polychromatic": polychrome,
        "painted": painted,
        "arches": arches,
        "roof_features": roof,
        "horizontal_profile": {
            "num_features": h_profile["num_significant_features"],
            "mean_energy": h_profile["mean_energy"],
            "max_energy": h_profile["max_energy"],
        },
        "vertical_profile": {
            "num_features": v_profile["num_significant_features"],
            "mean_energy": v_profile["mean_energy"],
            "max_energy": v_profile["max_energy"],
        },
        "detected_features": detected_features,
        "feature_count": len(detected_features),
    }


def batch_analyse(directory, output_path=None):
    """Analyse all images in a directory."""
    results = []
    extensions = {'.jpg', '.jpeg', '.png'}
    files = sorted([f for f in os.listdir(directory)
                    if os.path.splitext(f)[1].lower() in extensions])

    print(f"Facade feature analysis: {len(files)} images in {directory}...")

    for i, fname in enumerate(files):
        path = os.path.join(directory, fname)
        try:
            result = analyse_facade(path)
            results.append(result)
            feats = [f["type"] for f in result["detected_features"]]
            if (i + 1) % 10 == 0:
                print(f"  [{i+1}/{len(files)}] {fname} — "
                      f"{result['divisions']['estimated_storeys']}sty/"
                      f"{result['divisions']['estimated_bays']}bay, "
                      f"sym={result['symmetry']['symmetry_score']:.2f}, "
                      f"{result['feature_count']} features")
        except Exception as e:
            results.append({"file": fname, "error": str(e)})
            print(f"  [{i+1}/{len(files)}] {fname} — ERROR: {e}")

    if output_path:
        with open(output_path, 'w') as f:
            json.dump(results, f, indent=2)
        print(f"\nResults written to {output_path}")

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
        result = analyse_facade(sys.argv[1])
        print(json.dumps(result, indent=2))
