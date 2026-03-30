#!/usr/bin/env python3
"""Extract printable feature decals (signage/posters/murals) from photos."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
IN_SHORT = ROOT / "outputs" / "printable_features" / "printable_reference_shortlist.csv"
PHOTO_DIR = ROOT / "PHOTOS KENSINGTON"
OUT_DIR = ROOT / "outputs" / "printable_features" / "decals"
OUT_IMG = OUT_DIR / "extracted"
OUT_CSV = ROOT / "outputs" / "printable_features" / "printable_decal_catalog.csv"
OUT_JSON = ROOT / "outputs" / "printable_features" / "printable_decal_catalog.json"

MAX_PER_IMG = 2
MAX_TOTAL = 320
TARGET = 1024


def patch_score(rgb: np.ndarray, y0: int, y1: int, x0: int, x1: int) -> float:
    p = rgb[y0:y1, x0:x1]
    if p.size == 0:
        return 0.0
    lum = 0.2126 * p[:, :, 0] + 0.7152 * p[:, :, 1] + 0.0722 * p[:, :, 2]
    gx = np.abs(np.diff(lum, axis=1)).mean() if p.shape[1] > 1 else 0.0
    gy = np.abs(np.diff(lum, axis=0)).mean() if p.shape[0] > 1 else 0.0
    sat = (np.max(p, axis=2) - np.min(p, axis=2)).mean()
    return float(0.45 * sat + 0.55 * (gx + gy))


def alpha_from_crop(crop: Image.Image) -> Image.Image:
    hsv = np.asarray(crop.convert("HSV"), dtype=np.float32)
    sat = hsv[:, :, 1] / 255.0
    val = hsv[:, :, 2] / 255.0
    alpha = np.clip((sat - 0.17) * 2.1 + (val - 0.10) * 0.35, 0.0, 1.0)
    a = Image.fromarray((alpha * 255).astype(np.uint8), mode="L")
    return a.filter(ImageFilter.GaussianBlur(radius=2.0))


def main() -> int:
    OUT_IMG.mkdir(parents=True, exist_ok=True)

    src = list(csv.DictReader(IN_SHORT.open("r", encoding="utf-8", newline="")))
    out = []

    for r in src:
        fn = (r.get("filename") or "").strip()
        if not fn:
            continue
        p = PHOTO_DIR / fn
        if not p.exists():
            continue

        img = Image.open(p).convert("RGB")
        if max(img.size) > 1600:
            sc = 1600 / max(img.size)
            img = img.resize((int(img.size[0] * sc), int(img.size[1] * sc)), Image.Resampling.LANCZOS)

        arr = np.asarray(img, dtype=np.float32) / 255.0
        h, w, _ = arr.shape

        tw = max(180, int(w * 0.28))
        th = max(180, int(h * 0.28))
        sx = max(80, tw // 3)
        sy = max(80, th // 3)

        cands = []
        for y0 in range(0, max(1, h - th + 1), sy):
            for x0 in range(0, max(1, w - tw + 1), sx):
                x1 = min(w, x0 + tw)
                y1 = min(h, y0 + th)
                s = patch_score(arr, y0, y1, x0, x1)
                if s > 0.10:
                    cands.append((s, x0, y0, x1, y1))
        cands.sort(reverse=True)

        used = []
        picked = []
        for s, x0, y0, x1, y1 in cands:
            ok = True
            for _, ax0, ay0, ax1, ay1 in used:
                ix0 = max(x0, ax0); iy0 = max(y0, ay0); ix1 = min(x1, ax1); iy1 = min(y1, ay1)
                if ix0 < ix1 and iy0 < iy1:
                    inter = (ix1 - ix0) * (iy1 - iy0)
                    aa = (x1 - x0) * (y1 - y0)
                    bb = (ax1 - ax0) * (ay1 - ay0)
                    iou = inter / max(1.0, aa + bb - inter)
                    if iou > 0.35:
                        ok = False
                        break
            if not ok:
                continue
            used.append((s, x0, y0, x1, y1))
            picked.append((s, x0, y0, x1, y1))
            if len(picked) >= MAX_PER_IMG:
                break

        for idx, (s, x0, y0, x1, y1) in enumerate(picked, start=1):
            crop = img.crop((x0, y0, x1, y1))
            alpha = alpha_from_crop(crop)
            cov = float((np.asarray(alpha) > 40).mean())
            if cov < 0.08 or cov > 0.95:
                continue

            cw, ch = crop.size
            side = max(cw, ch)
            canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
            rgba = crop.convert("RGBA")
            rgba.putalpha(alpha)
            canvas.alpha_composite(rgba, ((side - cw) // 2, (side - ch) // 2))
            canvas = canvas.resize((TARGET, TARGET), Image.Resampling.LANCZOS)

            decal_id = f"print_{Path(fn).stem}_{idx:02d}"
            op = OUT_IMG / f"{decal_id}.png"
            canvas.save(op)

            out.append(
                {
                    "decal_id": decal_id,
                    "category": r.get("category") or "other_printable",
                    "source_filename": fn,
                    "source_path": str(p.resolve()),
                    "decal_texture_path": str(op.resolve()),
                    "score": round(float(s), 4),
                    "alpha_coverage": round(cov, 4),
                    "crop_x0": x0,
                    "crop_y0": y0,
                    "crop_x1": x1,
                    "crop_y1": y1,
                    "image_width": w,
                    "image_height": h,
                }
            )
            if len(out) >= MAX_TOTAL:
                break
        if len(out) >= MAX_TOTAL:
            break

    with OUT_CSV.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0].keys()) if out else ["decal_id", "category", "source_filename", "source_path", "decal_texture_path", "score", "alpha_coverage", "crop_x0", "crop_y0", "crop_x1", "crop_y1", "image_width", "image_height"])
        w.writeheader()
        if out:
            w.writerows(out)

    OUT_JSON.write_text(json.dumps({"count": len(out), "items": out}, indent=2), encoding="utf-8")
    print(f"[OK] Wrote {OUT_CSV}")
    print(f"[OK] Wrote {OUT_JSON}")
    print(f"[INFO] extracted={len(out)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
