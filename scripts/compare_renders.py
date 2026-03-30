#!/usr/bin/env python3
"""
Build photo-vs-render comparison pairs for SSIM analysis.

Output: outputs/photo_render_pairs.json
"""
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PARAMS_DIR = ROOT / "params"
PHOTOS_DIR = ROOT / "PHOTOS KENSINGTON"
PHOTO_INDEX = PHOTOS_DIR / "csv" / "photo_address_index.csv"
RENDERS_DIR = ROOT / "outputs" / "full"
OUTPUT_FILE = ROOT / "outputs" / "photo_render_pairs.json"


def load_photo_index() -> dict:
    index = {}
    if not PHOTO_INDEX.exists():
        return index
    with open(PHOTO_INDEX, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            addr = (row.get("address_or_location") or "").strip()
            fname = (row.get("filename") or "").strip()
            if addr and fname:
                index.setdefault(addr, []).append(fname)
    return index


def find_photo(address: str, photo_index: dict) -> str:
    if address in photo_index:
        return photo_index[address][0]
    addr_lower = address.lower()
    for key, photos in photo_index.items():
        if addr_lower in key.lower() or key.lower() in addr_lower:
            return photos[0]
    return ""


def find_render(stem: str) -> str:
    for ext in (".png", ".jpg"):
        r = RENDERS_DIR / (stem + ext)
        if r.exists():
            return str(r)
    return ""


def main():
    photo_index = load_photo_index()
    pairs = []
    photo_only = 0
    render_only = 0

    for param_file in sorted(PARAMS_DIR.glob("*.json")):
        if param_file.name.startswith("_") or "backup" in param_file.name:
            continue
        with open(param_file, encoding="utf-8") as f:
            params = json.load(f)
        if params.get("skipped"):
            continue

        address = params.get("building_name", param_file.stem.replace("_", " "))
        photo = find_photo(address, photo_index)
        render = find_render(param_file.stem)

        if photo and render:
            pairs.append({
                "address": address,
                "photo_path": str(PHOTOS_DIR / photo),
                "render_path": render,
            })
        elif photo:
            photo_only += 1
        elif render:
            render_only += 1

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(pairs, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print(f"Photo-Render Comparison Pairs")
    print(f"{'='*50}")
    print(f"Both photo+render: {len(pairs)}")
    print(f"Photo only: {photo_only}")
    print(f"Render only: {render_only}")
    print(f"Output: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
