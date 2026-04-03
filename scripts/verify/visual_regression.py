#!/usr/bin/env python3
"""Visual regression testing — compare current renders against baseline references.

Computes SSIM (or MSE-based fallback) between matching render PNGs and reports
regressions that fall below a configurable threshold. Designed for CI use
(exit code 1 on any regression).

Usage:
    python scripts/verify/visual_regression.py --renders outputs/full/ --references outputs/qa_visual_check/
    python scripts/verify/visual_regression.py --renders outputs/full/ --references outputs/qa_visual_check/ --threshold 0.90
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_OUTPUT = REPO_ROOT / "outputs" / "visual_regression"
DEFAULT_THRESHOLD = 0.85


# ---------------------------------------------------------------------------
# Image comparison helpers
# ---------------------------------------------------------------------------

def _load_image_as_array(path: Path):
    """Load an image file as a 256x256 grayscale numpy array."""
    from PIL import Image
    import numpy as np

    img = Image.open(path).convert("L")
    img = img.resize((256, 256), Image.LANCZOS)
    return np.asarray(img, dtype=np.float64)


def _compute_ssim(img_a, img_b) -> float:
    """Compute SSIM between two grayscale numpy arrays.

    Tries scikit-image first; falls back to a simple MSE-based similarity score.
    Returns a float in [0, 1] where 1 = identical.
    """
    try:
        from skimage.metrics import structural_similarity
        score, _ = structural_similarity(img_a, img_b, full=True)
        return float(score)
    except ImportError:
        pass

    # Fallback: convert MSE to a 0-1 similarity score
    import numpy as np

    mse = float(np.mean((img_a - img_b) ** 2))
    # Map MSE to similarity: score = 1 / (1 + mse/1000)
    # At MSE=0 -> 1.0, MSE=1000 -> 0.5, MSE=5000 -> 0.17
    return 1.0 / (1.0 + mse / 1000.0)


# ---------------------------------------------------------------------------
# Comparison logic
# ---------------------------------------------------------------------------

def collect_png_files(directory: Path) -> dict[str, Path]:
    """Return {filename: path} for all .png files in a directory."""
    if not directory.exists():
        return {}
    return {p.name: p for p in sorted(directory.glob("*.png"))}


def run_regression(
    renders_dir: Path,
    references_dir: Path,
    threshold: float,
) -> tuple[dict, list[dict]]:
    """Compare renders against references and classify each.

    Returns (summary_dict, results_list).
    """
    import numpy as np

    render_files = collect_png_files(renders_dir)
    reference_files = collect_png_files(references_dir)

    all_names = sorted(set(render_files.keys()) | set(reference_files.keys()))

    results = []
    scores = []

    for name in all_names:
        has_render = name in render_files
        has_reference = name in reference_files

        if has_render and not has_reference:
            results.append({"file": name, "score": None, "status": "new"})
            continue

        if has_reference and not has_render:
            results.append({"file": name, "score": None, "status": "missing"})
            continue

        # Both exist — compute similarity
        try:
            render_arr = _load_image_as_array(render_files[name])
            reference_arr = _load_image_as_array(reference_files[name])
            score = round(_compute_ssim(render_arr, reference_arr), 4)
        except Exception as exc:
            # Treat load errors as regressions
            results.append({
                "file": name,
                "score": 0.0,
                "status": "regression",
                "error": str(exc),
            })
            continue

        status = "pass" if score >= threshold else "regression"
        scores.append(score)
        results.append({"file": name, "score": score, "status": status})

    # Sort: regressions first (lowest score), then missing, new, pass
    status_order = {"regression": 0, "missing": 1, "new": 2, "pass": 3}
    results.sort(key=lambda r: (status_order.get(r["status"], 9), -(r["score"] or 0)))

    passed = sum(1 for r in results if r["status"] == "pass")
    regressions = sum(1 for r in results if r["status"] == "regression")
    new = sum(1 for r in results if r["status"] == "new")
    missing = sum(1 for r in results if r["status"] == "missing")
    avg_score = round(float(np.mean(scores)), 4) if scores else 0.0

    summary = {
        "total": len(results),
        "passed": passed,
        "regressions": regressions,
        "new": new,
        "missing": missing,
        "avg_score": avg_score,
    }

    return summary, results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Visual regression testing — compare current renders against baseline references",
    )
    parser.add_argument(
        "--renders", type=Path, required=True,
        help="Directory containing current render PNGs",
    )
    parser.add_argument(
        "--references", type=Path, required=True,
        help="Directory containing baseline reference PNGs",
    )
    parser.add_argument(
        "--threshold", type=float, default=DEFAULT_THRESHOLD,
        help=f"SSIM threshold for pass/fail (default: {DEFAULT_THRESHOLD})",
    )
    parser.add_argument(
        "--output", type=Path, default=DEFAULT_OUTPUT,
        help="Report output directory (default: outputs/visual_regression/)",
    )
    args = parser.parse_args()

    # Validate inputs
    if not args.renders.exists():
        print(f"Error: renders directory not found: {args.renders}", file=sys.stderr)
        sys.exit(1)
    if not args.references.exists():
        print(f"Error: references directory not found: {args.references}", file=sys.stderr)
        sys.exit(1)

    start = time.time()
    summary, results = run_regression(args.renders, args.references, args.threshold)
    elapsed = time.time() - start

    # Write report
    report = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "threshold": args.threshold,
        "renders_dir": str(args.renders),
        "references_dir": str(args.references),
        "elapsed_seconds": round(elapsed, 1),
        "summary": summary,
        "results": results,
    }

    args.output.mkdir(parents=True, exist_ok=True)
    report_path = args.output / "visual_regression_report.json"
    report_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    # Print summary
    print(
        f"Visual regression: {summary['passed']} passed, "
        f"{summary['regressions']} regressions, "
        f"{summary['new']} new, "
        f"{summary['missing']} missing "
        f"(threshold: {args.threshold})"
    )

    if summary["total"] > 0:
        print(f"Average score: {summary['avg_score']:.4f}")

    if summary["regressions"] > 0:
        print(f"\nRegressions ({summary['regressions']}):")
        for r in results:
            if r["status"] == "regression":
                score_str = f"{r['score']:.4f}" if r["score"] is not None else "N/A"
                print(f"  {score_str}  {r['file']}")

    if summary["missing"] > 0:
        print(f"\nMissing renders ({summary['missing']}):")
        for r in results:
            if r["status"] == "missing":
                print(f"  {r['file']}")

    print(f"\nReport: {report_path}")

    # Exit code 1 if any regressions found (for CI use)
    sys.exit(1 if summary["regressions"] > 0 else 0)


if __name__ == "__main__":
    main()
