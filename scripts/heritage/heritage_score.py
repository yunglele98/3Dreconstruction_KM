#!/usr/bin/env python3
"""Compute heritage significance score per building (0-100).

Scores based on: contributing status (30), date (20), features (20),
typology (15), sub-area (15).

Usage:
    python scripts/heritage/heritage_score.py
"""
import argparse
import json
from pathlib import Path

REPO = Path(__file__).parent.parent.parent

SUB_AREA_SCORES = {"Market": 15, "Residential": 10, "n/a": 5}
TYPOLOGY_SCORES = {
    "Bay-and-Gable": 15, "Semi-detached": 12, "Row": 12,
    "Detached": 11, "Converted": 10, "Commercial": 8,
    "Industrial": 7, "Institutional": 13,
}


def date_score(cd):
    if not cd:
        return 5
    cd = cd.lower()
    if "pre-1889" in cd or "pre-1880" in cd:
        return 20
    if "188" in cd:
        return 18
    if "189" in cd:
        return 16
    if "190" in cd:
        return 14
    if "191" in cd:
        return 12
    if "192" in cd or "193" in cd:
        return 10
    if "194" in cd or "195" in cd:
        return 8
    return 6


def feature_score(n):
    if n >= 8: return 20
    if n >= 6: return 16
    if n >= 4: return 12
    if n >= 2: return 8
    if n >= 1: return 5
    return 2


def compute_score(b):
    score = 0
    c = b.get("contributing")
    if c is True or c == "contributing":
        score += 30
    elif c == "non-contributing":
        score += 5
    else:
        score += 15
    score += date_score(b.get("construction_date", ""))
    score += feature_score(b.get("feature_count", 0))
    typology = b.get("typology", "")
    best = 5
    for k, v in TYPOLOGY_SCORES.items():
        if k.lower() in typology.lower():
            best = max(best, v)
    score += best
    sub_area = b.get("sub_area", "n/a")
    sa = 5
    for k, v in SUB_AREA_SCORES.items():
        if k.lower() in sub_area.lower():
            sa = max(sa, v)
    score += sa
    return min(score, 100)


def classify(score):
    if score >= 80: return "high"
    if score >= 60: return "medium"
    if score >= 40: return "low"
    return "minimal"


def main():
    parser = argparse.ArgumentParser(description="Compute heritage scores")
    parser.add_argument("--input", type=Path, default=REPO / "outputs" / "heritage" / "hcd_features.json")
    parser.add_argument("--output", type=Path, default=REPO / "outputs" / "heritage" / "heritage_scores.json")
    args = parser.parse_args()

    features = json.loads(args.input.read_text(encoding="utf-8"))
    results = {}
    sig_counts = {"high": 0, "medium": 0, "low": 0, "minimal": 0}

    for addr, data in features.items():
        s = compute_score(data)
        sig = classify(s)
        results[addr] = {**data, "heritage_score": s, "significance": sig}
        sig_counts[sig] += 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")

    scores = [r["heritage_score"] for r in results.values()]
    print(f"Heritage scores for {len(results)} buildings")
    print(f"  Mean: {sum(scores) / len(scores):.1f}, Min: {min(scores)}, Max: {max(scores)}")
    print(f"\nSignificance:")
    for level, count in sig_counts.items():
        print(f"  {level:10s} {count:4d} ({count / len(results) * 100:.0f}%)")
    top = sorted(results.items(), key=lambda x: -x[1]["heritage_score"])[:10]
    print(f"\nTop 10:")
    for addr, data in top:
        print(f"  {data['heritage_score']:3d} {addr}")


if __name__ == "__main__":
    main()
