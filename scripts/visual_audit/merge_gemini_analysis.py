#!/usr/bin/env python3
"""Merge Gemini per-building analysis into visual-audit report."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REPORT = REPO_ROOT / "outputs" / "visual_audit" / "audit_report.json"
DEFAULT_GEMINI_DIR = REPO_ROOT / "outputs" / "visual_audit" / "gemini_analysis"
DEFAULT_OUTPUT = REPO_ROOT / "outputs" / "visual_audit" / "audit_report_merged.json"
DEFAULT_PRIORITY = REPO_ROOT / "outputs" / "visual_audit" / "priority_queue_merged.json"

TIER_ORDER = ["critical", "high", "medium", "low", "acceptable", "no_photo"]


def _address_slug(address: str) -> str:
    return (
        (address or "")
        .replace(",", "")
        .replace("/", "_")
        .replace("\\", "_")
        .replace(" ", "_")
    )


def _load_gemini_for_address(gemini_dir: Path, address: str) -> dict | None:
    slug = _address_slug(address)
    candidates = [
        gemini_dir / f"{slug}.json",
        gemini_dir / f"{slug.lower()}.json",
    ]
    for candidate in candidates:
        if candidate.exists():
            try:
                return json.loads(candidate.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                return None
    return None


def _coerce_score(value) -> float | None:
    if isinstance(value, (int, float)):
        val = float(value)
        if val > 1.0:
            val = val / 5.0
        return max(0.0, min(1.0, val))
    return None


def _extract_weighted_gap(gemini: dict) -> tuple[float | None, float]:
    # Try direct gap_score first (Gemini vision format)
    direct_gap = gemini.get("gap_score")
    if isinstance(direct_gap, (int, float)):
        # Compute average confidence from categories
        categories = gemini.get("categories", gemini.get("category_ratings", {}))
        if isinstance(categories, dict) and categories:
            confs = [
                float(v.get("confidence", 1.0))
                for v in categories.values()
                if isinstance(v, dict) and isinstance(v.get("confidence"), (int, float))
            ]
            avg_conf = sum(confs) / len(confs) if confs else 0.8
        else:
            avg_conf = 0.8
        return float(direct_gap), round(avg_conf, 3)

    # Fallback: compute from category_ratings (numeric score format)
    ratings = gemini.get("category_ratings", gemini.get("categories", {}))
    if not isinstance(ratings, dict):
        return None, 0.0

    weighted_sum = 0.0
    weight_total = 0.0
    for _, payload in ratings.items():
        score = None
        conf = 1.0
        if isinstance(payload, dict):
            score = _coerce_score(payload.get("score", payload.get("rating")))
            conf_val = payload.get("confidence")
            if isinstance(conf_val, (int, float)):
                conf = max(0.0, min(1.0, float(conf_val)))
        else:
            score = _coerce_score(payload)
        if score is None:
            continue
        weighted_sum += score * conf
        weight_total += conf

    if weight_total <= 0:
        return None, 0.0
    quality = weighted_sum / weight_total
    return round((1.0 - quality) * 100.0, 1), round(weight_total / max(len(ratings), 1), 3)


def _extract_suggestions(gemini: dict) -> list:
    # Direct param_suggestions field
    suggestions = gemini.get("param_suggestions")
    if isinstance(suggestions, list):
        return suggestions
    if isinstance(suggestions, dict):
        return [suggestions]

    # Extract from categories (Gemini vision format)
    categories = gemini.get("categories", {})
    if isinstance(categories, dict):
        collected = []
        for cat_name, cat_data in categories.items():
            if not isinstance(cat_data, dict):
                continue
            ps = cat_data.get("param_suggestion", {})
            if isinstance(ps, dict) and ps:
                conf = float(cat_data.get("confidence", 0.0))
                for field, value in ps.items():
                    collected.append({
                        "path": field,
                        "value": value,
                        "confidence": conf,
                        "category": cat_name,
                    })
        if collected:
            return collected

    # priority_fixes fallback
    fixes = gemini.get("priority_fixes")
    if isinstance(fixes, list):
        return fixes

    return []


def merge_report(report: dict, gemini_dir: Path) -> dict:
    buildings = report.get("buildings")
    if not isinstance(buildings, list):
        return report

    merged = []
    gemini_hits = 0
    for building in buildings:
        if not isinstance(building, dict):
            continue
        address = building.get("address", "")
        gemini = _load_gemini_for_address(gemini_dir, address)
        if not gemini:
            merged.append(building)
            continue

        gemini_hits += 1
        original_gap = float(building.get("gap_score") or 0.0)
        gemini_gap, conf = _extract_weighted_gap(gemini)
        if gemini_gap is None:
            merged_gap = original_gap
        else:
            merged_gap = round((original_gap * 0.6) + (gemini_gap * 0.4), 1)

        merged_building = dict(building)
        merged_building["original_gap_score"] = original_gap
        merged_building["gap_score"] = merged_gap
        merged_building["gemini_confidence"] = conf
        merged_building["gemini_analysis"] = {
            "category_ratings": gemini.get("categories", gemini.get("category_ratings", {})),
            "param_suggestions": _extract_suggestions(gemini),
            "overall_match": gemini.get("overall_match", ""),
            "colmap_candidate": gemini.get("colmap_candidate", False),
            "summary": gemini.get("summary", gemini.get("notes", "")),
        }
        merged.append(merged_building)

    merged.sort(key=lambda x: x.get("gap_score") or -1, reverse=True)

    summary = report.get("summary", {})
    if not isinstance(summary, dict):
        summary = {}

    tier_counts = {}
    for row in merged:
        tier = row.get("tier", "no_photo")
        tier_counts[tier] = tier_counts.get(tier, 0) + 1
    ordered_tiers = {tier: tier_counts.get(tier, 0) for tier in TIER_ORDER if tier in tier_counts}

    new_summary = dict(summary)
    new_summary["gemini_merged"] = gemini_hits
    new_summary["tier_counts"] = ordered_tiers
    scores = [float(r["gap_score"]) for r in merged if r.get("gap_score") is not None]
    if scores:
        new_summary["avg_gap_score"] = round(sum(scores) / len(scores), 1)

    return {"summary": new_summary, "buildings": merged}


def main():
    parser = argparse.ArgumentParser(description="Merge Gemini analysis into audit report.")
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--gemini-dir", type=Path, default=DEFAULT_GEMINI_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--priority-output", type=Path, default=DEFAULT_PRIORITY)
    args = parser.parse_args()

    report = json.loads(args.report.read_text(encoding="utf-8"))
    merged = merge_report(report, args.gemini_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(merged, indent=2, ensure_ascii=False), encoding="utf-8")
    args.priority_output.write_text(
        json.dumps(merged.get("buildings", []), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(
        f"Merged {merged.get('summary', {}).get('gemini_merged', 0)} Gemini analyses "
        f"into {len(merged.get('buildings', []))} buildings."
    )


if __name__ == "__main__":
    main()
