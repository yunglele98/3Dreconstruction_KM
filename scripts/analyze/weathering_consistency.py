#!/usr/bin/env python3
"""Analyze weathering and aging consistency for realism.

Detects:
- Buildings in "good" condition with Pre-1889 construction (unlikely without restoration)
- Buildings in "poor" condition missing visual decay cues (mortar erosion, efflorescence)
- Uniform condition across entire streets (unrealistic)
- Missing weathering detail for brick buildings (mortar joint width, roughness)
- Era-condition mismatches that would look wrong in renders

Outputs recommendations for roughness, mortar erosion, and colour desaturation.

Usage:
    python scripts/analyze/weathering_consistency.py
    python scripts/analyze/weathering_consistency.py --street "Nassau St"
"""

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
PARAMS_DIR = ROOT / "params"

# Expected condition distribution by era (Toronto heritage buildings)
ERA_CONDITION_PRIORS = {
    "Pre-1889": {"good": 0.10, "fair": 0.55, "poor": 0.35},
    "1889-1903": {"good": 0.20, "fair": 0.55, "poor": 0.25},
    "1904-1913": {"good": 0.30, "fair": 0.55, "poor": 0.15},
    "1914-1930": {"good": 0.40, "fair": 0.50, "poor": 0.10},
}

# Weathering detail recommendations by condition
WEATHERING_RECOMMENDATIONS = {
    "poor": {
        "roughness_bias": 0.15,
        "mortar_erosion_mm": 3.0,
        "colour_desaturation": 0.15,
        "efflorescence_probability": 0.6,
        "spalling_probability": 0.4,
        "staining_probability": 0.7,
    },
    "fair": {
        "roughness_bias": 0.08,
        "mortar_erosion_mm": 1.5,
        "colour_desaturation": 0.08,
        "efflorescence_probability": 0.3,
        "spalling_probability": 0.1,
        "staining_probability": 0.4,
    },
    "good": {
        "roughness_bias": 0.02,
        "mortar_erosion_mm": 0.5,
        "colour_desaturation": 0.02,
        "efflorescence_probability": 0.05,
        "spalling_probability": 0.0,
        "staining_probability": 0.1,
    },
}


def analyze_building_weathering(params):
    """Analyze a single building for weathering realism issues."""
    issues = []
    address = params.get("building_name", "?")
    condition = str(params.get("condition", "")).lower()
    material = str(params.get("facade_material", "")).lower()
    hcd = params.get("hcd_data", {})
    era = hcd.get("construction_date", "") if isinstance(hcd, dict) else ""

    # 1. Era-condition mismatch
    if era in ERA_CONDITION_PRIORS and condition:
        prior = ERA_CONDITION_PRIORS[era].get(condition, 0)
        if prior < 0.15:
            issues.append({
                "type": "ERA_CONDITION_UNLIKELY",
                "detail": f"{era} building in '{condition}' condition "
                          f"(only {prior:.0%} expected)",
                "suggestion": f"Consider 'fair' or add restoration notes",
            })

    # 2. Missing mortar detail on brick
    if "brick" in material:
        fd = params.get("facade_detail", {})
        if isinstance(fd, dict):
            if not fd.get("mortar_joint_width_mm"):
                issues.append({
                    "type": "MISSING_MORTAR_DETAIL",
                    "detail": "Brick building missing mortar_joint_width_mm",
                    "suggestion": "Add mortar_joint_width_mm: 8-12mm for heritage brick",
                })
            if not fd.get("bond_pattern"):
                issues.append({
                    "type": "MISSING_BOND_PATTERN",
                    "detail": "Brick building missing bond_pattern",
                    "suggestion": "Add bond_pattern: 'running bond' (most common in KM)",
                })

    # 3. Condition but no visual cues
    dfa = params.get("deep_facade_analysis", {})
    if isinstance(dfa, dict):
        condition_notes = dfa.get("condition_notes", "")
        condition_obs = str(dfa.get("condition_observed", "")).lower()
        if condition == "poor" and condition_notes and "good" in str(condition_notes).lower():
            issues.append({
                "type": "CONDITION_CONFLICT",
                "detail": f"Condition 'poor' but notes say: {str(condition_notes)[:80]}",
                "suggestion": "Reconcile condition with photo observations",
            })
        if condition_obs and condition_obs != condition and condition:
            issues.append({
                "type": "CONDITION_DISAGREEMENT",
                "detail": f"Param condition='{condition}' but DFA observed='{condition_obs}'",
                "suggestion": f"Update condition to '{condition_obs}' (photo-based)",
            })

    # 4. Generate weathering recommendation
    rec = WEATHERING_RECOMMENDATIONS.get(condition, WEATHERING_RECOMMENDATIONS["fair"])

    return {
        "address": address,
        "condition": condition,
        "era": era,
        "material": material,
        "issues": issues,
        "weathering_params": rec,
    }


def main():
    parser = argparse.ArgumentParser(description="Weathering consistency analysis")
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

    all_results = []
    street_summaries = []

    streets = [args.street] if args.street else sorted(by_street.keys())
    for street in streets:
        buildings = by_street.get(street, [])
        if not buildings:
            continue

        results = [analyze_building_weathering(b) for b in buildings]
        all_results.extend(results)

        # Street-level uniformity check
        conditions = Counter(r["condition"] for r in results if r["condition"])
        total = sum(conditions.values())
        dominant_cond, dominant_count = conditions.most_common(1)[0] if conditions else ("", 0)
        uniformity = dominant_count / total if total else 0

        issues_count = sum(len(r["issues"]) for r in results)
        condition_issues = sum(
            1 for r in results
            if any(i["type"] == "CONDITION_DISAGREEMENT" for i in r["issues"])
        )

        summary = {
            "street": street,
            "building_count": len(results),
            "condition_distribution": dict(conditions),
            "condition_uniformity": round(uniformity, 2),
            "total_issues": issues_count,
            "condition_disagreements": condition_issues,
        }

        if uniformity > 0.8 and total >= 5:
            summary["flag"] = (
                f"UNIFORM_CONDITION: {uniformity:.0%} of buildings are "
                f"'{dominant_cond}' (unrealistic for a full street)"
            )

        street_summaries.append(summary)

    # Print results
    total_issues = sum(s["total_issues"] for s in street_summaries)
    disagreements = sum(s["condition_disagreements"] for s in street_summaries)
    uniform = [s for s in street_summaries if "flag" in s]

    print("=== Weathering & Aging Consistency Analysis ===")
    print(f"Buildings analyzed: {len(all_results)}")
    print(f"Total issues: {total_issues}")
    print(f"Condition disagreements (param vs photo): {disagreements}")
    print(f"Overly uniform streets: {len(uniform)}")
    print()

    for s in sorted(street_summaries, key=lambda x: -x["total_issues"]):
        if s["total_issues"] > 0 or "flag" in s or args.street:
            cond_str = ", ".join(f"{k}:{v}" for k, v in sorted(s["condition_distribution"].items()))
            print(f"  {s['street']:25s}  [{cond_str}]  issues={s['total_issues']}")
            if "flag" in s:
                print(f"    ⚠ {s['flag']}")

    # Save
    out = ROOT / "outputs" / "weathering_consistency.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    report = {"street_summaries": street_summaries, "building_details": all_results}
    with open(out, "w") as f:
        json.dump(report, f, indent=2)
    print(f"\nReport saved: {out}")


if __name__ == "__main__":
    main()
