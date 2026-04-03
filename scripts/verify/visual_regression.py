#!/usr/bin/env python3
"""Visual regression testing: compare current renders against reference renders.

Uses SSIM to detect unexpected visual changes in building renders after
generator modifications. Flags buildings where the render changed significantly.

Usage:
    python scripts/verify/visual_regression.py --renders outputs/geometry_qa/ --references outputs/buildings_renders_v1/
    python scripts/verify/visual_regression.py --renders outputs/full/ --references outputs/qa_visual_check/ --threshold 0.90
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np


REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def parse_args():
    parser = argparse.ArgumentParser(description="Visual regression testing via SSIM.")
    parser.add_argument("--renders", type=Path, required=True, help="Directory with current renders")
    parser.add_argument("--references", type=Path, required=True, help="Directory with reference renders")
    parser.add_argument("--output", type=Path, default=REPO_ROOT / "outputs" / "visual_regression_report.json")
    parser.add_argument("--threshold", type=float, default=0.85, help="SSIM below this = regression (default 0.85)")
    parser.add_argument("--limit", type=int, default=None)
    return parser.parse_args()


def compute_ssim(img_a, img_b):
    """Compute SSIM between two images."""
    try:
        from skimage.metrics import structural_similarity as ssim
        import cv2

        # Load and resize to common size
        a = cv2.imread(str(img_a), cv2.IMREAD_GRAYSCALE)
        b = cv2.imread(str(img_b), cv2.IMREAD_GRAYSCALE)
        if a is None or b is None:
            return None

        h = min(a.shape[0], b.shape[0], 512)
        w = min(a.shape[1], b.shape[1], 512)
        a = cv2.resize(a, (w, h))
        b = cv2.resize(b, (w, h))

        return float(ssim(a, b))

    except ImportError:
        # Fallback: numpy-based simple comparison
        from PIL import Image
        a = np.array(Image.open(img_a).convert("L").resize((256, 256)))
        b = np.array(Image.open(img_b).convert("L").resize((256, 256)))
        a = a.astype(np.float64)
        b = b.astype(np.float64)

        mu_a = np.mean(a)
        mu_b = np.mean(b)
        sig_a = np.std(a)
        sig_b = np.std(b)
        sig_ab = np.mean((a - mu_a) * (b - mu_b))

        c1 = (0.01 * 255) ** 2
        c2 = (0.03 * 255) ** 2

        num = (2 * mu_a * mu_b + c1) * (2 * sig_ab + c2)
        den = (mu_a**2 + mu_b**2 + c1) * (sig_a**2 + sig_b**2 + c2)
        return float(num / den)


def main():
    args = parse_args()

    if not args.renders.exists():
        print(f"ERROR: Renders directory not found: {args.renders}")
        sys.exit(1)
    if not args.references.exists():
        print(f"ERROR: References directory not found: {args.references}")
        sys.exit(1)

    # Find matching pairs
    renders = {p.stem: p for p in args.renders.glob("*.png")}
    refs = {p.stem: p for p in args.references.glob("*.png")}

    common = sorted(set(renders.keys()) & set(refs.keys()))
    if args.limit:
        common = common[: args.limit]

    print(f"Visual regression: {len(common)} matching pairs "
          f"(renders: {len(renders)}, references: {len(refs)})")
    print(f"  Threshold: SSIM >= {args.threshold}")

    results = []
    regressions = 0
    start = time.time()

    for i, stem in enumerate(common, 1):
        score = compute_ssim(renders[stem], refs[stem])
        if score is None:
            results.append({"address": stem.replace("_", " "), "ssim": None, "status": "error"})
            continue

        status = "pass" if score >= args.threshold else "regression"
        if status == "regression":
            regressions += 1

        results.append({
            "address": stem.replace("_", " "),
            "ssim": round(score, 4),
            "status": status,
            "render": str(renders[stem]),
            "reference": str(refs[stem]),
        })

        if i % 100 == 0:
            print(f"  [{i}/{len(common)}] {regressions} regressions so far")

    elapsed = time.time() - start
    results.sort(key=lambda r: r.get("ssim") or 0)

    report = {
        "generated": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "threshold": args.threshold,
        "total_compared": len(results),
        "regressions": regressions,
        "pass": len(results) - regressions,
        "avg_ssim": round(np.mean([r["ssim"] for r in results if r.get("ssim") is not None]), 4),
        "results": results,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\nDone in {elapsed:.1f}s: {len(results) - regressions} pass, {regressions} regressions")
    if regressions:
        print(f"\nTop regressions:")
        for r in results[:5]:
            if r["status"] == "regression":
                print(f"  {r['address']:40s} SSIM={r['ssim']}")

    print(f"\nReport: {args.output}")


if __name__ == "__main__":
    main()
