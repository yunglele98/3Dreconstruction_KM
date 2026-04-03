"""
segment_facades.py -- Detect architectural elements in Kensington Market field photos.

Uses YOLOv11 (ultralytics) for occlusion detection (cars, persons, trucks) and
contour analysis for window/door detection, since COCO has no "window" class.

Usage:
    python scripts/sense/segment_facades.py [--limit N] [--input-dir PATH]
                                             [--output-dir PATH] [--annotate]
"""

import argparse
import json
import sys
import traceback
from pathlib import Path

import cv2
import numpy as np

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_INPUT_DIR = Path("PHOTOS KENSINGTON sorted")
DEFAULT_OUTPUT_DIR = Path("segmentation")
PHOTO_GLOB = "**/*.jpg"

# COCO class IDs relevant to building facades (occlusion markers)
# 0=person, 2=car, 7=truck, 5=bus, 3=motorcycle, 1=bicycle
COCO_OCCLUSION_CLASSES = {
    0: "person",
    2: "car",
    3: "motorcycle",
    5: "bus",
    7: "truck",
}

# Custom YOLO facade classes (from data/training/classes.txt)
FACADE_CLASSES = [
    "wall", "window", "door", "roof", "balcony", "shop", "cornice",
    "pilaster", "column", "molding", "sill", "lintel", "arch",
    "shutter", "awning", "sign", "chimney", "bay_window", "porch",
    "foundation", "gutter", "downspout", "fire_escape",
]

# Window contour detection parameters
WINDOW_ASPECT_MIN = 0.7     # width/height -- can be nearly square or taller
WINDOW_ASPECT_MAX = 4.0     # max width/height (some wide windows)
WINDOW_MIN_AREA_FRAC = 0.0004  # min fraction of image area (tuned for 12MP field photos)
WINDOW_MAX_AREA_FRAC = 0.15   # max fraction of image area (not a door or whole wall)

# Door detection parameters -- larger, ground-level rectangles
DOOR_ASPECT_MIN = 0.2       # doors are taller than wide
DOOR_ASPECT_MAX = 1.2
DOOR_MIN_AREA_FRAC = 0.001  # tuned for 12MP field photos
DOOR_MAX_AREA_FRAC = 0.20
DOOR_GROUND_FRAC = 0.55     # door bottom must be in lower 45% of image

# Floor clustering: group elements by Y-band
FLOOR_BAND_FRAC = 0.18      # fraction of image height per floor band

# Storefront: dark region must span >70% of width in storefront zone
STOREFRONT_FRAC = 0.70

# Confidence assigned to contour-detected elements (not a model score)
CONTOUR_CONFIDENCE = 0.75
DOOR_CONFIDENCE = 0.70

# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------

def safe_print(msg: str) -> None:
    """Print with cp1252-safe encoding (no unicode arrows/symbols)."""
    try:
        print(msg)
        sys.stdout.flush()
    except UnicodeEncodeError:
        print(msg.encode("ascii", errors="replace").decode("ascii"))
        sys.stdout.flush()


def load_yolo_model(weights: str | None = None):
    """Load YOLOv11 model. Uses custom weights if provided, else COCO pretrained.

    Args:
        weights: Path to custom .pt weights (e.g. from train_yolo_facade.py).
                 If None, loads yolo11n.pt (COCO pretrained).

    Returns model or None on failure.
    """
    try:
        from ultralytics import YOLO
        model_path = weights or "yolo11n.pt"
        model = YOLO(model_path)
        safe_print(f"  YOLO model loaded: {model_path}")
        return model
    except Exception as exc:
        safe_print(f"[WARN] Could not load YOLO model: {exc}")
        safe_print("[WARN] Occlusion detection will be skipped.")
        return None


# ---------------------------------------------------------------------------
# YOLO occlusion detection
# ---------------------------------------------------------------------------

def detect_occlusions(model, image_path: Path) -> list:
    """
    Run YOLO on the image and return a deduplicated list of occlusion class names
    found (person, car, truck, etc.).
    """
    if model is None:
        return []
    try:
        results = model.predict(
            source=str(image_path),
            verbose=False,
            conf=0.35,
            iou=0.45,
        )
        found = set()
        for result in results:
            if result.boxes is None:
                continue
            for cls_id in result.boxes.cls.cpu().numpy().astype(int):
                if cls_id in COCO_OCCLUSION_CLASSES:
                    found.add(COCO_OCCLUSION_CLASSES[cls_id])
        return sorted(found)
    except Exception as exc:
        safe_print(f"  [WARN] YOLO inference failed for {image_path.name}: {exc}")
        return []


# ---------------------------------------------------------------------------
# Custom YOLO facade element detection (trained on Kensington data)
# ---------------------------------------------------------------------------

def detect_facade_elements_yolo(model, image_path: Path, image_hw: tuple) -> list:
    """
    Run a custom-trained YOLO facade model on the image.
    Returns list of element dicts with class, bbox, confidence, floor.
    """
    if model is None:
        return []
    try:
        results = model.predict(
            source=str(image_path),
            verbose=False,
            conf=0.25,
            iou=0.45,
        )
        elements = []
        h_img, w_img = image_hw
        for result in results:
            if result.boxes is None:
                continue
            for i, box in enumerate(result.boxes):
                cls_id = int(box.cls[0])
                conf = float(box.conf[0])
                x1, y1, x2, y2 = [int(v) for v in box.xyxy[0].tolist()]

                cls_name = model.names.get(cls_id, f"class_{cls_id}")

                # Skip non-architectural detections
                if cls_name in ("person", "car", "truck", "bus", "motorcycle", "bicycle"):
                    continue

                elements.append({
                    "class": cls_name,
                    "bbox": [x1, y1, x2, y2],
                    "confidence": round(conf, 3),
                    "floor": None,
                })
        return elements
    except Exception as exc:
        safe_print(f"  [WARN] Custom YOLO inference failed for {image_path.name}: {exc}")
        return []


# ---------------------------------------------------------------------------
# Contour-based window / door detection
# ---------------------------------------------------------------------------

def preprocess_for_dark_regions(bgr: np.ndarray) -> np.ndarray:
    """
    Convert to grayscale, apply CLAHE, then threshold to isolate dark regions
    (windows are darker than surrounding masonry/stucco).
    Returns a binary mask where dark regions are white.
    """
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
    eq = clahe.apply(gray)
    # Adaptive threshold -- works better than global for varied lighting
    thresh = cv2.adaptiveThreshold(
        eq, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV,
        blockSize=31,
        C=8,
    )
    # Morphological close to fill gaps inside window panes
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    closed = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel, iterations=2)
    # Remove tiny noise
    opened = cv2.morphologyEx(closed, cv2.MORPH_OPEN, kernel, iterations=1)
    return opened


def rect_from_contour(contour) -> tuple:
    """Return (x1, y1, x2, y2) bounding rect for a contour."""
    x, y, w, h = cv2.boundingRect(contour)
    return x, y, x + w, y + h


def is_rectangular(contour, tolerance: float = 0.75) -> bool:
    """Check that contour fills at least `tolerance` of its bounding rect."""
    area = cv2.contourArea(contour)
    x, y, w, h = cv2.boundingRect(contour)
    rect_area = w * h
    if rect_area == 0:
        return False
    return (area / rect_area) >= tolerance


def detect_windows(bgr: np.ndarray) -> list:
    """
    Detect window-like rectangular dark regions.
    Returns list of element dicts.
    """
    h, w = bgr.shape[:2]
    image_area = h * w
    mask = preprocess_for_dark_regions(bgr)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    elements = []
    for cnt in contours:
        area = cv2.contourArea(cnt)
        area_frac = area / image_area
        if area_frac < WINDOW_MIN_AREA_FRAC or area_frac > WINDOW_MAX_AREA_FRAC:
            continue
        if not is_rectangular(cnt, tolerance=0.65):
            continue
        x1, y1, x2, y2 = rect_from_contour(cnt)
        bw = x2 - x1
        bh = y2 - y1
        if bh == 0:
            continue
        aspect = bw / bh  # width / height
        if aspect < WINDOW_ASPECT_MIN or aspect > WINDOW_ASPECT_MAX:
            continue
        elements.append({
            "class": "window",
            "bbox": [x1, y1, x2, y2],
            "confidence": CONTOUR_CONFIDENCE,
            "floor": None,  # assigned later
        })
    return elements


def detect_doors(bgr: np.ndarray) -> list:
    """
    Detect door-like regions: larger, taller-than-wide, near ground level.
    Returns list of element dicts.
    """
    h, w = bgr.shape[:2]
    image_area = h * w
    mask = preprocess_for_dark_regions(bgr)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    elements = []
    for cnt in contours:
        area = cv2.contourArea(cnt)
        area_frac = area / image_area
        if area_frac < DOOR_MIN_AREA_FRAC or area_frac > DOOR_MAX_AREA_FRAC:
            continue
        if not is_rectangular(cnt, tolerance=0.60):
            continue
        x1, y1, x2, y2 = rect_from_contour(cnt)
        bw = x2 - x1
        bh = y2 - y1
        if bh == 0:
            continue
        aspect = bw / bh
        if aspect < DOOR_ASPECT_MIN or aspect > DOOR_ASPECT_MAX:
            continue
        # Bottom of door must be in lower portion of image
        if (y2 / h) < DOOR_GROUND_FRAC:
            continue
        elements.append({
            "class": "door",
            "bbox": [x1, y1, x2, y2],
            "confidence": DOOR_CONFIDENCE,
            "floor": 1,  # doors are always ground floor
        })
    return elements


# ---------------------------------------------------------------------------
# Floor assignment
# ---------------------------------------------------------------------------

def assign_floors(elements: list, image_height: int) -> list:
    """
    Assign floor numbers to elements based on their vertical midpoint.
    Floor 1 = bottom band, increasing upward.
    """
    band_px = image_height * FLOOR_BAND_FRAC
    for el in elements:
        if el.get("floor") is not None:
            continue
        x1, y1, x2, y2 = el["bbox"]
        mid_y = (y1 + y2) / 2.0
        # Invert: bottom of image = floor 1
        dist_from_bottom = image_height - mid_y
        floor = max(1, int(dist_from_bottom / band_px) + 1)
        el["floor"] = floor
    return elements


def count_windows_by_floor(elements: list) -> dict:
    counts = {}
    for el in elements:
        if el["class"] == "window":
            floor_key = str(el.get("floor", 1))
            counts[floor_key] = counts.get(floor_key, 0) + 1
    return counts


# ---------------------------------------------------------------------------
# Storefront detection
# ---------------------------------------------------------------------------

def detect_storefront(bgr: np.ndarray) -> bool:
    """
    Heuristic: check if the storefront zone (50-80% down) has a wide, dark,
    low-saturation region typical of glass storefronts.
    Uses absolute brightness threshold to avoid false positives from shadows.
    """
    h, w = bgr.shape[:2]
    y_start = int(h * 0.50)
    y_end = int(h * 0.80)
    strip = bgr[y_start:y_end, :]
    strip_h = y_end - y_start

    # Skip if overall scene is dark (night/dusk photos trigger false positives)
    gray = cv2.cvtColor(strip, cv2.COLOR_BGR2GRAY)
    if np.median(gray) < 80:
        return False

    # Absolute brightness threshold -- storefront glass is genuinely dark
    _, dark_mask = cv2.threshold(gray, 35, 255, cv2.THRESH_BINARY_INV)

    # Close gaps in storefront glass
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (15, 5))
    closed = cv2.morphologyEx(dark_mask, cv2.MORPH_CLOSE, kernel, iterations=2)

    contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for cnt in contours:
        _, _, cw, ch = cv2.boundingRect(cnt)
        area = cv2.contourArea(cnt)
        area_frac = area / (w * strip_h) if (w * strip_h) > 0 else 0
        if cw / w >= STOREFRONT_FRAC and ch / strip_h >= 0.30 and area_frac >= 0.12:
            return True
    return False


# ---------------------------------------------------------------------------
# Annotation drawing
# ---------------------------------------------------------------------------

CLASS_COLORS = {
    "window":       (255, 165,   0),   # orange (BGR)
    "door":         (  0, 200,  50),   # green
    "person":       (  0,   0, 255),   # red
    "car":          (255,   0,   0),   # blue
    "truck":        (180,   0, 180),   # purple
    "bus":          (180, 100,   0),
    "motorcycle":   (  0, 180, 180),
    # Custom facade classes
    "wall":         (200, 200, 200),
    "roof":         (153,  51, 102),
    "balcony":      ( 51, 153, 255),
    "shop":         (255, 153,   0),
    "storefront":   (255, 153,   0),
    "cornice":      (204,   0, 204),
    "pilaster":     (102, 153,  51),
    "column":       (153, 102,  51),
    "molding":      (153, 102, 204),
    "sill":         ( 51, 153, 102),
    "lintel":       (102,  51, 153),
    "arch":         ( 51, 102,  51),
    "shutter":      (102, 102, 153),
    "awning":       (153, 102, 102),
    "sign":         ( 51, 153, 204),
    "chimney":      ( 51,  51, 153),
    "bay_window":   (  0, 204, 255),
    "porch":        (204, 204,   0),
    "bargeboard":   (102,  51, 255),
    "foundation":   (102, 153, 153),
    "gutter":       (153, 153, 102),
    "downspout":    (153, 153, 153),
    "fire_escape":  ( 51,  51, 204),
}
DEFAULT_COLOR = (200, 200, 200)


def draw_annotations(bgr: np.ndarray, elements: list) -> np.ndarray:
    annotated = bgr.copy()
    for el in elements:
        x1, y1, x2, y2 = el["bbox"]
        color = CLASS_COLORS.get(el["class"], DEFAULT_COLOR)
        cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 2)
        label = el["class"]
        if el.get("floor") is not None:
            label += f" F{el['floor']}"
        conf = el.get("confidence", 0.0)
        label += f" {conf:.2f}"
        cv2.putText(
            annotated, label,
            (x1, max(y1 - 6, 12)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.45, color, 1, cv2.LINE_AA,
        )
    return annotated


# ---------------------------------------------------------------------------
# Per-photo processing
# ---------------------------------------------------------------------------

def derive_address(photo_path: Path, input_dir: Path) -> str:
    """
    Attempt to derive a human-readable address from the directory structure.
    Expects: input_dir/<street>/<photo>.jpg
    """
    try:
        rel = photo_path.relative_to(input_dir)
        parts = rel.parts
        if len(parts) >= 2:
            return parts[-2]  # street folder name
        return parts[0]
    except ValueError:
        return photo_path.parent.name


def process_photo(
    photo_path: Path,
    input_dir: Path,
    output_dir: Path,
    model,
    annotate: bool,
    facade_model=None,
) -> bool:
    """
    Process a single photo. Returns True on success, False on error.
    Skips if output JSON already exists (unless force mode via facade_model).

    Args:
        facade_model: Custom-trained YOLO facade model. When provided,
                      uses model detections instead of contour heuristics.
    """
    stem = photo_path.stem
    json_out = output_dir / f"{stem}_elements.json"
    png_out = output_dir / f"{stem}_annotated.png"

    # When re-running with custom model, overwrite existing results
    if json_out.exists() and facade_model is None:
        return True  # idempotent skip

    bgr = cv2.imread(str(photo_path))
    if bgr is None:
        safe_print(f"  [WARN] Cannot read image: {photo_path}")
        return False

    h, w = bgr.shape[:2]

    # Occlusion detection via COCO-pretrained YOLO
    occlusions = detect_occlusions(model, photo_path)

    if facade_model is not None:
        # Use custom-trained YOLO for architectural element detection
        all_elements = detect_facade_elements_yolo(facade_model, photo_path, (h, w))
        detection_method = "custom_yolo"
    else:
        # Fallback: contour-based heuristic detection
        windows = detect_windows(bgr)
        doors = detect_doors(bgr)
        all_elements = windows + doors
        detection_method = "contour_heuristic"

    all_elements = assign_floors(all_elements, h)

    window_counts = count_windows_by_floor(all_elements)
    has_storefront = detect_storefront(bgr)
    address = derive_address(photo_path, input_dir)

    result = {
        "photo": photo_path.name,
        "address": address,
        "elements": all_elements,
        "window_count_by_floor": window_counts,
        "has_storefront": has_storefront,
        "occlusions": occlusions,
        "detection_method": detection_method,
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    with open(json_out, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)

    if annotate:
        annotated = draw_annotations(bgr, all_elements)
        cv2.imwrite(str(png_out), annotated)

    return True


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Detect architectural elements in Kensington Market field photos."
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=DEFAULT_INPUT_DIR,
        help="Root directory containing sorted street photo subdirectories.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory to write JSON (and optionally PNG) outputs.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Process at most N photos (useful for testing).",
    )
    parser.add_argument(
        "--annotate",
        action="store_true",
        help="Also save annotated PNG images with bounding boxes.",
    )
    parser.add_argument(
        "--custom-weights",
        type=Path,
        default=None,
        help="Path to custom-trained YOLO weights for facade elements. "
             "When provided, uses model detections instead of contour heuristics "
             "and overwrites existing segmentation results.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing segmentation results even without custom weights.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    input_dir: Path = args.input_dir
    output_dir: Path = args.output_dir

    if not input_dir.exists():
        safe_print(f"[ERROR] Input directory not found: {input_dir.resolve()}")
        sys.exit(1)

    photos = sorted(input_dir.glob(PHOTO_GLOB))
    if not photos:
        safe_print(f"[ERROR] No .jpg files found under {input_dir.resolve()}")
        sys.exit(1)

    if args.limit is not None:
        photos = photos[: args.limit]

    safe_print(f"Found {len(photos)} photos under {input_dir.resolve()}")
    safe_print(f"Output dir: {output_dir.resolve()}")
    if args.annotate:
        safe_print("Annotation mode: ON (saving annotated PNGs)")

    safe_print("Loading YOLO model (COCO, for occlusion detection) ...")
    model = load_yolo_model()
    safe_print("YOLO model ready." if model is not None else "Continuing without YOLO.")

    # Load custom facade model if provided
    facade_model = None
    if args.custom_weights:
        if not args.custom_weights.exists():
            safe_print(f"[ERROR] Custom weights not found: {args.custom_weights}")
            sys.exit(1)
        safe_print(f"Loading custom facade model: {args.custom_weights}")
        facade_model = load_yolo_model(str(args.custom_weights))
        if facade_model:
            safe_print(f"  Custom model classes: {list(facade_model.names.values())[:8]}...")
            safe_print("  Mode: CUSTOM YOLO (overwriting existing results)")
        else:
            safe_print("[WARN] Failed to load custom model, falling back to contours.")

    output_dir.mkdir(parents=True, exist_ok=True)

    success_count = 0
    error_count = 0
    skip_count = 0

    for idx, photo_path in enumerate(photos, start=1):
        stem = photo_path.stem
        json_out = output_dir / f"{stem}_elements.json"

        # Skip existing unless we have custom model or --force
        if json_out.exists() and facade_model is None and not args.force:
            skip_count += 1
            if idx % 50 == 0:
                safe_print(
                    f"  [{idx}/{len(photos)}] skipped (already done): {photo_path.name}"
                )
            continue

        try:
            ok = process_photo(
                photo_path, input_dir, output_dir, model, args.annotate,
                facade_model=facade_model,
            )
            if ok:
                success_count += 1
            else:
                error_count += 1
        except Exception:
            error_count += 1
            safe_print(f"  [ERROR] Unhandled exception on {photo_path.name}:")
            traceback.print_exc()

        if idx % 50 == 0:
            safe_print(
                f"  [{idx}/{len(photos)}] ok={success_count} "
                f"skip={skip_count} err={error_count} -- {photo_path.name}"
            )

    safe_print("")
    safe_print("=== Done ===")
    safe_print(f"  Total:    {len(photos)}")
    safe_print(f"  Success:  {success_count}")
    safe_print(f"  Skipped:  {skip_count}")
    safe_print(f"  Errors:   {error_count}")


if __name__ == "__main__":
    main()
