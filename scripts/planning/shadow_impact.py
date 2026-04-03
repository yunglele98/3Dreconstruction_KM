#!/usr/bin/env python3
"""Stage 11 — SCENARIOS: Analyze shadow impact of height changes.

Computes shadow length changes for buildings whose height changed
between baseline and scenario params.

Usage:
    python scripts/planning/shadow_impact.py --baseline params/ --scenario outputs/scenarios/gentle_density/
"""

import argparse
import json
import math
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# Sun altitude angles by season for Toronto (~43.65 N)
SUN_ALTITUDES = {
    "summer": {"noon": 70.0, "morning": 35.0, "evening": 35.0},
    "winter": {"noon": 23.0, "morning": 10.0, "evening": 10.0},
    "equinox": {"noon": 46.5, "morning": 20.0, "evening": 20.0},
}


def shadow_length(height_m: float, sun_altitude_deg: float) -> float:
    """Compute shadow length given building height and sun altitude.

    Returns float('inf') when sun is at or below horizon.
    """
    if sun_altitude_deg <= 0:
        return float("inf")
    return height_m / math.tan(math.radians(sun_altitude_deg))


def load_buildings(params_dir: Path) -> dict[str, dict]:
    """Load buildings indexed by address."""
    buildings = {}
    for f in sorted(params_dir.glob("*.json")):
        if f.name.startswith("_"):
            continue
        data = json.loads(f.read_text(encoding="utf-8"))
        if data.get("skipped"):
            continue
        addr = data.get("_meta", {}).get("address", f.stem.replace("_", " "))
        buildings[addr] = data
    return buildings


def analyze_shadow_impact(
    baseline_dir: Path,
    scenario_dir: Path,
    *,
    season: str = "equinox",
) -> dict:
    """Compare shadow lengths between baseline and scenario.

    Returns a result dict with per-building changes and summary stats.
    """
    altitudes = SUN_ALTITUDES.get(season, SUN_ALTITUDES["equinox"])
    baseline = load_buildings(baseline_dir)
    scenario = load_buildings(scenario_dir)

    changes = []
    for addr, scen_data in scenario.items():
        base_data = baseline.get(addr)
        if base_data is None:
            continue

        base_h = base_data.get("total_height_m", 0)
        scen_h = scen_data.get("total_height_m", 0)
        delta_h = scen_h - base_h

        if abs(delta_h) < 0.01:
            continue

        # Compute shadow at worst case (lowest sun altitude)
        min_alt = min(altitudes.values())
        base_shadow = shadow_length(base_h, min_alt)
        scen_shadow = shadow_length(scen_h, min_alt)

        if base_shadow == float("inf") or scen_shadow == float("inf"):
            max_shadow_increase = float("inf")
        else:
            max_shadow_increase = scen_shadow - base_shadow

        def _safe_round(v: float) -> float | None:
            return round(v, 2) if v != float("inf") else None

        changes.append({
            "address": addr,
            "baseline_height_m": base_h,
            "scenario_height_m": scen_h,
            "height_delta_m": round(delta_h, 2),
            "baseline_max_shadow_m": _safe_round(base_shadow),
            "scenario_max_shadow_m": _safe_round(scen_shadow),
            "max_shadow_increase_m": _safe_round(max_shadow_increase),
            "season": season,
        })

    return {
        "season": season,
        "sun_altitudes": altitudes,
        "buildings_with_height_change": len(changes),
        "changes": changes,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze shadow impact")
    parser.add_argument("--baseline", type=Path, default=REPO_ROOT / "params")
    parser.add_argument("--scenario", required=True, type=Path)
    parser.add_argument("--season", default="equinox", choices=["summer", "winter", "equinox"])
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    result = analyze_shadow_impact(args.baseline, args.scenario, season=args.season)

    if args.output:
        args.output.write_text(
            json.dumps(result, indent=2), encoding="utf-8"
        )
    print(f"Shadow analysis ({args.season}): {result['buildings_with_height_change']} buildings affected")
    for c in result["changes"][:10]:
        print(f"  {c['address']}: +{c['height_delta_m']}m height → +{c['max_shadow_increase_m']}m shadow")


if __name__ == "__main__":
    main()
