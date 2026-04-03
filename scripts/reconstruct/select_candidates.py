#!/usr/bin/env python3
"""Select buildings with sufficient photo coverage for COLMAP photogrammetry.

Cross-references params/ with photo_address_index.csv to find buildings
with >= min_views geotagged photos. Adds spatial clustering to group
nearby buildings for block-level COLMAP runs and estimates photo overlap.

Usage:
    python scripts/reconstruct/select_candidates.py --params params/ --min-views 3
    python scripts/reconstruct/select_candidates.py --params params/ --street "Augusta Ave"
    python scripts/reconstruct/select_candidates.py --params params/ --min-views 1 --cluster
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def load_photo_index(index_path: Path) -> dict[str, list[str]]:
    """Load photo index CSV, return lowercased address -> [filenames]."""
    by_address: dict[str, list[str]] = defaultdict(list)
    if not index_path.exists():
        return dict(by_address)
    with open(index_path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            addr = (row.get("address_or_location") or "").strip()
            fname = (row.get("filename") or "").strip()
            if addr and fname:
                by_address[addr.lower()].append(fname)
    return dict(by_address)


def estimate_overlap(photo_count: int, facade_width_m: float) -> float:
    """Estimate photo overlap quality for COLMAP.

    More photos relative to facade width = better overlap.
    Returns 0-1 score where 1 = excellent overlap for reconstruction.
    """
    if photo_count == 0 or facade_width_m <= 0:
        return 0.0
    # Rough heuristic: 1 photo per 2m of facade is minimal,
    # 1 photo per 1m is good, more is better
    density = photo_count / max(facade_width_m, 1.0)
    return min(1.0, density / 1.0)  # saturates at 1 photo/metre


def haversine_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """Haversine distance in metres between two WGS84 points."""
    R = 6371000
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def cluster_candidates(candidates: list[dict], max_distance_m: float = 50.0) -> list[dict]:
    """Cluster nearby candidates into COLMAP blocks.

    Buildings within max_distance_m of each other are grouped for
    block-level reconstruction (more efficient than per-building).
    """
    if not candidates:
        return []

    # Filter to candidates with coords
    with_coords = [c for c in candidates if c.get("lon") and c.get("lat")]
    without_coords = [c for c in candidates if not (c.get("lon") and c.get("lat"))]

    # Simple greedy clustering
    assigned = [False] * len(with_coords)
    clusters = []

    for i, c in enumerate(with_coords):
        if assigned[i]:
            continue
        cluster = [c]
        assigned[i] = True

        for j in range(i + 1, len(with_coords)):
            if assigned[j]:
                continue
            dist = haversine_m(c["lon"], c["lat"],
                               with_coords[j]["lon"], with_coords[j]["lat"])
            if dist <= max_distance_m:
                cluster.append(with_coords[j])
                assigned[j] = True

        total_photos = sum(m["photo_count"] for m in cluster)
        streets = list(set(m["street"] for m in cluster if m.get("street")))
        clusters.append({
            "cluster_id": len(clusters),
            "buildings": len(cluster),
            "total_photos": total_photos,
            "streets": streets,
            "method": "block" if len(cluster) >= 3 else "per_building",
            "addresses": [m["address"] for m in cluster],
            "centroid_lon": np.mean([m["lon"] for m in cluster]),
            "centroid_lat": np.mean([m["lat"] for m in cluster]),
        })

    return clusters


def select_candidates(
    params_dir: Path,
    photo_index_path: Path,
    audit_priority_path: Path,
    min_views: int = 3,
    street_filter: str | None = None,
) -> list[dict]:
    """Select buildings with enough photos for photogrammetry.

    Args:
        params_dir: Directory with building param JSON files.
        photo_index_path: Path to photo_address_index.csv.
        audit_priority_path: Path to visual audit priority JSON (optional boost).
        min_views: Minimum number of photos required.
        street_filter: If set, only include buildings on this street.

    Returns:
        List of candidate dicts sorted by priority.
    """
    photo_index = load_photo_index(photo_index_path)

    # Load audit priority scores if available
    audit_scores: dict[str, float] = {}
    if audit_priority_path.exists():
        try:
            audit_data = json.loads(audit_priority_path.read_text(encoding="utf-8"))
            for entry in audit_data:
                addr = (entry.get("address") or "").lower()
                if addr:
                    audit_scores[addr] = entry.get("priority_score", 0)
        except (json.JSONDecodeError, OSError):
            pass

    candidates = []
    for param_file in sorted(params_dir.glob("*.json")):
        if param_file.name.startswith("_"):
            continue

        try:
            data = json.loads(param_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue

        if data.get("skipped"):
            continue

        address = (
            data.get("_meta", {}).get("address")
            or data.get("building_name")
            or param_file.stem.replace("_", " ")
        )
        street = data.get("site", {}).get("street", "")

        if street_filter and street_filter.lower() not in street.lower():
            continue

        photos = photo_index.get(address.lower(), [])
        photo_count = len(photos)

        if photo_count < min_views:
            continue

        contributing = data.get("hcd_data", {}).get("contributing") == "Yes"
        construction_date = data.get("hcd_data", {}).get("construction_date", "")
        audit_score = audit_scores.get(address.lower(), 0)
        facade_width = data.get("facade_width_m", 5.0)
        overlap = estimate_overlap(photo_count, facade_width)

        site = data.get("site", {})
        lon = site.get("lon")
        lat = site.get("lat")

        # Reconstruction method recommendation
        if photo_count >= 5 and overlap >= 0.5:
            method = "colmap_dense"
        elif photo_count >= 3:
            method = "colmap_sparse"
        elif photo_count >= 2:
            method = "dust3r"
        else:
            method = "dust3r_single"

        candidates.append({
            "address": address,
            "street": street,
            "param_file": str(param_file.name),
            "photo_count": photo_count,
            "photos": photos,
            "contributing": contributing,
            "construction_date": construction_date,
            "audit_score": audit_score,
            "overlap_score": round(overlap, 3),
            "recommended_method": method,
            "facade_width_m": facade_width,
            "lon": lon,
            "lat": lat,
        })

    # Sort: contributing first, then overlap, then photo count
    candidates.sort(
        key=lambda c: (c["contributing"], c["overlap_score"], c["photo_count"], c["audit_score"]),
        reverse=True,
    )

    return candidates


def main():
    parser = argparse.ArgumentParser(description="Select photogrammetry candidates")
    parser.add_argument("--params", type=Path, default=REPO_ROOT / "params")
    parser.add_argument("--photo-index", type=Path,
                        default=REPO_ROOT / "PHOTOS KENSINGTON" / "csv" / "photo_address_index.csv")
    parser.add_argument("--audit-priority", type=Path,
                        default=REPO_ROOT / "outputs" / "visual_audit" / "colmap_priority.json")
    parser.add_argument("--min-views", type=int, default=3)
    parser.add_argument("--street", type=str, default=None)
    parser.add_argument("--cluster", action="store_true",
                        help="Group candidates into spatial clusters for block COLMAP")
    parser.add_argument("--cluster-distance", type=float, default=50.0,
                        help="Max distance (m) for spatial clustering")
    parser.add_argument("--output", type=Path,
                        default=REPO_ROOT / "reconstruction_candidates.json")
    args = parser.parse_args()

    candidates = select_candidates(
        args.params, args.photo_index, args.audit_priority,
        min_views=args.min_views, street_filter=args.street,
    )

    print(f"Selected {len(candidates)} candidates (min {args.min_views} views)")

    # Method summary
    from collections import Counter
    methods = Counter(c["recommended_method"] for c in candidates)
    for method, count in methods.most_common():
        print(f"  {method}: {count}")

    for c in candidates[:10]:
        tag = "[HCD]" if c["contributing"] else "     "
        print(f"  {tag} {c['address']}: {c['photo_count']} photos, "
              f"overlap={c['overlap_score']:.2f}, method={c['recommended_method']}")
    if len(candidates) > 10:
        print(f"  ... and {len(candidates) - 10} more")

    output = {"candidates": candidates}

    if args.cluster:
        clusters = cluster_candidates(candidates, args.cluster_distance)
        output["clusters"] = clusters
        block_clusters = [cl for cl in clusters if cl["method"] == "block"]
        print(f"\nSpatial clusters: {len(clusters)} total, {len(block_clusters)} block-level")
        for cl in clusters[:5]:
            print(f"  Cluster {cl['cluster_id']}: {cl['buildings']} buildings, "
                  f"{cl['total_photos']} photos, {cl['method']}")

    args.output.write_text(
        json.dumps(output, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"\nOutput: {args.output}")


if __name__ == "__main__":
    main()
