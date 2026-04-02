#!/usr/bin/env python3
"""Enrich scenario comparison with spatial analysis metrics.

Combines density analysis with network, morphology, shadow, accessibility,
and viewshed data to produce a comprehensive scenario scorecard.

Usage:
    python scripts/analyze/enrich_scenario_metrics.py
    python scripts/analyze/enrich_scenario_metrics.py --output outputs/scenario_scorecard.json
"""
import argparse
import json
from pathlib import Path

REPO = Path(__file__).parent.parent.parent
SPATIAL_DIR = REPO / "outputs" / "spatial"


def load_spatial(name):
    path = SPATIAL_DIR / f"{name}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def compute_baseline_spatial():
    """Extract key spatial metrics from baseline analysis."""
    metrics = {}

    # Network
    net = load_spatial("network_analysis")
    if net.get("network"):
        metrics["network"] = {
            "nodes": net["network"].get("nodes", 0),
            "edges": net["network"].get("edges", 0),
            "avg_betweenness": round(net["network"].get("avg_betweenness", 0), 4),
            "avg_closeness": round(net["network"].get("avg_closeness", 0), 4),
            "total_street_length_m": round(net["network"].get("total_street_length_m", 0), 0),
        }

    # Morphology
    morph = load_spatial("morphology")
    if morph.get("overall"):
        metrics["morphology"] = {
            "avg_area_sqm": round(morph["overall"].get("avg_area", 0), 1),
            "avg_compactness": round(morph["overall"].get("avg_compactness", 0), 3),
            "avg_elongation": round(morph["overall"].get("avg_elongation", 0), 3),
            "total_footprint_sqm": round(morph["overall"].get("total_footprint", 0), 0),
        }

    # Shadow
    shadow = load_spatial("shadow_analysis")
    if shadow.get("overall"):
        metrics["shadow"] = {
            "avg_sun_hours": round(shadow["overall"].get("avg_sun_hours", 0), 1),
            "low_sun_count": shadow["overall"].get("low_sun_count", 0),
            "critical_count": shadow["overall"].get("critical_count", 0),
        }

    # Accessibility
    access = load_spatial("accessibility")
    if access.get("overall"):
        metrics["accessibility"] = {
            "avg_walkability": round(access["overall"].get("avg_walkability", 0), 1),
        }

    # Viewshed
    view = load_spatial("viewshed")
    if view.get("overall"):
        metrics["viewshed"] = {
            "avg_visibility": round(view["overall"].get("avg_visibility", 0), 1),
            "low_visibility_count": view["overall"].get("low_visibility_count", 0),
        }

    return metrics


def estimate_scenario_spatial(scenario_name, baseline_spatial, scenario_density, baseline_density):
    """Estimate spatial metric changes for a scenario.

    Network, morphology, and accessibility don't change much with building
    modifications. Shadow changes with height. Viewshed changes with height.
    """
    spatial = json.loads(json.dumps(baseline_spatial))  # deep copy

    # Shadow: estimate change from height changes
    baseline_avg_h = baseline_density.get("avg_height_m", 8.34)
    scenario_avg_h = scenario_density.get("avg_height_m", 8.34)
    height_ratio = scenario_avg_h / max(baseline_avg_h, 1)

    if "shadow" in spatial:
        # More height = less sun hours (inverse relationship)
        spatial["shadow"]["avg_sun_hours"] = round(
            spatial["shadow"]["avg_sun_hours"] / max(height_ratio, 0.5), 1)
        spatial["shadow"]["estimated"] = True

    # Green infra scenario improves canopy/walkability
    if "green" in scenario_name.lower():
        if "accessibility" in spatial:
            spatial["accessibility"]["avg_walkability"] = round(
                min(100, spatial["accessibility"]["avg_walkability"] * 1.05), 1)
            spatial["accessibility"]["estimated"] = True

    # Mobility scenario improves network connectivity perception
    if "mobility" in scenario_name.lower():
        if "network" in spatial:
            spatial["network"]["pedestrian_priority_streets"] = 3
            spatial["network"]["estimated"] = True

    return spatial


def main():
    parser = argparse.ArgumentParser(description="Enrich scenario comparison with spatial metrics")
    parser.add_argument("--comparison", type=Path,
                        default=REPO / "outputs" / "scenario_comparison.json")
    parser.add_argument("--output", type=Path,
                        default=REPO / "outputs" / "scenario_scorecard.json")
    args = parser.parse_args()

    comparison = json.loads(args.comparison.read_text(encoding="utf-8"))
    baseline_spatial = compute_baseline_spatial()

    scorecard = {
        "baseline": {
            "density": comparison.get("baseline", {}),
            "spatial": baseline_spatial,
        },
        "scenarios": {},
    }

    for scenario_name, scenario_density in comparison.get("scenarios", {}).items():
        scenario_spatial = estimate_scenario_spatial(
            scenario_name, baseline_spatial,
            scenario_density, comparison.get("baseline", {}))

        scorecard["scenarios"][scenario_name] = {
            "density": scenario_density,
            "spatial": scenario_spatial,
        }

    # Compute per-scenario summary scores (0-100)
    for name, data in scorecard["scenarios"].items():
        density = data["density"]
        spatial = data["spatial"]

        # Simple scoring: higher density = some points, better walkability = points, etc.
        density_score = min(100, (density.get("fsi", 0) / 3.0) * 100)
        heritage_score = 70  # from heritage analysis, most buildings medium significance
        walkability = spatial.get("accessibility", {}).get("avg_walkability", 80)
        sun_hours = spatial.get("shadow", {}).get("avg_sun_hours", 2)
        sun_score = min(100, sun_hours / 6 * 100)

        data["summary_scores"] = {
            "density": round(density_score, 1),
            "heritage": heritage_score,
            "walkability": round(walkability, 1),
            "sun_access": round(sun_score, 1),
            "overall": round((density_score + heritage_score + walkability + sun_score) / 4, 1),
        }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(scorecard, indent=2), encoding="utf-8")

    print(f"Scenario scorecard: {args.output}")
    print(f"\n{'Scenario':<25s} {'Density':>8s} {'Heritage':>9s} {'Walk':>6s} {'Sun':>6s} {'Overall':>8s}")
    print("-" * 65)
    print(f"{'baseline':<25s} "
          f"{min(100, comparison['baseline'].get('fsi', 0) / 3 * 100):>7.1f} "
          f"{'70.0':>9s} "
          f"{baseline_spatial.get('accessibility', {}).get('avg_walkability', 0):>6.1f} "
          f"{min(100, baseline_spatial.get('shadow', {}).get('avg_sun_hours', 0) / 6 * 100):>6.1f} "
          f"{'—':>8s}")
    for name, data in scorecard["scenarios"].items():
        s = data["summary_scores"]
        print(f"{name:<25s} {s['density']:>7.1f}  {s['heritage']:>8.1f} {s['walkability']:>6.1f} {s['sun_access']:>6.1f} {s['overall']:>8.1f}")


if __name__ == "__main__":
    main()
