#!/usr/bin/env python3
"""Detect and classify decorative architectural elements from facade photos.

Specialized analysis for heritage-significant elements:
- Cornices (dentil, bracketed, simple)
- Bargeboard (styles: ornate, simple, scrolled)
- String courses and belt courses
- Quoins (stone, brick contrasting)
- Voussoirs and arched lintels
- Bay windows (canted, box, oriel)
- Ornamental shingles
- Brackets and corbelling
- Polychromatic brickwork
- Window hoods and drip moulds

Usage:
    python scripts/sense/detect_decorative.py --photo facade.jpg
    python scripts/sense/detect_decorative.py --photo-dir "PHOTOS KENSINGTON/" --limit 50
    python scripts/sense/detect_decorative.py --params params/ --enrich --apply
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


def detect_cornice(img: np.ndarray, gray: np.ndarray) -> dict | None:
    """Detect cornice type and dimensions.

    Cornices appear as strong horizontal features at the roofline
    with shadow patterns indicating projection.
    """
    h, w = gray.shape
    # Top 12% of image
    top = gray[:int(h * 0.12), int(w * 0.1):int(w * 0.9)]
    if top.size == 0:
        return None

    # Strong horizontal edge = cornice
    row_diff = np.abs(np.diff(top.astype(np.float32), axis=0))
    max_edge = np.max(np.mean(row_diff, axis=1)) if row_diff.size > 0 else 0

    if max_edge < 15:
        return None

    # Classify cornice type from edge pattern
    edge_profile = np.mean(row_diff, axis=1)
    peak_count = np.sum(edge_profile > edge_profile.mean() + edge_profile.std())

    if peak_count >= 4:
        style = "dentil"
        height_mm = 250
        projection_mm = 200
    elif peak_count >= 2:
        style = "bracketed"
        height_mm = 200
        projection_mm = 180
    else:
        style = "simple"
        height_mm = 150
        projection_mm = 120

    # Estimate colour from cornice region
    cornice_strip = img[:int(h * 0.08), int(w * 0.2):int(w * 0.8)]
    if cornice_strip.size > 0:
        rgb = cornice_strip.reshape(-1, 3).mean(axis=0)
        colour_hex = f"#{int(rgb[0]):02x}{int(rgb[1]):02x}{int(rgb[2]):02x}"
    else:
        colour_hex = None

    return {
        "present": True,
        "style": style,
        "height_mm": height_mm,
        "projection_mm": projection_mm,
        "colour_hex": colour_hex,
        "confidence": min(1.0, max_edge / 50),
    }


def detect_bargeboard(img: np.ndarray, gray: np.ndarray) -> dict | None:
    """Detect bargeboard on gable roofs.

    Bargeboards appear along the rake (sloped edge) of gable roofs
    as decorative trim with characteristic silhouette patterns.
    """
    h, w = gray.shape
    top_20 = gray[:int(h * 0.2), :]
    if top_20.size == 0:
        return None

    # Check for gable (V-shaped brightness pattern)
    col_means = np.mean(top_20.astype(np.float32), axis=0)
    center = w // 2
    left_slope = col_means[:center]
    right_slope = col_means[center:]

    # Gable shows decreasing brightness toward peak
    if len(left_slope) < 10 or len(right_slope) < 10:
        return None

    left_trend = np.mean(np.diff(left_slope[-20:])) if len(left_slope) >= 20 else 0
    right_trend = np.mean(np.diff(right_slope[:20])) if len(right_slope) >= 20 else 0

    # Left should decrease (negative), right should increase (positive)
    if not (left_trend < -0.1 and right_trend > 0.1):
        return None

    # Classify complexity
    edge_region = gray[:int(h * 0.15), :]
    from PIL import Image, ImageFilter
    pil = Image.fromarray(edge_region)
    edges = np.array(pil.filter(ImageFilter.FIND_EDGES), dtype=np.float32)
    edge_density = np.mean(edges)

    if edge_density > 25:
        style = "ornate"
    elif edge_density > 15:
        style = "scrolled"
    else:
        style = "simple"

    # Bargeboard colour
    rake_strip = img[:int(h * 0.1), int(w * 0.3):int(w * 0.7)]
    if rake_strip.size > 0:
        rgb = rake_strip.reshape(-1, 3).mean(axis=0)
        colour_hex = f"#{int(rgb[0]):02x}{int(rgb[1]):02x}{int(rgb[2]):02x}"
    else:
        colour_hex = None

    return {
        "present": True,
        "style": style,
        "colour_hex": colour_hex,
        "width_mm": 200 if style == "ornate" else 150,
        "confidence": min(1.0, edge_density / 30),
    }


def detect_string_courses(img: np.ndarray, gray: np.ndarray) -> dict | None:
    """Detect horizontal string courses / belt courses.

    String courses are thin horizontal bands between floors,
    often in contrasting stone or brick.
    """
    h, w = gray.shape
    facade = gray[int(h * 0.15):int(h * 0.85), int(w * 0.1):int(w * 0.9)]
    if facade.size == 0:
        return None

    # Horizontal profile
    row_means = np.mean(facade.astype(np.float32), axis=1)
    row_diff = np.abs(np.diff(row_means))

    # String courses create sharp brightness changes
    threshold = row_diff.mean() + 2 * row_diff.std()
    strong_lines = np.sum(row_diff > threshold)

    if strong_lines < 2:
        return None

    return {
        "present": True,
        "count": int(strong_lines // 2),  # Each course has 2 edges
        "width_mm": 100,
        "projection_mm": 30,
        "confidence": min(1.0, strong_lines / 6),
    }


def detect_quoins(img: np.ndarray, gray: np.ndarray) -> dict | None:
    """Detect quoins at building corners.

    Quoins appear as alternating large blocks at facade edges,
    often in contrasting stone colour.
    """
    h, w = gray.shape
    # Left and right 8% strips
    left_strip = gray[int(h * 0.15):int(h * 0.8), :int(w * 0.08)]
    right_strip = gray[int(h * 0.15):int(h * 0.8), int(w * 0.92):]
    center_strip = gray[int(h * 0.15):int(h * 0.8), int(w * 0.4):int(w * 0.6)]

    if left_strip.size == 0 or center_strip.size == 0:
        return None

    # Quoins: edge strips have different brightness pattern than center
    left_var = np.var(left_strip.astype(np.float32))
    right_var = np.var(right_strip.astype(np.float32))
    center_var = np.var(center_strip.astype(np.float32))

    # Quoins create higher variance at edges (alternating blocks)
    if max(left_var, right_var) > center_var * 1.5:
        # Estimate quoin colour
        edge_pixels = np.concatenate([
            img[int(h * 0.3):int(h * 0.5), :int(w * 0.06)].reshape(-1, 3),
            img[int(h * 0.3):int(h * 0.5), int(w * 0.94):].reshape(-1, 3),
        ], axis=0)
        if edge_pixels.size > 0:
            rgb = edge_pixels.mean(axis=0)
            colour_hex = f"#{int(rgb[0]):02x}{int(rgb[1]):02x}{int(rgb[2]):02x}"
        else:
            colour_hex = None

        return {
            "present": True,
            "strip_width_mm": 200,
            "projection_mm": 20,
            "colour_hex": colour_hex,
            "confidence": min(1.0, max(left_var, right_var) / center_var / 2),
        }

    return None


def detect_voussoirs(gray: np.ndarray) -> dict | None:
    """Detect voussoirs / arched window headers.

    Voussoirs appear as fan-shaped stone elements above windows,
    creating arc patterns in the facade.
    """
    h, w = gray.shape
    # Focus on upper-mid facade where window headers are
    header_region = gray[int(h * 0.2):int(h * 0.5), int(w * 0.1):int(w * 0.9)]
    if header_region.size == 0:
        return None

    # Arc patterns: column-wise variance in narrow horizontal bands
    rh = header_region.shape[0]
    band_h = max(1, rh // 10)
    band_variances = []
    for i in range(0, rh - band_h, band_h):
        band = header_region[i:i + band_h, :]
        band_variances.append(np.var(band.astype(np.float32)))

    if not band_variances:
        return None

    # Voussoirs create alternating high/low variance bands
    var_diff = np.abs(np.diff(band_variances))
    oscillation = np.mean(var_diff)

    if oscillation > 200:
        return {
            "present": True,
            "colour_hex": None,  # Would need colour analysis
            "confidence": min(1.0, oscillation / 500),
        }

    return None


def detect_bay_window(img: np.ndarray, gray: np.ndarray) -> dict | None:
    """Detect bay windows from shadow/depth patterns."""
    h, w = gray.shape
    mid = gray[int(h * 0.3):int(h * 0.7), :]
    if mid.size == 0:
        return None

    # Bay windows create horizontal brightness variation
    col_means = np.mean(mid.astype(np.float32), axis=0)

    # Find brightest contiguous region (bay projects forward = catches more light)
    threshold = col_means.mean() + 0.5 * col_means.std()
    above = col_means > threshold

    # Find longest contiguous run above threshold
    max_run = 0
    current_run = 0
    run_start = 0
    best_start = 0
    for i, v in enumerate(above):
        if v:
            if current_run == 0:
                run_start = i
            current_run += 1
            if current_run > max_run:
                max_run = current_run
                best_start = run_start
        else:
            current_run = 0

    # Bay window: bright region covering 20-50% of facade width
    bay_pct = max_run / w
    if 0.2 < bay_pct < 0.5 and max_run > 30:
        center_pct = (best_start + max_run / 2) / w
        if center_pct < 0.35:
            position = "left"
        elif center_pct > 0.65:
            position = "right"
        else:
            position = "center"

        return {
            "present": True,
            "type": "canted",
            "width_pct": round(bay_pct * 100, 1),
            "position": position,
            "confidence": min(1.0, bay_pct * 3),
        }

    return None


def analyze_decorative(image_path: Path) -> dict:
    """Run all decorative element detectors on a single photo."""
    from PIL import Image

    img = Image.open(image_path).convert("RGB")
    max_side = 1024
    w, h = img.size
    if max(w, h) > max_side:
        scale = max_side / max(w, h)
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)

    img_array = np.array(img)
    gray = np.mean(img_array, axis=2).astype(np.uint8)

    elements = {}

    detectors = [
        ("cornice", detect_cornice),
        ("bargeboard", detect_bargeboard),
        ("string_courses", detect_string_courses),
        ("quoins", detect_quoins),
        ("stone_voussoirs", detect_voussoirs),
        ("bay_window", detect_bay_window),
    ]

    for name, detector in detectors:
        try:
            if name in ("cornice", "bargeboard", "bay_window"):
                result = detector(img_array, gray)
            elif name == "stone_voussoirs":
                result = detector(gray)
            else:
                result = detector(img_array, gray)

            if result:
                elements[name] = result
        except Exception as e:
            logger.warning(f"Detector {name} failed: {e}")

    return {
        "source_photo": image_path.name,
        "decorative_elements_detected": elements,
        "element_count": len(elements),
    }


def enrich_params_decorative(
    params_dir: Path,
    photo_dir: Path,
    apply: bool = False,
) -> dict:
    """Analyze photos and enrich params with decorative element detections."""
    import csv
    from collections import defaultdict

    photo_index_path = REPO_ROOT / "PHOTOS KENSINGTON" / "csv" / "photo_address_index.csv"
    photo_index = defaultdict(list)
    if photo_index_path.exists():
        with open(photo_index_path, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                addr = (row.get("address_or_location") or "").strip().lower()
                fname = (row.get("filename") or "").strip()
                if addr and fname:
                    photo_index[addr].append(fname)

    stats = {"analyzed": 0, "enriched": 0, "skipped": 0}

    for param_file in sorted(params_dir.glob("*.json")):
        if param_file.name.startswith("_"):
            continue
        try:
            data = json.loads(param_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if data.get("skipped"):
            continue

        address = data.get("_meta", {}).get("address") or data.get("building_name", param_file.stem)
        photos = photo_index.get(address.lower(), [])
        if not photos:
            stats["skipped"] += 1
            continue

        # Analyze first available photo
        photo_path = photo_dir / photos[0]
        if not photo_path.exists():
            stats["skipped"] += 1
            continue

        try:
            result = analyze_decorative(photo_path)
            stats["analyzed"] += 1

            detected = result.get("decorative_elements_detected", {})
            if not detected:
                continue

            # Merge into decorative_elements (only add missing)
            dec = data.get("decorative_elements", {})
            changed = False
            for elem_name, elem_data in detected.items():
                if elem_name not in dec or not dec[elem_name].get("present"):
                    dec[elem_name] = elem_data
                    changed = True

            if changed:
                data["decorative_elements"] = dec
                if apply:
                    param_file.write_text(
                        json.dumps(data, indent=2, ensure_ascii=False),
                        encoding="utf-8",
                    )
                stats["enriched"] += 1

        except Exception as e:
            logger.warning(f"Error analyzing {address}: {e}")

    return stats


def main():
    parser = argparse.ArgumentParser(description="Detect decorative elements from photos")
    parser.add_argument("--photo", type=Path, default=None)
    parser.add_argument("--photo-dir", type=Path, default=None)
    parser.add_argument("--params", type=Path, default=None)
    parser.add_argument("--enrich", action="store_true", help="Enrich params from photo analysis")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if args.photo:
        result = analyze_decorative(args.photo)
        print(json.dumps(result, indent=2))
        return

    if args.params and args.enrich:
        photo_dir = REPO_ROOT / "PHOTOS KENSINGTON"
        stats = enrich_params_decorative(args.params, photo_dir, args.apply)
        print(f"Decorative enrichment ({'APPLIED' if args.apply else 'DRY RUN'}): {stats}")
        return

    if args.photo_dir:
        photos = [f for f in sorted(args.photo_dir.iterdir())
                  if f.suffix.lower() in SUPPORTED_EXTS]
        if args.limit:
            photos = photos[:args.limit]

        for photo in photos:
            result = analyze_decorative(photo)
            elements = result.get("decorative_elements_detected", {})
            if elements:
                print(f"  {photo.name}: {', '.join(elements.keys())}")


if __name__ == "__main__":
    main()
