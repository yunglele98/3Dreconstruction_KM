#!/usr/bin/env python3
"""Extract graffiti decal crops from Kensington photo references."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
IN_SHORTLIST = ROOT / "outputs" / "alley_garages" / "graffiti_reference_shortlist.csv"
IN_SEMANTIC = ROOT / "outputs" / "alley_garages" / "graffiti_semantic_catalog.csv"
PHOTO_DIR = ROOT / "PHOTOS KENSINGTON"
OUT_DIR = ROOT / "outputs" / "alley_garages" / "graffiti_decals"
OUT_IMG = OUT_DIR / "extracted"
OUT_CSV = ROOT / "outputs" / "alley_garages" / "graffiti_decal_catalog.csv"
OUT_JSON = ROOT / "outputs" / "alley_garages" / "graffiti_decal_catalog.json"

MAX_IMAGES = 180
MAX_PATCH_PER_IMAGE = 2
TARGET_SIZE = 1024
MAX_DECALS_TOTAL = 260


@dataclass
class Candidate:
    x0: int
    y0: int
    x1: int
    y1: int
    score: float


def load_style_map() -> dict[str, str]:
    if not IN_SEMANTIC.exists():
        return {}
    style_map: dict[str, str] = {}
    with IN_SEMANTIC.open("r", encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            fn = (r.get("filename") or "").strip()
            if fn:
                style_map[fn] = (r.get("style") or "generic_urban_marking").strip()
    return style_map


def to_array(img: Image.Image) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    rgb = np.asarray(img.convert("RGB"), dtype=np.float32) / 255.0
    hsv = np.asarray(img.convert("HSV"), dtype=np.float32)
    sat = hsv[:, :, 1] / 255.0
    val = hsv[:, :, 2] / 255.0
    lum = 0.2126 * rgb[:, :, 0] + 0.7152 * rgb[:, :, 1] + 0.0722 * rgb[:, :, 2]
    return sat, val, lum


def edge_strength(lum: np.ndarray) -> np.ndarray:
    gx = np.zeros_like(lum)
    gy = np.zeros_like(lum)
    gx[:, 1:] = np.abs(lum[:, 1:] - lum[:, :-1])
    gy[1:, :] = np.abs(lum[1:, :] - lum[:-1, :])
    return np.clip(gx + gy, 0.0, 1.0)


def build_candidates(sat: np.ndarray, val: np.ndarray, edge: np.ndarray) -> list[Candidate]:
    h, w = sat.shape
    tw = max(180, int(w * 0.30))
    th = max(180, int(h * 0.30))
    sx = max(80, tw // 3)
    sy = max(80, th // 3)

    cands: list[Candidate] = []
    for y0 in range(0, max(1, h - th + 1), sy):
        for x0 in range(0, max(1, w - tw + 1), sx):
            y1 = min(h, y0 + th)
            x1 = min(w, x0 + tw)
            s = sat[y0:y1, x0:x1]
            v = val[y0:y1, x0:x1]
            e = edge[y0:y1, x0:x1]

            sat_m = float(np.mean(s))
            edge_m = float(np.mean(e))
            dark_ratio = float(np.mean(v < 0.15))
            bright_ratio = float(np.mean(v > 0.88))

            sky_penalty = 0.0
            if y0 < h * 0.2 and bright_ratio > 0.45 and edge_m < 0.08:
                sky_penalty = 0.55

            score = sat_m * 0.55 + edge_m * 0.45 - 0.2 * dark_ratio - 0.15 * bright_ratio - sky_penalty
            if score > 0.12:
                cands.append(Candidate(x0, y0, x1, y1, score))

    cands.sort(key=lambda c: c.score, reverse=True)
    return cands


def iou(a: Candidate, b: Candidate) -> float:
    ix0 = max(a.x0, b.x0)
    iy0 = max(a.y0, b.y0)
    ix1 = min(a.x1, b.x1)
    iy1 = min(a.y1, b.y1)
    if ix0 >= ix1 or iy0 >= iy1:
        return 0.0
    inter = float((ix1 - ix0) * (iy1 - iy0))
    aa = float((a.x1 - a.x0) * (a.y1 - a.y0))
    bb = float((b.x1 - b.x0) * (b.y1 - b.y0))
    return inter / max(1.0, aa + bb - inter)


def select_non_overlapping(cands: list[Candidate], k: int) -> list[Candidate]:
    out: list[Candidate] = []
    for c in cands:
        if any(iou(c, o) > 0.35 for o in out):
            continue
        out.append(c)
        if len(out) >= k:
            break
    return out


def alpha_from_sat(crop: Image.Image) -> Image.Image:
    hsv = np.asarray(crop.convert("HSV"), dtype=np.float32)
    sat = hsv[:, :, 1] / 255.0
    val = hsv[:, :, 2] / 255.0
    alpha = np.clip((sat - 0.20) * 2.3 + (val - 0.15) * 0.25, 0.0, 1.0)
    a = Image.fromarray((alpha * 255).astype(np.uint8), mode="L")
    return a.filter(ImageFilter.GaussianBlur(radius=2.2))


def alpha_metrics(a: Image.Image) -> tuple[float, float]:
    arr = np.asarray(a, dtype=np.float32) / 255.0
    coverage = float(np.mean(arr > 0.18))
    avg = float(np.mean(arr))
    return coverage, avg


def colorfulness(crop: Image.Image) -> float:
    arr = np.asarray(crop.convert("RGB"), dtype=np.float32)
    rg = np.abs(arr[:, :, 0] - arr[:, :, 1])
    yb = np.abs(0.5 * (arr[:, :, 0] + arr[:, :, 1]) - arr[:, :, 2])
    return float(np.mean(rg) + np.mean(yb)) / 255.0


def phash_64(crop: Image.Image) -> int:
    # Fast average-hash style fingerprint for near-duplicate pruning.
    g = crop.convert("L").resize((16, 16), Image.Resampling.BILINEAR)
    arr = np.asarray(g, dtype=np.float32)
    med = float(np.median(arr))
    bits = (arr > med).astype(np.uint8).flatten()
    out = 0
    for b in bits[:64]:
        out = (out << 1) | int(b)
    return out


def hamming64(a: int, b: int) -> int:
    return int((a ^ b).bit_count())


def main() -> int:
    OUT_IMG.mkdir(parents=True, exist_ok=True)

    style_map = load_style_map()
    src = list(csv.DictReader(IN_SHORTLIST.open("r", encoding="utf-8", newline="")))[:MAX_IMAGES]

    out_rows: list[dict[str, object]] = []
    seen_hashes: list[int] = []
    for r in src:
        fn = (r.get("filename") or "").strip()
        if not fn:
            continue
        p = PHOTO_DIR / fn
        if not p.exists():
            continue

        img = Image.open(p).convert("RGB")
        w0, h0 = img.size
        scale = 1.0
        long_side = max(w0, h0)
        if long_side > 1600:
            scale = 1600.0 / long_side
            img = img.resize((int(w0 * scale), int(h0 * scale)), Image.Resampling.LANCZOS)

        sat, val, lum = to_array(img)
        edge = edge_strength(lum)
        cands = build_candidates(sat, val, edge)
        picks = select_non_overlapping(cands, MAX_PATCH_PER_IMAGE)
        if not picks:
            continue

        for idx, c in enumerate(picks, start=1):
            crop = img.crop((c.x0, c.y0, c.x1, c.y1))
            # Reject near-flat or low-information crops.
            cf = colorfulness(crop)
            if cf < 0.06 and c.score < 0.2:
                continue

            # Normalize to square decal size.
            cw, ch = crop.size
            side = max(cw, ch)
            canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
            ox = (side - cw) // 2
            oy = (side - ch) // 2

            alpha = alpha_from_sat(crop)
            coverage, alpha_avg = alpha_metrics(alpha)
            if coverage < 0.10 or coverage > 0.92:
                continue

            fp = phash_64(crop)
            if any(hamming64(fp, old) <= 5 for old in seen_hashes):
                continue
            seen_hashes.append(fp)

            rgba = crop.convert("RGBA")
            rgba.putalpha(alpha)
            canvas.alpha_composite(rgba, (ox, oy))
            canvas = canvas.resize((TARGET_SIZE, TARGET_SIZE), Image.Resampling.LANCZOS)

            decal_id = f"graff_{Path(fn).stem}_{idx:02d}"
            out_path = OUT_IMG / f"{decal_id}.png"
            canvas.save(out_path)

            style = style_map.get(fn, "generic_urban_marking")
            out_rows.append(
                {
                    "decal_id": decal_id,
                    "source_filename": fn,
                    "source_path": str(p.resolve()),
                    "decal_texture_path": str(out_path.resolve()),
                    "style": style,
                    "score": round(c.score, 4),
                    "alpha_coverage": round(coverage, 4),
                    "alpha_avg": round(alpha_avg, 4),
                    "colorfulness": round(cf, 4),
                    "fingerprint64": fp,
                    "crop_x0": c.x0,
                    "crop_y0": c.y0,
                    "crop_x1": c.x1,
                    "crop_y1": c.y1,
                    "image_width": img.size[0],
                    "image_height": img.size[1],
                }
            )
            if len(out_rows) >= MAX_DECALS_TOTAL:
                break
        if len(out_rows) >= MAX_DECALS_TOTAL:
            break

    with OUT_CSV.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=list(out_rows[0].keys())
            if out_rows
            else [
                "decal_id",
                "source_filename",
                "source_path",
                "decal_texture_path",
                "style",
                "score",
                "alpha_coverage",
                "alpha_avg",
                "colorfulness",
                "fingerprint64",
                "crop_x0",
                "crop_y0",
                "crop_x1",
                "crop_y1",
                "image_width",
                "image_height",
            ],
        )
        w.writeheader()
        if out_rows:
            w.writerows(out_rows)

    OUT_JSON.write_text(
        json.dumps(
            {
                "count": len(out_rows),
                "output_dir": str(OUT_IMG.resolve()),
                "items": out_rows,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    print(f"[OK] Wrote {OUT_CSV}")
    print(f"[OK] Wrote {OUT_JSON}")
    print(f"[INFO] extracted_decals={len(out_rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
