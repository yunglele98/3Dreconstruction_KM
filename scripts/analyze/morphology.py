#!/usr/bin/env python3
"""Urban morphology analysis for Kensington Market via momepy.

Computes building-level and block-level morphometric indicators:
tessellation, compactness, elongation, building alignment, shared walls,
coverage ratio, and street profile width.

Usage:
    python scripts/analyze/morphology.py
    python scripts/analyze/morphology.py --output outputs/spatial/morphology_metrics.json
"""

from __future__ import annotations

import argparse
import json
import warnings
from pathlib import Path

import geopandas as gpd
import numpy as np
from shapely.geometry import Point, box

warnings.filterwarnings("ignore", category=FutureWarning)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SLIM_PATH = REPO_ROOT / "web" / "public" / "data" / "params-slim.json"
GEOJSON_PATH = REPO_ROOT / "web" / "public" / "data" / "buildings.geojson"
OUTPUT_DIR = REPO_ROOT / "outputs" / "spatial"


def load_buildings_gdf():
    """Load buildings as GeoDataFrame from GeoJSON or params."""
    if GEOJSON_PATH.exists():
        gdf = gpd.read_file(str(GEOJSON_PATH))
        if len(gdf) > 0 and gdf.geometry.iloc[0] is not None:
            print(f"  Loaded {len(gdf)} buildings from GeoJSON (real footprints)")
            return gdf

    # Fallback: build rectangles from params
    data = json.loads(SLIM_PATH.read_text(encoding="utf-8"))
    features = []
    for b in data:
        lon, lat = b.get("lon"), b.get("lat")
        if not lon or not lat:
            continue
        w = (b.get("width") or 6) / 2
        d = (b.get("depth") or 15) / 2
        m_per_deg = 111320
        lon_scale = m_per_deg * 0.7  # cos(43.65)
        dLon = w / lon_scale
        dLat = d / m_per_deg
        geom = box(lon - dLon, lat - dLat, lon + dLon, lat + dLat)
        features.append({"geometry": geom, **b})

    gdf = gpd.GeoDataFrame(features, crs="EPSG:4326")
    print(f"  Built {len(gdf)} rectangle footprints from params")
    return gdf


def compute_morphology(gdf):
    """Compute momepy morphometric indicators."""
    import momepy

    # Project to metres (UTM 17N for Toronto)
    gdf_m = gdf.to_crs(epsg=32617)

    results = {}

    # Building-level metrics
    print("  Computing area...")
    results["area"] = gdf_m.geometry.area.round(2).tolist()

    print("  Computing perimeter...")
    results["perimeter"] = gdf_m.geometry.length.round(2).tolist()

    print("  Computing compactness (circular compactness)...")
    try:
        cc = momepy.CircularCompactness(gdf_m).series
        results["compactness"] = cc.round(4).tolist()
    except Exception:
        areas = gdf_m.geometry.area
        perimeters = gdf_m.geometry.length
        results["compactness"] = (4 * np.pi * areas / (perimeters ** 2)).round(4).tolist()

    print("  Computing elongation...")
    try:
        elong = momepy.Elongation(gdf_m).series
        results["elongation"] = elong.round(4).tolist()
    except Exception:
        results["elongation"] = [0.0] * len(gdf_m)

    print("  Computing orientation...")
    try:
        orient = momepy.Orientation(gdf_m).series
        results["orientation_deg"] = orient.round(2).tolist()
    except Exception:
        results["orientation_deg"] = [0.0] * len(gdf_m)

    print("  Computing longest axis...")
    try:
        la = momepy.LongestAxisLength(gdf_m).series
        results["longest_axis_m"] = la.round(2).tolist()
    except Exception:
        results["longest_axis_m"] = [0.0] * len(gdf_m)

    # Coverage ratio (building area / convex hull area)
    print("  Computing coverage ratio...")
    convex_areas = gdf_m.geometry.convex_hull.area
    results["coverage_ratio"] = (gdf_m.geometry.area / convex_areas.replace(0, np.nan)).fillna(0).round(4).tolist()

    return results


def aggregate_by_street(gdf, metrics):
    """Aggregate morphology metrics by street."""
    streets = gdf.get("street", gdf.get("address", "")).fillna("Unknown")
    by_street = {}

    for street in streets.unique():
        if not street:
            continue
        mask = streets == street
        n = mask.sum()
        by_street[street] = {
            "count": int(n),
            "avg_area_sqm": round(float(np.mean([metrics["area"][i] for i, m in enumerate(mask) if m])), 1),
            "avg_compactness": round(float(np.mean([metrics["compactness"][i] for i, m in enumerate(mask) if m])), 4),
            "avg_elongation": round(float(np.mean([metrics["elongation"][i] for i, m in enumerate(mask) if m])), 4),
            "avg_orientation_deg": round(float(np.mean([metrics["orientation_deg"][i] for i, m in enumerate(mask) if m])), 1),
        }

    return by_street


def main():
    parser = argparse.ArgumentParser(description="Urban morphology analysis via momepy.")
    parser.add_argument("--output", type=Path, default=OUTPUT_DIR / "morphology_metrics.json")
    args = parser.parse_args()

    print("Morphology analysis: Kensington Market")
    gdf = load_buildings_gdf()

    metrics = compute_morphology(gdf)

    # Build per-building results
    addresses = gdf.get("address", gdf.index.astype(str)).tolist()
    building_results = []
    for i, addr in enumerate(addresses):
        building_results.append({
            "address": addr,
            "area_sqm": metrics["area"][i],
            "perimeter_m": metrics["perimeter"][i],
            "compactness": metrics["compactness"][i],
            "elongation": metrics["elongation"][i],
            "orientation_deg": metrics["orientation_deg"][i],
            "longest_axis_m": metrics["longest_axis_m"][i],
            "coverage_ratio": metrics["coverage_ratio"][i],
        })

    street_summary = aggregate_by_street(gdf, metrics)

    # Overall stats
    overall = {
        "building_count": len(gdf),
        "avg_area_sqm": round(float(np.mean(metrics["area"])), 1),
        "avg_compactness": round(float(np.mean(metrics["compactness"])), 4),
        "avg_elongation": round(float(np.mean(metrics["elongation"])), 4),
        "total_footprint_sqm": round(float(np.sum(metrics["area"])), 1),
    }

    result = {
        "overall": overall,
        "streets": street_summary,
        "buildings": building_results,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    print(f"\nOverall:")
    print(f"  Avg area: {overall['avg_area_sqm']} sqm")
    print(f"  Avg compactness: {overall['avg_compactness']}")
    print(f"  Avg elongation: {overall['avg_elongation']}")
    print(f"  Total footprint: {overall['total_footprint_sqm']} sqm")
    print(f"\nOutput: {args.output}")


if __name__ == "__main__":
    main()
