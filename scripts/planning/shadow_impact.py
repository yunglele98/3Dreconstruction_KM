#!/usr/bin/env python3
"""Estimate shadow impact for a scenario vs baseline.

Computes simple shadow length projections based on building height and
sun angle for different times of day/seasons. Identifies buildings where
height changes affect shadow casting on neighbours.

Usage:
    python scripts/planning/shadow_impact.py --baseline params/ --scenario scenarios/10yr_gentle_density/params/
    python scripts/planning/shadow_impact.py --scenario scenarios/10yr_gentle_density/params/ --season winter
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PARAMS_DIR = REPO_ROOT / "params"

# Toronto sun elevation angles (approximate, degrees above horizon)
# At winter solstice noon: ~24 deg, summer solstice noon: ~70 deg
SUN_ANGLES = {
    "winter_9am": 12,
    "winter_noon": 24,
    "winter_3pm": 15,
    "spring_9am": 28,
    "spring_noon": 48,
    "spring_3pm": 32,
    "summer_9am": 40,
    "summer_noon": 70,
    "summer_3pm": 45,
    "fall_9am": 25,
    "fall_noon": 42,
    "fall_3pm": 28,
}


def shadow_length(height_m: float, sun_elevation_deg: float) -> float:
    """Compute horizontal shadow length from a vertical surface."""
    if sun_elevation_deg <= 0:
        return float("inf")
    return height_m / math.tan(math.radians(sun_elevation_deg))


def load_heights(params_dir: Path) -> dict:
    """Load building heights keyed by address."""
    heights = {}
    for f in sorted(params_dir.glob("*.json")):
        if f.name.startswith("_"):
            continue
        try:
            params = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if params.get("skipped"):
            continue

        address = params.get("_meta", {}).get("address", f.stem.replace("_", " "))
        h = params.get("total_height_m", 0) or 0
        heights[address] = {
            "height_m": h,
            "floors": params.get("floors", 0) or 0,
            "street": params.get("site", {}).get("street", ""),
        }
    return heights


def analyze_shadow_impact(
    baseline_dir: Path,
    scenario_dir: Path,
    season: str = "winter",
) -> dict:
    """Compare shadow impacts between baseline and scenario."""
    baseline = load_heights(baseline_dir)
    scenario = load_heights(scenario_dir)

    # Filter to season-relevant sun angles
    angles = {k: v for k, v in SUN_ANGLES.items() if k.startswith(season)}
    if not angles:
        angles = {k: v for k, v in SUN_ANGLES.items() if k.startswith("winter")}

    changes = []
    for address in set(baseline.keys()) | set(scenario.keys()):
        base_h = baseline.get(address, {}).get("height_m", 0)
        scen_h = scenario.get(address, {}).get("height_m", 0)
        delta = scen_h - base_h

        if abs(delta) < 0.5:
            continue

        base_shadows = {k: round(shadow_length(base_h, v), 1) for k, v in angles.items()}
        scen_shadows = {k: round(shadow_length(scen_h, v), 1) for k, v in angles.items()}
        shadow_deltas = {k: round(scen_shadows[k] - base_shadows[k], 1) for k in angles}

        worst_time = max(shadow_deltas, key=lambda k: shadow_deltas[k])

        changes.append({
            "address": address,
            "street": scenario.get(address, baseline.get(address, {})).get("street", ""),
            "height_baseline_m": base_h,
            "height_scenario_m": scen_h,
            "height_delta_m": round(delta, 1),
            "shadow_lengths_baseline": base_shadows,
            "shadow_lengths_scenario": scen_shadows,
            "shadow_deltas": shadow_deltas,
            "worst_time": worst_time,
            "max_shadow_increase_m": shadow_deltas[worst_time],
        })

    changes.sort(key=lambda c: c["max_shadow_increase_m"], reverse=True)

    return {
        "season": season,
        "sun_angles_used": angles,
        "buildings_with_height_change": len(changes),
        "max_shadow_increase_m": changes[0]["max_shadow_increase_m"] if changes else 0,
        "changes": changes,
    }


def main():
    parser = argparse.ArgumentParser(description="Estimate shadow impact for scenario.")
    parser.add_argument("--baseline", type=Path, default=PARAMS_DIR)
    parser.add_argument("--scenario", type=Path, required=True)
    parser.add_argument("--season", default="winter", choices=["winter", "spring", "summer", "fall"])
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    result = analyze_shadow_impact(args.baseline, args.scenario, args.season)

    output = args.output or (args.scenario.parent / "shadow_analysis.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    print(f"Shadow impact analysis ({args.season})")
    print(f"Buildings with height change: {result['buildings_with_height_change']}")
    if result["changes"]:
        print(f"Max shadow increase: {result['max_shadow_increase_m']}m")
        print(f"\nTop changes:")
        for c in result["changes"][:10]:
            print(f"  {c['address']}: +{c['height_delta_m']}m height -> "
                  f"+{c['max_shadow_increase_m']}m shadow at {c['worst_time']}")

    print(f"\nOutput: {output}")


if __name__ == "__main__":
    main()
