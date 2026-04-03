#!/usr/bin/env python3
"""Analyze streetscape continuity for visual realism.

Detects:
- Height mismatches between adjacent party-wall buildings (should be flush)
- Abrupt material transitions (brick→stucco→brick on a row)
- Setback irregularities (one building jutting out from a uniform row)
- Missing party walls on row buildings
- Roof type discontinuities that break skyline rhythm

Outputs per-street continuity scores and specific fix recommendations.

Usage:
    python scripts/analyze/streetscape_continuity.py
    python scripts/analyze/streetscape_continuity.py --street "Augusta Ave"
"""

import argparse
import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
PARAMS_DIR = ROOT / "params"


def load_street_buildings():
    """Load buildings grouped by street, sorted by street number."""
    by_street = defaultdict(list)
    for f in sorted(PARAMS_DIR.glob("*.json")):
        if f.name.startswith("_"):
            continue
        data = json.loads(f.read_text(encoding="utf-8"))
        if data.get("skipped"):
            continue
        site = data.get("site", {})
        street = site.get("street", "Unknown") if isinstance(site, dict) else "Unknown"
        num = site.get("street_number", "") if isinstance(site, dict) else ""
        try:
            sort_key = int("".join(c for c in str(num) if c.isdigit()) or "0")
        except ValueError:
            sort_key = 0
        data["_sort_num"] = sort_key
        by_street[street].append(data)

    for street in by_street:
        by_street[street].sort(key=lambda b: b["_sort_num"])
    return by_street


def analyze_adjacent_pairs(buildings):
    """Analyze pairs of adjacent buildings for continuity issues."""
    issues = []

    for i in range(len(buildings) - 1):
        a = buildings[i]
        b = buildings[i + 1]
        addr_a = a.get("building_name", "?")
        addr_b = b.get("building_name", "?")

        # 1. Height mismatch on party-wall buildings
        a_pw_right = a.get("party_wall_right", False)
        b_pw_left = b.get("party_wall_left", False)
        if a_pw_right or b_pw_left:
            h_a = a.get("total_height_m", 0)
            h_b = b.get("total_height_m", 0)
            if h_a > 0 and h_b > 0:
                diff = abs(h_a - h_b)
                if diff > 2.0:
                    issues.append({
                        "type": "HEIGHT_STEP",
                        "severity": "high" if diff > 4.0 else "medium",
                        "pair": [addr_a, addr_b],
                        "detail": f"Party-wall height step: {h_a:.1f}m vs {h_b:.1f}m "
                                  f"(Δ{diff:.1f}m)",
                    })

        # 2. Material transition
        mat_a = str(a.get("facade_material", "")).lower()
        mat_b = str(b.get("facade_material", "")).lower()
        if mat_a and mat_b and mat_a != mat_b:
            # Check if this is an isolated odd-one-out
            if i > 0:
                mat_prev = str(buildings[i - 1].get("facade_material", "")).lower()
                if mat_prev == mat_b and mat_a != mat_b:
                    issues.append({
                        "type": "MATERIAL_OUTLIER",
                        "severity": "low",
                        "pair": [addr_a],
                        "detail": f"{addr_a} is {mat_a} between {mat_prev} "
                                  f"neighbours (possible renovation)",
                    })

        # 3. Missing party wall on row typology
        hcd_a = a.get("hcd_data", {})
        hcd_b = b.get("hcd_data", {})
        typ_a = str(hcd_a.get("typology", "")) if isinstance(hcd_a, dict) else ""
        typ_b = str(hcd_b.get("typology", "")) if isinstance(hcd_b, dict) else ""
        if "Row" in typ_a and not a.get("party_wall_right"):
            issues.append({
                "type": "MISSING_PARTY_WALL",
                "severity": "medium",
                "pair": [addr_a],
                "detail": f"{addr_a} is Row typology but party_wall_right=False",
            })

        # 4. Setback discontinuity
        sb_a = a.get("site", {}).get("setback_m", 0) if isinstance(a.get("site"), dict) else 0
        sb_b = b.get("site", {}).get("setback_m", 0) if isinstance(b.get("site"), dict) else 0
        if isinstance(sb_a, (int, float)) and isinstance(sb_b, (int, float)):
            if sb_a > 0 and sb_b > 0 and abs(sb_a - sb_b) > 2.0:
                issues.append({
                    "type": "SETBACK_JUMP",
                    "severity": "low",
                    "pair": [addr_a, addr_b],
                    "detail": f"Setback jump: {sb_a:.1f}m → {sb_b:.1f}m",
                })

        # 5. Roof type discontinuity in a row
        roof_a = str(a.get("roof_type", "")).lower()
        roof_b = str(b.get("roof_type", "")).lower()
        if (a_pw_right or b_pw_left) and roof_a and roof_b and roof_a != roof_b:
            issues.append({
                "type": "ROOF_DISCONTINUITY",
                "severity": "low",
                "pair": [addr_a, addr_b],
                "detail": f"Party-wall pair with different roofs: "
                          f"{roof_a} / {roof_b}",
            })

    return issues


def analyze_street(buildings, street_name):
    """Full continuity analysis for one street."""
    if len(buildings) < 2:
        return None

    issues = analyze_adjacent_pairs(buildings)

    # Compute continuity score
    pair_count = len(buildings) - 1
    high_issues = sum(1 for i in issues if i["severity"] == "high")
    med_issues = sum(1 for i in issues if i["severity"] == "medium")
    low_issues = sum(1 for i in issues if i["severity"] == "low")

    penalty = high_issues * 10 + med_issues * 5 + low_issues * 2
    max_score = pair_count * 10
    score = max(0, 100 - (penalty / max(1, max_score)) * 100)

    return {
        "street": street_name,
        "building_count": len(buildings),
        "pair_count": pair_count,
        "continuity_score": round(score, 1),
        "issues": {
            "high": high_issues,
            "medium": med_issues,
            "low": low_issues,
            "total": len(issues),
        },
        "details": issues,
    }


def main():
    parser = argparse.ArgumentParser(description="Streetscape continuity analysis")
    parser.add_argument("--street", help="Analyze single street")
    args = parser.parse_args()

    by_street = load_street_buildings()
    results = []

    streets = [args.street] if args.street else sorted(by_street.keys())
    for street in streets:
        buildings = by_street.get(street, [])
        result = analyze_street(buildings, street)
        if result:
            results.append(result)

    results.sort(key=lambda r: r["continuity_score"])

    print("=== Streetscape Continuity Analysis ===")
    print(f"Streets: {len(results)}")
    avg_score = sum(r["continuity_score"] for r in results) / max(1, len(results))
    print(f"Average continuity score: {avg_score:.1f}/100")
    print()

    for r in results:
        icon = "✓" if r["continuity_score"] >= 80 else "△" if r["continuity_score"] >= 50 else "✗"
        print(f"  {icon} {r['street']:25s}  score={r['continuity_score']:5.1f}  "
              f"buildings={r['building_count']:3d}  "
              f"issues={r['issues']['total']:2d} "
              f"(H:{r['issues']['high']} M:{r['issues']['medium']} L:{r['issues']['low']})")

    # Detail for worst streets
    worst = [r for r in results if r["continuity_score"] < 70]
    if worst:
        print(f"\n--- Streets needing attention ({len(worst)}) ---")
        for r in worst[:5]:
            print(f"\n  {r['street']} (score {r['continuity_score']}):")
            for issue in r["details"][:10]:
                sev = {"high": "!!!", "medium": " ! ", "low": "   "}[issue["severity"]]
                print(f"    [{sev}] {issue['detail']}")

    out = ROOT / "outputs" / "streetscape_continuity.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nReport saved: {out}")


if __name__ == "__main__":
    main()
