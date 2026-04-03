#!/usr/bin/env python3
"""Master reconstruction pipeline report.

Aggregates all analysis outputs into a single dashboard JSON, gracefully
handling missing analysis files by skipping absent sections.

Usage:
    python scripts/analyze/reconstruction_pipeline_report.py
    python scripts/analyze/reconstruction_pipeline_report.py --output outputs/pipeline_report.json
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
OUTPUTS_DIR = REPO_ROOT / "outputs"
PARAMS_DIR = REPO_ROOT / "params"

# Analysis sources: (key, file_path_relative_to_outputs)
ANALYSIS_SOURCES = [
    ("texture_fidelity", "texture_analysis/texture_fidelity_report.json"),
    ("geometric_accuracy", "geometric_analysis/geometric_accuracy_report.json"),
    ("facade_completeness", "facade_completeness/facade_completeness_report.json"),
    ("splat_readiness", "splat_readiness/splat_readiness_report.json"),
    ("heritage_fidelity", "heritage_analysis/heritage_fidelity_report.json"),
    ("render_quality", "render_quality/render_quality_report.json"),
    ("style_consistency", "style_analysis/style_consistency_report.json"),
    ("photo_coverage", "photo_coverage/photo_coverage_report.json"),
    ("visual_audit", "visual_audit/priority_queue.json"),
]

# COLMAP analysis directory (may contain multiple JSON files)
COLMAP_DIR_KEY = "colmap_analysis"
COLMAP_DIR = "colmap_analysis"


def _load_json(path: Path) -> dict | list | None:
    """Load a JSON file, returning None on failure."""
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _summarize_report(key: str, data: dict | list) -> dict:
    """Extract a compact summary from a loaded analysis report."""
    summary: dict = {}
    if isinstance(data, dict):
        # Copy common top-level scalars
        for field in (
            "generated", "total_renders", "total_buildings", "total_streets_analyzed",
            "avg_quality_score", "avg_consistency_score", "avg_facade_completeness",
            "avg_geometric_accuracy", "avg_heritage_fidelity",
            "splat_ready_count", "total_outliers",
            "min_quality_score", "max_quality_score",
            "tier_distribution",
        ):
            if field in data:
                summary[field] = data[field]
        # For list-type reports, report count
        for list_field in ("renders", "buildings", "streets", "items", "candidates"):
            if list_field in data and isinstance(data[list_field], list):
                summary[f"{list_field}_count"] = len(data[list_field])
    elif isinstance(data, list):
        summary["item_count"] = len(data)
    return summary


def _count_active_buildings() -> tuple[int, int, int]:
    """Count total active buildings and their generation methods from params."""
    total = 0
    photogrammetric = 0
    parametric = 0
    if not PARAMS_DIR.is_dir():
        return total, photogrammetric, parametric
    for jf in PARAMS_DIR.glob("*.json"):
        if jf.name.startswith("_"):
            continue
        try:
            data = json.loads(jf.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if data.get("skipped"):
            continue
        total += 1
        meta = data.get("_meta") or {}
        method = meta.get("generation_method", "parametric")
        if method == "photogrammetric":
            photogrammetric += 1
        else:
            parametric += 1
    return total, photogrammetric, parametric


def _extract_top_priority(analyses: dict, n: int = 20) -> list[dict]:
    """Extract top N priority buildings from available analyses."""
    # Try visual audit priority queue first
    audit = analyses.get("visual_audit")
    if audit and isinstance(audit, list):
        return [
            {"address": item.get("address", "unknown"), "priority_score": item.get("priority_score", item.get("score", 0))}
            for item in audit[:n]
        ]
    if audit and isinstance(audit, dict):
        items = audit.get("buildings") or audit.get("items") or audit.get("queue") or []
        return [
            {"address": item.get("address", "unknown"), "priority_score": item.get("priority_score", item.get("score", 0))}
            for item in items[:n]
        ]

    # Fallback: use render quality worst-scoring buildings
    rq = analyses.get("render_quality")
    if rq and isinstance(rq, dict):
        renders = rq.get("renders") or []
        # Sort ascending by score (worst first)
        worst = sorted(
            [r for r in renders if "overall_score" in r],
            key=lambda r: r["overall_score"],
        )
        return [
            {"address": r.get("file", "unknown").replace(".png", ""), "priority_score": round(1.0 - r["overall_score"], 3)}
            for r in worst[:n]
        ]

    return []


def _safe_mean(values: list[float]) -> float:
    """Compute mean, returning 0.0 for empty lists."""
    return round(float(np.mean(values)), 3) if values else 0.0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Master reconstruction pipeline report"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=OUTPUTS_DIR / "pipeline_report.json",
        help="Output path for the master dashboard JSON",
    )
    args = parser.parse_args()

    output_path: Path = args.output
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Load all analysis sources
    analyses: dict[str, dict | list] = {}
    per_analysis: dict[str, dict] = {}
    loaded = []
    missing = []

    for key, rel_path in ANALYSIS_SOURCES:
        full_path = OUTPUTS_DIR / rel_path
        data = _load_json(full_path)
        if data is not None:
            analyses[key] = data
            per_analysis[key] = _summarize_report(key, data)
            loaded.append(key)
        else:
            missing.append(key)

    # Load COLMAP analysis directory
    colmap_dir = OUTPUTS_DIR / COLMAP_DIR
    colmap_files: list[dict] = []
    if colmap_dir.is_dir():
        for cf in sorted(colmap_dir.glob("*.json")):
            data = _load_json(cf)
            if data is not None:
                colmap_files.append({"file": cf.name, "data": _summarize_report("colmap", data)})
    if colmap_files:
        analyses[COLMAP_DIR_KEY] = colmap_files
        per_analysis[COLMAP_DIR_KEY] = {"files_loaded": len(colmap_files)}
        loaded.append(COLMAP_DIR_KEY)
    else:
        missing.append(COLMAP_DIR_KEY)

    # Count buildings
    total_buildings, photogrammetric, parametric = _count_active_buildings()

    # Extract key metrics from loaded analyses
    avg_facade_completeness = 0.0
    fc = analyses.get("facade_completeness")
    if fc and isinstance(fc, dict):
        avg_facade_completeness = fc.get("avg_facade_completeness", 0.0)

    avg_geometric_accuracy = 0.0
    ga = analyses.get("geometric_accuracy")
    if ga and isinstance(ga, dict):
        avg_geometric_accuracy = ga.get("avg_geometric_accuracy", 0.0)

    splat_ready_count = 0
    sr = analyses.get("splat_readiness")
    if sr and isinstance(sr, dict):
        splat_ready_count = sr.get("splat_ready_count", 0)

    avg_heritage_fidelity = 0.0
    hf = analyses.get("heritage_fidelity")
    if hf and isinstance(hf, dict):
        avg_heritage_fidelity = hf.get("avg_heritage_fidelity", 0.0)

    avg_render_quality = 0.0
    rq = analyses.get("render_quality")
    if rq and isinstance(rq, dict):
        avg_render_quality = rq.get("avg_quality_score", 0.0)

    avg_style_consistency = 0.0
    sc = analyses.get("style_consistency")
    if sc and isinstance(sc, dict):
        avg_style_consistency = sc.get("avg_consistency_score", 0.0)

    top_priority = _extract_top_priority(analyses, n=20)

    report = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "total_buildings": total_buildings,
            "avg_facade_completeness": avg_facade_completeness,
            "avg_geometric_accuracy": avg_geometric_accuracy,
            "avg_render_quality": avg_render_quality,
            "avg_style_consistency": avg_style_consistency,
            "splat_ready_count": splat_ready_count,
            "heritage_fidelity_avg": avg_heritage_fidelity,
            "top_priority_buildings": top_priority,
            "reconstruction_coverage": {
                "photogrammetric": photogrammetric,
                "parametric": parametric,
            },
        },
        "analyses_loaded": loaded,
        "analyses_missing": missing,
        "per_analysis": per_analysis,
    }

    output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Pipeline report written to {output_path}")
    print(f"  Total buildings: {total_buildings} (photogrammetric: {photogrammetric}, parametric: {parametric})")
    print(f"  Analyses loaded: {len(loaded)}/{len(loaded) + len(missing)}")
    if loaded:
        print(f"    Loaded: {', '.join(loaded)}")
    if missing:
        print(f"    Missing: {', '.join(missing)}")
    if top_priority:
        print(f"  Top priority buildings: {len(top_priority)}")


if __name__ == "__main__":
    main()
