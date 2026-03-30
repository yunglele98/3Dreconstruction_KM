#!/usr/bin/env python3
"""
Enrich gable_window entries and heritage_expression descriptions.

Part A: Fill roof_detail.gable_window for gable/cross-gable buildings
Part B: Generate facade_detail.heritage_expression from decorative elements

Dry-run by default; pass --apply to write changes.
"""
import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PARAMS_DIR = ROOT / "params"

GABLE_KEYWORDS = ["gable window", "attic window", "half-storey", "projecting gable"]

# Map decorative_elements keys to readable names
FEATURE_NAMES = {
    "stone_voussoirs": "stone voussoirs over window openings",
    "gable_brackets": "decorative brackets",
    "ornamental_shingles": "ornamental shingles in the gable",
    "string_courses": "continuous string courses",
    "cornice": "projecting cornice",
    "decorative_brickwork": "decorative brickwork",
    "bargeboard": "carved bargeboard",
    "quoins": "stone quoins",
}


def has_gable_keyword(params: dict) -> bool:
    """Check if HCD statement mentions gable window keywords."""
    hcd = params.get("hcd_data", {})
    statement = (hcd.get("statement_of_contribution") or "").lower()
    features = hcd.get("building_features", [])
    features_text = " ".join(features).lower() if isinstance(features, list) else str(features).lower()
    combined = statement + " " + features_text

    return any(kw in combined for kw in GABLE_KEYWORDS)


def has_half_storey_in_dfa(params: dict) -> bool:
    dfa = params.get("deep_facade_analysis", {})
    return bool(dfa.get("has_half_storey_gable"))


def enrich_gable_window(params: dict) -> list:
    """Fill roof_detail.gable_window for gable buildings."""
    changes = []
    roof_type = (params.get("roof_type") or "").lower()

    if roof_type not in ("gable", "cross-gable"):
        return changes

    floors = params.get("floors", 1)
    if floors < 2:
        return changes

    roof_detail = params.setdefault("roof_detail", {})
    gw = roof_detail.get("gable_window")

    # Skip if already set
    if isinstance(gw, dict) and gw.get("present") is not None:
        return changes

    if has_gable_keyword(params) or has_half_storey_in_dfa(params):
        roof_detail["gable_window"] = {
            "present": True,
            "width_m": 0.6,
            "height_m": 0.8,
            "type": "double_hung",
            "arch_type": "flat",
        }
        changes.append("gable_window: present=true (from HCD/DFA)")
    else:
        roof_detail["gable_window"] = {"present": False}
        changes.append("gable_window: present=false (no HCD mention)")

    return changes


def build_feature_list(params: dict) -> list:
    """Build readable feature list from decorative elements."""
    features = []
    dec = params.get("decorative_elements", {})

    for key, readable in FEATURE_NAMES.items():
        val = dec.get(key)
        if isinstance(val, dict) and val.get("present"):
            features.append(readable)

    bay = params.get("bay_window", {})
    if isinstance(bay, dict) and bay.get("present"):
        features.append("bay window")

    if params.get("has_storefront"):
        features.append("ground-floor storefront")

    return features


def enrich_heritage_expression(params: dict) -> list:
    """Generate facade_detail.heritage_expression."""
    changes = []
    facade_detail = params.setdefault("facade_detail", {})

    if facade_detail.get("heritage_expression"):
        return changes

    features = build_feature_list(params)
    if features:
        features_text = ", ".join(features)
        expression = f"Character-defining elements include {features_text}."
    else:
        expression = "Character-defining elements include its original massing and streetscape presence."

    facade_detail["heritage_expression"] = expression
    changes.append("heritage_expression filled")

    # Also fill heritage_summary if missing
    if not facade_detail.get("heritage_summary"):
        hcd = params.get("hcd_data", {})
        date = hcd.get("construction_date", "unknown era")
        typology = hcd.get("typology", "building")
        summary = (
            f"This {typology.lower() if typology else 'building'} dates to the {date} period. "
            f"{expression}"
        )
        facade_detail["heritage_summary"] = summary
        changes.append("heritage_summary filled")

    return changes


def process(apply: bool = False) -> None:
    stats = {"gable_enriched": 0, "heritage_enriched": 0, "skipped": 0, "no_change": 0}
    change_counts = Counter()

    for param_file in sorted(PARAMS_DIR.glob("*.json")):
        if param_file.name.startswith("_") or "backup" in param_file.name:
            continue
        with open(param_file, encoding="utf-8") as f:
            params = json.load(f)
        if params.get("skipped"):
            stats["skipped"] += 1
            continue

        gable_changes = enrich_gable_window(params)
        heritage_changes = enrich_heritage_expression(params)
        all_changes = gable_changes + heritage_changes

        if not all_changes:
            stats["no_change"] += 1
            continue

        if gable_changes:
            stats["gable_enriched"] += 1
        if heritage_changes:
            stats["heritage_enriched"] += 1

        for c in all_changes:
            key = c.split(":")[0].strip() if ":" in c else c
            change_counts[key] += 1

        if apply:
            meta = params.setdefault("_meta", {})
            fixes = meta.setdefault("handoff_fixes_applied", [])
            fixes.append({
                "fix": "enrich_roof_and_heritage",
                "changes": all_changes[:10],
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
            with open(param_file, "w", encoding="utf-8") as f:
                json.dump(params, f, indent=2, ensure_ascii=False)
                f.write("\n")

    print(f"Roof & Heritage Enrichment")
    print(f"{'='*50}")
    print(f"Gable windows enriched: {stats['gable_enriched']}, "
          f"Heritage expressions: {stats['heritage_enriched']}, "
          f"No change: {stats['no_change']}, Skipped: {stats['skipped']}")
    print(f"\nChange counts:")
    for ct, count in change_counts.most_common():
        print(f"  {ct}: {count}")


def main():
    parser = argparse.ArgumentParser(description="Enrich gable windows and heritage expressions")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    process(apply=args.apply)


if __name__ == "__main__":
    main()
