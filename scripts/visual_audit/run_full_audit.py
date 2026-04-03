#!/usr/bin/env python3
"""Phase 0: Visual audit entry point — compare parametric renders against field photos.

Produces a ranked priority queue of buildings sorted by visual discrepancy (worst first),
driving which buildings get photogrammetry, segmentation, or colour fixes.

Usage:
    python scripts/visual_audit/run_full_audit.py                    # full audit (~35 min)
    python scripts/visual_audit/run_full_audit.py --limit 20         # quick test
    python scripts/visual_audit/run_full_audit.py --output outputs/visual_audit_test/
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import re
import time
from pathlib import Path

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PHOTO_INDEX = REPO_ROOT / "PHOTOS KENSINGTON" / "csv" / "photo_address_index.csv"
RENDERS_DIR = REPO_ROOT / "outputs" / "buildings_renders_v1"
DEFAULT_OUTPUT = REPO_ROOT / "outputs" / "visual_audit"

# ---------------------------------------------------------------------------
# Image comparison helpers
# ---------------------------------------------------------------------------

def _load_image_as_array(path):
    """Load an image file as a numpy-compatible grayscale array."""
    from PIL import Image
    import numpy as np
    img = Image.open(path).convert("L")
    # Resize to common resolution for fair comparison
    img = img.resize((256, 256), Image.LANCZOS)
    return np.asarray(img, dtype=np.float64)


def _compute_ssim(img_a, img_b):
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
    # At MSE=0 → 1.0, MSE=1000 → 0.5, MSE=5000 → 0.17
    return 1.0 / (1.0 + mse / 1000.0)


# ---------------------------------------------------------------------------
# Photo index loader
# ---------------------------------------------------------------------------

def load_photo_index(index_path: Path) -> dict[str, list[Path]]:
    """Load photo-address CSV and return {address: [photo_paths]}.

    Expects columns: filename (or photo), address.
    """
    if not index_path.exists():
        logger.warning("Photo index not found: %s", index_path)
        return {}

    photos_dir = index_path.parent.parent  # PHOTOS KENSINGTON/
    mapping: dict[str, list[Path]] = {}

    with index_path.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        # Normalise header names (lowercase, strip)
        if reader.fieldnames:
            reader.fieldnames = [h.strip().lower() for h in reader.fieldnames]
        for row in reader:
            filename = (row.get("filename") or row.get("photo") or row.get("file") or "").strip()
            address = (row.get("address") or row.get("address_full") or "").strip()
            if not filename or not address:
                continue
            photo_path = photos_dir / filename
            if not photo_path.exists():
                # Try subdirectories
                candidates = list(photos_dir.rglob(filename))
                if candidates:
                    photo_path = candidates[0]
                else:
                    continue
            mapping.setdefault(address, []).append(photo_path)

    logger.info("Photo index: %d addresses, %d photos", len(mapping), sum(len(v) for v in mapping.values()))
    return mapping


def _sanitize_filename(address: str) -> str:
    """Convert address to the filename stem used for renders (spaces → underscores)."""
    return re.sub(r"\s+", "_", address.strip())


def find_render(address: str, renders_dir: Path) -> Path | None:
    """Find a render PNG for a given address."""
    stem = _sanitize_filename(address)
    # Try common patterns
    for pattern in [f"{stem}.png", f"{stem}.jpg", f"{stem}_render.png"]:
        p = renders_dir / pattern
        if p.exists():
            return p
    # Glob fallback
    candidates = list(renders_dir.glob(f"{stem}*"))
    image_exts = {".png", ".jpg", ".jpeg"}
    for c in candidates:
        if c.suffix.lower() in image_exts:
            return c
    return None


# ---------------------------------------------------------------------------
# Issue detection heuristics
# ---------------------------------------------------------------------------

def detect_issues(score: float) -> list[str]:
    """Detect likely issues based on SSIM score thresholds."""
    issues = []
    if score < 0.20:
        issues.append("major_geometry_mismatch")
        issues.append("colour_mismatch")
    elif score < 0.35:
        issues.append("geometry_mismatch")
        issues.append("possible_colour_mismatch")
    elif score < 0.50:
        issues.append("moderate_discrepancy")
    elif score < 0.65:
        issues.append("minor_discrepancy")
    if not issues:
        issues.append("acceptable")
    return issues


def score_to_tier(score: float) -> str:
    """Map SSIM score to priority tier."""
    if score < 0.20:
        return "critical"
    elif score < 0.35:
        return "high"
    elif score < 0.50:
        return "medium"
    elif score < 0.65:
        return "low"
    return "acceptable"


# ---------------------------------------------------------------------------
# Main audit logic
# ---------------------------------------------------------------------------

def run_audit(photo_index: dict[str, list[Path]], renders_dir: Path, limit: int | None = None) -> list[dict]:
    """Compare renders against photos for each building.

    Returns a list of audit entries sorted by score (worst first).
    """
    import numpy as np

    addresses = sorted(photo_index.keys())
    if limit:
        addresses = addresses[:limit]

    results = []
    skipped_no_render = 0
    skipped_load_error = 0

    for addr in addresses:
        render_path = find_render(addr, renders_dir)
        if render_path is None:
            skipped_no_render += 1
            logger.debug("No render for: %s", addr)
            continue

        # Use the first available photo for comparison
        photo_path = photo_index[addr][0]

        try:
            render_arr = _load_image_as_array(render_path)
            photo_arr = _load_image_as_array(photo_path)
        except Exception as exc:
            skipped_load_error += 1
            logger.warning("Image load error for %s: %s", addr, exc)
            continue

        score = _compute_ssim(render_arr, photo_arr)
        issues = detect_issues(score)

        results.append({
            "address": addr,
            "score": round(score, 4),
            "tier": score_to_tier(score),
            "render_path": str(render_path.relative_to(REPO_ROOT)),
            "photo_path": str(photo_path.relative_to(REPO_ROOT)),
            "photo_count": len(photo_index[addr]),
            "needs": issues,
        })

    # Sort worst first (lowest score)
    results.sort(key=lambda x: x["score"])

    logger.info(
        "Audit complete: %d compared, %d skipped (no render), %d skipped (load error)",
        len(results), skipped_no_render, skipped_load_error,
    )
    return results


def build_summary(results: list[dict]) -> dict:
    """Build aggregate audit summary statistics."""
    import numpy as np

    if not results:
        return {
            "total_audited": 0,
            "avg_score": 0,
            "median_score": 0,
            "min_score": 0,
            "max_score": 0,
            "tier_distribution": {},
            "score_histogram": {},
        }

    scores = [r["score"] for r in results]
    tiers = {}
    for r in results:
        tiers[r["tier"]] = tiers.get(r["tier"], 0) + 1

    # Score histogram (buckets of 0.1)
    histogram = {}
    for s in scores:
        bucket = f"{int(s * 10) / 10:.1f}-{int(s * 10) / 10 + 0.1:.1f}"
        histogram[bucket] = histogram.get(bucket, 0) + 1

    return {
        "total_audited": len(results),
        "avg_score": round(float(np.mean(scores)), 4),
        "median_score": round(float(np.median(scores)), 4),
        "min_score": round(float(min(scores)), 4),
        "max_score": round(float(max(scores)), 4),
        "tier_distribution": tiers,
        "score_histogram": histogram,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Phase 0: Visual audit — compare parametric renders against field photos",
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Limit to N buildings for quick testing",
    )
    parser.add_argument(
        "--output", type=Path, default=DEFAULT_OUTPUT,
        help="Output directory (default: outputs/visual_audit/)",
    )
    parser.add_argument(
        "--photo-index", type=Path, default=PHOTO_INDEX,
        help="Path to photo address index CSV",
    )
    parser.add_argument(
        "--renders-dir", type=Path, default=RENDERS_DIR,
        help="Path to renders directory",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    start = time.time()

    # Load photo index
    logger.info("Loading photo index from %s", args.photo_index)
    photo_index = load_photo_index(args.photo_index)
    if not photo_index:
        logger.error("No photos found in index. Exiting.")
        return

    # Verify renders directory
    if not args.renders_dir.exists():
        logger.error("Renders directory not found: %s", args.renders_dir)
        return

    # Run audit
    logger.info(
        "Running audit: %d addresses, renders from %s%s",
        len(photo_index),
        args.renders_dir,
        f" (limit {args.limit})" if args.limit else "",
    )
    results = run_audit(photo_index, args.renders_dir, limit=args.limit)

    # Write outputs
    args.output.mkdir(parents=True, exist_ok=True)

    priority_path = args.output / "priority_queue.json"
    priority_path.write_text(
        json.dumps({"buildings": results}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    logger.info("Priority queue: %s (%d buildings)", priority_path, len(results))

    summary = build_summary(results)
    summary_path = args.output / "audit_summary.json"
    summary_path.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    logger.info("Audit summary: %s", summary_path)

    elapsed = time.time() - start
    logger.info("Done in %.1f seconds", elapsed)

    # Print quick stats
    if results:
        logger.info("")
        logger.info("=== Audit Summary ===")
        logger.info("  Total audited:  %d", summary["total_audited"])
        logger.info("  Avg score:      %.3f", summary["avg_score"])
        logger.info("  Median score:   %.3f", summary["median_score"])
        logger.info("  Tiers: %s", ", ".join(f"{k}={v}" for k, v in sorted(summary["tier_distribution"].items())))
        logger.info("")
        logger.info("  Worst 5:")
        for r in results[:5]:
            logger.info("    %.3f  %s  [%s]", r["score"], r["address"], ", ".join(r["needs"]))


if __name__ == "__main__":
    main()
