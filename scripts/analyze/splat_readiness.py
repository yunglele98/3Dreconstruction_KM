#!/usr/bin/env python3
"""Gaussian splat readiness assessment for each building.

Evaluates photo coverage, angle diversity, COLMAP reconstruction status,
depth maps, and segmentation availability.  Produces a readiness score
(0-100) and tier per building.

Usage:
    python scripts/analyze/splat_readiness.py
    python scripts/analyze/splat_readiness.py --params params/ \
        --photo-index "PHOTOS KENSINGTON/csv/photo_address_index.csv" \
        --colmap point_clouds/colmap/ \
        --output outputs/splat_readiness/
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import defaultdict
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _load_params(params_dir: Path) -> list[dict]:
    result = []
    for p in sorted(params_dir.glob("*.json")):
        if p.name.startswith("_"):
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if data.get("skipped"):
            continue
        data["_file"] = str(p)
        result.append(data)
    return result


def _address(params: dict) -> str:
    return (
        params.get("building_name")
        or params.get("_meta", {}).get("address")
        or Path(params.get("_file", "unknown")).stem.replace("_", " ")
    )


def _street(params: dict) -> str:
    site = params.get("site") or {}
    street = site.get("street", "")
    if street:
        return street
    addr = _address(params)
    parts = addr.split()
    for i, p in enumerate(parts):
        if p.isdigit() and i < len(parts) - 1:
            return " ".join(parts[i + 1:])
    return addr


def _sanitize(addr: str) -> str:
    return re.sub(r"[^\w]", "_", addr.strip())


def _load_photo_index(index_path: Path) -> dict[str, list[str]]:
    """Return {address: [filename_strings]}."""
    mapping: dict[str, list[str]] = defaultdict(list)
    if not index_path.exists():
        return mapping
    with open(index_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            addr = (row.get("address") or row.get("ADDRESS") or "").strip()
            photo = (row.get("filename") or row.get("photo") or row.get("file") or "").strip()
            if addr and photo:
                mapping[addr].append(photo)
    return mapping


def _estimate_angle_diversity(filenames: list[str]) -> float:
    """Heuristic 0-1 for angle diversity from filenames/folders.

    Different parent folder names or significantly different numeric
    suffixes suggest different viewpoints.
    """
    if len(filenames) <= 1:
        return 0.0

    # Collect parent folder names and base names
    folders = set()
    numbers = []
    for fn in filenames:
        p = Path(fn)
        folders.add(str(p.parent).lower())
        # Extract trailing numbers from filename
        m = re.search(r"(\d+)", p.stem)
        if m:
            numbers.append(int(m.group(1)))

    folder_diversity = min(1.0, len(folders) / 3.0)

    num_diversity = 0.0
    if len(numbers) >= 2:
        spread = max(numbers) - min(numbers)
        num_diversity = min(1.0, spread / 20.0)

    count_bonus = min(1.0, len(filenames) / 10.0)

    return min(1.0, folder_diversity * 0.3 + num_diversity * 0.3 + count_bonus * 0.4)


def _check_colmap(colmap_dir: Path, address: str) -> dict:
    """Check if COLMAP reconstruction exists for this building."""
    sanitized = _sanitize(address)
    result = {"exists": False, "workspace_found": False, "points": 0}

    if not colmap_dir.exists():
        return result

    # Check for per-building workspace
    for pattern in [sanitized, sanitized.lower(), address.replace(" ", "_")]:
        ws = colmap_dir / pattern
        if ws.is_dir():
            result["workspace_found"] = True
            # Check for sparse reconstruction
            sparse = ws / "sparse" / "0"
            if sparse.is_dir():
                result["exists"] = True
                # Try to read points3D count from block_report.json
                report = ws / "block_report.json"
                if report.exists():
                    try:
                        rdata = json.loads(report.read_text(encoding="utf-8"))
                        result["points"] = rdata.get("num_points3D", 0)
                    except Exception:
                        pass
                # Check .ply files
                for ply in ws.rglob("*.ply"):
                    result["exists"] = True
                    break
            break

    # Also check for .ply files directly named after the building
    for ext in (".ply", ".las", ".laz"):
        candidate = colmap_dir / f"{sanitized}{ext}"
        if candidate.exists():
            result["exists"] = True
            break

    return result


def _check_depth_map(address: str) -> bool:
    sanitized = _sanitize(address)
    depth_dir = REPO_ROOT / "depth_maps"
    if not depth_dir.exists():
        return False
    for ext in (".npy", ".png"):
        if (depth_dir / f"{sanitized}{ext}").exists():
            return True
    # Glob fallback
    return any(depth_dir.glob(f"{sanitized}*"))


def _check_segmentation(address: str) -> bool:
    sanitized = _sanitize(address)
    seg_dir = REPO_ROOT / "segmentation"
    if not seg_dir.exists():
        return False
    for ext in (".json", ".png"):
        if (seg_dir / f"{sanitized}{ext}").exists():
            return True
    return any(seg_dir.glob(f"{sanitized}*"))


def assess_building(
    address: str,
    photo_filenames: list[str],
    colmap_dir: Path,
    params: dict,
) -> dict:
    street = _street(params)
    result: dict = {"address": address, "street": street}

    # 1. Photo count (30 pts: 5+ = 20, 10+ = 30)
    n_photos = len(photo_filenames)
    result["photo_count"] = n_photos
    if n_photos >= 10:
        photo_score = 30.0
    elif n_photos >= 5:
        photo_score = 20.0 + (n_photos - 5) * 2.0
    elif n_photos >= 3:
        photo_score = 10.0 + (n_photos - 3) * 5.0
    elif n_photos >= 1:
        photo_score = n_photos * 3.0
    else:
        photo_score = 0.0
    result["photo_score"] = round(min(30.0, photo_score), 1)

    # 2. Angle diversity (20 pts)
    diversity = _estimate_angle_diversity(photo_filenames)
    result["angle_diversity"] = round(diversity, 3)
    diversity_score = diversity * 20.0
    result["diversity_score"] = round(diversity_score, 1)

    # 3. COLMAP reconstruction (25 pts)
    colmap = _check_colmap(colmap_dir, address)
    result["colmap"] = colmap
    colmap_score = 0.0
    if colmap["exists"]:
        colmap_score = 25.0
    elif colmap["workspace_found"]:
        colmap_score = 10.0
    result["colmap_score"] = round(colmap_score, 1)

    # 4. Depth map (15 pts)
    has_depth = _check_depth_map(address)
    result["has_depth_map"] = has_depth
    depth_score = 15.0 if has_depth else 0.0
    result["depth_score"] = round(depth_score, 1)

    # 5. Segmentation (10 pts)
    has_seg = _check_segmentation(address)
    result["has_segmentation"] = has_seg
    seg_score = 10.0 if has_seg else 0.0
    result["seg_score"] = round(seg_score, 1)

    # Overall
    total = photo_score + diversity_score + colmap_score + depth_score + seg_score
    total = min(100.0, max(0.0, total))
    result["readiness_score"] = round(total, 1)

    if total >= 70:
        result["tier"] = "ready"
    elif total >= 30:
        result["tier"] = "needs-photos"
    else:
        result["tier"] = "parametric-only"

    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Gaussian splat readiness assessment")
    parser.add_argument("--params", type=Path, default=REPO_ROOT / "params")
    parser.add_argument("--photo-index", type=Path, default=REPO_ROOT / "PHOTOS KENSINGTON" / "csv" / "photo_address_index.csv")
    parser.add_argument("--colmap", type=Path, default=REPO_ROOT / "point_clouds" / "colmap")
    parser.add_argument("--output", type=Path, default=REPO_ROOT / "outputs" / "splat_readiness")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)

    print(f"Loading photo index from {args.photo_index} ...")
    photo_index = _load_photo_index(args.photo_index)
    print(f"  {len(photo_index)} addresses in index")

    print(f"Loading params from {args.params} ...")
    buildings = _load_params(args.params)
    print(f"  {len(buildings)} active buildings")

    results = []
    for i, params in enumerate(buildings):
        if args.limit and i >= args.limit:
            break
        addr = _address(params)
        photos = photo_index.get(addr, [])
        result = assess_building(addr, photos, args.colmap, params)
        results.append(result)

    # Aggregate
    scores = [r["readiness_score"] for r in results]
    arr = np.array(scores) if scores else np.array([0.0])

    tier_counts = defaultdict(int)
    for r in results:
        tier_counts[r["tier"]] += 1

    # Per-street
    street_data: dict[str, list[dict]] = defaultdict(list)
    for r in results:
        street_data[r["street"]].append(r)

    street_summary = {}
    for s, items in sorted(street_data.items()):
        s_scores = [it["readiness_score"] for it in items]
        street_summary[s] = {
            "count": len(items),
            "avg_score": round(sum(s_scores) / len(s_scores), 1),
            "ready": sum(1 for it in items if it["tier"] == "ready"),
            "needs_photos": sum(1 for it in items if it["tier"] == "needs-photos"),
            "parametric_only": sum(1 for it in items if it["tier"] == "parametric-only"),
        }

    # Priority acquisition targets (low score, some photos)
    priority = sorted(
        [r for r in results if r["tier"] == "needs-photos"],
        key=lambda r: -r["photo_count"],  # prioritise those closest to ready
    )[:20]
    priority_brief = [
        {"address": r["address"], "score": r["readiness_score"], "photos": r["photo_count"]}
        for r in priority
    ]

    # Ranked readiness list (top candidates)
    ranked = sorted(results, key=lambda r: -r["readiness_score"])[:30]
    ranked_brief = [
        {"address": r["address"], "score": r["readiness_score"], "tier": r["tier"]}
        for r in ranked
    ]

    summary = {
        "total_buildings": len(results),
        "avg_score": round(float(arr.mean()), 1),
        "median_score": round(float(np.median(arr)), 1),
        "tier_distribution": dict(tier_counts),
        "per_street_summary": street_summary,
        "top_30_ready": ranked_brief,
        "priority_acquisition_targets": priority_brief,
    }

    report = {"summary": summary, "buildings": results}
    out_path = args.output / "splat_readiness_report.json"
    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\nReport written to {out_path}")
    print(f"  Buildings: {len(results)} | Avg: {summary['avg_score']} | Median: {summary['median_score']}")
    print(f"  Tiers: {dict(tier_counts)}")


if __name__ == "__main__":
    main()
