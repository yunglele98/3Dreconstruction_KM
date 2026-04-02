#!/usr/bin/env python3
"""Estimate annual sun hours per building from heights and positions.

Uses simplified solar geometry for Toronto (43.65N) to compute shadow
casting between neighbouring buildings across seasons. Identifies
buildings that receive less than threshold sun hours.

Usage:
    python scripts/analyze/shadow_analysis.py
    python scripts/analyze/shadow_analysis.py --output outputs/spatial/shadow_metrics.json
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

# Toronto latitude
LATITUDE = 43.65

# Solar angles by season and hour (elevation degrees above horizon)
# Computed for Toronto latitude
SOLAR_SCHEDULE = {
    "winter": {  # Dec 21
        8: 5, 9: 12, 10: 18, 11: 22, 12: 24, 13: 22, 14: 18, 15: 12, 16: 5,
    },
    "spring": {  # Mar 21
        7: 5, 8: 15, 9: 28, 10: 38, 11: 45, 12: 48, 13: 45, 14: 38, 15: 28, 16: 15, 17: 5,
    },
    "summer": {  # Jun 21
        6: 5, 7: 15, 8: 28, 9: 40, 10: 52, 11: 62, 12: 70, 13: 62, 14: 52, 15: 40, 16: 28, 17: 15, 18: 5,
    },
    "fall": {  # Sep 21
        7: 5, 8: 15, 9: 25, 10: 35, 11: 42, 12: 45, 13: 42, 14: 35, 15: 25, 16: 15, 17: 5,
    },
}


def load_buildings():
    data = json.loads(SLIM_PATH.read_text(encoding="utf-8"))
    return [b for b in data if b.get("lon") and b.get("lat") and b.get("height")]


def shadow_length_m(height_m, sun_elevation_deg):
    """Horizontal shadow length from a building of given height."""
    if sun_elevation_deg <= 0:
        return 999
    return height_m / math.tan(math.radians(sun_elevation_deg))


def distance_m(b1, b2):
    """Approximate distance in metres between two buildings."""
    dx = (b2["lon"] - b1["lon"]) * 111320 * math.cos(math.radians(LATITUDE))
    dy = (b2["lat"] - b1["lat"]) * 111320
    return math.sqrt(dx * dx + dy * dy)


def compute_sun_hours(buildings):
    """Estimate sun hours per building considering neighbour shadows."""
    n = len(buildings)

    # Build spatial index: for each building, find neighbours within 50m
    neighbours = defaultdict(list)
    for i in range(n):
        for j in range(i + 1, n):
            d = distance_m(buildings[i], buildings[j])
            if d < 50:
                neighbours[i].append((j, d))
                neighbours[j].append((i, d))

    results = []
    season_weights = {"winter": 90, "spring": 92, "summer": 92, "fall": 91}  # days per season

    for i, b in enumerate(buildings):
        h = b.get("height") or 7
        season_hours = {}
        total_sun_hours = 0

        for season, schedule in SOLAR_SCHEDULE.items():
            sun_count = 0
            total_slots = len(schedule)

            for hour, elev in schedule.items():
                # Check if any neighbour's shadow reaches this building
                shadowed = False
                for j, dist in neighbours[i]:
                    nb_h = buildings[j].get("height") or 7
                    shadow_len = shadow_length_m(nb_h, elev)

                    # Shadow reaches if shadow length > distance AND neighbour is
                    # roughly south (in northern hemisphere, shadows go north)
                    if shadow_len > dist:
                        # Check if neighbour is roughly south
                        dy = (b["lat"] - buildings[j]["lat"]) * 111320
                        if dy > 0:  # neighbour is south of us
                            shadowed = True
                            break

                if not shadowed:
                    sun_count += 1

            hours_per_day = sun_count  # each slot = ~1 hour
            season_hours[season] = hours_per_day
            total_sun_hours += hours_per_day * season_weights[season]

        results.append({
            "address": b["address"],
            "lon": b["lon"],
            "lat": b["lat"],
            "street": b.get("street", ""),
            "height_m": h,
            "sun_hours_winter": season_hours.get("winter", 0),
            "sun_hours_spring": season_hours.get("spring", 0),
            "sun_hours_summer": season_hours.get("summer", 0),
            "sun_hours_fall": season_hours.get("fall", 0),
            "annual_sun_hours": total_sun_hours,
            "avg_daily_sun_hours": round(total_sun_hours / 365, 1),
        })

    return results


def main():
    parser = argparse.ArgumentParser(description="Estimate annual sun hours per building.")
    parser.add_argument("--output", type=Path, default=OUTPUT_DIR / "shadow_metrics.json")
    args = parser.parse_args()

    print("Shadow analysis: Kensington Market")
    buildings = load_buildings()
    print(f"  {len(buildings)} buildings with height data")

    print("  Computing sun hours (neighbour shadowing)...")
    building_metrics = compute_sun_hours(buildings)

    # Per-street aggregation
    by_street = defaultdict(list)
    for m in building_metrics:
        by_street[m["street"]].append(m)

    street_summary = {}
    for street, bldgs in sorted(by_street.items()):
        if not street:
            continue
        sun = [b["avg_daily_sun_hours"] for b in bldgs]
        street_summary[street] = {
            "count": len(bldgs),
            "avg_daily_sun_hours": round(float(np.mean(sun)), 1),
            "min_daily_sun_hours": round(float(np.min(sun)), 1),
            "low_sun_count": sum(1 for s in sun if s < 4),
        }

    all_sun = [b["avg_daily_sun_hours"] for b in building_metrics]
    overall = {
        "building_count": len(building_metrics),
        "avg_daily_sun_hours": round(float(np.mean(all_sun)), 1),
        "low_sun_buildings": sum(1 for s in all_sun if s < 4),
        "critical_sun_buildings": sum(1 for s in all_sun if s < 2),
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

    print(f"\nOverall: avg {overall['avg_daily_sun_hours']} hrs/day")
    print(f"  Low sun (<4 hrs): {overall['low_sun_buildings']} buildings")
    print(f"  Critical (<2 hrs): {overall['critical_sun_buildings']} buildings")
    print(f"\nOutput: {args.output}")


if __name__ == "__main__":
    main()
