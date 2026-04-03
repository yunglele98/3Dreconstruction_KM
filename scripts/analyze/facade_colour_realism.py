#!/usr/bin/env python3
"""Analyze facade colour distribution for realism.

Detects:
- Streets where every building has the same brick colour (unrealistic)
- Buildings whose brick colour doesn't match their era
- Missing colour variation within rows of identical typology
- Facade colours that are over-saturated or implausible for heritage brick

Outputs a JSON report with per-street colour diversity scores and
specific buildings flagged for colour correction.

Usage:
    python scripts/analyze/facade_colour_realism.py
    python scripts/analyze/facade_colour_realism.py --street "Augusta Ave"
    python scripts/analyze/facade_colour_realism.py --fix-suggestions
"""

import argparse
import colorsys
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
PARAMS_DIR = ROOT / "params"

# Era-appropriate brick colour ranges (HSV hue, saturation, value)
# Based on Toronto heritage brick manufacturing periods
ERA_BRICK_PROFILES = {
    "Pre-1889": {
        "label": "Rich red / brown (hand-pressed)",
        "hue_range": (0, 30),       # red-orange
        "sat_range": (0.25, 0.75),
        "val_range": (0.25, 0.75),
        "typical_hexes": ["#B85A3A", "#8A3A2A", "#7A5C44", "#A04030"],
    },
    "1889-1903": {
        "label": "Medium red / buff (machine-pressed)",
        "hue_range": (0, 40),
        "sat_range": (0.20, 0.65),
        "val_range": (0.30, 0.70),
        "typical_hexes": ["#B85A3A", "#C87040", "#D4B896"],
    },
    "1904-1913": {
        "label": "Buff / cream / orange (Edwardian)",
        "hue_range": (15, 50),
        "sat_range": (0.15, 0.55),
        "val_range": (0.45, 0.85),
        "typical_hexes": ["#D4B896", "#C87040", "#E8D8B0"],
    },
    "1914-1930": {
        "label": "Buff / grey / brown (interwar)",
        "hue_range": (10, 50),
        "sat_range": (0.10, 0.45),
        "val_range": (0.35, 0.70),
        "typical_hexes": ["#D4B896", "#8A8A8A", "#7A5C44"],
    },
}


def hex_to_hsv(hex_str):
    """Convert hex colour to HSV tuple (h=0-360, s=0-1, v=0-1)."""
    if not hex_str or not isinstance(hex_str, str):
        return None
    hex_str = hex_str.lstrip("#")
    if len(hex_str) != 6:
        return None
    try:
        r, g, b = int(hex_str[0:2], 16), int(hex_str[2:4], 16), int(hex_str[4:6], 16)
    except ValueError:
        return None
    h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
    return (h * 360, s, v)


def colour_distance(hex1, hex2):
    """Rough perceptual distance between two hex colours."""
    hsv1 = hex_to_hsv(hex1)
    hsv2 = hex_to_hsv(hex2)
    if not hsv1 or not hsv2:
        return 999
    dh = min(abs(hsv1[0] - hsv2[0]), 360 - abs(hsv1[0] - hsv2[0])) / 180
    ds = abs(hsv1[1] - hsv2[1])
    dv = abs(hsv1[2] - hsv2[2])
    return (dh ** 2 + ds ** 2 + dv ** 2) ** 0.5


def check_era_match(hex_str, era):
    """Check if a brick colour is plausible for its construction era."""
    profile = ERA_BRICK_PROFILES.get(era)
    if not profile:
        return True, ""  # unknown era, can't check
    hsv = hex_to_hsv(hex_str)
    if not hsv:
        return True, ""
    h, s, v = hsv
    issues = []
    hlo, hhi = profile["hue_range"]
    if not (hlo <= h <= hhi or (hlo > hhi and (h >= hlo or h <= hhi))):
        issues.append(f"hue {h:.0f} outside era range [{hlo}-{hhi}]")
    slo, shi = profile["sat_range"]
    if s < slo or s > shi:
        issues.append(f"saturation {s:.2f} outside [{slo}-{shi}]")
    vlo, vhi = profile["val_range"]
    if v < vlo or v > vhi:
        issues.append(f"value {v:.2f} outside [{vlo}-{vhi}]")
    return len(issues) == 0, "; ".join(issues)


def analyze_street(buildings, street_name):
    """Analyze colour realism for a single street."""
    colours = []
    era_mismatches = []

    for b in buildings:
        fd = b.get("facade_detail", {})
        brick_hex = None
        if isinstance(fd, dict):
            brick_hex = fd.get("brick_colour_hex")
        if not brick_hex:
            cp = b.get("colour_palette", {})
            if isinstance(cp, dict):
                brick_hex = cp.get("facade")
        if not brick_hex:
            continue

        era = ""
        hcd = b.get("hcd_data", {})
        if isinstance(hcd, dict):
            era = hcd.get("construction_date", "")

        colours.append({
            "address": b.get("building_name", "?"),
            "hex": brick_hex,
            "era": era,
            "material": str(b.get("facade_material", "")).lower(),
        })

        # Check era appropriateness
        if "brick" in str(b.get("facade_material", "")).lower():
            ok, reason = check_era_match(brick_hex, era)
            if not ok:
                era_mismatches.append({
                    "address": b.get("building_name", "?"),
                    "hex": brick_hex,
                    "era": era,
                    "issue": reason,
                })

    if not colours:
        return None

    # Compute colour diversity
    unique_hexes = set(c["hex"] for c in colours)
    diversity_ratio = len(unique_hexes) / len(colours) if colours else 0

    # Check for suspiciously uniform streets
    hex_counts = Counter(c["hex"] for c in colours)
    dominant_hex, dominant_count = hex_counts.most_common(1)[0]
    uniformity = dominant_count / len(colours)

    # Compute average pairwise distance
    hexes = [c["hex"] for c in colours[:20]]  # limit for performance
    distances = []
    for i in range(len(hexes)):
        for j in range(i + 1, len(hexes)):
            distances.append(colour_distance(hexes[i], hexes[j]))
    avg_distance = sum(distances) / len(distances) if distances else 0

    return {
        "street": street_name,
        "building_count": len(colours),
        "unique_colours": len(unique_hexes),
        "diversity_ratio": round(diversity_ratio, 3),
        "dominant_colour": dominant_hex,
        "uniformity": round(uniformity, 3),
        "avg_colour_distance": round(avg_distance, 3),
        "era_mismatches": era_mismatches,
        "flags": [],
    }


def load_buildings():
    """Load all active building params grouped by street."""
    by_street = defaultdict(list)
    for f in sorted(PARAMS_DIR.glob("*.json")):
        if f.name.startswith("_"):
            continue
        data = json.loads(f.read_text(encoding="utf-8"))
        if data.get("skipped"):
            continue
        street = data.get("site", {}).get("street", "Unknown")
        by_street[street].append(data)
    return by_street


def main():
    parser = argparse.ArgumentParser(description="Facade colour realism analysis")
    parser.add_argument("--street", help="Analyze single street")
    parser.add_argument("--fix-suggestions", action="store_true",
                        help="Include suggested fix colours")
    args = parser.parse_args()

    by_street = load_buildings()
    results = []

    streets = [args.street] if args.street else sorted(by_street.keys())
    for street in streets:
        buildings = by_street.get(street, [])
        if not buildings:
            continue
        result = analyze_street(buildings, street)
        if not result:
            continue

        # Flag issues
        if result["uniformity"] > 0.6 and result["building_count"] >= 5:
            result["flags"].append(
                f"LOW_DIVERSITY: {result['uniformity']:.0%} of buildings share "
                f"colour {result['dominant_colour']}"
            )
        if result["avg_colour_distance"] < 0.05 and result["building_count"] >= 5:
            result["flags"].append(
                f"NEAR_IDENTICAL: avg colour distance {result['avg_colour_distance']:.3f}"
            )
        if result["era_mismatches"]:
            result["flags"].append(
                f"ERA_MISMATCH: {len(result['era_mismatches'])} buildings have "
                f"colours outside their era's typical range"
            )

        if args.fix_suggestions and result["era_mismatches"]:
            for mm in result["era_mismatches"]:
                profile = ERA_BRICK_PROFILES.get(mm["era"], {})
                mm["suggested_hexes"] = profile.get("typical_hexes", [])

        results.append(result)

    # Summary
    total_flags = sum(len(r["flags"]) for r in results)
    total_era = sum(len(r["era_mismatches"]) for r in results)
    low_div = [r for r in results if any("LOW_DIVERSITY" in f for f in r["flags"])]

    print(f"=== Facade Colour Realism Analysis ===")
    print(f"Streets analyzed: {len(results)}")
    print(f"Total flags: {total_flags}")
    print(f"Era mismatches: {total_era}")
    print(f"Low-diversity streets: {len(low_div)}")
    print()

    for r in sorted(results, key=lambda x: -len(x["flags"])):
        if r["flags"] or args.street:
            print(f"  {r['street']} ({r['building_count']} buildings)")
            print(f"    Diversity: {r['diversity_ratio']:.1%} "
                  f"({r['unique_colours']} unique colours)")
            print(f"    Avg distance: {r['avg_colour_distance']:.3f}")
            for flag in r["flags"]:
                print(f"    ⚠ {flag}")
            if r["era_mismatches"] and (args.street or args.fix_suggestions):
                for mm in r["era_mismatches"][:5]:
                    print(f"    → {mm['address']}: {mm['hex']} ({mm['era']}) - {mm['issue']}")
                    if "suggested_hexes" in mm:
                        print(f"      Suggested: {', '.join(mm['suggested_hexes'])}")
            print()

    # Save report
    out = ROOT / "outputs" / "facade_colour_realism.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w") as f:
        json.dump(results, f, indent=2)
    print(f"Report saved: {out}")


if __name__ == "__main__":
    main()
