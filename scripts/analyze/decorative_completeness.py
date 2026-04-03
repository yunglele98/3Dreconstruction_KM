#!/usr/bin/env python3
"""Analyze decorative element completeness for visual richness.

Heritage buildings in Kensington Market have distinctive decorative features
that make each era recognizable. This script identifies buildings that are
missing expected decorative elements for their era and typology.

Detects:
- Victorian buildings (Pre-1889) missing ornamental shingles, bargeboards
- Edwardian buildings missing string courses, voussoirs
- Row buildings missing cornices (visual cap to the roofline)
- Contributing heritage buildings with zero decorative elements
- Bay-and-gable buildings missing gable trim

Usage:
    python scripts/analyze/decorative_completeness.py
    python scripts/analyze/decorative_completeness.py --era "Pre-1889"
"""

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
PARAMS_DIR = ROOT / "params"

# Expected decorative elements by era and typology
ERA_DECORATIVE_EXPECTATIONS = {
    "Pre-1889": {
        "common": ["cornice", "string_courses", "stone_voussoirs", "ornamental_shingles"],
        "gable_roof": ["bargeboard", "gable_brackets", "ridge_finial"],
        "bay_and_gable": ["bargeboard", "ornamental_shingles", "bay_window"],
        "label": "Victorian",
    },
    "1889-1903": {
        "common": ["cornice", "string_courses"],
        "gable_roof": ["bargeboard", "ornamental_shingles"],
        "bay_and_gable": ["bargeboard", "ornamental_shingles", "bay_window"],
        "label": "Late Victorian",
    },
    "1904-1913": {
        "common": ["cornice", "string_courses", "quoins"],
        "gable_roof": ["bargeboard"],
        "bay_and_gable": ["bay_window"],
        "label": "Edwardian",
    },
    "1914-1930": {
        "common": ["cornice"],
        "gable_roof": [],
        "bay_and_gable": ["bay_window"],
        "label": "Interwar",
    },
}


def get_present_elements(params):
    """Return set of decorative element names that are present."""
    present = set()
    dec = params.get("decorative_elements", {})
    if not isinstance(dec, dict):
        return present

    for key, val in dec.items():
        if isinstance(val, dict):
            if val.get("present", False):
                present.add(key)
        elif isinstance(val, bool) and val:
            present.add(key)
        elif isinstance(val, str) and val.lower() not in ("none", "false", ""):
            present.add(key)

    # Also check top-level fields
    if params.get("bay_window", {}).get("present", False):
        present.add("bay_window")
    if params.get("has_storefront"):
        present.add("storefront")

    return present


def analyze_building(params):
    """Analyze decorative completeness for one building."""
    address = params.get("building_name", "?")
    hcd = params.get("hcd_data", {})
    if not isinstance(hcd, dict):
        hcd = {}

    era = hcd.get("construction_date", "")
    typology = hcd.get("typology", "")
    contributing = hcd.get("contributing", "")
    roof_type = str(params.get("roof_type", "")).lower()

    present = get_present_elements(params)
    expectations = ERA_DECORATIVE_EXPECTATIONS.get(era, {})

    missing = []
    expected_count = 0

    # Check common elements
    for elem in expectations.get("common", []):
        expected_count += 1
        if elem not in present:
            missing.append(elem)

    # Check roof-specific elements
    if "gable" in roof_type:
        for elem in expectations.get("gable_roof", []):
            expected_count += 1
            if elem not in present:
                missing.append(elem)

    # Check typology-specific
    if "Bay-and-Gable" in typology or "bay_and_gable" in typology.lower().replace("-", "_"):
        for elem in expectations.get("bay_and_gable", []):
            expected_count += 1
            if elem not in present:
                missing.append(elem)

    completeness = (expected_count - len(missing)) / max(1, expected_count)

    result = {
        "address": address,
        "era": era,
        "era_label": expectations.get("label", "Unknown"),
        "typology": typology,
        "contributing": contributing,
        "roof_type": roof_type,
        "present_elements": sorted(present),
        "missing_elements": missing,
        "expected_count": expected_count,
        "completeness": round(completeness, 2),
    }

    # Flag contributing buildings with very low completeness
    if contributing == "Yes" and completeness < 0.3 and expected_count >= 3:
        result["flag"] = (
            f"Contributing heritage building with {completeness:.0%} "
            f"decorative completeness (missing: {', '.join(missing)})"
        )

    return result


def main():
    parser = argparse.ArgumentParser(description="Decorative completeness analysis")
    parser.add_argument("--era", help="Filter by construction era")
    parser.add_argument("--contributing-only", action="store_true",
                        help="Only analyze contributing heritage buildings")
    args = parser.parse_args()

    results = []
    for f in sorted(PARAMS_DIR.glob("*.json")):
        if f.name.startswith("_"):
            continue
        data = json.loads(f.read_text(encoding="utf-8"))
        if data.get("skipped"):
            continue

        hcd = data.get("hcd_data", {})
        if not isinstance(hcd, dict):
            hcd = {}

        if args.era and hcd.get("construction_date", "") != args.era:
            continue
        if args.contributing_only and hcd.get("contributing") != "Yes":
            continue

        result = analyze_building(data)
        results.append(result)

    # Summary
    avg_completeness = sum(r["completeness"] for r in results) / max(1, len(results))
    flagged = [r for r in results if "flag" in r]
    missing_counts = Counter(
        elem for r in results for elem in r["missing_elements"]
    )

    print("=== Decorative Element Completeness Analysis ===")
    print(f"Buildings analyzed: {len(results)}")
    print(f"Average completeness: {avg_completeness:.0%}")
    print(f"Flagged contributing buildings: {len(flagged)}")
    print()

    print("Most commonly missing elements:")
    for elem, count in missing_counts.most_common(10):
        pct = count / len(results) * 100
        print(f"  {elem:30s} {count:4d} ({pct:.0f}%)")

    # By era
    print("\nCompleteness by era:")
    by_era = defaultdict(list)
    for r in results:
        by_era[r["era"]].append(r["completeness"])
    for era in sorted(by_era.keys()):
        vals = by_era[era]
        avg = sum(vals) / len(vals)
        label = ERA_DECORATIVE_EXPECTATIONS.get(era, {}).get("label", "")
        print(f"  {era:15s} ({label:15s}): {avg:.0%} avg "
              f"({len(vals)} buildings)")

    # Show worst
    worst = [r for r in results if r["completeness"] < 0.3 and r["expected_count"] >= 3]
    if worst:
        print(f"\n--- Buildings with <30% completeness ({len(worst)}) ---")
        for r in sorted(worst, key=lambda x: x["completeness"])[:15]:
            c = "⚑" if r.get("contributing") == "Yes" else " "
            print(f"  {c} {r['address']:35s} {r['completeness']:4.0%} "
                  f"missing: {', '.join(r['missing_elements'])}")

    out = ROOT / "outputs" / "decorative_completeness.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nReport saved: {out}")


if __name__ == "__main__":
    main()
