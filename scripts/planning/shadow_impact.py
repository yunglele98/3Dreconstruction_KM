#!/usr/bin/env python3
"""Estimate shadow impact of height-change interventions.

For each intervention that changes building height, estimates shadow length
at three winter sun angles (9am, noon, 3pm). Writes shadow_analysis.json
to the scenario directory.

Usage:
    python scripts/planning/shadow_impact.py --baseline params/ --scenario scenarios/10yr_gentle_density/
"""

import argparse
import json
import math
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
PARAMS = REPO / "params"

# Toronto winter sun elevation angles (degrees above horizon)
# These are approximate for latitude 43.65 N in December
SUN_ANGLES = {
    "winter_9am": 12,
    "winter_noon": 24,
    "winter_3pm": 15,
}

DEFAULT_FLOOR_HEIGHT_M = 3.0


def load_params(params_dir: Path) -> dict:
    """Load all param files keyed by building_name."""
    buildings = {}
    for f in sorted(params_dir.glob("*.json")):
        if f.name.startswith("_"):
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if data.get("skipped"):
            continue
        name = data.get("building_name") or data.get("_meta", {}).get("address", "")
        if name:
            buildings[name] = data
    return buildings


def load_interventions(scenario_dir: Path) -> dict:
    path = scenario_dir / "interventions.json"
    return json.loads(path.read_text(encoding="utf-8"))


def shadow_length(height_m: float, sun_angle_deg: float) -> float:
    """Compute shadow length from building height and sun elevation angle."""
    if sun_angle_deg <= 0 or height_m <= 0:
        return 0.0
    return round(height_m / math.tan(math.radians(sun_angle_deg)), 1)


def get_height(params: dict) -> float:
    """Get building height from params, with fallback."""
    h = params.get("total_height_m")
    if h:
        return float(h)
    h = params.get("city_data", {}).get("height_avg_m")
    if h:
        return float(h)
    floors = params.get("floors") or 0
    return floors * DEFAULT_FLOOR_HEIGHT_M


def main():
    parser = argparse.ArgumentParser(description="Estimate shadow impact of scenario interventions")
    parser.add_argument("--baseline", required=True, help="Path to baseline params directory")
    parser.add_argument("--scenario", required=True, help="Path to scenario directory")
    parser.add_argument("--sun-angle", type=float, default=None,
                        help="Override default sun angle (degrees, used for all times)")
    args = parser.parse_args()

    baseline_dir = Path(args.baseline)
    if not baseline_dir.is_absolute():
        baseline_dir = REPO / baseline_dir
    scenario_dir = Path(args.scenario)
    if not scenario_dir.is_absolute():
        scenario_dir = REPO / scenario_dir

    sun_angles = SUN_ANGLES
    if args.sun_angle:
        sun_angles = {k: args.sun_angle for k in SUN_ANGLES}

    print(f"Loading baseline params from {baseline_dir} ...")
    buildings = load_params(baseline_dir)
    print(f"  {len(buildings)} buildings loaded")

    scenario_data = load_interventions(scenario_dir)
    interventions = scenario_data.get("interventions", [])
    print(f"  {len(interventions)} interventions")

    changes = []
    height_change_types = {"add_floor", "new_build", "demolish"}

    for intervention in interventions:
        address = intervention.get("address", "")
        itype = intervention.get("type", "")
        override = intervention.get("params_override", {})

        # Determine baseline and scenario heights
        if address in buildings:
            baseline_height = get_height(buildings[address])
            street = buildings[address].get("site", {}).get("street", "")
        else:
            baseline_height = 0.0
            street = ""

        # Calculate scenario height
        if itype == "add_floor" and "floors" in override:
            old_floors = buildings.get(address, {}).get("floors") or 0
            new_floors = override["floors"]
            added = max(0, new_floors - old_floors)
            scenario_height = baseline_height + added * DEFAULT_FLOOR_HEIGHT_M
        elif itype == "new_build":
            scenario_height = override.get("floors", 2) * DEFAULT_FLOOR_HEIGHT_M
        elif itype == "demolish":
            scenario_height = 0.0
        else:
            # Non-height-change intervention -- skip
            continue

        height_delta = round(scenario_height - baseline_height, 1)
        if abs(height_delta) < 0.1:
            continue

        shadow_baseline = {}
        shadow_scenario = {}
        shadow_deltas = {}

        for time_key, angle in sun_angles.items():
            sb = shadow_length(baseline_height, angle)
            ss = shadow_length(scenario_height, angle)
            shadow_baseline[time_key] = sb
            shadow_scenario[time_key] = ss
            shadow_deltas[time_key] = round(ss - sb, 1)

        worst_time = max(shadow_deltas, key=lambda k: shadow_deltas[k])
        max_increase = shadow_deltas[worst_time]

        changes.append({
            "address": address,
            "street": street,
            "height_baseline_m": round(baseline_height, 2),
            "height_scenario_m": round(scenario_height, 2),
            "height_delta_m": height_delta,
            "shadow_lengths_baseline": shadow_baseline,
            "shadow_lengths_scenario": shadow_scenario,
            "shadow_deltas": shadow_deltas,
            "worst_time": worst_time,
            "max_shadow_increase_m": max_increase,
        })

    # Sort by worst shadow increase descending
    changes.sort(key=lambda c: c["max_shadow_increase_m"], reverse=True)

    max_overall = max((c["max_shadow_increase_m"] for c in changes), default=0)

    result = {
        "season": "winter",
        "sun_angles_used": dict(sun_angles),
        "buildings_with_height_change": len(changes),
        "max_shadow_increase_m": max_overall,
        "changes": changes,
    }

    out_path = scenario_dir / "shadow_analysis.json"
    out_path.write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"\nShadow analysis written to {out_path}")
    print(f"  {len(changes)} buildings with height changes")
    print(f"  Max shadow increase: {max_overall} m")


if __name__ == "__main__":
    main()
