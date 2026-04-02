#!/usr/bin/env python3
"""Walkability and accessibility scoring for Kensington Market.

Computes walking distance to amenities (transit, parks, shops) using
network analysis. Falls back to Euclidean distance if pandana is
unavailable.

Usage:
    python scripts/analyze/accessibility.py
    python scripts/analyze/accessibility.py --output outputs/spatial/accessibility_metrics.json
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

import geopandas as gpd
import numpy as np
from shapely.geometry import Point

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SLIM_PATH = REPO_ROOT / "web" / "public" / "data" / "params-slim.json"
OUTPUT_DIR = REPO_ROOT / "outputs" / "spatial"

# Kensington Market bounding box
BBOX_NORTH = 43.659
BBOX_SOUTH = 43.650
BBOX_EAST = -79.396
BBOX_WEST = -79.409

# Amenity categories to query from OSM
AMENITY_TAGS = {
    "transit": {"highway": "bus_stop", "railway": "subway_entrance"},
    "food": {"shop": ["supermarket", "convenience", "bakery", "butcher", "greengrocer"]},
    "restaurant": {"amenity": ["restaurant", "cafe", "bar"]},
    "park": {"leisure": ["park", "garden"]},
    "school": {"amenity": ["school", "library"]},
    "health": {"amenity": ["pharmacy", "clinic", "hospital"]},
}


def load_buildings():
    data = json.loads(SLIM_PATH.read_text(encoding="utf-8"))
    return [b for b in data if b.get("lon") and b.get("lat")]


def fetch_amenities():
    """Fetch amenities from OSM via OSMnx."""
    import osmnx as ox

    amenities = {}

    # Transit stops
    print("  Fetching transit stops...")
    try:
        transit = ox.features_from_bbox(
            bbox=(BBOX_WEST, BBOX_SOUTH, BBOX_EAST, BBOX_NORTH),
            tags={"highway": "bus_stop"},
        )
        amenities["transit"] = transit
        print(f"    {len(transit)} transit stops")
    except Exception as e:
        print(f"    Transit fetch failed: {e}")
        amenities["transit"] = gpd.GeoDataFrame()

    # Food/shops
    print("  Fetching food shops...")
    try:
        food = ox.features_from_bbox(
            bbox=(BBOX_WEST, BBOX_SOUTH, BBOX_EAST, BBOX_NORTH),
            tags={"shop": True},
        )
        amenities["food"] = food
        print(f"    {len(food)} shops")
    except Exception as e:
        print(f"    Food fetch failed: {e}")
        amenities["food"] = gpd.GeoDataFrame()

    # Restaurants/cafes
    print("  Fetching restaurants...")
    try:
        restaurants = ox.features_from_bbox(
            bbox=(BBOX_WEST, BBOX_SOUTH, BBOX_EAST, BBOX_NORTH),
            tags={"amenity": ["restaurant", "cafe", "bar"]},
        )
        amenities["restaurant"] = restaurants
        print(f"    {len(restaurants)} restaurants")
    except Exception as e:
        print(f"    Restaurant fetch failed: {e}")
        amenities["restaurant"] = gpd.GeoDataFrame()

    # Parks
    print("  Fetching parks...")
    try:
        parks = ox.features_from_bbox(
            bbox=(BBOX_WEST, BBOX_SOUTH, BBOX_EAST, BBOX_NORTH),
            tags={"leisure": ["park", "garden"]},
        )
        amenities["park"] = parks
        print(f"    {len(parks)} parks/gardens")
    except Exception as e:
        print(f"    Parks fetch failed: {e}")
        amenities["park"] = gpd.GeoDataFrame()

    return amenities


def euclidean_distance_m(lon1, lat1, lon2, lat2):
    """Approximate Euclidean distance in metres."""
    dx = (lon2 - lon1) * 111320 * np.cos(np.radians(lat1))
    dy = (lat2 - lat1) * 111320
    return np.sqrt(dx ** 2 + dy ** 2)


def compute_nearest_distances(buildings, amenities):
    """For each building, compute distance to nearest amenity of each type."""
    results = []

    # Pre-compute amenity centroids
    amenity_points = {}
    for cat, gdf in amenities.items():
        if len(gdf) == 0:
            amenity_points[cat] = np.array([]).reshape(0, 2)
            continue
        centroids = gdf.geometry.to_crs(epsg=32617).centroid.to_crs(epsg=4326)
        amenity_points[cat] = np.column_stack([centroids.x.values, centroids.y.values])

    for b in buildings:
        blon, blat = b["lon"], b["lat"]
        distances = {}

        for cat, pts in amenity_points.items():
            if len(pts) == 0:
                distances[f"dist_{cat}_m"] = None
                distances[f"count_{cat}_400m"] = 0
                continue

            dists = euclidean_distance_m(blon, blat, pts[:, 0], pts[:, 1])
            distances[f"dist_{cat}_m"] = round(float(np.min(dists)), 1)
            distances[f"count_{cat}_400m"] = int(np.sum(dists <= 400))

        # Walkability score (0-100): composite of distance to amenities
        # Lower distances = higher score
        scores = []
        for cat in ["transit", "food", "restaurant", "park"]:
            d = distances.get(f"dist_{cat}_m")
            if d is not None:
                # 0m -> 100, 400m -> 50, 800m -> 0
                scores.append(max(0, min(100, 100 - d * 100 / 800)))
        walkability = round(float(np.mean(scores)), 1) if scores else 0

        results.append({
            "address": b["address"],
            "lon": blon,
            "lat": blat,
            "street": b.get("street", ""),
            **distances,
            "walkability_score": walkability,
        })

    return results


def main():
    parser = argparse.ArgumentParser(description="Walkability and accessibility analysis.")
    parser.add_argument("--output", type=Path, default=OUTPUT_DIR / "accessibility_metrics.json")
    args = parser.parse_args()

    print("Accessibility analysis: Kensington Market")
    buildings = load_buildings()
    print(f"  {len(buildings)} buildings loaded")

    amenities = fetch_amenities()

    print("  Computing distances...")
    building_metrics = compute_nearest_distances(buildings, amenities)

    # Per-street aggregation
    by_street = defaultdict(list)
    for m in building_metrics:
        by_street[m["street"]].append(m)

    street_summary = {}
    for street, bldgs in sorted(by_street.items()):
        if not street:
            continue
        walk_scores = [b["walkability_score"] for b in bldgs]
        street_summary[street] = {
            "count": len(bldgs),
            "avg_walkability": round(float(np.mean(walk_scores)), 1),
            "min_walkability": round(float(np.min(walk_scores)), 1),
            "max_walkability": round(float(np.max(walk_scores)), 1),
        }

    # Overall
    all_scores = [b["walkability_score"] for b in building_metrics]
    overall = {
        "building_count": len(building_metrics),
        "avg_walkability": round(float(np.mean(all_scores)), 1),
        "amenity_counts": {cat: len(gdf) for cat, gdf in amenities.items()},
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

    print(f"\nOverall walkability: {overall['avg_walkability']}/100")
    print(f"Top 5 streets by walkability:")
    for s, v in sorted(street_summary.items(), key=lambda x: -x[1]["avg_walkability"])[:5]:
        print(f"  {s}: {v['avg_walkability']}")
    print(f"\nOutput: {args.output}")


if __name__ == "__main__":
    main()
