#!/usr/bin/env python3
from __future__ import annotations
import csv, json
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
IN = ROOT / 'outputs' / 'road_markings' / 'roadmark_photo_references.csv'
PHD = ROOT / 'PHOTOS KENSINGTON'
OUT = ROOT / 'outputs' / 'road_markings' / 'decals' / 'extracted'
CAT = ROOT / 'outputs' / 'road_markings' / 'roadmark_decal_catalog_extracted.csv'
JS = ROOT / 'outputs' / 'road_markings' / 'roadmark_decal_catalog_extracted.json'

TARGET = 1024
MAX_TOTAL = 180


def alpha_from_crop(crop: Image.Image) -> Image.Image:
    hsv = np.asarray(crop.convert('HSV'), dtype=np.float32)
    sat = hsv[:, :, 1] / 255.0
    val = hsv[:, :, 2] / 255.0
    # Favor bright painted markings on darker road.
    a = np.clip((val - 0.35) * 2.1 + (sat - 0.08) * 0.8, 0, 1)
    img = Image.fromarray((a * 255).astype(np.uint8), 'L')
    return img.filter(ImageFilter.GaussianBlur(radius=1.7))


def fp64(img: Image.Image) -> int:
    g = img.convert('L').resize((16, 16), Image.Resampling.BILINEAR)
    arr = np.asarray(g, dtype=np.float32)
    med = float(np.median(arr))
    bits = (arr > med).astype(np.uint8).flatten()
    out = 0
    for b in bits[:64]:
        out = (out << 1) | int(b)
    return out


def hd(a: int, b: int) -> int:
    return int((a ^ b).bit_count())


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    seen = []

    refs = list(csv.DictReader(IN.open('r', encoding='utf-8', newline='')))
    for r in refs:
        fn = r.get('filename') or ''
        p = PHD / fn
        if not p.exists():
            continue

        img = Image.open(p).convert('RGB')
        if max(img.size) > 1800:
            sc = 1800 / max(img.size)
            img = img.resize((int(img.size[0] * sc), int(img.size[1] * sc)), Image.Resampling.LANCZOS)

        w, h = img.size
        # Multiple lower-road crops to improve capture diversity.
        windows = [
            (0.05, 0.58, 0.95, 0.98),
            (0.15, 0.62, 0.85, 0.97),
            (0.25, 0.65, 0.75, 0.96),
        ]

        kept_local = 0
        for idx, (x0r, y0r, x1r, y1r) in enumerate(windows, start=1):
            crop = img.crop((int(w * x0r), int(h * y0r), int(w * x1r), int(h * y1r)))
            a = alpha_from_crop(crop)
            cov = float((np.asarray(a) > 36).mean())
            if cov < 0.05 or cov > 0.96:
                continue

            f = fp64(crop)
            if any(hd(f, s) <= 4 for s in seen):
                continue
            seen.append(f)

            side = max(crop.size)
            canvas = Image.new('RGBA', (side, side), (0, 0, 0, 0))
            rgba = crop.convert('RGBA')
            rgba.putalpha(a)
            canvas.alpha_composite(rgba, ((side - crop.size[0]) // 2, (side - crop.size[1]) // 2))
            canvas = canvas.resize((TARGET, TARGET), Image.Resampling.LANCZOS)

            did = f"rmx_{Path(fn).stem}_{idx:02d}"
            op = OUT / f'{did}.png'
            canvas.save(op)

            rows.append({
                'decal_id': did,
                'category': r.get('category') or 'marking_lane_text',
                'source_filename': fn,
                'decal_texture_path': str(op.resolve()),
                'alpha_coverage': round(cov, 4),
                'source_type': 'photo_extract',
            })
            kept_local += 1
            if len(rows) >= MAX_TOTAL or kept_local >= 2:
                break
        if len(rows) >= MAX_TOTAL:
            break

    with CAT.open('w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else ['decal_id','category','source_filename','decal_texture_path','alpha_coverage','source_type'])
        w.writeheader()
        if rows:
            w.writerows(rows)

    JS.write_text(json.dumps({'count': len(rows), 'items': rows}, indent=2), encoding='utf-8')
    print('[OK] Wrote', CAT)
    print('[INFO] extracted=', len(rows))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
