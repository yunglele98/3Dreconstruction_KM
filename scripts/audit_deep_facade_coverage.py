#!/usr/bin/env python3
"""
Audit deep_facade_analysis coverage by street.

Reports total buildings, count with/without deep_facade_analysis, and
coverage percentage per street. Flags streets below 80%.
"""
import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PARAMS_DIR = ROOT / "params"
OUTPUT_FILE = ROOT / "outputs" / "deep_facade_coverage_report.json"

COVERAGE_THRESHOLD = 0.80


def get_street(params: dict, filename: str) -> str:
    site = params.get("site", {})
    street = (site.get("street") or "").strip()
    if street:
        return street
    name = params.get("building_name", filename.replace("_", " "))
    for suffix in ("Ave", "St", "Pl", "Sq", "Terrace"):
        parts = name.split()
        for i, part in enumerate(parts):
            if part == suffix and i > 0:
                street_parts = []
                for j in range(i, -1, -1):
                    if parts[j].replace("-", "").replace("A", "").replace("a", "").isdigit():
                        break
                    street_parts.insert(0, parts[j])
                if street_parts:
                    return " ".join(street_parts)
    return "Unknown"


def main():
    by_street = defaultdict(lambda: {"total": 0, "with_dfa": 0, "without_dfa": 0})
    total_active = 0
    total_dfa = 0

    for param_file in sorted(PARAMS_DIR.glob("*.json")):
        if param_file.name.startswith("_") or "backup" in param_file.name:
            continue
        with open(param_file, encoding="utf-8") as f:
            params = json.load(f)
        if params.get("skipped"):
            continue

        total_active += 1
        street = get_street(params, param_file.stem)
        by_street[street]["total"] += 1

        if params.get("deep_facade_analysis"):
            by_street[street]["with_dfa"] += 1
            total_dfa += 1
        else:
            by_street[street]["without_dfa"] += 1

    # Build report
    street_reports = []
    flagged = []
    for street, counts in sorted(by_street.items(), key=lambda x: -x[1]["total"]):
        coverage = counts["with_dfa"] / counts["total"] if counts["total"] > 0 else 0
        entry = {
            "street": street,
            "total": counts["total"],
            "with_dfa": counts["with_dfa"],
            "without_dfa": counts["without_dfa"],
            "coverage_pct": round(coverage * 100, 1),
        }
        street_reports.append(entry)
        if coverage < COVERAGE_THRESHOLD:
            flagged.append(entry)

    report = {
        "total_active_buildings": total_active,
        "total_with_dfa": total_dfa,
        "total_without_dfa": total_active - total_dfa,
        "overall_coverage_pct": round(total_dfa / total_active * 100, 1) if total_active > 0 else 0,
        "streets": street_reports,
        "flagged_below_80pct": flagged,
    }

    # Console summary
    print(f"Deep Facade Coverage Report")
    print(f"{'='*60}")
    print(f"Total active: {total_active}, With DFA: {total_dfa}, Coverage: {report['overall_coverage_pct']}%")
    print(f"\n{'Street':<25} {'Total':>6} {'DFA':>6} {'Miss':>6} {'Cov%':>8}")
    print("-" * 55)
    for s in street_reports:
        flag = " ***" if s["coverage_pct"] < 80 else ""
        print(f"{s['street']:<25} {s['total']:>6} {s['with_dfa']:>6} {s['without_dfa']:>6} {s['coverage_pct']:>7.1f}%{flag}")

    if flagged:
        print(f"\n*** {len(flagged)} streets below 80% coverage")

    # Write JSON
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(f"\nReport written to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
