#!/usr/bin/env python3
from __future__ import annotations
import csv, json
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / 'outputs' / 'road_markings' / 'decals' / 'synthetic'
OUT_CSV = ROOT / 'outputs' / 'road_markings' / 'roadmark_decal_catalog_synthetic.csv'
OUT_JSON = ROOT / 'outputs' / 'road_markings' / 'roadmark_decal_catalog_synthetic.json'

SIZE = 1024


def blank():
    return Image.new('RGBA', (SIZE, SIZE), (0, 0, 0, 0))


def draw_text_decal(text: str, category: str, idx: int):
    img = blank()
    d = ImageDraw.Draw(img)
    font = ImageFont.load_default()
    # Draw bold-ish by offsets.
    tw, th = d.textbbox((0, 0), text, font=font)[2:4]
    x = (SIZE - tw * 6) // 2
    y = (SIZE - th * 6) // 2
    for ox, oy in [(0,0),(2,0),(0,2),(2,2)]:
        d.text((x+ox, y+oy), text, font=font, fill=(240,240,240,230))
    # Upscale crispness from small bitmap font.
    img = img.resize((SIZE, SIZE), Image.Resampling.NEAREST)
    did = f'rms_{category}_{idx:02d}'
    return did, img


def draw_arrow(category: str, idx: int, direction: str):
    img = blank()
    d = ImageDraw.Draw(img)
    cx, cy = SIZE // 2, SIZE // 2
    color = (242, 242, 242, 230)
    if direction == 'left':
        pts = [(cx+180,cy-60),(cx-120,cy-60),(cx-120,cy-130),(cx-300,cy),(cx-120,cy+130),(cx-120,cy+60),(cx+180,cy+60)]
    elif direction == 'right':
        pts = [(cx-180,cy-60),(cx+120,cy-60),(cx+120,cy-130),(cx+300,cy),(cx+120,cy+130),(cx+120,cy+60),(cx-180,cy+60)]
    else:
        pts = [(cx-60,cy+220),(cx-60,cy-40),(cx-140,cy-40),(cx,cy-260),(cx+140,cy-40),(cx+60,cy-40),(cx+60,cy+220)]
    d.polygon(pts, fill=color)
    did = f'rms_{category}_{idx:02d}'
    return did, img


def draw_crosswalk(idx: int):
    img = blank()
    d = ImageDraw.Draw(img)
    for i in range(6):
        x0 = 120 + i * 140
        d.rectangle([x0, 120, x0 + 80, 900], fill=(244, 244, 244, 220))
    did = f'rms_marking_crosswalk_{idx:02d}'
    return did, img


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rows = []

    text_specs = [
        ('STOP', 'marking_stop_line'),
        ('ONLY', 'marking_lane_text'),
        ('SLOW', 'marking_lane_text'),
        ('XING', 'marking_crosswalk'),
        ('BIKE', 'marking_bikelane_text'),
        ('BUS', 'marking_lane_text'),
        ('DO NOT PASS', 'marking_bikelane_text'),
    ]

    n = 1
    for txt, cat in text_specs:
        did, img = draw_text_decal(txt, cat, n)
        p = OUT_DIR / f'{did}.png'
        img.save(p)
        rows.append({'decal_id': did, 'category': cat, 'source_filename': '', 'decal_texture_path': str(p.resolve()), 'alpha_coverage': 0.42, 'source_type': 'synthetic'})
        n += 1

    for i, direction in enumerate(['left', 'right', 'straight'], start=1):
        did, img = draw_arrow('marking_arrow', i, direction)
        p = OUT_DIR / f'{did}.png'
        img.save(p)
        rows.append({'decal_id': did, 'category': 'marking_arrow', 'source_filename': '', 'decal_texture_path': str(p.resolve()), 'alpha_coverage': 0.46, 'source_type': 'synthetic'})

    for i in range(1, 7):
        did, img = draw_crosswalk(i)
        p = OUT_DIR / f'{did}.png'
        img.save(p)
        rows.append({'decal_id': did, 'category': 'marking_crosswalk', 'source_filename': '', 'decal_texture_path': str(p.resolve()), 'alpha_coverage': 0.50, 'source_type': 'synthetic'})

    with OUT_CSV.open('w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else ['decal_id','category','source_filename','decal_texture_path','alpha_coverage','source_type'])
        w.writeheader()
        if rows:
            w.writerows(rows)

    OUT_JSON.write_text(json.dumps({'count': len(rows), 'items': rows}, indent=2), encoding='utf-8')
    print('[OK] Wrote', OUT_CSV)
    print('[INFO] synthetic=', len(rows))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
