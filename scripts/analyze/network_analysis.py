#!/usr/bin/env python3
"""Street network analysis for Kensington Market via OSMnx.

Computes betweenness centrality, closeness centrality, connectivity,
and intersection density for the study area street network. Results
are joined to buildings by nearest edge.

Usage:
    python scripts/analyze/network_analysis.py
    python scripts/analyze/network_analysis.py --output outputs/spatial/network_metrics.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import geopandas as gpd
import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SLIM_PATH = REPO_ROOT / "web" / "public" / "data" / "params-slim.json"
OUTPUT_DIR = REPO_ROOT / "outputs" / "spatial"

# Kensington Market bounding box (N, S, E, W)
BBOX_NORTH = 43.658
BBOX_SOUTH = 43.651
BBOX_EAST = -79.397
BBOX_WEST = -79.408


def load_buildings():
    data = json.loads(SLIM_PATH.read_text(encoding="utf-8"))
    return [b for b in data if b.get("lon") and b.get("lat")]


def fetch_network():
    """Download street network from OSM via OSMnx."""
    import osmnx as ox

    G = ox.graph_from_bbox(
        bbox=(BBOX_WEST, BBOX_SOUTH, BBOX_EAST, BBOX_NORTH),
        network_type="walk",
    )
    print(f"  Network: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges")
    return G


def compute_centrality(G):
    """Compute node-level centrality metrics."""
    import networkx as nx

    print("  Computing betweenness centrality...")
    betweenness = nx.betweenness_centrality(G, weight="length")

    print("  Computing closeness centrality...")
    closeness = nx.closeness_centrality(G, distance="length")

    print("  Computing degree...")
    degree = dict(G.degree())

    return betweenness, closeness, degree


def nearest_node_metrics(buildings, G, betweenness, closeness, degree):
    """Assign network metrics to each building by nearest node."""
    import osmnx as ox

    lats = [b["lat"] for b in buildings]
    lons = [b["lon"] for b in buildings]
    nearest_nodes = ox.distance.nearest_nodes(G, lons, lats)

    results = []
    for b, node in zip(buildings, nearest_nodes):
        results.append({
            "address": b["address"],
            "lon": b["lon"],
            "lat": b["lat"],
            "street": b.get("street", ""),
            "nearest_node": int(node),
            "betweenness": round(betweenness.get(node, 0), 6),
            "closeness": round(closeness.get(node, 0), 6),
            "degree": degree.get(node, 0),
        })

    return results


def compute_network_stats(G, betweenness, closeness, degree):
    """Aggregate network-level statistics."""
    import osmnx as ox

    stats = ox.stats.basic_stats(G)

    return {
        "node_count": G.number_of_nodes(),
        "edge_count": G.number_of_edges(),
        "avg_degree": round(np.mean(list(degree.values())), 2),
        "avg_betweenness": round(np.mean(list(betweenness.values())), 6),
        "avg_closeness": round(np.mean(list(closeness.values())), 6),
        "max_betweenness_node": int(max(betweenness, key=betweenness.get)),
        "intersection_count": stats.get("intersection_count", 0),
        "street_length_total_m": round(stats.get("street_length_total", 0), 1),
        "street_length_avg_m": round(stats.get("street_length_avg", 0), 1),
    }


def main():
    parser = argparse.ArgumentParser(description="Street network analysis via OSMnx.")
    parser.add_argument("--output", type=Path, default=OUTPUT_DIR / "network_metrics.json")
    args = parser.parse_args()

    print("Network analysis: Kensington Market")
    buildings = load_buildings()
    print(f"  {len(buildings)} buildings loaded")

    G = fetch_network()
    betweenness, closeness, degree = compute_centrality(G)

    building_metrics = nearest_node_metrics(buildings, G, betweenness, closeness, degree)
    network_stats = compute_network_stats(G, betweenness, closeness, degree)

    # Per-street aggregation
    from collections import defaultdict
    by_street = defaultdict(list)
    for m in building_metrics:
        by_street[m["street"]].append(m)

    street_summary = {}
    for street, bldgs in sorted(by_street.items()):
        if not street:
            continue
        street_summary[street] = {
            "count": len(bldgs),
            "avg_betweenness": round(np.mean([b["betweenness"] for b in bldgs]), 6),
            "avg_closeness": round(np.mean([b["closeness"] for b in bldgs]), 6),
            "avg_degree": round(np.mean([b["degree"] for b in bldgs]), 2),
        }

    result = {
        "network": network_stats,
        "streets": street_summary,
        "buildings": building_metrics,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    print(f"\nNetwork stats:")
    print(f"  Nodes: {network_stats['node_count']}, Edges: {network_stats['edge_count']}")
    print(f"  Avg betweenness: {network_stats['avg_betweenness']}")
    print(f"  Avg closeness: {network_stats['avg_closeness']}")
    print(f"  Total street length: {network_stats['street_length_total_m']:.0f}m")
    print(f"\nTop 5 streets by centrality:")
    for s, v in sorted(street_summary.items(), key=lambda x: -x[1]["avg_betweenness"])[:5]:
        print(f"  {s}: betw={v['avg_betweenness']:.4f}, close={v['avg_closeness']:.4f}")
    print(f"\nOutput: {args.output}")


if __name__ == "__main__":
    main()
