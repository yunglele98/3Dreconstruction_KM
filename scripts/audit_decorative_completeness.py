#!/usr/bin/env python3
"""
Audit decorative element completeness vs HCD statement_of_contribution.

For each active building, parses hcd_data.statement_of_contribution for
decorative keywords and checks if decorative_elements contains them.
"""
import json
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PARAMS_DIR = ROOT / "params"
OUTPUT_FILE = ROOT / "outputs" / "decorative_completeness_audit.json"

# Keyword -> decorative_elements key mapping
KEYWORD_MAP = {
    "voussoir": "stone_voussoirs",
    "bracket": "gable_brackets",
    "shingle": "ornamental_shingles",
    "cornice": "cornice",
    "string course": "string_courses",
    "quoin": "quoins",
    "bargeboard": "bargeboard",
    "bay window": "bay_window_shape",
    "dormer": None,  # tracked in roof_features, not decorative_elements
    "chimney": None,
}


def extract_hcd_keywords(statement: str) -> list:
    """Extract decorative keywords from HCD statement of contribution."""
    if not statement:
        return []
    lower = statement.lower()
    found = []
    for kw in KEYWORD_MAP:
        if kw in lower:
            found.append(kw)
    return found


def element_present(decorative: dict, key: str) -> bool:
    if not key or key not in decorative:
        return False
    val = decorative[key]
    if isinstance(val, dict):
        return val.get("present", False) or bool(val)
    return bool(val)


def main():
    findings = []
    stats = {"total_checked": 0, "total_missing": 0, "total_complete": 0}
    keyword_stats = defaultdict(lambda: {"mentioned": 0, "present": 0, "missing": 0})

    for param_file in sorted(PARAMS_DIR.glob("*.json")):
        if param_file.name.startswith("_") or "backup" in param_file.name:
            continue
        with open(param_file, encoding="utf-8") as f:
            params = json.load(f)
        if params.get("skipped"):
            continue

        hcd = params.get("hcd_data", {})
        statement = (hcd.get("statement_of_contribution") or "")
        features_list = hcd.get("building_features", [])
        features_text = " ".join(features_list) if isinstance(features_list, list) else str(features_list)
        combined = statement + " " + features_text

        keywords = extract_hcd_keywords(combined)
        if not keywords:
            continue

        stats["total_checked"] += 1
        decorative = params.get("decorative_elements", {})
        missing = []

        for kw in keywords:
            dec_key = KEYWORD_MAP.get(kw)
            keyword_stats[kw]["mentioned"] += 1
            if dec_key and not element_present(decorative, dec_key):
                missing.append(kw)
                keyword_stats[kw]["missing"] += 1
            else:
                keyword_stats[kw]["present"] += 1

        if missing:
            stats["total_missing"] += 1
            address = params.get("building_name", param_file.stem.replace("_", " "))
            findings.append({
                "address": address,
                "file": param_file.name,
                "hcd_keywords": keywords,
                "missing_elements": missing,
            })
        else:
            stats["total_complete"] += 1

    report = {
        "summary": stats,
        "keyword_stats": dict(keyword_stats),
        "findings": findings,
    }

    print(f"Decorative Completeness Audit")
    print(f"{'='*50}")
    print(f"Buildings with HCD keywords: {stats['total_checked']}")
    print(f"  Complete: {stats['total_complete']}")
    print(f"  Missing elements: {stats['total_missing']}")

    print(f"\nKeyword coverage:")
    for kw, s in sorted(keyword_stats.items(), key=lambda x: -x[1]["missing"]):
        print(f"  {kw:<20} mentioned: {s['mentioned']:>4}  present: {s['present']:>4}  missing: {s['missing']:>4}")

    if findings:
        print(f"\nTop 10 buildings with missing elements:")
        for f in findings[:10]:
            print(f"  {f['address']}: missing {f['missing_elements']}")

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(f"\nReport: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
