#!/usr/bin/env python3
"""Phase 0: Full visual audit — compare parametric renders against field photos.

Compares outputs/buildings_renders_v1/ renders against PHOTOS KENSINGTON/ to
produce a ranked priority queue driving downstream pipeline decisions.

Usage:
    python scripts/visual_audit/run_full_audit.py                    # full audit
    python scripts/visual_audit/run_full_audit.py --limit 20         # quick test
    python scripts/visual_audit/run_full_audit.py --street "Augusta Ave"
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
RENDERS_DIR = REPO_ROOT / "outputs" / "buildings_renders_v1"
PHOTO_DIR = REPO_ROOT / "PHOTOS KENSINGTON"
PHOTO_INDEX = PHOTO_DIR / "csv" / "photo_address_index.csv"
PARAMS_DIR = REPO_ROOT / "params"
OUTPUT_DIR = REPO_ROOT / "outputs" / "visual_audit"


def load_photo_index() -> dict[str, list[str]]:
    """Load photo index CSV, return address -> [filenames]."""
    by_address: dict[str, list[str]] = defaultdict(list)
    if not PHOTO_INDEX.exists():
        return dict(by_address)
    with open(PHOTO_INDEX, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            addr = (row.get("address_or_location") or "").strip()
            fname = (row.get("filename") or "").strip()
            if addr and fname:
                by_address[addr].append(fname)
    return dict(by_address)


def compute_ssim_score(render_path: Path, photo_path: Path) -> float:
    """Compute SSIM between render and photo. Returns 0.0 on error."""
    try:
        from PIL import Image
        from skimage.metrics import structural_similarity

        render = np.array(Image.open(render_path).convert("RGB").resize((512, 512)))
        photo = np.array(Image.open(photo_path).convert("RGB").resize((512, 512)))
        return structural_similarity(render, photo, channel_axis=2, data_range=255)
    except Exception:
        return 0.0


def compute_colour_distance(render_path: Path, photo_path: Path) -> float:
    """Compute mean colour distance between render and photo."""
    try:
        from PIL import Image
        render = np.array(Image.open(render_path).convert("RGB").resize((256, 256)), dtype=np.float32)
        photo = np.array(Image.open(photo_path).convert("RGB").resize((256, 256)), dtype=np.float32)

        render_mean = render.reshape(-1, 3).mean(axis=0)
        photo_mean = photo.reshape(-1, 3).mean(axis=0)
        return float(np.linalg.norm(render_mean - photo_mean))
    except Exception:
        return 255.0


def audit_building(address: str, render_path: Path | None, photo_paths: list[Path],
                   params: dict) -> dict:
    """Audit a single building's render against photos."""
    result = {
        "address": address,
        "has_render": render_path is not None and render_path.exists(),
        "photo_count": len(photo_paths),
        "ssim_score": 0.0,
        "colour_distance": 255.0,
        "issues": [],
        "priority_score": 0.0,
    }

    if not result["has_render"]:
        result["issues"].append("no_render")
        result["priority_score"] = 100.0  # Highest priority
        return result

    if not photo_paths:
        result["issues"].append("no_photos")
        result["priority_score"] = 10.0  # Low priority — can't compare
        return result

    # Compare against best photo
    best_ssim = 0.0
    best_colour_dist = 255.0
    for pp in photo_paths[:3]:  # Limit to 3 photos
        ssim = compute_ssim_score(render_path, pp)
        cdist = compute_colour_distance(render_path, pp)
        if ssim > best_ssim:
            best_ssim = ssim
            best_colour_dist = cdist

    result["ssim_score"] = round(best_ssim, 4)
    result["colour_distance"] = round(best_colour_dist, 1)

    # Identify issues
    if best_ssim < 0.3:
        result["issues"].append("major_geometry_mismatch")
    elif best_ssim < 0.5:
        result["issues"].append("moderate_geometry_mismatch")

    if best_colour_dist > 80:
        result["issues"].append("colour_mismatch")

    # Check param completeness
    if not params.get("facade_detail", {}).get("brick_colour_hex"):
        result["issues"].append("missing_brick_colour")
    if not params.get("windows_detail"):
        result["issues"].append("missing_window_detail")

    # HCD contributing buildings get priority boost
    contributing = params.get("hcd_data", {}).get("contributing") == "Yes"

    # Priority score: higher = needs more attention
    score = (1.0 - best_ssim) * 50 + best_colour_dist / 5
    if contributing:
        score *= 1.5
    if len(result["issues"]) > 2:
        score *= 1.3
    result["priority_score"] = round(score, 1)

    return result


def run_audit(
    limit: int | None = None,
    street_filter: str | None = None,
) -> list[dict]:
    """Run full visual audit across all buildings."""
    photo_index = load_photo_index()
    results = []
    count = 0

    for param_file in sorted(PARAMS_DIR.glob("*.json")):
        if param_file.name.startswith("_"):
            continue
        if limit and count >= limit:
            break

        try:
            params = json.loads(param_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue

        if params.get("skipped"):
            continue

        address = params.get("_meta", {}).get("address") or params.get("building_name", param_file.stem)
        street = params.get("site", {}).get("street", "")

        if street_filter and street_filter.lower() not in street.lower():
            continue

        # Find render
        stem = param_file.stem
        render_path = None
        for ext in [".png", ".jpg"]:
            candidate = RENDERS_DIR / f"{stem}{ext}"
            if candidate.exists():
                render_path = candidate
                break

        # Find photos
        photo_filenames = photo_index.get(address, [])
        photo_paths = []
        for fname in photo_filenames:
            fp = PHOTO_DIR / fname
            if fp.exists():
                photo_paths.append(fp)

        result = audit_building(address, render_path, photo_paths, params)
        result["street"] = street
        results.append(result)
        count += 1

        if count % 50 == 0:
            logger.info(f"  Audited {count} buildings...")

    # Sort by priority (highest first)
    results.sort(key=lambda r: r["priority_score"], reverse=True)
    return results


def generate_colmap_priority(results: list[dict]) -> list[dict]:
    """Generate COLMAP block priority queue from audit results."""
    by_street: dict[str, list[dict]] = defaultdict(list)
    for r in results:
        by_street[r.get("street", "unknown")].append(r)

    blocks = []
    for street, buildings in by_street.items():
        photo_buildings = [b for b in buildings if b["photo_count"] >= 3]
        avg_priority = np.mean([b["priority_score"] for b in buildings]) if buildings else 0
        blocks.append({
            "block": street,
            "building_count": len(buildings),
            "total_photos": sum(b["photo_count"] for b in buildings),
            "colmap_candidates": len(photo_buildings),
            "priority_score": round(float(avg_priority), 1),
        })

    blocks.sort(key=lambda b: b["priority_score"], reverse=True)
    return blocks


def main():
    parser = argparse.ArgumentParser(description="Phase 0: Full visual audit")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--street", type=str, default=None)
    parser.add_argument("--output", type=Path, default=OUTPUT_DIR)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    logger.info("Phase 0: Visual Audit")
    logger.info(f"  Renders: {RENDERS_DIR}")
    logger.info(f"  Photos: {PHOTO_DIR}")

    results = run_audit(limit=args.limit, street_filter=args.street)

    args.output.mkdir(parents=True, exist_ok=True)

    # Save priority queue
    pq_path = args.output / "priority_queue.json"
    pq_path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")

    # Save COLMAP priority
    colmap_pq = generate_colmap_priority(results)
    colmap_path = args.output / "colmap_priority.json"
    colmap_path.write_text(json.dumps(colmap_pq, indent=2, ensure_ascii=False), encoding="utf-8")

    # Summary
    issues_count = sum(1 for r in results if r["issues"])
    no_render = sum(1 for r in results if not r["has_render"])
    no_photos = sum(1 for r in results if r["photo_count"] == 0)

    logger.info(f"\nAudit complete: {len(results)} buildings")
    logger.info(f"  With issues: {issues_count}")
    logger.info(f"  No render: {no_render}")
    logger.info(f"  No photos: {no_photos}")
    logger.info(f"  Output: {pq_path}")

    # Print top 10 priority
    logger.info(f"\nTop 10 priority buildings:")
    for r in results[:10]:
        issues = ", ".join(r["issues"]) if r["issues"] else "none"
        logger.info(f"  [{r['priority_score']:5.1f}] {r['address']}: {issues}")


if __name__ == "__main__":
    main()
