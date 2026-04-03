#!/usr/bin/env python3
"""Texture fidelity analysis: compare render outputs against field photos.

Computes colour histogram intersection, dominant colour extraction,
approximate CIEDE2000 delta-E, edge density ratio, and material
consistency for each matched building.

Usage:
    python scripts/analyze/texture_fidelity.py
    python scripts/analyze/texture_fidelity.py --renders outputs/buildings_renders_v1/ \
        --photos "PHOTOS KENSINGTON sorted/" \
        --photo-index "PHOTOS KENSINGTON/csv/photo_address_index.csv" \
        --output outputs/texture_analysis/
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
from collections import defaultdict
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# ---------------------------------------------------------------------------
# Colour-space helpers (stdlib + numpy only)
# ---------------------------------------------------------------------------

def _hex_to_rgb(h: str) -> tuple[int, int, int] | None:
    """Convert '#RRGGBB' or 'RRGGBB' to (R, G, B) ints, or None."""
    h = (h or "").strip().lstrip("#")
    if len(h) != 6:
        return None
    try:
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    except ValueError:
        return None


def _srgb_to_linear(c: float) -> float:
    return ((c + 0.055) / 1.055) ** 2.4 if c > 0.04045 else c / 12.92


def _rgb_to_lab(r: int, g: int, b: int) -> tuple[float, float, float]:
    """Approximate sRGB -> CIE Lab via D65 XYZ intermediate."""
    # Normalise to [0,1] then linearise
    rl, gl, bl = (_srgb_to_linear(c / 255.0) for c in (r, g, b))
    # sRGB D65 matrix
    x = rl * 0.4124564 + gl * 0.3575761 + bl * 0.1804375
    y = rl * 0.2126729 + gl * 0.7151522 + bl * 0.0721750
    z = rl * 0.0193339 + gl * 0.1191920 + bl * 0.9503041
    # D65 reference white
    xn, yn, zn = 0.95047, 1.0, 1.08883

    def f(t: float) -> float:
        return t ** (1.0 / 3.0) if t > 0.008856 else 7.787 * t + 16.0 / 116.0

    fx, fy, fz = f(x / xn), f(y / yn), f(z / zn)
    L = 116.0 * fy - 16.0
    a = 500.0 * (fx - fy)
    b_val = 200.0 * (fy - fz)
    return (L, a, b_val)


def _delta_e_cie76(lab1: tuple, lab2: tuple) -> float:
    """CIE76 colour difference (simplified; good enough for screening)."""
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(lab1, lab2)))


# ---------------------------------------------------------------------------
# Image helpers (Pillow)
# ---------------------------------------------------------------------------

def _load_image_array(path: Path) -> np.ndarray | None:
    """Load image as uint8 RGB numpy array, or None on failure."""
    try:
        from PIL import Image
        img = Image.open(path).convert("RGB")
        return np.asarray(img, dtype=np.uint8)
    except Exception:
        return None


def _colour_histogram(arr: np.ndarray, bins: int = 64) -> np.ndarray:
    """Compute normalised RGB histogram (bins per channel, concatenated)."""
    hists = []
    for ch in range(3):
        h, _ = np.histogram(arr[:, :, ch].ravel(), bins=bins, range=(0, 256))
        hists.append(h.astype(np.float64))
    hist = np.concatenate(hists)
    s = hist.sum()
    if s > 0:
        hist /= s
    return hist


def _histogram_intersection(h1: np.ndarray, h2: np.ndarray) -> float:
    """Histogram intersection score in [0, 1]; 1 = identical."""
    return float(np.minimum(h1, h2).sum())


def _dominant_colours(arr: np.ndarray, k: int = 5, bins: int = 8) -> list[dict]:
    """Extract top-k dominant colours via coarse RGB binning."""
    quantised = (arr // (256 // bins)).reshape(-1, 3)
    # Pack into single int for counting
    packed = quantised[:, 0].astype(np.int32) * bins * bins + quantised[:, 1].astype(np.int32) * bins + quantised[:, 2].astype(np.int32)
    unique, counts = np.unique(packed, return_counts=True)
    order = np.argsort(-counts)[:k]
    total = arr.shape[0] * arr.shape[1]
    result = []
    half_bin = (256 // bins) // 2
    for idx in order:
        val = int(unique[idx])
        r_bin = val // (bins * bins)
        g_bin = (val % (bins * bins)) // bins
        b_bin = val % bins
        r = r_bin * (256 // bins) + half_bin
        g = g_bin * (256 // bins) + half_bin
        b = b_bin * (256 // bins) + half_bin
        hex_col = f"#{r:02X}{g:02X}{b:02X}"
        result.append({
            "hex": hex_col,
            "rgb": [r, g, b],
            "pct": round(float(counts[idx]) / total * 100, 2),
        })
    return result


def _edge_density(arr: np.ndarray) -> float:
    """Compute mean Sobel edge magnitude on grayscale image."""
    gray = arr[:, :, 0].astype(np.float64) * 0.299 + arr[:, :, 1].astype(np.float64) * 0.587 + arr[:, :, 2].astype(np.float64) * 0.114
    # Sobel kernels via slicing (avoid scipy)
    gx = np.zeros_like(gray)
    gy = np.zeros_like(gray)
    gx[1:-1, 1:-1] = (
        -gray[:-2, :-2] + gray[:-2, 2:]
        - 2 * gray[1:-1, :-2] + 2 * gray[1:-1, 2:]
        - gray[2:, :-2] + gray[2:, 2:]
    )
    gy[1:-1, 1:-1] = (
        -gray[:-2, :-2] - 2 * gray[:-2, 1:-1] - gray[:-2, 2:]
        + gray[2:, :-2] + 2 * gray[2:, 1:-1] + gray[2:, 2:]
    )
    mag = np.sqrt(gx ** 2 + gy ** 2)
    return float(mag.mean())


# ---------------------------------------------------------------------------
# Matching helpers
# ---------------------------------------------------------------------------

def _sanitize_address(addr: str) -> str:
    return re.sub(r"[^\w]", "_", addr.strip())


def _load_photo_index(index_path: Path) -> dict[str, list[Path]]:
    """Return {address: [photo_paths]} from CSV index."""
    mapping: dict[str, list[Path]] = defaultdict(list)
    if not index_path.exists():
        return mapping
    with open(index_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            addr = (row.get("address") or row.get("ADDRESS") or "").strip()
            photo = (row.get("filename") or row.get("photo") or row.get("file") or "").strip()
            if addr and photo:
                mapping[addr].append(Path(photo))
    return mapping


def _find_render(renders_dir: Path, address: str) -> Path | None:
    sanitized = _sanitize_address(address)
    for ext in (".png", ".jpg", ".jpeg"):
        candidate = renders_dir / f"{sanitized}{ext}"
        if candidate.exists():
            return candidate
    # Glob fallback
    for p in renders_dir.glob(f"{sanitized}*"):
        if p.suffix.lower() in (".png", ".jpg", ".jpeg"):
            return p
    return None


def _load_params(params_dir: Path) -> dict[str, dict]:
    """Load all non-skipped, non-metadata param files keyed by address."""
    result = {}
    for p in sorted(params_dir.glob("*.json")):
        if p.name.startswith("_"):
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if data.get("skipped"):
            continue
        addr = data.get("building_name") or data.get("_meta", {}).get("address") or p.stem.replace("_", " ")
        result[addr] = data
    return result


# ---------------------------------------------------------------------------
# Per-building analysis
# ---------------------------------------------------------------------------

def analyze_building(
    address: str,
    render_path: Path,
    photo_path: Path,
    params: dict | None,
) -> dict:
    render_arr = _load_image_array(render_path)
    photo_arr = _load_image_array(photo_path)
    result: dict = {"address": address, "render": str(render_path), "photo": str(photo_path)}

    if render_arr is None or photo_arr is None:
        result["error"] = "failed to load one or both images"
        result["overall_score"] = 0.0
        return result

    # 1. Histogram intersection
    rh = _colour_histogram(render_arr)
    ph = _colour_histogram(photo_arr)
    hist_score = _histogram_intersection(rh, ph)
    result["histogram_intersection"] = round(hist_score, 4)

    # 2. Dominant colours
    render_dom = _dominant_colours(render_arr)
    photo_dom = _dominant_colours(photo_arr)
    result["render_dominant_colours"] = render_dom
    result["photo_dominant_colours"] = photo_dom

    # 3. Delta-E between top dominant colours
    delta_es = []
    for rc, pc in zip(render_dom[:3], photo_dom[:3]):
        lab1 = _rgb_to_lab(*rc["rgb"])
        lab2 = _rgb_to_lab(*pc["rgb"])
        delta_es.append(round(_delta_e_cie76(lab1, lab2), 2))
    result["delta_e_top3"] = delta_es
    avg_de = sum(delta_es) / len(delta_es) if delta_es else 100.0
    result["avg_delta_e"] = round(avg_de, 2)

    # 4. Edge density comparison
    render_edges = _edge_density(render_arr)
    photo_edges = _edge_density(photo_arr)
    edge_ratio = render_edges / photo_edges if photo_edges > 0 else 0.0
    result["render_edge_density"] = round(render_edges, 2)
    result["photo_edge_density"] = round(photo_edges, 2)
    result["edge_density_ratio"] = round(edge_ratio, 4)

    # 5. Material consistency (facade hex vs observed dominant)
    material_match = None
    if params:
        facade_hex = (
            (params.get("facade_detail") or {}).get("brick_colour_hex")
            or params.get("facade_colour")
            or (params.get("colour_palette") or {}).get("facade")
        )
        if facade_hex:
            param_rgb = _hex_to_rgb(facade_hex)
            if param_rgb and photo_dom:
                photo_top_rgb = tuple(photo_dom[0]["rgb"])
                lab_p = _rgb_to_lab(*param_rgb)
                lab_ph = _rgb_to_lab(*photo_top_rgb)
                de = _delta_e_cie76(lab_p, lab_ph)
                material_match = {
                    "param_hex": facade_hex,
                    "photo_dominant_hex": photo_dom[0]["hex"],
                    "delta_e": round(de, 2),
                    "match": "good" if de < 15 else ("moderate" if de < 30 else "poor"),
                }
    result["material_consistency"] = material_match

    # Overall score: weighted combination (0-100)
    # Histogram 30%, delta-E 30% (inverted), edge ratio 20%, material 20%
    score = hist_score * 30.0
    # delta-E: 0 perfect, 100+ terrible -> scale to 0-30
    de_score = max(0.0, 30.0 - avg_de * 0.3)
    score += de_score
    # Edge ratio: ideal = 1.0, penalise deviation
    er_score = max(0.0, 20.0 - abs(1.0 - edge_ratio) * 20.0)
    score += er_score
    # Material match
    if material_match:
        mm_de = material_match["delta_e"]
        mm_score = max(0.0, 20.0 - mm_de * 0.2)
        score += mm_score
    else:
        score += 10.0  # neutral if no param hex

    result["overall_score"] = round(min(100.0, max(0.0, score)), 1)
    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Texture fidelity analysis: renders vs field photos")
    parser.add_argument("--renders", type=Path, default=REPO_ROOT / "outputs" / "buildings_renders_v1")
    parser.add_argument("--photos", type=Path, default=REPO_ROOT / "PHOTOS KENSINGTON sorted")
    parser.add_argument("--photo-index", type=Path, default=REPO_ROOT / "PHOTOS KENSINGTON" / "csv" / "photo_address_index.csv")
    parser.add_argument("--params", type=Path, default=REPO_ROOT / "params")
    parser.add_argument("--output", type=Path, default=REPO_ROOT / "outputs" / "texture_analysis")
    parser.add_argument("--limit", type=int, default=0, help="Limit number of buildings (0 = all)")
    args = parser.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)

    print(f"Loading photo index from {args.photo_index} ...")
    photo_index = _load_photo_index(args.photo_index)
    print(f"  {len(photo_index)} addresses in index")

    print(f"Loading params from {args.params} ...")
    all_params = _load_params(args.params)
    print(f"  {len(all_params)} active buildings")

    results: list[dict] = []
    matched = 0
    skipped = 0

    for address, photo_paths in sorted(photo_index.items()):
        if args.limit and matched >= args.limit:
            break

        render_path = _find_render(args.renders, address)
        if render_path is None:
            skipped += 1
            continue

        # Pick first existing photo
        photo_file = None
        for pp in photo_paths:
            candidate = args.photos / pp if not pp.is_absolute() else pp
            if candidate.exists():
                photo_file = candidate
                break
        if photo_file is None:
            skipped += 1
            continue

        params = all_params.get(address)
        print(f"  Analyzing: {address}")
        result = analyze_building(address, render_path, photo_file, params)
        results.append(result)
        matched += 1

    # Summary
    scores = [r["overall_score"] for r in results if "error" not in r]
    summary = {
        "total_analyzed": len(results),
        "skipped_no_match": skipped,
        "avg_score": round(sum(scores) / len(scores), 1) if scores else 0.0,
        "median_score": round(float(np.median(scores)), 1) if scores else 0.0,
        "min_score": round(min(scores), 1) if scores else 0.0,
        "max_score": round(max(scores), 1) if scores else 0.0,
        "score_histogram": {
            "0-20": sum(1 for s in scores if s < 20),
            "20-40": sum(1 for s in scores if 20 <= s < 40),
            "40-60": sum(1 for s in scores if 40 <= s < 60),
            "60-80": sum(1 for s in scores if 60 <= s < 80),
            "80-100": sum(1 for s in scores if s >= 80),
        },
        "worst_10": sorted(
            [{"address": r["address"], "score": r["overall_score"]} for r in results if "error" not in r],
            key=lambda x: x["score"],
        )[:10],
    }

    report = {"summary": summary, "buildings": results}

    out_path = args.output / "texture_fidelity_report.json"
    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nReport written to {out_path}")
    print(f"  Analyzed: {len(results)} | Skipped: {skipped} | Avg score: {summary['avg_score']}")


if __name__ == "__main__":
    main()
