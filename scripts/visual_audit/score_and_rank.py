#!/usr/bin/env python3
"""Phase 0, Stages 3-5: Classify discrepancies, score, and rank buildings.

Takes comparison metrics from Stage 2, classifies issue types, computes a
composite gap score (0-100), and builds a tiered priority queue that routes
each building to the V7 pipeline stages it needs.

Usage:
    python scripts/visual_audit/score_and_rank.py --comparisons outputs/visual_audit/comparisons.json
    python scripts/visual_audit/score_and_rank.py --comparisons outputs/visual_audit/comparisons.json --params params/
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).parent.parent.parent
PARAMS_DIR = REPO_ROOT / "params"


# ── Stage 3: Classify ──────────────────────────────────────────────────────

def classify_discrepancies(metrics: dict, params: dict) -> list[dict]:
    """Determine what kind of discrepancy exists based on metrics + params."""
    issues = []

    # Colour issues
    lab_dist = metrics.get("lab_distance", 0)
    if lab_dist > 25:
        facade_mat = (params.get("facade_material") or "").lower()
        if facade_mat == "brick":
            issues.append({
                "type": "wrong_brick_colour",
                "severity": "medium",
                "description": f"Brick colour doesn't match photo (LAB: {lab_dist:.1f})",
                "fix_pipeline": "colour_recalibration",
                "fix_stage": "3b_fusion",
            })
        else:
            issues.append({
                "type": "wrong_paint_colour",
                "severity": "medium",
                "description": f"Facade colour doesn't match photo (LAB: {lab_dist:.1f})",
                "fix_pipeline": "colour_recalibration",
                "fix_stage": "3b_fusion",
            })

    if metrics.get("hist_avg", 1) < 0.4:
        issues.append({
            "type": "wrong_material",
            "severity": "high",
            "description": "Facade material appears completely wrong",
            "fix_pipeline": "param_correction",
            "fix_stage": "3b_fusion",
        })

    # Structural issues
    aspect_diff = metrics.get("aspect_ratio_diff")
    if aspect_diff is not None and aspect_diff > 0.25:
        issues.append({
            "type": "wrong_proportions",
            "severity": "high",
            "description": f"Building proportions mismatch (aspect diff: {aspect_diff:.2f})",
            "fix_pipeline": "param_correction",
            "fix_stage": "3b_fusion",
        })

    win_diff = metrics.get("window_count_diff", 0)
    if win_diff > 3:
        issues.append({
            "type": "wrong_window_count",
            "severity": "medium",
            "description": f"Window count: render {metrics.get('render_window_count', '?')}, photo {metrics.get('photo_window_count', '?')}",
            "fix_pipeline": "segmentation_fusion",
            "fix_stage": "1b_segmentation",
        })

    edge_sim = metrics.get("edge_similarity", 1)
    if edge_sim < 0.1:
        issues.append({
            "type": "missing_features",
            "severity": "high",
            "description": "Major structural features missing (bay window, porch, decorative, etc.)",
            "fix_pipeline": "element_library",
            "fix_stage": "2e_element_extraction",
        })

    # Roof issues
    ssim_val = metrics.get("ssim", 1)
    roof_type = (params.get("roof_type") or "").lower()
    if ssim_val < 0.35 and roof_type in ("gable", "cross-gable", "hip"):
        issues.append({
            "type": "possible_wrong_roof",
            "severity": "medium",
            "description": "Low structural match — roof type may be incorrect",
            "fix_pipeline": "segmentation_fusion",
            "fix_stage": "1b_segmentation",
        })

    # Storefront issues
    has_storefront = params.get("has_storefront", False)
    if has_storefront and edge_sim < 0.15:
        issues.append({
            "type": "storefront_mismatch",
            "severity": "medium",
            "description": "Storefront doesn't match photo",
            "fix_pipeline": "storefront_enrichment",
            "fix_stage": "3c_post_enrichment",
        })

    if not issues:
        issues.append({
            "type": "acceptable",
            "severity": "none",
            "description": "Model matches photo within tolerance",
            "fix_pipeline": None,
            "fix_stage": None,
        })

    return issues


# ── Stage 4: Score ─────────────────────────────────────────────────────────

def compute_gap_score(metrics: dict, issues: list[dict]) -> dict:
    """Composite gap score: 0 = perfect match, 100 = completely wrong."""
    scores = {
        "structural": (1 - metrics.get("ssim", 0)) * 25,
        "colour": min(metrics.get("lab_distance", 0) / 50 * 25, 25),
        "edges": (1 - metrics.get("edge_similarity", 0)) * 20,
        "proportions": min((metrics.get("aspect_ratio_diff") or 0) / 0.5 * 15, 15),
        "windows": min(metrics.get("window_count_diff", 0) / 5 * 10, 10),
        "histogram": (1 - metrics.get("hist_avg", 0)) * 5,
    }

    base_score = sum(scores.values())

    severity_bonus = 0
    for issue in issues:
        if issue["severity"] == "high":
            severity_bonus += 10
        elif issue["severity"] == "medium":
            severity_bonus += 5

    return {
        "gap_score": round(min(base_score + severity_bonus, 100), 1),
        "component_scores": {k: round(v, 2) for k, v in scores.items()},
        "severity_bonus": severity_bonus,
    }


# ── Stage 5: Rank ─────────────────────────────────────────────────────────

FIX_ROUTING = {
    "colour_recalibration": "Stage 3b: fuse_depth + rebuild_colour_palettes",
    "param_correction": "Stage 3b: fuse_segmentation + manual param review",
    "segmentation_fusion": "Stage 1b: segment_facades → Stage 3b: fuse_segmentation",
    "element_library": "Stage 2e: extract_elements → Stage 4: hybrid generator",
    "storefront_enrichment": "Stage 3c: enrich_storefronts_advanced",
    "photogrammetry": "Stage 2b: COLMAP → Stage 2d: clip → Stage 4c: hybrid",
}


def compute_percentile_thresholds(scores: list[float]) -> dict[str, float]:
    """Compute tier thresholds from actual score distribution.

    Uses percentiles so tiers spread across the real data rather than
    hard-coded boundaries that assume a calibrated pipeline.
    """
    import numpy as np
    if not scores:
        return {"acceptable": 0, "low": 25, "medium": 50, "high": 75, "critical": 90}
    return {
        "acceptable": float(np.percentile(scores, 25)),   # bottom 25%
        "low": float(np.percentile(scores, 50)),           # 25-50%
        "medium": float(np.percentile(scores, 75)),        # 50-75%
        "high": float(np.percentile(scores, 90)),          # 75-90%
        "critical": float(np.percentile(scores, 90)),      # top 10%
    }


# Module-level thresholds — set by score_and_rank() from actual data
_TIER_THRESHOLDS: dict[str, float] | None = None


def assign_tier(gap_score: float, match_status: str) -> str:
    if match_status == "no_photo":
        return "no_photo"
    if _TIER_THRESHOLDS:
        if gap_score >= _TIER_THRESHOLDS["high"]:
            return "critical"
        if gap_score >= _TIER_THRESHOLDS["medium"]:
            return "high"
        if gap_score >= _TIER_THRESHOLDS["low"]:
            return "medium"
        if gap_score >= _TIER_THRESHOLDS["acceptable"]:
            return "low"
        return "acceptable"
    # Fallback absolute thresholds
    if gap_score >= 70:
        return "critical"
    if gap_score >= 50:
        return "high"
    if gap_score >= 30:
        return "medium"
    if gap_score >= 15:
        return "low"
    return "acceptable"


def route_building(gap_score: float, issues: list[dict],
                   photo_count: int) -> list[str]:
    """Determine which V7 pipeline stages this building needs."""
    needed = set()

    for issue in issues:
        fs = issue.get("fix_stage")
        if fs:
            needed.add(fs)

    if gap_score >= 70:
        needed.update(["1b_segmentation", "2e_element_extraction",
                        "3b_fusion", "4c_hybrid_generation"])
        if photo_count >= 3:
            needed.add("2b_photogrammetry")
    elif gap_score >= 50:
        needed.update(["1b_segmentation", "3b_fusion"])
        if photo_count >= 3:
            needed.add("2b_photogrammetry")
    elif gap_score >= 30:
        needed.update(["1b_segmentation", "3b_fusion", "3c_post_enrichment"])
    elif gap_score >= 15:
        needed.add("3b_fusion")

    return sorted(needed)


def load_params(address: str, params_dir: Path) -> dict:
    """Load building params for classification context."""
    param_file = params_dir / (address.replace(" ", "_") + ".json")
    if not param_file.exists():
        return {}
    try:
        return json.loads(param_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def score_and_rank(comparisons: list[dict], params_dir: Path) -> dict:
    """Full Stage 3-5: classify, score, rank all buildings."""
    global _TIER_THRESHOLDS

    # First pass: compute all gap scores to calibrate tier thresholds
    raw_scores = []
    for entry in comparisons:
        if entry.get("match_status") == "matched" and entry.get("metrics"):
            m = entry["metrics"]
            params = load_params(entry.get("address", ""), params_dir)
            issues = classify_discrepancies(m, params)
            sr = compute_gap_score(m, issues)
            raw_scores.append(sr["gap_score"])

    if raw_scores:
        _TIER_THRESHOLDS = compute_percentile_thresholds(raw_scores)
        logger.info("  Tier thresholds (from %d scores): acceptable<%.1f, low<%.1f, medium<%.1f, high<%.1f, critical>=%.1f",
                     len(raw_scores),
                     _TIER_THRESHOLDS["acceptable"], _TIER_THRESHOLDS["low"],
                     _TIER_THRESHOLDS["medium"], _TIER_THRESHOLDS["high"],
                     _TIER_THRESHOLDS["high"])

    buildings = []

    for entry in comparisons:
        address = entry.get("address", "")
        match_status = entry.get("match_status", "no_photo")
        metrics = entry.get("metrics")

        if metrics is None or match_status != "matched":
            buildings.append({
                "address": address,
                "gap_score": 0,
                "tier": "no_photo",
                "primary_issue": {"type": "no_photo", "severity": "none"},
                "all_issues": [],
                "metrics": None,
                "needed_stages": [],
                "fix_route": "manual_review",
                "render": entry.get("render"),
                "photo": entry.get("photo"),
                "photo_path": entry.get("photo_path"),
                "photo_count": entry.get("photo_count", 0),
            })
            continue

        params = load_params(address, params_dir)
        issues = classify_discrepancies(metrics, params)
        score_result = compute_gap_score(metrics, issues)
        gap = score_result["gap_score"]
        tier = assign_tier(gap, match_status)
        photo_count = entry.get("photo_count", 0)
        needed_stages = route_building(gap, issues, photo_count)

        primary = issues[0] if issues else {"type": "acceptable", "severity": "none"}
        fix_route = FIX_ROUTING.get(primary.get("fix_pipeline"), "manual_review")

        # Add param context
        hcd = params.get("hcd_data", {})

        buildings.append({
            "address": address,
            "gap_score": gap,
            "tier": tier,
            "component_scores": score_result["component_scores"],
            "severity_bonus": score_result["severity_bonus"],
            "primary_issue": primary,
            "all_issues": issues,
            "metrics": metrics,
            "needed_stages": needed_stages,
            "fix_route": fix_route,
            "render": entry.get("render"),
            "photo": entry.get("photo"),
            "photo_path": entry.get("photo_path"),
            "photo_count": photo_count,
            "hcd_contributing": hcd.get("contributing"),
            "era": hcd.get("construction_date"),
            "typology": hcd.get("typology"),
        })

    # Sort by gap score descending
    buildings.sort(key=lambda b: b["gap_score"], reverse=True)

    # Tier counts
    tier_counts = {}
    for b in buildings:
        tier_counts[b["tier"]] = tier_counts.get(b["tier"], 0) + 1

    # Top issues
    issue_counts = {}
    for b in buildings:
        for issue in b.get("all_issues", []):
            t = issue["type"]
            if t != "acceptable":
                issue_counts[t] = issue_counts.get(t, 0) + 1

    # Pipeline routing summary
    stage_buildings: dict[str, list[str]] = {}
    for b in buildings:
        for stage in b.get("needed_stages", []):
            stage_buildings.setdefault(stage, []).append(b["address"])
    skip_count = sum(1 for b in buildings
                     if b["tier"] == "acceptable" or b["tier"] == "no_photo")

    pipeline_routing = {}
    for stage, addrs in sorted(stage_buildings.items()):
        pipeline_routing[stage] = {
            "building_count": len(addrs),
            "buildings": addrs[:20],  # first 20 for readability
        }
    pipeline_routing["skip"] = {"building_count": skip_count}

    total_compared = sum(1 for b in buildings if b["tier"] != "no_photo")

    return {
        "total_buildings": len(buildings),
        "total_compared": total_compared,
        "total_no_photo": tier_counts.get("no_photo", 0),
        "tier_thresholds": _TIER_THRESHOLDS,
        "tier_counts": tier_counts,
        "top_issues": dict(sorted(issue_counts.items(),
                                   key=lambda x: x[1], reverse=True)),
        "pipeline_routing": pipeline_routing,
        "buildings": buildings,
    }


def main():
    parser = argparse.ArgumentParser(description="Phase 0: Score and rank buildings")
    parser.add_argument("--comparisons", type=Path,
                        default=REPO_ROOT / "outputs" / "visual_audit" / "comparisons.json")
    parser.add_argument("--params", type=Path, default=PARAMS_DIR)
    parser.add_argument("--output", type=Path,
                        default=REPO_ROOT / "outputs" / "visual_audit" / "priority_queue.json")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    comparisons = json.loads(args.comparisons.read_text(encoding="utf-8"))
    logger.info("Loaded %d comparisons", len(comparisons))

    result = score_and_rank(comparisons, args.params)

    logger.info("\n=== Priority Queue ===")
    for tier, count in result["tier_counts"].items():
        logger.info("  %-12s %d", tier, count)
    logger.info("\n=== Top Issues ===")
    for issue, count in list(result["top_issues"].items())[:7]:
        logger.info("  %-25s %d", issue, count)
    logger.info("\n=== Pipeline Routing ===")
    for stage, info in result["pipeline_routing"].items():
        logger.info("  %-30s %d buildings", stage, info["building_count"])

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    logger.info("\nSaved → %s", args.output)


if __name__ == "__main__":
    main()
