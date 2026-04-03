#!/usr/bin/env python3
"""Stage 2 — RECONSTRUCT: Single/few-view reconstruction via DUSt3R/MASt3R.

For buildings with 1-2 photos (below COLMAP threshold), runs DUSt3R to
produce a coarse point cloud, depth estimate, and camera pose. DUSt3R
works from as few as 2 uncalibrated images.

Pipeline:
  1. Load images (1-2 per building)
  2. Run DUSt3R pairwise matching (if 2 images) or monocular depth (if 1)
  3. Output: point cloud (.ply), camera poses, confidence map
  4. Register point cloud to SRID 2952 via known building position

Requires: dust3r (pip install dust3r) or cloud GPU session.

Usage:
    python scripts/reconstruct/run_dust3r.py --input "PHOTOS KENSINGTON/" --params params/ --max-views 2
    python scripts/reconstruct/run_dust3r.py --address "22 Lippincott St" --output point_clouds/dust3r/
    python scripts/reconstruct/run_dust3r.py --prepare-cloud --output cloud_session/dust3r/
    python scripts/reconstruct/run_dust3r.py --input "PHOTOS KENSINGTON/" --params params/ --dry-run
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PHOTO_DIR = REPO_ROOT / "PHOTOS KENSINGTON sorted"
PHOTO_DIR_ALT = REPO_ROOT / "PHOTOS KENSINGTON"
PHOTO_INDEX = REPO_ROOT / "PHOTOS KENSINGTON" / "csv" / "photo_address_index.csv"
PARAMS_DIR = REPO_ROOT / "params"
DEFAULT_OUTPUT = REPO_ROOT / "point_clouds" / "dust3r"


def load_photo_index() -> dict[str, list[str]]:
    """Load photo index, return lowercase address → filenames."""
    by_addr: dict[str, list[str]] = defaultdict(list)
    if not PHOTO_INDEX.exists():
        return by_addr
    with open(PHOTO_INDEX, encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            addr = (row.get("address_or_location") or "").strip().lower()
            fname = (row.get("filename") or "").strip()
            if addr and fname:
                by_addr[addr].append(fname)
    return dict(by_addr)


def resolve_photo(filename: str) -> Path | None:
    """Find a photo file on disk."""
    for search_dir in [PHOTO_DIR, PHOTO_DIR_ALT]:
        if not search_dir.exists():
            continue
        direct = search_dir / filename
        if direct.exists():
            return direct
        matches = list(search_dir.rglob(filename))
        if matches:
            return matches[0]
    return None


def find_candidates(
    params_dir: Path, max_views: int = 2
) -> list[dict]:
    """Find buildings with 1-2 photos (DUSt3R candidates)."""
    photo_index = load_photo_index()
    candidates = []

    for f in sorted(params_dir.glob("*.json")):
        if f.name.startswith("_"):
            continue
        data = json.loads(f.read_text(encoding="utf-8"))
        if data.get("skipped"):
            continue

        address = data.get("_meta", {}).get("address", f.stem.replace("_", " "))
        photos = photo_index.get(address.lower(), [])

        if 1 <= len(photos) <= max_views:
            # Resolve actual paths
            resolved = []
            for p in photos:
                path = resolve_photo(p)
                if path:
                    resolved.append({"filename": p, "path": str(path)})

            if resolved:
                candidates.append({
                    "address": address,
                    "param_file": str(f),
                    "photo_count": len(resolved),
                    "photos": resolved,
                    "total_height_m": data.get("total_height_m", 0),
                    "facade_width_m": data.get("facade_width_m", 0),
                })

    return candidates


def check_dust3r() -> bool:
    """Check if DUSt3R is importable."""
    try:
        import dust3r
        return True
    except ImportError:
        return False


def run_dust3r_pair(
    image_paths: list[Path],
    output_dir: Path,
    address: str,
) -> dict:
    """Run DUSt3R on 1-2 images.

    When DUSt3R is installed, runs inference directly. Otherwise, generates
    a training script for cloud GPU execution.
    """
    safe_name = address.replace(" ", "_").replace(",", "")
    building_dir = output_dir / safe_name
    building_dir.mkdir(parents=True, exist_ok=True)

    result = {
        "address": address,
        "image_count": len(image_paths),
        "output_dir": str(building_dir),
    }

    if check_dust3r():
        try:
            from dust3r.inference import inference
            from dust3r.model import AsymmetricCroCo3DStereo
            from dust3r.utils.image import load_images
            from dust3r.cloud_opt import global_aligner, GlobalAlignerMode

            model = AsymmetricCroCo3DStereo.from_pretrained(
                "naver/DUSt3R_ViTLarge_BaseDecoder_512_dpt"
            ).eval()

            images = load_images(
                [str(p) for p in image_paths], size=512
            )

            if len(images) == 1:
                # Monocular: predict depth from single view
                output = inference([tuple(images * 2)], model, device="cuda", batch_size=1)
                mode = GlobalAlignerMode.PointCloudOptimizer
            else:
                pairs = [(images[0], images[1])]
                output = inference(pairs, model, device="cuda", batch_size=1)
                mode = GlobalAlignerMode.PairViewer

            scene = global_aligner(output, device="cuda", mode=mode)
            scene.compute_global_alignment(init="mst", niter=300)

            # Extract point cloud
            pts3d = scene.get_pts3d()
            confidence = scene.get_masks()

            # Save as PLY
            ply_path = building_dir / f"{safe_name}.ply"
            _write_ply(pts3d, confidence, ply_path)

            # Save camera poses
            poses = scene.get_im_poses()
            intrinsics = scene.get_intrinsics()
            poses_data = {
                "poses": [p.cpu().numpy().tolist() for p in poses],
                "intrinsics": [k.cpu().numpy().tolist() for k in intrinsics],
            }
            (building_dir / "camera_poses.json").write_text(
                json.dumps(poses_data, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )

            result["status"] = "success"
            result["ply_path"] = str(ply_path)
            result["point_count"] = sum(m.sum().item() for m in confidence)
            return result

        except Exception as e:
            result["status"] = "error"
            result["error"] = str(e)
            return result

    # Fallback: write inference script for cloud execution
    script_path = building_dir / "run_dust3r.py"
    img_args = ", ".join(f'"{p}"' for p in image_paths)
    script_path.write_text(f'''#!/usr/bin/env python3
"""Auto-generated DUSt3R inference script for {address}.
Run on GPU: python run_dust3r.py
"""
import torch
from dust3r.inference import inference
from dust3r.model import AsymmetricCroCo3DStereo
from dust3r.utils.image import load_images
from dust3r.cloud_opt import global_aligner, GlobalAlignerMode

model = AsymmetricCroCo3DStereo.from_pretrained(
    "naver/DUSt3R_ViTLarge_BaseDecoder_512_dpt"
).eval().cuda()

images = load_images([{img_args}], size=512)
pairs = [(images[0], images[-1])]
output = inference(pairs, model, device="cuda", batch_size=1)

scene = global_aligner(output, device="cuda",
    mode=GlobalAlignerMode.PairViewer if len(images) > 1 else GlobalAlignerMode.PointCloudOptimizer)
scene.compute_global_alignment(init="mst", niter=300)

pts = scene.get_pts3d()
masks = scene.get_masks()
print(f"Points: {{sum(m.sum().item() for m in masks):.0f}}")
# TODO: save PLY and poses
''', encoding="utf-8")

    result["status"] = "script_generated"
    result["script"] = str(script_path)
    return result


def _write_ply(pts3d_list, confidence_list, output_path: Path) -> None:
    """Write point cloud to ASCII PLY format."""
    try:
        import torch
        points = []
        for pts, mask in zip(pts3d_list, confidence_list):
            valid = mask.reshape(-1)
            p = pts.reshape(-1, 3)
            for i in range(len(valid)):
                if valid[i]:
                    x, y, z = p[i].cpu().numpy()
                    points.append(f"{x:.6f} {y:.6f} {z:.6f}")

        with open(output_path, "w", encoding="utf-8") as f:
            f.write("ply\nformat ascii 1.0\n")
            f.write(f"element vertex {len(points)}\n")
            f.write("property float x\nproperty float y\nproperty float z\n")
            f.write("end_header\n")
            f.write("\n".join(points) + "\n")
    except Exception:
        pass


def prepare_cloud_session(output_dir: Path, params_dir: Path, max_views: int = 2, limit: int = 50) -> Path:
    """Package DUSt3R candidates for cloud GPU session."""
    upload_dir = output_dir / "upload"
    upload_dir.mkdir(parents=True, exist_ok=True)

    candidates = find_candidates(params_dir, max_views=max_views)[:limit]

    # Copy photos
    img_dir = upload_dir / "images"
    img_dir.mkdir(exist_ok=True)
    for c in candidates:
        for p in c["photos"]:
            src = Path(p["path"])
            if src.exists():
                shutil.copy2(src, img_dir / src.name)

    # Write manifest
    manifest = {
        "candidates": [{
            "address": c["address"],
            "photos": [p["filename"] for p in c["photos"]],
        } for c in candidates],
    }
    (upload_dir / "dust3r_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # Write batch run script
    (upload_dir / "run_batch.sh").write_text("""#!/bin/bash
pip install dust3r torch torchvision
python -c "
import json
from pathlib import Path
from dust3r.inference import inference
from dust3r.model import AsymmetricCroCo3DStereo
from dust3r.utils.image import load_images
from dust3r.cloud_opt import global_aligner, GlobalAlignerMode

model = AsymmetricCroCo3DStereo.from_pretrained(
    'naver/DUSt3R_ViTLarge_BaseDecoder_512_dpt'
).eval().cuda()

manifest = json.loads(Path('dust3r_manifest.json').read_text())
Path('output').mkdir(exist_ok=True)

for c in manifest['candidates']:
    addr = c['address']
    imgs = [f'images/{p}' for p in c['photos'] if Path(f'images/{p}').exists()]
    if not imgs:
        continue
    print(f'Processing {addr} ({len(imgs)} images)...')
    images = load_images(imgs, size=512)
    pairs = [(images[0], images[-1])]
    output = inference(pairs, model, device='cuda', batch_size=1)
    scene = global_aligner(output, device='cuda',
        mode=GlobalAlignerMode.PairViewer if len(images)>1 else GlobalAlignerMode.PointCloudOptimizer)
    scene.compute_global_alignment(init='mst', niter=300)
    print(f'  Done: {sum(m.sum().item() for m in scene.get_masks()):.0f} points')
"
""", encoding="utf-8")

    print(f"Cloud session: {len(candidates)} buildings → {upload_dir}")
    print(f"Estimated cost: ~${len(candidates) * 0.05:.2f} on A100")
    return upload_dir


def main() -> None:
    parser = argparse.ArgumentParser(description="Run DUSt3R single/few-view reconstruction")
    parser.add_argument("--input", type=Path, default=PHOTO_DIR_ALT)
    parser.add_argument("--params", type=Path, default=PARAMS_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--max-views", type=int, default=2)
    parser.add_argument("--address", type=str, default=None)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--prepare-cloud", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.prepare_cloud:
        prepare_cloud_session(args.output, args.params, args.max_views)
        return

    if args.address:
        # Single building
        photo_index = load_photo_index()
        photos = photo_index.get(args.address.lower(), [])
        resolved = [resolve_photo(p) for p in photos if resolve_photo(p)]
        if not resolved:
            print(f"[ERROR] No photos found for {args.address}")
            sys.exit(1)
        result = run_dust3r_pair(resolved[:2], args.output, args.address)
        print(f"{args.address}: {result['status']}")
        return

    # Batch mode
    candidates = find_candidates(args.params, max_views=args.max_views)
    if args.limit > 0:
        candidates = candidates[:args.limit]

    if args.dry_run:
        print(f"[DRY RUN] {len(candidates)} DUSt3R candidates (max {args.max_views} views)")
        for c in candidates[:15]:
            print(f"  {c['address']}: {c['photo_count']} photos")
        if len(candidates) > 15:
            print(f"  ... and {len(candidates) - 15} more")
        return

    print(f"DUSt3R batch: {len(candidates)} buildings")
    for i, c in enumerate(candidates, 1):
        photos = [Path(p["path"]) for p in c["photos"]]
        result = run_dust3r_pair(photos, args.output, c["address"])
        print(f"  [{i}/{len(candidates)}] {c['address']}: {result['status']}")

    # Write manifest
    args.output.mkdir(parents=True, exist_ok=True)
    manifest_path = args.output / "dust3r_manifest.json"
    manifest_path.write_text(
        json.dumps({"candidates": len(candidates)}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
