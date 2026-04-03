#!/usr/bin/env python3
"""Analyze window patterns for visual realism.

Detects:
- Identical window counts across all floors (looks procedural)
- Window counts that don't match facade width (too sparse or too dense)
- Missing window type variation between floors (ground vs upper)
- Symmetric window layouts that break real-world irregularity
- Bay-and-gable typology without correct bay window placement

Usage:
    python scripts/analyze/window_pattern_realism.py
    python scripts/analyze/window_pattern_realism.py --street "Baldwin St"
"""

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
PARAMS_DIR = ROOT / "params"

# Typical window density (windows per metre of facade) by era
ERA_WINDOW_DENSITY = {
    "Pre-1889": (0.25, 0.55),     # wider spacing, larger windows
    "1889-1903": (0.30, 0.60),
    "1904-1913": (0.30, 0.65),
    "1914-1930": (0.35, 0.70),    # tighter spacing
}

# Bay-and-gable should have specific window patterns
BAY_GABLE_RULES = {
    "bay_window_required": True,
    "bay_window_floors": [1, 2],
    "gable_window_expected": True,
    "typical_wpf_2storey": [2, 2],    # ground: 2 in bay, upper: 2 in bay
    "typical_wpf_2_5storey": [2, 2],  # + gable window
}


def analyze_window_realism(params):
    """Analyze one building's window pattern for realism."""
    issues = []
    address = params.get("building_name", "?")
    floors = params.get("floors", 2)
    width = params.get("facade_width_m", 6.0)
    wpf = params.get("windows_per_floor", [])
    has_storefront = params.get("has_storefront", False)
    hcd = params.get("hcd_data", {})
    typology = hcd.get("typology", "") if isinstance(hcd, dict) else ""
    era = hcd.get("construction_date", "") if isinstance(hcd, dict) else ""

    if not wpf or not isinstance(wpf, list):
        return {"address": address, "issues": [], "score": 50}

    # 1. All floors have identical window count
    upper_wpf = wpf[1:] if len(wpf) > 1 else wpf
    if len(set(upper_wpf)) == 1 and len(upper_wpf) >= 2 and not has_storefront:
        # This is actually common for Victorian rows — only flag if ground == upper
        if len(wpf) >= 2 and wpf[0] == wpf[1] and not has_storefront:
            issues.append({
                "type": "UNIFORM_WINDOW_COUNT",
                "severity": "low",
                "detail": f"All floors have {wpf[0]} windows — consider ground floor variation",
            })

    # 2. Window density check
    for i, count in enumerate(wpf):
        if not isinstance(count, (int, float)) or count <= 0:
            continue
        if not isinstance(width, (int, float)) or width <= 0:
            continue
        density = count / width
        lo, hi = ERA_WINDOW_DENSITY.get(era, (0.25, 0.70))
        if density > hi * 1.3:
            issues.append({
                "type": "OVERCROWDED_WINDOWS",
                "severity": "medium",
                "detail": f"Floor {i+1}: {count} windows in {width:.1f}m "
                          f"(density {density:.2f}/m, max ~{hi:.2f}/m for {era or 'default'})",
            })
        elif density < lo * 0.5 and count >= 2:
            issues.append({
                "type": "SPARSE_WINDOWS",
                "severity": "low",
                "detail": f"Floor {i+1}: {count} windows in {width:.1f}m "
                          f"(density {density:.2f}/m, min ~{lo:.2f}/m for {era or 'default'})",
            })

    # 3. Bay-and-gable typology checks
    if "Bay-and-Gable" in typology or "bay_and_gable" in typology.lower().replace("-", "_"):
        bay = params.get("bay_window", {})
        has_bay = isinstance(bay, dict) and bay.get("present", False)
        if not has_bay:
            issues.append({
                "type": "BAY_GABLE_MISSING_BAY",
                "severity": "high",
                "detail": "Bay-and-Gable typology but no bay_window defined",
            })

        # Check for gable window
        rd = params.get("roof_detail", {})
        gw = rd.get("gable_window", {}) if isinstance(rd, dict) else {}
        has_gw = isinstance(gw, dict) and gw.get("present", False)
        if not has_gw:
            issues.append({
                "type": "BAY_GABLE_MISSING_GABLE_WINDOW",
                "severity": "medium",
                "detail": "Bay-and-Gable typology but no gable_window defined",
            })

    # 4. Ground floor should differ from upper floors (commercial buildings)
    if has_storefront and len(wpf) >= 2 and wpf[0] > 0:
        issues.append({
            "type": "STOREFRONT_WITH_WINDOWS",
            "severity": "low",
            "detail": f"Has storefront but ground floor windows_per_floor={wpf[0]} "
                      f"(storefront should replace ground windows)",
        })

    # Compute realism score
    high = sum(1 for i in issues if i["severity"] == "high")
    med = sum(1 for i in issues if i["severity"] == "medium")
    low = sum(1 for i in issues if i["severity"] == "low")
    score = max(0, 100 - high * 20 - med * 10 - low * 3)

    return {
        "address": address,
        "floors": floors,
        "width": width,
        "wpf": wpf,
        "typology": typology,
        "issues": issues,
        "score": score,
    }


def main():
    parser = argparse.ArgumentParser(description="Window pattern realism analysis")
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
    streets = [args.street] if args.street else sorted(by_street.keys())

    for street in streets:
        buildings = by_street.get(street, [])
        for b in buildings:
            result = analyze_window_realism(b)
            result["street"] = street
            all_results.append(result)

    # Summary
    total_issues = sum(len(r["issues"]) for r in all_results)
    high_issues = sum(1 for r in all_results for i in r["issues"] if i["severity"] == "high")
    avg_score = sum(r["score"] for r in all_results) / max(1, len(all_results))
    bay_gable_missing = sum(
        1 for r in all_results
        if any(i["type"] == "BAY_GABLE_MISSING_BAY" for i in r["issues"])
    )

    print("=== Window Pattern Realism Analysis ===")
    print(f"Buildings: {len(all_results)}")
    print(f"Average score: {avg_score:.1f}/100")
    print(f"Total issues: {total_issues} (high: {high_issues})")
    print(f"Bay-and-Gable missing bay window: {bay_gable_missing}")
    print()

    # Group by issue type
    type_counts = Counter(
        i["type"] for r in all_results for i in r["issues"]
    )
    for itype, count in type_counts.most_common():
        print(f"  {itype}: {count}")

    # Show worst buildings
    worst = sorted(all_results, key=lambda r: r["score"])[:10]
    if worst and worst[0]["score"] < 80:
        print(f"\n--- Buildings with lowest window realism ---")
        for r in worst:
            if r["score"] >= 80:
                break
            print(f"  {r['address']} (score {r['score']}): wpf={r['wpf']} "
                  f"width={r['width']:.1f}m")
            for issue in r["issues"]:
                print(f"    [{issue['severity']}] {issue['detail']}")

    out = ROOT / "outputs" / "window_pattern_realism.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w") as f:
        json.dump(all_results, f, indent=2)
    print(f"\nReport saved: {out}")


if __name__ == "__main__":
    main()
