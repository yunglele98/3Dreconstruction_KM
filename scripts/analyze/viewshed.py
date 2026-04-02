#!/usr/bin/env python3
"""Visibility scoring from road centerlines for Kensington Market.

Estimates how visible each building facade is from the street network.
Buildings at intersections or on wide streets score higher. Uses a
simplified raycasting approach from sample points along road centerlines.

Usage:
    python scripts/analyze/viewshed.py
    python scripts/analyze/viewshed.py --output outputs/spatial/viewshed_metrics.json
"""

from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SLIM_PATH = REPO_ROOT / "web" / "public" / "data" / "params-slim.json"
OUTPUT_DIR = REPO_ROOT / "outputs" / "spatial"

LATITUDE = 43.65
DEG_TO_M_LON = 111320 * math.cos(math.radians(LATITUDE))
DEG_TO_M_LAT = 111320


def load_buildings():
    data = json.loads(SLIM_PATH.read_text(encoding="utf-8"))
    return [b for b in data if b.get("lon") and b.get("lat")]


def generate_viewpoints():
    """Generate viewpoints along streets from OSM or a regular grid."""
    try:
        import osmnx as ox

        G = ox.graph_from_bbox(
            bbox=(-79.409, 43.650, -79.396, 43.659),
            network_type="walk",
        )
        # Sample points along edges
        viewpoints = []
        edges = ox.graph_to_gdfs(G, nodes=False)
        for _, edge in edges.iterrows():
            geom = edge.geometry
            length = geom.length * 111320  # approx metres
            n_points = max(1, int(length / 10))  # one point every ~10m
            for i in range(n_points):
                frac = i / max(n_points, 1)
                pt = geom.interpolate(frac, normalized=True)
                viewpoints.append((pt.x, pt.y))

        print(f"  {len(viewpoints)} viewpoints from street network")
        return viewpoints

    except Exception as e:
        print(f"  OSMnx failed ({e}), using grid fallback")
        # Fallback: regular grid
        viewpoints = []
        for lon in np.arange(-79.408, -79.397, 0.0001):
            for lat in np.arange(43.651, 43.658, 0.0001):
                viewpoints.append((lon, lat))
        print(f"  {len(viewpoints)} viewpoints from grid")
        return viewpoints


def compute_visibility(buildings, viewpoints):
    """Score each building by how many viewpoints can see its facade."""
    n_buildings = len(buildings)
    n_viewpoints = len(viewpoints)

    # Pre-compute building positions in metres (relative to centroid)
    cx = np.mean([b["lon"] for b in buildings])
    cy = np.mean([b["lat"] for b in buildings])

    bx = np.array([(b["lon"] - cx) * DEG_TO_M_LON for b in buildings])
    by = np.array([(b["lat"] - cy) * DEG_TO_M_LAT for b in buildings])
    bw = np.array([(b.get("width") or 6) / 2 for b in buildings])

    # For each viewpoint, find visible buildings (within 30m, unobstructed)
    visibility_count = np.zeros(n_buildings, dtype=int)
    max_view_dist = 30  # metres

    for vlon, vlat in viewpoints:
        vx = (vlon - cx) * DEG_TO_M_LON
        vy = (vlat - cy) * DEG_TO_M_LAT

        # Distances to all buildings
        dx = bx - vx
        dy = by - vy
        dists = np.sqrt(dx * dx + dy * dy)

        # Buildings within view distance
        nearby = np.where(dists < max_view_dist)[0]

        # Simple occlusion: sort by distance, mark closer buildings as blocking
        if len(nearby) == 0:
            continue

        sorted_idx = nearby[np.argsort(dists[nearby])]

        # First 3 nearest are visible (simplified - no full raycasting)
        for idx in sorted_idx[:3]:
            visibility_count[idx] += 1

    # Normalize to 0-100
    max_vis = max(visibility_count.max(), 1)
    visibility_scores = (visibility_count / max_vis * 100).round(1)

    results = []
    for i, b in enumerate(buildings):
        results.append({
            "address": b["address"],
            "lon": b["lon"],
            "lat": b["lat"],
            "street": b.get("street", ""),
            "visibility_count": int(visibility_count[i]),
            "visibility_score": float(visibility_scores[i]),
            "height_m": b.get("height"),
            "width_m": b.get("width"),
        })

    return results


def main():
    parser = argparse.ArgumentParser(description="Visibility scoring from road centerlines.")
    parser.add_argument("--output", type=Path, default=OUTPUT_DIR / "viewshed_metrics.json")
    args = parser.parse_args()

    print("Viewshed analysis: Kensington Market")
    buildings = load_buildings()
    print(f"  {len(buildings)} buildings loaded")

    viewpoints = generate_viewpoints()

    print("  Computing visibility scores...")
    building_metrics = compute_visibility(buildings, viewpoints)

    # Per-street aggregation
    by_street = defaultdict(list)
    for m in building_metrics:
        by_street[m["street"]].append(m)

    street_summary = {}
    for street, bldgs in sorted(by_street.items()):
        if not street:
            continue
        scores = [b["visibility_score"] for b in bldgs]
        street_summary[street] = {
            "count": len(bldgs),
            "avg_visibility": round(float(np.mean(scores)), 1),
            "max_visibility": round(float(np.max(scores)), 1),
            "high_visibility_count": sum(1 for s in scores if s >= 70),
        }

    all_scores = [b["visibility_score"] for b in building_metrics]
    overall = {
        "building_count": len(building_metrics),
        "viewpoint_count": len(viewpoints),
        "avg_visibility": round(float(np.mean(all_scores)), 1),
        "high_visibility_buildings": sum(1 for s in all_scores if s >= 70),
        "low_visibility_buildings": sum(1 for s in all_scores if s < 20),
    }

    result = {
        "overall": overall,
        "streets": street_summary,
        "buildings": building_metrics,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    print(f"\nOverall visibility: {overall['avg_visibility']}/100")
    print(f"  High visibility (>=70): {overall['high_visibility_buildings']} buildings")
    print(f"  Low visibility (<20): {overall['low_visibility_buildings']} buildings")
    print(f"\nTop 5 streets by visibility:")
    for s, v in sorted(street_summary.items(), key=lambda x: -x[1]["avg_visibility"])[:5]:
        print(f"  {s}: {v['avg_visibility']}")
    print(f"\nOutput: {args.output}")


if __name__ == "__main__":
    main()
