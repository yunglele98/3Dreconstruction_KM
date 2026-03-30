#!/usr/bin/env python3
"""
Extract facade textures from building photos and generate PBR maps.

Reads photo index, detects front facade plane via edge detection,
applies perspective transform for rectification, and generates
normal, roughness, and albedo maps for PBR rendering.
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import numpy as np

try:
    import cv2
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False


def load_photo_index(csv_path):
    """
    Load photo index from CSV.
    Returns dict mapping address → list of photo filenames.
    """
    address_to_photos = {}
    with open(csv_path, "r", encoding="utf-8") as f:
        lines = f.readlines()
        # Skip header
        for line in lines[1:]:
            parts = line.strip().split(",")
            if len(parts) >= 2:
                filename = parts[0].strip()
                address_or_location = parts[1].strip()
                if address_or_location and address_or_location not in ("address_or_location",):
                    if address_or_location not in address_to_photos:
                        address_to_photos[address_or_location] = []
                    address_to_photos[address_or_location].append(filename)
    return address_to_photos


def select_best_photo(photos, photo_dir):
    """
    Select best front-facing photo (prefer those without 'back', 'lane', 'side').
    Returns Path to selected photo or None if no valid photo found.
    """
    skip_keywords = ("back", "lane", "side", "rear")
    candidates = []
    for photo in photos:
        photo_path = photo_dir / photo
        if not photo_path.exists():
            continue
        # Prefer photos without skip keywords in filename
        lower_name = photo.lower()
        if not any(kw in lower_name for kw in skip_keywords):
            candidates.append(photo_path)

    # If no preferred candidates, use any existing photo
    if not candidates:
        for photo in photos:
            photo_path = photo_dir / photo
            if photo_path.exists():
                candidates.append(photo_path)

    return candidates[0] if candidates else None


def detect_facade_plane(image):
    """
    Detect front facade bounding box via edge detection.

    Args:
        image: OpenCV image (BGR)

    Returns:
        Tuple of (x, y, w, h) for detected facade, or None if no clear plane found.
    """
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    # Canny edge detection
    edges = cv2.Canny(gray, 50, 150)

    # Find contours
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    img_area = image.shape[0] * image.shape[1]
    min_area = img_area * 0.2

    best_rect = None
    best_area = 0

    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        area = w * h

        # Filter: large vertical rectangles
        if area > min_area and h > 0 and w > 0:
            aspect_ratio = h / w
            if aspect_ratio > 1.0 and area > best_area:
                best_rect = (x, y, w, h)
                best_area = area

    return best_rect


def rectify_facade(image, rect):
    """
    Apply perspective transform to rectify facade to orthographic view.

    Args:
        image: OpenCV image (BGR)
        rect: Tuple of (x, y, w, h) or None for full image

    Returns:
        Rectified image
    """
    if rect is None:
        return image

    x, y, w, h = rect

    # Source points: corners of detected rectangle
    src_pts = np.float32([
        [x, y],
        [x + w, y],
        [x + w, y + h],
        [x, y + h]
    ])

    # Destination points: full rectangle for output
    dst_pts = np.float32([
        [0, 0],
        [w, 0],
        [w, h],
        [0, h]
    ])

    # Compute perspective transform
    mat = cv2.getPerspectiveTransform(src_pts, dst_pts)
    rectified = cv2.warpPerspective(image, mat, (w, h))

    return rectified


def resize_to_target(image, target_size):
    """
    Resize image to target size (preserving aspect ratio, pad if needed).
    """
    h, w = image.shape[:2]
    scale = min(target_size / w, target_size / h)
    new_w = int(w * scale)
    new_h = int(h * scale)

    resized = cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_LANCZOS4)

    # Pad to target size
    padded = np.zeros((target_size, target_size, *image.shape[2:]), dtype=resized.dtype)
    y_off = (target_size - new_h) // 2
    x_off = (target_size - new_w) // 2
    padded[y_off:y_off + new_h, x_off:x_off + new_w] = resized

    return padded


def generate_normal_map(image):
    """
    Generate normal map from image via Sobel gradients.

    Returns:
        RGB normal map (uint8)
    """
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255.0

    # Compute gradients
    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)

    # Normalize gradients to normal map (X, Y, Z)
    gz = np.ones_like(gx)

    # Stack and normalize
    normal = np.stack([gx, gy, gz], axis=2)
    normal_mag = np.sqrt(np.sum(normal ** 2, axis=2, keepdims=True))
    normal_mag[normal_mag == 0] = 1.0
    normal = normal / normal_mag

    # Convert to RGB: normal range [-1, 1] → [0, 255]
    normal_rgb = ((normal + 1.0) / 2.0 * 255.0).astype(np.uint8)

    return normal_rgb


def generate_roughness_map(image):
    """
    Generate roughness map from local variance in image.

    Returns:
        Grayscale roughness map (uint8)
    """
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255.0

    # Compute local variance in 16x16 sliding window
    kernel_size = 16
    mean = cv2.blur(gray, (kernel_size, kernel_size))
    sqr = cv2.blur(gray ** 2, (kernel_size, kernel_size))
    variance = sqr - mean ** 2
    variance[variance < 0] = 0

    roughness = np.sqrt(variance)
    roughness_normalized = (roughness * 255.0).astype(np.uint8)

    return roughness_normalized


def generate_albedo_map(image, target_size):
    """
    Generate albedo map (rectified facade with gamma correction).

    Returns:
        BGR image (uint8)
    """
    # Gamma correction for better material appearance
    img_float = image.astype(np.float32) / 255.0
    gamma = 2.2
    albedo = np.power(img_float, 1.0 / gamma)
    albedo = (albedo * 255.0).astype(np.uint8)

    return albedo


def process_building(address, photos, photo_dir, output_dir, target_size, skip_existing, manifest):
    """
    Process a single building: load photo, rectify facade, generate PBR maps.

    Returns:
        Dict with processing result (or None if skipped)
    """
    # Select best photo
    best_photo = select_best_photo(photos, photo_dir)
    if best_photo is None:
        print(f"  [SKIP] No valid photo found for {address}")
        return None

    # Check if already exists
    address_safe = address.replace(" ", "_").replace("/", "_")
    facade_path = output_dir / f"{address_safe}_facade.png"
    if skip_existing and facade_path.exists():
        print(f"  [SKIP] Textures already exist for {address}")
        return None

    # Load image
    image = cv2.imread(str(best_photo))
    if image is None:
        print(f"  [ERROR] Failed to load photo: {best_photo}")
        return None

    print(f"  Processing {address}")
    print(f"    Photo: {best_photo.name}")

    # Detect facade plane
    rect = detect_facade_plane(image)
    facade_detected = rect is not None
    if rect:
        print(f"    Facade detected: {rect}")
    else:
        print(f"    No facade detected, using full image")

    # Rectify facade
    rectified = rectify_facade(image, rect)

    # Resize to target
    rectified = resize_to_target(rectified, target_size)

    # Save facade texture
    cv2.imwrite(str(facade_path), rectified)
    h, w = rectified.shape[:2]

    # Generate PBR maps
    normal_map = generate_normal_map(rectified)
    normal_path = output_dir / f"{address_safe}_normal.png"
    cv2.imwrite(str(normal_path), normal_map)

    roughness_map = generate_roughness_map(rectified)
    roughness_path = output_dir / f"{address_safe}_roughness.png"
    cv2.imwrite(str(roughness_path), roughness_map)

    albedo_map = generate_albedo_map(rectified, target_size)
    albedo_path = output_dir / f"{address_safe}_albedo.png"
    cv2.imwrite(str(albedo_path), albedo_map)

    result = {
        "address": address,
        "source_photo": best_photo.name,
        "facade_detected": facade_detected,
        "output_files": {
            "facade": facade_path.name,
            "normal": normal_path.name,
            "roughness": roughness_path.name,
            "albedo": albedo_path.name
        },
        "dimensions_px": [w, h],
        "timestamp": datetime.now().isoformat()
    }

    manifest.append(result)
    print(f"    Done: {w}x{h}px")

    return result


def main():
    parser = argparse.ArgumentParser(
        description="Extract facade textures from building photos and generate PBR maps."
    )
    parser.add_argument(
        "--address",
        type=str,
        help="Single address to process (e.g., '160 Baldwin St')"
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Process all buildings with photos"
    )
    parser.add_argument(
        "--output-size",
        type=int,
        default=2048,
        help="Target texture resolution (default 2048)"
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="Skip buildings with existing textures"
    )

    args = parser.parse_args()

    if not HAS_CV2:
        print("ERROR: opencv-python (cv2) is required but not installed.", file=sys.stderr)
        print("Install with: pip install opencv-python numpy", file=sys.stderr)
        sys.exit(1)

    if not args.address and not args.all:
        parser.print_help()
        sys.exit(1)

    # Resolve paths
    base_dir = Path(__file__).parent.parent
    photo_dir = base_dir / "PHOTOS KENSINGTON"
    csv_path = photo_dir / "csv" / "photo_address_index.csv"
    output_dir = base_dir / "outputs" / "textures"

    if not csv_path.exists():
        print(f"ERROR: Photo index not found: {csv_path}", file=sys.stderr)
        sys.exit(1)

    if not photo_dir.exists():
        print(f"ERROR: Photo directory not found: {photo_dir}", file=sys.stderr)
        sys.exit(1)

    output_dir.mkdir(parents=True, exist_ok=True)

    # Load photo index
    print("Loading photo index...")
    address_to_photos = load_photo_index(csv_path)
    print(f"Loaded {len(address_to_photos)} buildings with photos")

    manifest = []

    if args.address:
        # Process single address
        if args.address not in address_to_photos:
            print(f"ERROR: Address not found in photo index: {args.address}", file=sys.stderr)
            sys.exit(1)

        photos = address_to_photos[args.address]
        process_building(
            args.address, photos, photo_dir, output_dir,
            args.output_size, args.skip_existing, manifest
        )

    elif args.all:
        # Process all buildings
        print(f"Processing {len(address_to_photos)} buildings...")
        for i, (address, photos) in enumerate(sorted(address_to_photos.items()), 1):
            print(f"[{i}/{len(address_to_photos)}]")
            process_building(
                address, photos, photo_dir, output_dir,
                args.output_size, args.skip_existing, manifest
            )

    # Write manifest
    manifest_path = output_dir / "texture_manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    print(f"\nDone! Processed {len(manifest)} buildings")
    print(f"Manifest: {manifest_path}")
    print(f"Output directory: {output_dir}")


if __name__ == "__main__":
    main()
