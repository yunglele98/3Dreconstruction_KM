#!/usr/bin/env python3
"""Analyze roofline silhouette for visual interest and realism.

A realistic streetscape needs varied rooflines — monotone heights and
identical roof types look procedurally generated. This script scores
roofline diversity per street block.

Detects:
- Blocks where every building has the same height (flat skyline)
- Blocks with no gable/peak variety (all flat or all gable)
- Missing chimneys on pre-1930 buildings (should be common)
- Missing dormers on 2.5-storey buildings with gable roofs
- Height rhythm irregularities (e.g. tall-short-tall is fine, but
  monotonically increasing looks unnatural for heritage rows)

Usage:
    python scripts/analyze/roofline_silhouette.py
    python scripts/analyze/roofline_silhouette.py --street "Baldwin St"
"""

import argparse
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
PARAMS_DIR = ROOT / "params"


def height_rhythm_score(heights):
    """Score the rhythm/variety of building heights along a street.

    Returns 0-100 where 100 = good variety, 0 = perfectly uniform.
    Real streets have some variation but not wild swings.
    """
    if len(heights) < 3:
        return 50

    # Standard deviation relative to mean
    mean_h = sum(heights) / len(heights)
    if mean_h == 0:
        return 0
    std_h = (sum((h - mean_h) ** 2 for h in heights) / len(heights)) ** 0.5
    cv = std_h / mean_h  # coefficient of variation

    # Too uniform (cv < 0.05) or too chaotic (cv > 0.5) both score poorly
    if cv < 0.03:
        return 20  # nearly identical heights
    elif cv < 0.08:
        return 60  # slight variation
    elif cv < 0.25:
        return 100  # good variety (typical for heritage)
    elif cv < 0.40:
        return 70  # high variation but possible
    else:
        return 40  # suspicious variation


def analyze_street(buildings, street_name):
    """Analyze roofline silhouette for one street."""
    if len(buildings) < 3:
        return None

    heights = []
    roof_types = Counter()
    has_chimney = 0
    pre_1930 = 0
    missing_chimney = []
    missing_dormer = []

    for b in buildings:
        h = b.get("total_height_m", 0)
        if isinstance(h, (int, float)) and h > 0:
            heights.append(h)

        rt = str(b.get("roof_type", "")).lower()
        roof_types[rt] += 1

        hcd = b.get("hcd_data", {})
        era = hcd.get("construction_date", "") if isinstance(hcd, dict) else ""
        if era and ("pre" in era.lower() or any(
            y in era for y in ["1889", "1903", "1904", "1913", "1914", "1930"]
        )):
            pre_1930 += 1
            roof_features = b.get("roof_features", [])
            if isinstance(roof_features, list) and "chimney" in roof_features:
                has_chimney += 1
            else:
                missing_chimney.append(b.get("building_name", "?"))

        # 2.5 storey gable buildings should have dormers
        floors = b.get("floors", 0)
        if isinstance(floors, (int, float)) and floors >= 2:
            dfa = b.get("deep_facade_analysis", {})
            has_half = False
            if isinstance(dfa, dict):
                has_half = dfa.get("has_half_storey_gable", False)
            if has_half and "gable" in rt:
                rf = b.get("roof_features", [])
                if isinstance(rf, list) and "dormers" not in rf:
                    missing_dormer.append(b.get("building_name", "?"))

    if not heights:
        return None

    rhythm = height_rhythm_score(heights)
    roof_diversity = len(roof_types) / max(1, len(buildings))
    dominant_roof, dominant_count = roof_types.most_common(1)[0]
    roof_uniformity = dominant_count / len(buildings)
    chimney_rate = has_chimney / max(1, pre_1930)

    # Peak height range
    min_h = min(heights)
    max_h = max(heights)

    score = (
        rhythm * 0.3 +
        min(100, roof_diversity * 300) * 0.2 +
        min(100, chimney_rate * 150) * 0.2 +
        (100 - roof_uniformity * 100) * 0.3
    )

    return {
        "street": street_name,
        "building_count": len(buildings),
        "height_range": [round(min_h, 1), round(max_h, 1)],
        "height_rhythm_score": rhythm,
        "roof_types": dict(roof_types),
        "roof_diversity": round(roof_diversity, 2),
        "roof_uniformity": round(roof_uniformity, 2),
        "dominant_roof": dominant_roof,
        "chimney_rate": round(chimney_rate, 2),
        "pre_1930_count": pre_1930,
        "missing_chimneys": len(missing_chimney),
        "missing_dormers": len(missing_dormer),
        "silhouette_score": round(score, 1),
        "details": {
            "missing_chimney_addresses": missing_chimney[:10],
            "missing_dormer_addresses": missing_dormer[:10],
        },
    }


def main():
    parser = argparse.ArgumentParser(description="Roofline silhouette analysis")
    parser.add_argument("--street", help="Analyze single street")
    args = parser.parse_args()

    by_street = defaultdict(list)
    for f in sorted(PARAMS_DIR.glob("*.json")):
        if f.name.startswith("_"):
            continue
        data = json.loads(f.read_text(encoding="utf-8"))
        if data.get("skipped"):
            continue
        street = data.get("site", {}).get("street", "Unknown")
        by_street[street].append(data)

    results = []
    streets = [args.street] if args.street else sorted(by_street.keys())
    for street in streets:
        result = analyze_street(by_street.get(street, []), street)
        if result:
            results.append(result)

    results.sort(key=lambda r: r["silhouette_score"])

    total_missing_ch = sum(r["missing_chimneys"] for r in results)
    total_missing_do = sum(r["missing_dormers"] for r in results)
    avg_score = sum(r["silhouette_score"] for r in results) / max(1, len(results))

    print("=== Roofline Silhouette Analysis ===")
    print(f"Streets: {len(results)}")
    print(f"Average silhouette score: {avg_score:.1f}/100")
    print(f"Missing chimneys (pre-1930): {total_missing_ch}")
    print(f"Missing dormers (2.5-storey gable): {total_missing_do}")
    print()

    for r in results:
        icon = "✓" if r["silhouette_score"] >= 60 else "△" if r["silhouette_score"] >= 40 else "✗"
        print(f"  {icon} {r['street']:25s}  score={r['silhouette_score']:5.1f}  "
              f"heights=[{r['height_range'][0]:.0f}-{r['height_range'][1]:.0f}m]  "
              f"rhythm={r['height_rhythm_score']:3d}  "
              f"roofs={dict(r['roof_types'])}  "
              f"chimneys={r['chimney_rate']:.0%}")

    out = ROOT / "outputs" / "roofline_silhouette.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nReport saved: {out}")


if __name__ == "__main__":
    main()
