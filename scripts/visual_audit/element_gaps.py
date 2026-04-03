#!/usr/bin/env python3
"""Identify most commonly missing/wrong elements from Gemini visual analyses."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_GEMINI_DIR = REPO_ROOT / "outputs" / "visual_audit" / "gemini_analysis"
DEFAULT_PARAMS_DIR = REPO_ROOT / "params"
DEFAULT_ASSETS_DIR = REPO_ROOT / "assets" / "elements"
DEFAULT_OUTPUT = REPO_ROOT / "outputs" / "visual_audit" / "element_gaps.json"

# Ratings that indicate a problem (not "correct" or "minor_diff")
PROBLEM_RATINGS = {
    "wrong_material", "wrong_type", "wrong_style", "wrong_count",
    "wrong_proportions", "wrong_pitch", "wrong_shade", "wrong_chimney",
    "completely_off", "too_narrow", "too_wide", "too_short", "too_tall",
    "too_clean",
    "missing_awning", "missing_bay", "missing_dormer", "missing_other",
    "missing_porch", "missing_storefront",
}

MISSING_RATINGS = {
    "missing_awning", "missing_bay", "missing_dormer", "missing_other",
    "missing_porch", "missing_storefront",
}


def _load_era(address: str, params_dir: Path) -> str:
    slug = (address or "").replace(" ", "_").replace(",", "")
    param_path = params_dir / f"{slug}.json"
    if not param_path.exists():
        return "unknown"
    try:
        params = json.loads(param_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return "unknown"
    hcd = params.get("hcd_data")
    if isinstance(hcd, dict):
        era = hcd.get("construction_date", "")
        if era:
            return str(era)
    return "unknown"


def _scan_available_assets(assets_dir: Path) -> dict[str, list[str]]:
    available = {}
    if not assets_dir.exists():
        return available
    for subdir in assets_dir.iterdir():
        if subdir.is_dir():
            files = [f.stem for f in subdir.iterdir() if f.is_file()]
            if files:
                available[subdir.name] = files
    for f in assets_dir.iterdir():
        if f.is_file() and f.suffix in (".json", ".blend", ".obj", ".fbx", ".glb"):
            available.setdefault("_root", []).append(f.stem)
    return available


def analyze_gaps(gemini_dir: Path, params_dir: Path, assets_dir: Path) -> dict:
    category_problems: Counter = Counter()
    category_missing: Counter = Counter()
    rating_counts: Counter = Counter()
    by_era: dict[str, Counter] = {}
    addresses_by_category: dict[str, list[str]] = {}
    total_files = 0

    for json_file in sorted(gemini_dir.glob("*.json")):
        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue

        total_files += 1
        address = data.get("address", json_file.stem.replace("_", " "))
        era = _load_era(address, params_dir)
        categories = data.get("categories", {})

        for cat_name, cat_data in categories.items():
            if not isinstance(cat_data, dict):
                continue
            rating = (cat_data.get("rating") or "").lower().strip()
            if not rating:
                continue

            rating_counts[rating] += 1

            if rating in PROBLEM_RATINGS:
                category_problems[cat_name] += 1
                addresses_by_category.setdefault(cat_name, []).append(address)

                era_counter = by_era.setdefault(era, Counter())
                era_counter[cat_name] += 1

            if rating in MISSING_RATINGS:
                category_missing[cat_name] += 1

    available_assets = _scan_available_assets(assets_dir)

    gap_items = []
    for cat, count in category_problems.most_common():
        pct = round(count / max(total_files, 1) * 100, 1)
        missing_count = category_missing.get(cat, 0)
        asset_status = "available" if cat in available_assets else "not_found"
        sample_addresses = sorted(set(addresses_by_category.get(cat, [])))[:10]

        gap_items.append({
            "category": cat,
            "problem_count": count,
            "missing_count": missing_count,
            "pct_of_buildings": pct,
            "asset_status": asset_status,
            "sample_addresses": sample_addresses,
        })

    era_summary = {}
    for era, counter in sorted(by_era.items()):
        era_summary[era] = [
            {"category": cat, "count": cnt}
            for cat, cnt in counter.most_common()
        ]

    return {
        "total_analyses": total_files,
        "gaps": gap_items,
        "by_era": era_summary,
        "rating_distribution": dict(rating_counts.most_common()),
        "available_assets": {k: len(v) for k, v in available_assets.items()},
    }


def main():
    parser = argparse.ArgumentParser(description="Element library gap analysis from Gemini visual audits.")
    parser.add_argument("--gemini-dir", type=Path, default=DEFAULT_GEMINI_DIR)
    parser.add_argument("--params-dir", type=Path, default=DEFAULT_PARAMS_DIR)
    parser.add_argument("--assets-dir", type=Path, default=DEFAULT_ASSETS_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    result = analyze_gaps(args.gemini_dir, args.params_dir, args.assets_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Analyzed {result['total_analyses']} Gemini files.")
    print(f"Top element gaps:")
    for gap in result["gaps"][:8]:
        print(f"  {gap['category']:20s}: {gap['problem_count']:3d} problems ({gap['pct_of_buildings']}%) "
              f"[{gap['asset_status']}]")


if __name__ == "__main__":
    main()
