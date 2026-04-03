"""Fusion: combine Layer 1-4 results into composite score and pipeline routing."""

import json
import sys
from pathlib import Path

import numpy as np


def compute_fused_score(l1, l2, l3, l4):
    """Weighted composite score from all layers. 0=perfect, 100=completely wrong."""

    # Layer 1: pixel metrics (15%)
    pixel = 0.0
    if l1:
        pixel += (1 - max(l1.get("ssim", 0), 0)) * 5
        pixel += min(l1.get("lab_distance", 0) / 50 * 5, 5)
        pixel += (1 - max(l1.get("edge_similarity", 0), 0)) * 3
        pixel += min((l1.get("aspect_ratio_diff") or 0) / 0.5 * 2, 2)
    pixel = min(pixel, 15)

    # Layer 2: structural (25%)
    structural = 0.0
    if l2:
        # Per-floor: worst floor matters most
        floor_ssims = [f["ssim"] for f in l2.get("per_floor", []) if "ssim" in f]
        if floor_ssims:
            structural += (1 - min(floor_ssims)) * 8

        # Roof silhouette
        roof_d = l2.get("roof_silhouette", {}).get("hausdorff_distance")
        if roof_d is not None:
            structural += min(roof_d * 5, 5)

        # Window grid difference
        wg = l2.get("window_grid", {})
        structural += min(abs(wg.get("total_count_diff", 0)) * 1.5, 6)

        # Colour sample distances
        cs = l2.get("colour_samples", {})
        dists = [v.get("lab_distance", 0) for v in cs.values() if isinstance(v, dict)]
        if dists:
            structural += min(np.mean(dists) / 40 * 6, 6)
    structural = min(structural, 25)

    # Layer 3: semantic (25%)
    semantic = 0.0
    if l3:
        high_weight = ["window", "door", "storefront"]
        med_weight = ["chimney", "bay_window", "porch", "dormer", "awning"]
        for cls, data in l3.items():
            if not isinstance(data, dict):
                continue
            diff = abs(data.get("difference", 0))
            if cls in high_weight:
                semantic += min(diff * 3, 9)
            elif cls in med_weight:
                semantic += min(diff * 2, 6)
            else:
                semantic += min(diff * 1, 3)
    semantic = min(semantic, 25)

    # Layer 4: AI analysis (35%)
    ai = 0.0
    if l4 and "categories" in l4:
        weights = {
            "facade_material": 5, "facade_colour": 4, "windows": 5,
            "roof": 3, "ground_floor": 5, "decorative_elements": 4,
            "proportions": 5, "overall_impression": 4,
        }
        for cat, weight in weights.items():
            cat_data = l4.get("categories", {}).get(cat, {})
            score_10 = cat_data.get("score", 5)
            ai += (10 - score_10) / 10 * weight
    ai = min(ai, 35)

    total = pixel + structural + semantic + ai

    return {
        "gap_score": round(min(total, 100), 1),
        "components": {
            "pixel": round(pixel, 1),
            "structural": round(structural, 1),
            "semantic": round(semantic, 1),
            "ai": round(ai, 1),
        },
    }


def extract_issues(l1, l2, l3, l4):
    """Extract all identified issues from all layers."""
    issues = []

    # Layer 2 issues
    if l2:
        for floor in l2.get("per_floor", []):
            if floor.get("ssim", 1) < 0.15:
                issues.append({
                    "source": "structural", "severity": "high",
                    "type": f"floor_{floor['floor']}_mismatch",
                    "description": f"{floor.get('floor_name', 'Floor')} very low match (SSIM {floor['ssim']:.2f})",
                })

        wg = l2.get("window_grid", {})
        diff = abs(wg.get("total_count_diff", 0))
        if diff >= 2:
            issues.append({
                "source": "structural", "severity": "medium" if diff < 4 else "high",
                "type": "window_count_mismatch",
                "description": f"Window count: render {wg.get('render_windows', {}).get('total', '?')}, "
                              f"photo {wg.get('photo_windows', {}).get('total', '?')}",
            })

        cs = l2.get("colour_samples", {})
        facade_dist = cs.get("facade_center", {}).get("lab_distance", 0)
        if facade_dist > 30:
            issues.append({
                "source": "structural", "severity": "medium",
                "type": "facade_colour_mismatch",
                "description": f"Facade colour LAB distance: {facade_dist:.0f} "
                              f"(render: {cs.get('facade_center', {}).get('render_hex', '?')}, "
                              f"photo: {cs.get('facade_center', {}).get('photo_hex', '?')})",
            })

    # Layer 3 issues
    if l3:
        for cls, data in l3.items():
            if not isinstance(data, dict):
                continue
            if data.get("status") == "missing_in_render" and data.get("difference", 0) >= 1:
                issues.append({
                    "source": "semantic",
                    "severity": "high" if cls in ("window", "door", "storefront") else "medium",
                    "type": f"missing_{cls}",
                    "description": f"Photo has {data['photo_count']} {cls}, render has {data['render_count']}",
                })

    # Layer 4 issues
    if l4 and "categories" in l4:
        for cat, data in l4.get("categories", {}).items():
            if not isinstance(data, dict):
                continue
            score = data.get("score", 10)
            if score <= 4:
                issues.append({
                    "source": "ai",
                    "severity": "high" if score <= 2 else "medium",
                    "type": f"ai_{cat}",
                    "description": data.get("notes", ""),
                    "fix": data.get("fix"),
                })

        biggest = l4.get("biggest_issue")
        if biggest:
            issues.insert(0, {
                "source": "ai", "severity": "high",
                "type": "ai_biggest_issue",
                "description": biggest,
            })

    if not issues:
        issues.append({"source": "none", "severity": "none", "type": "acceptable",
                       "description": "Within acceptable tolerance"})

    return issues


def route_to_pipeline(gap_score, issues, l4, params):
    """Map building to V7 pipeline stages."""
    stages = set()

    if l4 and l4.get("colmap_recommendation"):
        photos = len(params.get("matched_photos", []))
        if photos >= 3:
            stages.update(["2b_photogrammetry", "2d_block_clip", "2e_element_extraction"])

    for issue in issues:
        t = issue.get("type", "")
        if "colour" in t or "material" in t:
            stages.add("3b_fuse_depth")
        if "window" in t or "door" in t:
            stages.update(["1b_segmentation", "3b_fuse_segmentation"])
        if any(e in t for e in ["cornice", "bracket", "bargeboard", "string", "decorative"]):
            stages.add("2e_element_extraction")
        if "storefront" in t:
            stages.add("3c_storefront_enrichment")
        if "roof" in t:
            stages.add("1b_segmentation")
        if "proportion" in t:
            stages.add("3b_fuse_depth")

    if gap_score >= 70:
        stages.update(["1b_segmentation", "3b_fuse_depth", "3b_fuse_segmentation"])
    elif gap_score >= 40:
        stages.add("3b_fuse_depth")

    return sorted(stages) if stages else ["skip"]


def run_fusion(l1_path, l2_path, l3_path, l4_dir, params_dir, output_dir):
    """Fuse all layer results into final audit report."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    params_dir = Path(params_dir)

    # Load Layer 1
    l1_data = json.loads(Path(l1_path).read_text(encoding="utf-8"))
    l1_buildings = {b["address"]: b for b in l1_data.get("buildings", [])}

    # Load Layer 2
    l2_data = {}
    if Path(l2_path).exists():
        l2_data = json.loads(Path(l2_path).read_text(encoding="utf-8"))

    # Load Layer 3
    l3_data = {}
    if Path(l3_path).exists():
        l3_data = json.loads(Path(l3_path).read_text(encoding="utf-8"))

    # Load Layer 4 (per-building JSONs)
    l4_dir = Path(l4_dir)
    l4_data = {}
    if l4_dir.exists():
        for f in l4_dir.glob("*.json"):
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
                addr = d.get("address", f.stem.replace("_", " "))
                l4_data[addr] = d
            except Exception:
                pass

    print(f"Fusion inputs: L1={len(l1_buildings)}, L2={len(l2_data)}, "
          f"L3={len(l3_data)}, L4={len(l4_data)}")

    # Fuse per building
    fused = []
    for address, l1 in l1_buildings.items():
        if l1.get("match_status") != "matched":
            fused.append({**l1, "fused_score": None, "tier": "no_photo"})
            continue

        l2 = l2_data.get(address, {})
        l3 = l3_data.get(address, {})
        l4 = l4_data.get(address, {})

        # Load params
        safe = address.replace(" ", "_")
        param_path = params_dir / f"{safe}.json"
        params = {}
        if param_path.exists():
            try:
                params = json.loads(param_path.read_text(encoding="utf-8"))
            except Exception:
                pass

        score_data = compute_fused_score(l1.get("metrics", {}), l2, l3, l4)
        issues = extract_issues(l1.get("metrics", {}), l2, l3, l4)
        routing = route_to_pipeline(score_data["gap_score"], issues, l4, params)

        fused.append({
            **l1,
            "fused_score": score_data["gap_score"],
            "score_components": score_data["components"],
            "issues": issues,
            "primary_issue": issues[0] if issues else None,
            "pipeline_routing": routing,
            "ai_overall_score": l4.get("overall_score"),
            "ai_biggest_issue": l4.get("biggest_issue"),
            "colmap_recommended": l4.get("colmap_recommendation", False),
            "has_layer2": bool(l2),
            "has_layer3": bool(l3),
            "has_layer4": bool(l4),
        })

    # Sort by fused score descending
    scored = [f for f in fused if f.get("fused_score") is not None]
    scored.sort(key=lambda f: f["fused_score"], reverse=True)
    unscored = [f for f in fused if f.get("fused_score") is None]

    # Percentile tiers
    if scored:
        all_scores = [f["fused_score"] for f in scored]
        p20, p40, p60, p80 = [float(np.percentile(all_scores, p)) for p in (20, 40, 60, 80)]
        for f in scored:
            g = f["fused_score"]
            f["tier"] = ("critical" if g >= p80 else "high" if g >= p60 else
                         "medium" if g >= p40 else "low" if g >= p20 else "acceptable")

    # Stats
    tier_counts = {}
    for f in scored + unscored:
        tier_counts[f.get("tier", "unknown")] = tier_counts.get(f.get("tier", "unknown"), 0) + 1

    # Pipeline stage demand
    stage_counts = {}
    for f in scored:
        for stage in f.get("pipeline_routing", []):
            stage_counts[stage] = stage_counts.get(stage, 0) + 1

    summary = {
        "total": len(fused),
        "scored": len(scored),
        "layers_available": {
            "layer1": len(l1_buildings),
            "layer2": len(l2_data),
            "layer3": len(l3_data),
            "layer4": len(l4_data),
        },
        "avg_fused_score": round(np.mean([f["fused_score"] for f in scored]), 1) if scored else 0,
        "tier_counts": tier_counts,
        "pipeline_stage_demand": dict(sorted(stage_counts.items(), key=lambda x: x[1], reverse=True)),
        "colmap_recommended": len([f for f in scored if f.get("colmap_recommended")]),
    }

    # Write outputs
    report = {"summary": summary, "buildings": scored + unscored}
    (output_dir / "audit_report_merged.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    (output_dir / "priority_queue.json").write_text(
        json.dumps(scored, indent=2, ensure_ascii=False), encoding="utf-8")
    (output_dir / "fusion_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\nFusion complete:")
    print(f"  Avg fused score: {summary['avg_fused_score']}")
    for tier in ["critical", "high", "medium", "low", "acceptable", "no_photo"]:
        print(f"  {tier:12s}: {tier_counts.get(tier, 0)}")
    print(f"\nPipeline demand:")
    for stage, count in list(summary["pipeline_stage_demand"].items())[:8]:
        print(f"  {stage:30s}: {count} buildings")
    print(f"COLMAP recommended: {summary['colmap_recommended']}")


if __name__ == "__main__":
    run_fusion(
        l1_path="outputs/visual_audit/audit_report.json",
        l2_path="outputs/visual_audit/layer2_results.json",
        l3_path="outputs/visual_audit/layer3_results.json",
        l4_dir="outputs/visual_audit/gemini_analysis",
        params_dir="params",
        output_dir="outputs/visual_audit",
    )
