#!/usr/bin/env python3
"""Heritage fidelity analysis: cross-reference HCD data against params.

For each HCD-contributing building, checks whether heritage plan features
(building_features, statement_of_contribution keywords) are actually
represented in the building's decorative_elements, roof_detail, and
other generator-readable fields.

Usage:
    python scripts/analyze/heritage_fidelity.py
    python scripts/analyze/heritage_fidelity.py --params params/ --output outputs/heritage_analysis/
"""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# ---------------------------------------------------------------------------
# Feature mapping: HCD feature keyword -> where to look in params
# ---------------------------------------------------------------------------

FEATURE_CHECKS: dict[str, list[dict]] = {
    "decorative brick": [
        {"path": "decorative_elements.decorative_brickwork.present", "expect": True},
    ],
    "decorative brickwork": [
        {"path": "decorative_elements.decorative_brickwork.present", "expect": True},
    ],
    "polychromatic brick": [
        {"path": "decorative_elements.decorative_brickwork.present", "expect": True},
    ],
    "string course": [
        {"path": "decorative_elements.string_courses.present", "expect": True},
    ],
    "quoin": [
        {"path": "decorative_elements.quoins.present", "expect": True},
    ],
    "voussoir": [
        {"path": "decorative_elements.stone_voussoirs.present", "expect": True},
    ],
    "stone voussoir": [
        {"path": "decorative_elements.stone_voussoirs.present", "expect": True},
    ],
    "lintel": [
        {"path": "decorative_elements.stone_lintels.present", "expect": True},
    ],
    "stone lintel": [
        {"path": "decorative_elements.stone_lintels.present", "expect": True},
    ],
    "bargeboard": [
        {"path": "decorative_elements.bargeboard.colour_hex", "expect_any": True},
    ],
    "bracket": [
        {"path": "decorative_elements.gable_brackets.type", "expect_any": True},
    ],
    "cornice": [
        {"path": "decorative_elements.cornice.present", "expect": True},
    ],
    "bay window": [
        {"path": "bay_window.present", "expect": True},
    ],
    "dormer": [
        {"path": "roof_features", "expect_contains": "dormer"},
    ],
    "chimney": [
        {"path": "roof_features", "expect_contains": "chimney"},
    ],
    "tower": [
        {"path": "roof_features", "expect_contains": "tower"},
    ],
    "turret": [
        {"path": "roof_features", "expect_contains": "turret"},
    ],
    "storefront": [
        {"path": "has_storefront", "expect": True},
    ],
    "shingle": [
        {"path": "decorative_elements.ornamental_shingles.present", "expect": True},
    ],
    "ornamental shingle": [
        {"path": "decorative_elements.ornamental_shingles.present", "expect": True},
    ],
    "gable": [
        {"path": "roof_type", "expect_in": ["gable", "cross-gable"]},
    ],
    "original window": [
        {"path": "windows_detail", "expect_any": True},
    ],
    "transom": [
        {"path": "doors_detail", "expect_any": True},
    ],
    "porch": [
        {"path": "porch_present", "expect": True},
    ],
    "parapet": [
        {"path": "roof_type", "expect_in": ["flat"]},
    ],
}

# Era ranges for construction date matching
ERA_RANGES: dict[str, tuple[int, int]] = {
    "pre-1889": (1800, 1888),
    "1889-1903": (1889, 1903),
    "1904-1913": (1904, 1913),
    "1914-1930": (1914, 1930),
    "1931+": (1931, 2030),
}

STYLE_ERA_MAP: dict[str, str] = {
    "victorian": "1889-1903",
    "edwardian": "1904-1913",
    "georgian": "pre-1889",
    "gothic": "pre-1889",
    "italianate": "pre-1889",
    "queen anne": "1889-1903",
    "arts and crafts": "1904-1913",
    "art deco": "1914-1930",
}


def _load_params(params_dir: Path) -> list[dict]:
    result = []
    for p in sorted(params_dir.glob("*.json")):
        if p.name.startswith("_"):
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if data.get("skipped"):
            continue
        data["_file"] = str(p)
        result.append(data)
    return result


def _address(params: dict) -> str:
    return (
        params.get("building_name")
        or params.get("_meta", {}).get("address")
        or Path(params.get("_file", "unknown")).stem.replace("_", " ")
    )


def _street(params: dict) -> str:
    site = params.get("site") or {}
    street = site.get("street", "")
    if street:
        return street
    addr = _address(params)
    parts = addr.split()
    for i, p in enumerate(parts):
        if p.isdigit() and i < len(parts) - 1:
            return " ".join(parts[i + 1:])
    return addr


def _resolve_path(params: dict, dotpath: str):
    """Resolve a dot-separated path like 'decorative_elements.cornice.present'."""
    parts = dotpath.split(".")
    obj = params
    for part in parts:
        if isinstance(obj, dict):
            obj = obj.get(part)
        else:
            return None
        if obj is None:
            return None
    return obj


def _check_feature(params: dict, feature_keyword: str) -> dict:
    """Check if a feature is represented in params. Returns check result."""
    checks = FEATURE_CHECKS.get(feature_keyword.lower(), [])
    if not checks:
        return {
            "feature": feature_keyword,
            "status": "unknown",
            "detail": "no check rule defined for this feature",
        }

    for check in checks:
        path = check["path"]
        value = _resolve_path(params, path)

        if "expect" in check:
            if value == check["expect"]:
                return {"feature": feature_keyword, "status": "present", "path": path, "value": value}
        elif "expect_any" in check:
            if value is not None and value is not False and value != "" and value != []:
                return {"feature": feature_keyword, "status": "present", "path": path}
        elif "expect_contains" in check:
            target = check["expect_contains"]
            if isinstance(value, list):
                if any(target.lower() in str(v).lower() for v in value):
                    return {"feature": feature_keyword, "status": "present", "path": path}
            elif isinstance(value, str) and target.lower() in value.lower():
                return {"feature": feature_keyword, "status": "present", "path": path}
        elif "expect_in" in check:
            if isinstance(value, str) and value.lower() in [v.lower() for v in check["expect_in"]]:
                return {"feature": feature_keyword, "status": "present", "path": path, "value": value}

    return {
        "feature": feature_keyword,
        "status": "missing",
        "detail": f"expected at {checks[0]['path']} but not found/false",
    }


def _extract_keywords_from_statement(statement: str) -> list[str]:
    """Extract heritage feature keywords from statement_of_contribution text."""
    if not statement:
        return []
    lower = statement.lower()
    found = []
    for keyword in FEATURE_CHECKS:
        if keyword in lower:
            found.append(keyword)
    return found


def _check_era_consistency(params: dict) -> dict | None:
    """Check if construction_date matches overall_style / era defaults."""
    hcd = params.get("hcd_data") or {}
    construction_date = hcd.get("construction_date", "")
    style = (params.get("overall_style") or "").lower()
    if not construction_date:
        return None

    result: dict = {"construction_date": construction_date}

    # Check style vs date
    if style:
        expected_era = STYLE_ERA_MAP.get(style)
        if expected_era:
            result["overall_style"] = style
            result["expected_era_for_style"] = expected_era
            result["era_match"] = expected_era == construction_date
        else:
            result["overall_style"] = style
            result["era_match"] = None  # no mapping for this style

    return result


def analyze_building(params: dict) -> dict | None:
    """Analyze heritage fidelity for a single building. Returns None if not contributing."""
    hcd = params.get("hcd_data") or {}
    contributing = (hcd.get("contributing") or "").lower()
    if contributing != "yes":
        return None

    addr = _address(params)
    street = _street(params)
    result: dict = {"address": addr, "street": street}

    # Collect features to check
    building_features = hcd.get("building_features") or []
    statement = hcd.get("statement_of_contribution", "")
    statement_keywords = _extract_keywords_from_statement(statement)

    # Deduplicate
    all_features = list(set(
        [f.lower().strip() for f in building_features]
        + [k.lower().strip() for k in statement_keywords]
    ))
    all_features = [f for f in all_features if f]

    result["hcd_features_listed"] = len(all_features)
    result["features"] = all_features

    # Check each feature
    checks = []
    present_count = 0
    missing_count = 0
    unknown_count = 0
    for feature in all_features:
        check = _check_feature(params, feature)
        checks.append(check)
        if check["status"] == "present":
            present_count += 1
        elif check["status"] == "missing":
            missing_count += 1
        else:
            unknown_count += 1

    result["feature_checks"] = checks
    result["features_present"] = present_count
    result["features_missing"] = missing_count
    result["features_unknown"] = unknown_count

    # Coverage score
    total_checkable = present_count + missing_count
    if total_checkable > 0:
        coverage = present_count / total_checkable
    else:
        coverage = 1.0  # No features listed = nothing to check
    result["feature_coverage"] = round(coverage, 3)

    # Discrepancies
    discrepancies = [c for c in checks if c["status"] == "missing"]
    result["discrepancies"] = discrepancies

    # Era consistency
    era_check = _check_era_consistency(params)
    if era_check:
        result["era_consistency"] = era_check

    # Overall score (0-100)
    score = coverage * 80.0
    # Bonus for era consistency
    if era_check and era_check.get("era_match") is True:
        score += 10.0
    elif era_check and era_check.get("era_match") is None:
        score += 5.0  # neutral
    # Bonus for having statement of contribution
    if statement:
        score += 10.0

    result["heritage_fidelity_score"] = round(min(100.0, max(0.0, score)), 1)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Heritage fidelity analysis")
    parser.add_argument("--params", type=Path, default=REPO_ROOT / "params")
    parser.add_argument("--output", type=Path, default=REPO_ROOT / "outputs" / "heritage_analysis")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)

    print(f"Loading params from {args.params} ...")
    buildings = _load_params(args.params)
    print(f"  {len(buildings)} active buildings")

    results = []
    skipped_non_contributing = 0
    for i, params in enumerate(buildings):
        if args.limit and len(results) >= args.limit:
            break
        result = analyze_building(params)
        if result is None:
            skipped_non_contributing += 1
            continue
        results.append(result)

    scores = [r["heritage_fidelity_score"] for r in results]
    arr = np.array(scores) if scores else np.array([0.0])

    # Coverage by feature type
    feature_stats: dict[str, dict[str, int]] = defaultdict(lambda: {"present": 0, "missing": 0, "unknown": 0})
    for r in results:
        for check in r.get("feature_checks", []):
            feature = check["feature"]
            status = check["status"]
            feature_stats[feature][status] += 1

    feature_coverage = {}
    for feat, stats in sorted(feature_stats.items()):
        total = stats["present"] + stats["missing"]
        cov = stats["present"] / total if total > 0 else 1.0
        feature_coverage[feat] = {
            "present": stats["present"],
            "missing": stats["missing"],
            "unknown": stats["unknown"],
            "coverage_pct": round(cov * 100, 1),
        }

    # Per-street
    street_data: dict[str, list[float]] = defaultdict(list)
    for r in results:
        street_data[r["street"]].append(r["heritage_fidelity_score"])
    street_avgs = {
        s: round(sum(v) / len(v), 1) for s, v in sorted(street_data.items())
    }

    # Most common discrepancies
    disc_counts: dict[str, int] = defaultdict(int)
    for r in results:
        for d in r.get("discrepancies", []):
            disc_counts[d["feature"]] += 1
    top_discrepancies = sorted(disc_counts.items(), key=lambda x: -x[1])[:15]

    # Worst buildings
    worst = sorted(results, key=lambda r: r["heritage_fidelity_score"])[:20]
    worst_brief = [
        {
            "address": r["address"],
            "score": r["heritage_fidelity_score"],
            "coverage": r["feature_coverage"],
            "missing": [d["feature"] for d in r["discrepancies"]],
        }
        for r in worst
    ]

    summary = {
        "total_contributing": len(results),
        "skipped_non_contributing": skipped_non_contributing,
        "avg_fidelity_score": round(float(arr.mean()), 1) if len(results) > 0 else 0.0,
        "median_fidelity_score": round(float(np.median(arr)), 1) if len(results) > 0 else 0.0,
        "min_score": round(float(arr.min()), 1) if len(results) > 0 else 0.0,
        "max_score": round(float(arr.max()), 1) if len(results) > 0 else 0.0,
        "score_histogram": {
            "0-20": int(np.sum(arr < 20)) if len(results) > 0 else 0,
            "20-40": int(np.sum((arr >= 20) & (arr < 40))) if len(results) > 0 else 0,
            "40-60": int(np.sum((arr >= 40) & (arr < 60))) if len(results) > 0 else 0,
            "60-80": int(np.sum((arr >= 60) & (arr < 80))) if len(results) > 0 else 0,
            "80-100": int(np.sum(arr >= 80)) if len(results) > 0 else 0,
        },
        "feature_coverage_by_type": feature_coverage,
        "top_discrepancies": [{"feature": f, "count": c} for f, c in top_discrepancies],
        "per_street_averages": street_avgs,
        "worst_20": worst_brief,
    }

    report = {"summary": summary, "buildings": results}
    out_path = args.output / "heritage_fidelity_report.json"
    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\nReport written to {out_path}")
    print(f"  Contributing buildings analyzed: {len(results)}")
    print(f"  Non-contributing skipped: {skipped_non_contributing}")
    if len(results) > 0:
        print(f"  Avg fidelity: {summary['avg_fidelity_score']} | Median: {summary['median_fidelity_score']}")
        if top_discrepancies:
            print(f"  Top missing features: {', '.join(f'{f}({c})' for f, c in top_discrepancies[:5])}")


if __name__ == "__main__":
    main()
