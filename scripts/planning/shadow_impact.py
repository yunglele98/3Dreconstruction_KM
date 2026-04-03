#!/usr/bin/env python3
"""Shadow impact analysis for scenario comparison.

Computes shadow length changes when buildings change height.

Usage:
    python scripts/planning/shadow_impact.py --baseline params/ --scenario outputs/scenarios/gentle_density/
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# Sun elevation angles by season for Toronto (43.65N latitude)
# Approximate solar noon elevations
SUN_ELEVATIONS = {
    "summer": {"min": 25.0, "noon": 69.9, "avg": 45.0},
    "winter": {"min": 5.0, "noon": 23.0, "avg": 12.0},
    "spring": {"min": 15.0, "noon": 46.5, "avg": 30.0},
    "fall": {"min": 15.0, "noon": 46.5, "avg": 30.0},
}


def shadow_length(height_m: float, sun_elevation_deg: float) -> float:
    """Compute shadow length for a given building height and sun angle.

    Args:
        height_m: Building height in metres.
        sun_elevation_deg: Sun elevation angle in degrees (0 = horizon, 90 = zenith).

    Returns:
        Shadow length in metres. Returns inf if sun is at horizon.
    """
    if sun_elevation_deg <= 0:
        return float("inf")
    return height_m / math.tan(math.radians(sun_elevation_deg))


def analyze_shadow_impact(
    baseline_dir: Path,
    scenario_dir: Path,
    season: str = "winter",
) -> dict:
    """Compare shadow impacts between baseline and scenario.

    Args:
        baseline_dir: Directory with baseline param files.
        scenario_dir: Directory with scenario param files.
        season: Season for sun angle lookup.

    Returns:
        Impact report dict.
    """
    sun_angles = SUN_ELEVATIONS.get(season, SUN_ELEVATIONS["winter"])

    # Load baseline heights
    baseline_heights: dict[str, float] = {}
    for f in sorted(baseline_dir.glob("*.json")):
        if f.name.startswith("_"):
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if data.get("skipped"):
            continue
        addr = data.get("_meta", {}).get("address") or data.get("building_name", f.stem)
        baseline_heights[f.stem] = data.get("total_height_m", 0)

    # Compare with scenario
    changes = []
    for f in sorted(scenario_dir.glob("*.json")):
        if f.name.startswith("_"):
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if data.get("skipped"):
            continue

        addr = data.get("_meta", {}).get("address") or data.get("building_name", f.stem)
        new_height = data.get("total_height_m", 0)
        old_height = baseline_heights.get(f.stem, 0)

        if abs(new_height - old_height) < 0.01:
            continue

        delta = new_height - old_height
        old_shadow = shadow_length(old_height, sun_angles["min"]) if old_height > 0 else 0
        new_shadow = shadow_length(new_height, sun_angles["min"]) if new_height > 0 else 0
        shadow_increase = new_shadow - old_shadow if old_shadow != float("inf") and new_shadow != float("inf") else float("inf")

        changes.append({
            "address": addr,
            "old_height_m": old_height,
            "new_height_m": new_height,
            "height_delta_m": delta,
            "old_shadow_m": round(old_shadow, 1) if old_shadow != float("inf") else "inf",
            "new_shadow_m": round(new_shadow, 1) if new_shadow != float("inf") else "inf",
            "max_shadow_increase_m": round(shadow_increase, 1) if shadow_increase != float("inf") else "inf",
            "season": season,
        })

    return {
        "season": season,
        "sun_angles": sun_angles,
        "buildings_with_height_change": len(changes),
        "changes": changes,
    }


def main():
    parser = argparse.ArgumentParser(description="Shadow impact analysis")
    parser.add_argument("--baseline", type=Path, default=REPO_ROOT / "params")
    parser.add_argument("--scenario", type=Path, required=True)
    parser.add_argument("--season", default="winter", choices=["summer", "winter", "spring", "fall"])
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    result = analyze_shadow_impact(args.baseline, args.scenario, args.season)
    print(f"Shadow impact ({args.season}): {result['buildings_with_height_change']} buildings affected")
    for c in result["changes"][:10]:
        print(f"  {c['address']}: height {c['height_delta_m']:+.1f}m, "
              f"shadow increase {c['max_shadow_increase_m']}m")

    if args.output:
        args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
