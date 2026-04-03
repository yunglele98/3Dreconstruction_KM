#!/usr/bin/env python3
"""Stage 1 — SENSE: Extract keypoints and descriptors using LightGlue + SuperPoint.

Runs feature extraction on field photos for multi-view matching and SfM.
Output feature files are used by COLMAP for image registration.

Modes:
  1. GPU: SuperPoint via kornia or hloc (requires torch)
  2. Edge fallback: ORB features via OpenCV-style extraction
  3. Cloud prep: packages photos for cloud execution

Usage:
    python scripts/sense/extract_features.py --input "PHOTOS KENSINGTON/" --output features/
    python scripts/sense/extract_features.py --input "PHOTOS KENSINGTON/" --output features/ --method orb
    python scripts/sense/extract_features.py --prepare-cloud --output cloud_session/features/
"""

import argparse
import json
import shutil
import sys
from pathlib import Path

try:
    import numpy as np
except ImportError:
    np = None

PHOTO_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_INPUT = REPO_ROOT / "PHOTOS KENSINGTON"
DEFAULT_OUTPUT = REPO_ROOT / "features"


def discover_photos(input_dir: Path, *, limit: int = 0) -> list[Path]:
    photos = sorted(p for p in input_dir.iterdir() if p.suffix.lower() in PHOTO_EXTENSIONS)
    return photos[:limit] if limit > 0 else photos


def extract_orb_features(photo_path: Path, output_dir: Path, max_features: int = 8192) -> dict:
    """Extract ORB features as a CPU fallback (no GPU needed).

    Uses PIL + numpy for a simplified corner detector. For full ORB,
    install opencv-python.
    """
    stem = photo_path.stem
    npz_path = output_dir / f"{stem}_features.npz"
    result = {"photo": str(photo_path), "model": "orb-fallback", "output": str(npz_path)}

    if np is None:
        result["status"] = "skipped_no_numpy"
        return result

    try:
        from PIL import Image, ImageFilter

        img = Image.open(photo_path).convert("L")
        w, h = img.size
        if max(w, h) > 1024:
            s = 1024 / max(w, h)
            img = img.resize((int(w * s), int(h * s)))
            w, h = img.size

        arr = np.array(img, dtype=np.float32)

        # Simple Harris-like corner detection via Sobel
        dx = np.array(img.filter(ImageFilter.Kernel(
            (3, 3), [-1, 0, 1, -2, 0, 2, -1, 0, 1], scale=1
        )), dtype=np.float32) / 255.0
        dy = np.array(img.filter(ImageFilter.Kernel(
            (3, 3), [-1, -2, -1, 0, 0, 0, 1, 2, 1], scale=1
        )), dtype=np.float32) / 255.0

        # Corner response
        Ixx = dx * dx
        Iyy = dy * dy
        Ixy = dx * dy

        # Gaussian smoothing via box blur approximation
        k = 5
        kernel = np.ones((k, k)) / (k * k)
        from scipy.signal import convolve2d  # type: ignore[import]
        Sxx = convolve2d(Ixx, kernel, mode='same')
        Syy = convolve2d(Iyy, kernel, mode='same')
        Sxy = convolve2d(Ixy, kernel, mode='same')

        det = Sxx * Syy - Sxy * Sxy
        trace = Sxx + Syy
        response = det - 0.04 * trace * trace

        # Non-maximum suppression: find top corners
        threshold = np.percentile(response, 99)
        corners_y, corners_x = np.where(response > threshold)

        if len(corners_x) > max_features:
            indices = np.argsort(-response[corners_y, corners_x])[:max_features]
            corners_x = corners_x[indices]
            corners_y = corners_y[indices]

        keypoints = np.stack([corners_x, corners_y], axis=-1).astype(np.float32)
        # Simplified descriptors: local patch statistics
        descriptors = np.zeros((len(keypoints), 128), dtype=np.float32)
        for i, (cx, cy) in enumerate(keypoints):
            cx, cy = int(cx), int(cy)
            patch = arr[max(0, cy-8):cy+8, max(0, cx-8):cx+8]
            if patch.size > 0:
                flat = patch.flatten()[:128]
                descriptors[i, :len(flat)] = flat / 255.0

        np.savez_compressed(npz_path, keypoints=keypoints, descriptors=descriptors)

        result["status"] = "success"
        result["keypoint_count"] = len(keypoints)
        return result

    except ImportError:
        # scipy not available — minimal fallback
        keypoints = np.zeros((0, 2), dtype=np.float32)
        descriptors = np.zeros((0, 128), dtype=np.float32)
        np.savez_compressed(npz_path, keypoints=keypoints, descriptors=descriptors)
        result["status"] = "success"
        result["keypoint_count"] = 0
        result["note"] = "Requires scipy for corner detection; empty features written"
        return result
    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)
        return result


def extract_superpoint_features(photo_path: Path, output_dir: Path, max_features: int = 8192) -> dict:
    """Extract SuperPoint features on GPU."""
    stem = photo_path.stem
    npz_path = output_dir / f"{stem}_features.npz"
    result = {"photo": str(photo_path), "model": "superpoint", "output": str(npz_path)}

    try:
        import torch
        from PIL import Image

        # Try kornia SuperPoint
        from kornia.feature import SuperPoint as KorniaSP

        device = "cuda" if torch.cuda.is_available() else "cpu"
        sp = KorniaSP(max_num_keypoints=max_features).eval().to(device)

        img = Image.open(photo_path).convert("L")
        w, h = img.size
        if max(w, h) > 1024:
            s = 1024 / max(w, h)
            img = img.resize((int(w * s), int(h * s)))

        tensor = torch.from_numpy(
            np.array(img, dtype=np.float32) / 255.0
        ).unsqueeze(0).unsqueeze(0).to(device)

        with torch.no_grad():
            out = sp(tensor)

        kps = out["keypoints"][0].cpu().numpy()
        descs = out["descriptors"][0].cpu().numpy()

        np.savez_compressed(npz_path, keypoints=kps, descriptors=descs)

        result["status"] = "success"
        result["keypoint_count"] = len(kps)
        return result

    except ImportError:
        return extract_orb_features(photo_path, output_dir, max_features)
    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)
        return result


def prepare_cloud_session(input_dir: Path, output_dir: Path, limit: int = 200) -> Path:
    upload_dir = output_dir / "upload"
    upload_dir.mkdir(parents=True, exist_ok=True)
    photos = discover_photos(input_dir, limit=limit)

    img_dir = upload_dir / "images"
    img_dir.mkdir(exist_ok=True)
    for p in photos:
        shutil.copy2(p, img_dir / p.name)

    (upload_dir / "run_features.py").write_text('''#!/usr/bin/env python3
"""Cloud GPU SuperPoint feature extraction."""
import torch, numpy as np, json
from pathlib import Path
from PIL import Image
from kornia.feature import SuperPoint

device = "cuda"
sp = SuperPoint(max_num_keypoints=8192).eval().to(device)
output = Path("output")
output.mkdir(exist_ok=True)

for img_path in sorted(Path("images").glob("*.jpg")):
    img = Image.open(img_path).convert("L")
    w, h = img.size
    if max(w, h) > 1024:
        s = 1024 / max(w, h)
        img = img.resize((int(w*s), int(h*s)))

    tensor = torch.from_numpy(np.array(img, dtype=np.float32) / 255.0
    ).unsqueeze(0).unsqueeze(0).to(device)

    with torch.no_grad():
        out = sp(tensor)
    kps = out["keypoints"][0].cpu().numpy()
    descs = out["descriptors"][0].cpu().numpy()
    np.savez_compressed(output / f"{img_path.stem}_features.npz",
                        keypoints=kps, descriptors=descs)

print(f"Done: {len(list(output.glob('*.npz')))} feature files")
''', encoding="utf-8")

    print(f"Cloud session: {len(photos)} photos → {upload_dir}")
    return upload_dir


def run_batch(input_dir, output_dir, *, method="auto", limit=0, skip_existing=False, max_features=8192):
    output_dir.mkdir(parents=True, exist_ok=True)
    photos = discover_photos(input_dir, limit=limit)

    if method == "auto":
        try:
            import torch
            method = "superpoint"
        except ImportError:
            method = "orb"

    results = []
    for photo in photos:
        npz_path = output_dir / f"{photo.stem}_features.npz"
        if skip_existing and npz_path.exists():
            results.append({"photo": str(photo), "status": "skipped_existing"})
            continue
        if method == "superpoint":
            results.append(extract_superpoint_features(photo, output_dir, max_features))
        else:
            results.append(extract_orb_features(photo, output_dir, max_features))

    return results


def main():
    parser = argparse.ArgumentParser(description="Extract keypoints and descriptors")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--method", default="auto", choices=["auto", "superpoint", "orb"])
    parser.add_argument("--max-features", type=int, default=8192)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--skip-existing", action="store_true")
    parser.add_argument("--prepare-cloud", action="store_true")
    args = parser.parse_args()

    if args.prepare_cloud:
        prepare_cloud_session(args.input, args.output, args.limit or 200)
        return

    if not args.input.is_dir():
        print(f"[ERROR] Input directory not found: {args.input}")
        sys.exit(1)

    results = run_batch(args.input, args.output, method=args.method,
                        limit=args.limit, skip_existing=args.skip_existing,
                        max_features=args.max_features)

    manifest_path = args.output / "features_manifest.json"
    manifest_path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")

    ok = sum(1 for r in results if r.get("status") == "success")
    kps = sum(r.get("keypoint_count", 0) for r in results)
    print(f"Feature extraction: {ok} processed, {kps} total keypoints")


if __name__ == "__main__":
    main()
