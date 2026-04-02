#!/usr/bin/env python3
"""Generate per-street heritage analysis report.

Usage:
    python scripts/heritage/generate_heritage_report.py
"""
import argparse
import json
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).parent.parent.parent


def extract_street(addr):
    parts = addr.split()
    if len(parts) > 1:
        return " ".join(parts[1:])
    return addr


def main():
    parser = argparse.ArgumentParser(description="Generate heritage report")
    parser.add_argument("--input", type=Path, default=REPO / "outputs" / "heritage" / "heritage_scores.json")
    parser.add_argument("--output", type=Path, default=REPO / "outputs" / "heritage" / "heritage_report.json")
    args = parser.parse_args()

    scores = json.loads(args.input.read_text(encoding="utf-8"))

    streets = defaultdict(list)
    for addr, data in scores.items():
        street = extract_street(addr)
        streets[street].append(data)

    report = {"streets": [], "summary": {}}
    all_scores = []

    for street_name, buildings in sorted(streets.items()):
        bscores = [b["heritage_score"] for b in buildings]
        all_scores.extend(bscores)
        sig_counts = defaultdict(int)
        feature_counts = defaultdict(int)
        typologies = defaultdict(int)
        dates = defaultdict(int)

        for b in buildings:
            sig_counts[b.get("significance", "unknown")] += 1
            for f in b.get("features", []):
                feature_counts[f] += 1
            typologies[b.get("typology", "unknown")] += 1
            dates[b.get("construction_date", "unknown")] += 1

        street_report = {
            "street": street_name,
            "building_count": len(buildings),
            "avg_score": round(sum(bscores) / len(bscores), 1),
            "min_score": min(bscores),
            "max_score": max(bscores),
            "significance": dict(sig_counts),
            "top_features": dict(sorted(feature_counts.items(), key=lambda x: -x[1])[:5]),
            "typologies": dict(typologies),
            "construction_dates": dict(dates),
        }
        report["streets"].append(street_report)

    # Sort by avg score descending
    report["streets"].sort(key=lambda s: -s["avg_score"])

    report["summary"] = {
        "total_buildings": len(scores),
        "total_streets": len(streets),
        "overall_avg_score": round(sum(all_scores) / max(len(all_scores), 1), 1),
        "overall_min": min(all_scores) if all_scores else 0,
        "overall_max": max(all_scores) if all_scores else 0,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Heritage report: {len(streets)} streets, {len(scores)} buildings")
    print(f"Overall avg score: {report['summary']['overall_avg_score']}")
    print(f"\nStreets by heritage score:")
    for s in report["streets"][:15]:
        print(f"  {s['avg_score']:5.1f}  {s['street']} ({s['building_count']} buildings)")


if __name__ == "__main__":
    main()
