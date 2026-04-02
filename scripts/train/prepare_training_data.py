#!/usr/bin/env python3
"""Prepare best facade photos for annotation in Label Studio.

Selects top-N photos by quality (resolution, facade visibility, coverage)
and copies them to data/training/images/ for annotation. Generates a
Label Studio import manifest.

Usage:
    python scripts/train/prepare_training_data.py
    python scripts/train/prepare_training_data.py --limit 200 --output data/training/
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
from pathlib import Path

from PIL import Image

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PHOTO_DIR = REPO_ROOT / "PHOTOS KENSINGTON sorted"
PHOTO_INDEX = REPO_ROOT / "PHOTOS KENSINGTON" / "csv" / "photo_address_index.csv"
PARAMS_DIR = REPO_ROOT / "params"
OUTPUT_DIR = REPO_ROOT / "data" / "training"

# Facade segmentation classes
CLASSES = [
    "wall", "window", "door", "roof", "balcony", "shop", "cornice",
    "pilaster", "column", "molding", "sill", "lintel", "arch",
    "shutter", "awning", "sign", "chimney", "bay_window", "porch",
    "foundation", "gutter", "downspout", "fire_escape",
]


def load_photo_index():
    """Load photo-to-address mapping."""
    if not PHOTO_INDEX.exists():
        return {}
    mapping = {}
    with open(PHOTO_INDEX, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            fname = (row.get("filename") or "").strip()
            addr = (row.get("address_or_location") or "").strip()
            if fname and addr:
                mapping[fname] = addr
    return mapping


def find_photo_on_disk(filename):
    """Locate a photo file in the photo directories."""
    for d in [PHOTO_DIR]:
        if not d.exists():
            continue
        matches = list(d.rglob(filename))
        if matches:
            return matches[0]
    return None


def score_photo(photo_path, address, params_data):
    """Score a photo for training data quality (0-100)."""
    score = 50  # baseline

    try:
        img = Image.open(photo_path)
        w, h = img.size

        # Resolution bonus (higher = better)
        megapixels = w * h / 1e6
        score += min(megapixels * 5, 20)

        # Landscape orientation bonus (wider = more facade visible)
        if w > h:
            score += 5

        # Minimum resolution threshold
        if min(w, h) < 800:
            score -= 20

    except Exception:
        score -= 30

    # Contributing building bonus
    param = params_data.get(address, {})
    hcd = param.get("hcd_data", {})
    if (hcd.get("contributing") or "").lower() == "yes":
        score += 10

    # Has storefront = more annotation variety
    if param.get("has_storefront"):
        score += 5

    # Has decorative elements = richer training data
    dec = param.get("decorative_elements", {})
    if isinstance(dec, dict):
        present_count = sum(1 for v in dec.values() if isinstance(v, dict) and v.get("present"))
        score += min(present_count * 2, 10)

    return max(0, min(100, score))


def load_params_data():
    """Load param data indexed by address."""
    data = {}
    for f in PARAMS_DIR.glob("*.json"):
        if f.name.startswith("_"):
            continue
        try:
            p = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if p.get("skipped"):
            continue
        addr = p.get("building_name", f.stem.replace("_", " "))
        data[addr] = p
    return data


def main():
    parser = argparse.ArgumentParser(description="Prepare facade photos for annotation.")
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--output", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    print("Preparing training data for facade segmentation")

    photo_index = load_photo_index()
    params_data = load_params_data()

    print(f"  Photo index: {len(photo_index)} entries")
    print(f"  Params: {len(params_data)} buildings")

    # Score and rank photos
    scored = []
    for fname, address in photo_index.items():
        path = find_photo_on_disk(fname)
        if not path:
            continue
        score = score_photo(path, address, params_data)
        scored.append({
            "filename": fname,
            "address": address,
            "path": path,
            "score": score,
        })

    scored.sort(key=lambda x: -x["score"])
    selected = scored[:args.limit]

    print(f"  Scored {len(scored)} photos, selected top {len(selected)}")
    if selected:
        print(f"  Score range: {selected[-1]['score']:.0f} - {selected[0]['score']:.0f}")

    if args.dry_run:
        print("\n  DRY RUN — would copy:")
        for s in selected[:10]:
            print(f"    {s['filename']} (score={s['score']:.0f}, {s['address']})")
        return

    # Copy photos
    img_dir = args.output / "images"
    img_dir.mkdir(parents=True, exist_ok=True)

    manifest = []
    for s in selected:
        dst = img_dir / s["filename"]
        if not dst.exists():
            shutil.copy2(s["path"], dst)
        manifest.append({
            "image": f"images/{s['filename']}",
            "address": s["address"],
            "score": s["score"],
        })

    # Write manifest for Label Studio import
    manifest_path = args.output / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    # Write Label Studio tasks JSON
    ls_tasks = []
    for m in manifest:
        ls_tasks.append({
            "data": {
                "image": f"/data/local-files/?d={m['image']}",
                "address": m["address"],
            },
        })

    ls_path = args.output / "label_studio_tasks.json"
    ls_path.write_text(
        json.dumps(ls_tasks, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    # Write classes file
    classes_path = args.output / "classes.txt"
    classes_path.write_text("\n".join(CLASSES) + "\n", encoding="utf-8")

    print(f"\n  Copied {len(manifest)} photos to {img_dir}")
    print(f"  Manifest: {manifest_path}")
    print(f"  Label Studio tasks: {ls_path}")
    print(f"  Classes ({len(CLASSES)}): {classes_path}")


if __name__ == "__main__":
    main()
