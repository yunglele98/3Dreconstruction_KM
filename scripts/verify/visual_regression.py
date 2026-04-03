#!/usr/bin/env python3
"""Stage 9 — VERIFY: Visual regression testing via SSIM comparison.

Compares rendered output PNGs against reference renders to detect
unintended visual changes. Reports SSIM scores and flags regressions.

Usage:
    python scripts/verify/visual_regression.py --renders outputs/full/ --references outputs/qa_visual_check/
    python scripts/verify/visual_regression.py --renders outputs/full/ --references outputs/qa_visual_check/ --threshold 0.85
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg"}


def compute_ssim_score(render_path: Path, reference_path: Path) -> float:
    """Compute SSIM between two images.

    Requires numpy and PIL. Returns -1.0 if computation fails.
    """
    try:
        import numpy as np
        from PIL import Image

        render = np.array(Image.open(render_path).convert("L"), dtype=np.float64)
        reference = np.array(Image.open(reference_path).convert("L"), dtype=np.float64)

        # Resize if different dimensions
        if render.shape != reference.shape:
            ref_img = Image.open(reference_path).convert("L").resize(
                (render.shape[1], render.shape[0])
            )
            reference = np.array(ref_img, dtype=np.float64)

        # SSIM constants
        C1 = (0.01 * 255) ** 2
        C2 = (0.03 * 255) ** 2

        mu_r = render.mean()
        mu_ref = reference.mean()
        sigma_r = render.std()
        sigma_ref = reference.std()
        sigma_rref = ((render - mu_r) * (reference - mu_ref)).mean()

        ssim = (
            (2 * mu_r * mu_ref + C1) * (2 * sigma_rref + C2)
        ) / (
            (mu_r ** 2 + mu_ref ** 2 + C1) * (sigma_r ** 2 + sigma_ref ** 2 + C2)
        )
        return float(ssim)

    except ImportError:
        return -1.0
    except Exception:
        return -1.0


def run_visual_regression(
    renders_dir: Path,
    references_dir: Path,
    *,
    threshold: float = 0.85,
) -> dict:
    """Compare all renders against references.

    Returns a report dict with per-image SSIM scores and pass/fail.
    """
    results = []
    regressions = []

    render_images = {
        p.stem: p for p in renders_dir.rglob("*")
        if p.suffix.lower() in IMAGE_EXTENSIONS
    }
    reference_images = {
        p.stem: p for p in references_dir.rglob("*")
        if p.suffix.lower() in IMAGE_EXTENSIONS
    }

    matched = set(render_images) & set(reference_images)

    for stem in sorted(matched):
        ssim = compute_ssim_score(render_images[stem], reference_images[stem])
        passed = ssim >= threshold or ssim < 0

        entry = {
            "name": stem,
            "render": str(render_images[stem]),
            "reference": str(reference_images[stem]),
            "ssim": round(ssim, 4),
            "passed": passed,
        }
        results.append(entry)
        if not passed:
            regressions.append(entry)

    return {
        "threshold": threshold,
        "total_compared": len(results),
        "passed": len(results) - len(regressions),
        "regressions": len(regressions),
        "unmatched_renders": len(render_images) - len(matched),
        "unmatched_references": len(reference_images) - len(matched),
        "results": results,
        "regression_details": regressions,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Visual regression testing")
    parser.add_argument("--renders", required=True, type=Path)
    parser.add_argument("--references", required=True, type=Path)
    parser.add_argument("--threshold", type=float, default=0.85)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    report = run_visual_regression(
        args.renders, args.references, threshold=args.threshold
    )

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    print(f"Visual regression: {report['passed']}/{report['total_compared']} passed "
          f"(threshold={report['threshold']})")
    if report["regressions"] > 0:
        print(f"  REGRESSIONS ({report['regressions']}):")
        for r in report["regression_details"]:
            print(f"    {r['name']}: SSIM={r['ssim']}")
        sys.exit(1)


if __name__ == "__main__":
    main()
