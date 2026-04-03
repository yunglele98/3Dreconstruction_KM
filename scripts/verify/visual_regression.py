#!/usr/bin/env python3
"""Visual regression testing — compare renders against references using SSIM.

Flags regressions when SSIM drops below threshold, generates HTML report
with side-by-side diffs.

Usage:
    python scripts/verify/visual_regression.py --renders outputs/full/ --references outputs/qa_visual_check/
    python scripts/verify/visual_regression.py --renders outputs/full/ --references outputs/qa_visual_check/ --threshold 0.85
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SUPPORTED_EXTS = {".png", ".jpg", ".jpeg"}


def compute_ssim(img_a: np.ndarray, img_b: np.ndarray) -> float:
    """Compute Structural Similarity Index between two images.

    Uses scikit-image if available, falls back to simple MSE-based metric.
    """
    try:
        from skimage.metrics import structural_similarity
        # Ensure same size
        min_h = min(img_a.shape[0], img_b.shape[0])
        min_w = min(img_a.shape[1], img_b.shape[1])
        a = img_a[:min_h, :min_w]
        b = img_b[:min_h, :min_w]

        if a.ndim == 3:
            return structural_similarity(a, b, channel_axis=2, data_range=255)
        else:
            return structural_similarity(a, b, data_range=255)
    except ImportError:
        # Fallback: normalized cross-correlation
        a = img_a.astype(np.float64).ravel()
        b = img_b.astype(np.float64).ravel()
        min_len = min(len(a), len(b))
        a, b = a[:min_len], b[:min_len]
        a_norm = a - a.mean()
        b_norm = b - b.mean()
        denom = np.sqrt(np.sum(a_norm ** 2) * np.sum(b_norm ** 2))
        if denom == 0:
            return 1.0
        return float(np.sum(a_norm * b_norm) / denom)


def compute_perceptual_hash(img: np.ndarray, hash_size: int = 8) -> str:
    """Compute a simple average hash for perceptual comparison."""
    from PIL import Image
    pil_img = Image.fromarray(img).convert("L").resize((hash_size, hash_size))
    pixels = np.array(pil_img)
    avg = pixels.mean()
    bits = (pixels > avg).flatten()
    return "".join("1" if b else "0" for b in bits)


def hamming_distance(hash_a: str, hash_b: str) -> int:
    """Hamming distance between two binary hash strings."""
    return sum(a != b for a, b in zip(hash_a, hash_b))


def compare_renders(
    renders_dir: Path,
    references_dir: Path,
    threshold: float = 0.85,
) -> list[dict]:
    """Compare render outputs against reference images.

    Args:
        renders_dir: Directory with current renders.
        references_dir: Directory with reference renders.
        threshold: SSIM threshold below which a regression is flagged.

    Returns:
        List of comparison result dicts.
    """
    from PIL import Image

    results = []
    render_files = {
        f.stem: f for f in renders_dir.rglob("*")
        if f.suffix.lower() in SUPPORTED_EXTS
    }
    ref_files = {
        f.stem: f for f in references_dir.rglob("*")
        if f.suffix.lower() in SUPPORTED_EXTS
    }

    matched = set(render_files.keys()) & set(ref_files.keys())
    unmatched_renders = set(render_files.keys()) - set(ref_files.keys())
    unmatched_refs = set(ref_files.keys()) - set(render_files.keys())

    for stem in sorted(matched):
        try:
            render_img = np.array(Image.open(render_files[stem]).convert("RGB"))
            ref_img = np.array(Image.open(ref_files[stem]).convert("RGB"))

            ssim = compute_ssim(render_img, ref_img)
            r_hash = compute_perceptual_hash(render_img)
            ref_hash = compute_perceptual_hash(ref_img)
            h_dist = hamming_distance(r_hash, ref_hash)

            status = "pass" if ssim >= threshold else "regression"
            results.append({
                "name": stem,
                "ssim": round(ssim, 4),
                "hash_distance": h_dist,
                "status": status,
                "render_path": str(render_files[stem]),
                "reference_path": str(ref_files[stem]),
            })
        except Exception as e:
            results.append({
                "name": stem,
                "ssim": 0,
                "status": "error",
                "error": str(e),
            })

    for stem in sorted(unmatched_renders):
        results.append({"name": stem, "status": "new", "render_path": str(render_files[stem])})

    for stem in sorted(unmatched_refs):
        results.append({"name": stem, "status": "missing", "reference_path": str(ref_files[stem])})

    return results


def generate_html_report(results: list[dict], output_path: Path):
    """Generate an HTML visual regression report."""
    regressions = [r for r in results if r["status"] == "regression"]
    passes = [r for r in results if r["status"] == "pass"]

    html = [
        "<!DOCTYPE html><html><head>",
        "<title>Visual Regression Report</title>",
        "<style>body{font-family:monospace;margin:20px}",
        "table{border-collapse:collapse;width:100%}",
        "td,th{border:1px solid #ccc;padding:8px;text-align:left}",
        ".regression{background:#fdd}.pass{background:#dfd}",
        ".new{background:#ddf}.missing{background:#ffd}</style></head><body>",
        f"<h1>Visual Regression Report</h1>",
        f"<p>Generated: {datetime.now().isoformat()}</p>",
        f"<p>Total: {len(results)} | Pass: {len(passes)} | "
        f"Regressions: {len(regressions)}</p>",
        "<table><tr><th>Name</th><th>SSIM</th><th>Status</th></tr>",
    ]

    for r in sorted(results, key=lambda x: x.get("ssim", 0)):
        css_class = r["status"]
        ssim_str = f"{r.get('ssim', 'N/A')}"
        html.append(f"<tr class='{css_class}'><td>{r['name']}</td>"
                     f"<td>{ssim_str}</td><td>{r['status']}</td></tr>")

    html.append("</table></body></html>")
    output_path.write_text("\n".join(html), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="Visual regression testing")
    parser.add_argument("--renders", type=Path, required=True)
    parser.add_argument("--references", type=Path, required=True)
    parser.add_argument("--threshold", type=float, default=0.85)
    parser.add_argument("--output", type=Path,
                        default=REPO_ROOT / "outputs" / "visual_regression_report.html")
    parser.add_argument("--json-output", type=Path, default=None)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    results = compare_renders(args.renders, args.references, args.threshold)
    regressions = [r for r in results if r["status"] == "regression"]

    generate_html_report(results, args.output)
    print(f"Visual regression: {len(results)} compared, {len(regressions)} regressions")
    print(f"Report: {args.output}")

    if args.json_output:
        args.json_output.write_text(json.dumps(results, indent=2), encoding="utf-8")

    for r in regressions:
        print(f"  REGRESSION: {r['name']} (SSIM={r['ssim']:.4f})")

    if regressions:
        sys.exit(1)


if __name__ == "__main__":
    main()
