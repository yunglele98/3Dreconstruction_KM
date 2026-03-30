#!/usr/bin/env python3
"""Batch SSIM comparison for render regression checks."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.ssim_single import compute_ssim, load_gray


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare matching images in two directories using SSIM.")
    parser.add_argument("--reference-dir", required=True)
    parser.add_argument("--new-dir", required=True)
    parser.add_argument("--threshold", type=float, default=0.85)
    parser.add_argument("--output", default="outputs/ssim_comparison.json")
    return parser.parse_args()


def find_matching_files(reference_dir: Path, new_dir: Path) -> list[str]:
    ref = {p.name for p in reference_dir.iterdir() if p.is_file()}
    new = {p.name for p in new_dir.iterdir() if p.is_file()}
    return sorted(ref & new)


def main() -> int:
    args = parse_args()
    reference_dir = Path(args.reference_dir)
    new_dir = Path(args.new_dir)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    matches = find_matching_files(reference_dir, new_dir)
    results = []
    for filename in matches:
        ref_path = reference_dir / filename
        new_path = new_dir / filename
        try:
            score = compute_ssim(load_gray(ref_path), load_gray(new_path))
            results.append(
                {
                    "filename": filename,
                    "reference": str(ref_path),
                    "candidate": str(new_path),
                    "ssim": round(score, 6),
                    "significant_change": score < args.threshold,
                }
            )
        except Exception as exc:
            results.append(
                {
                    "filename": filename,
                    "reference": str(ref_path),
                    "candidate": str(new_path),
                    "error": str(exc),
                    "ssim": 0.0,
                    "significant_change": True,
                }
            )

    sorted_results = sorted(results, key=lambda item: item["ssim"])
    changed = [item for item in sorted_results if item["significant_change"]]
    report = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "reference_dir": str(reference_dir),
        "new_dir": str(new_dir),
        "threshold": args.threshold,
        "total_compared": len(sorted_results),
        "significant_changes": len(changed),
        "results": sorted_results,
    }

    output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"[ssim] Wrote {output_path}")
    print(f"[ssim] Compared: {len(sorted_results)}")
    print(f"[ssim] Significant changes (<{args.threshold}): {len(changed)}")
    if changed:
        print("[ssim] Most changed:")
        for item in changed[:10]:
            print(f"  - {item['filename']}: {item['ssim']:.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
