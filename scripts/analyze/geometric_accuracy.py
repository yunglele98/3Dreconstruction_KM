#!/usr/bin/env python3
"""Geometric accuracy analysis for parametric building models.

Compares parametric model dimensions against LiDAR heights, lot widths,
lot depths, and expected floor counts.  Scores each building as
accurate (<5% error), moderate (5-15%), or poor (>15%).

Usage:
    python scripts/analyze/geometric_accuracy.py
    python scripts/analyze/geometric_accuracy.py --params params/ --output outputs/geometric_analysis/
"""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

FT_TO_M = 0.3048

# Expected floor counts by typology keyword
TYPOLOGY_FLOOR_HINTS: dict[str, int] = {
    "ontario cottage": 1,
    "cottage": 1,
    "bungalow": 1,
    "house-form": 2,
    "semi-detached": 2,
    "bay-and-gable": 2,
    "row": 2,
    "townhouse": 3,
    "institutional": 3,
    "commercial": 2,
    "mixed-use": 3,
}


def _load_params(params_dir: Path) -> list[dict]:
    """Load all active (non-skipped, non-metadata) param files."""
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


def _pct_error(measured: float, reference: float) -> float:
    if reference == 0:
        return 0.0
    return abs(measured - reference) / reference * 100.0


def _tier(pct: float) -> str:
    if pct < 5:
        return "accurate"
    if pct < 15:
        return "moderate"
    return "poor"


def _expected_floors_from_typology(params: dict) -> int | None:
    typology = (params.get("hcd_data") or {}).get("typology", "")
    if not typology:
        return None
    lower = typology.lower()
    for key, floors in TYPOLOGY_FLOOR_HINTS.items():
        if key in lower:
            return floors
    return None


def _window_count_consistency(params: dict) -> dict | None:
    """Compare windows_per_floor array vs windows_detail per-floor counts."""
    wpf = params.get("windows_per_floor")
    wd = params.get("windows_detail")
    if not wpf or not wd:
        return None

    mismatches = []
    for i, detail in enumerate(wd):
        floor_label = detail.get("floor", f"Floor {i}")
        detail_count = sum(w.get("count", 0) for w in detail.get("windows", []))
        if i < len(wpf):
            declared = wpf[i]
            if declared != detail_count:
                mismatches.append({
                    "floor": floor_label,
                    "windows_per_floor": declared,
                    "windows_detail_count": detail_count,
                })
    return {
        "consistent": len(mismatches) == 0,
        "mismatches": mismatches,
    }


def analyze_building(params: dict) -> dict:
    addr = _address(params)
    city = params.get("city_data") or {}
    hcd = params.get("hcd_data") or {}
    result: dict = {"address": addr}
    comparisons: list[dict] = []
    errors: list[float] = []

    # --- Height ---
    total_h = params.get("total_height_m")
    lidar_max = city.get("height_max_m")
    lidar_avg = city.get("height_avg_m")

    if total_h and lidar_max:
        pct = _pct_error(total_h, lidar_max)
        comparisons.append({
            "metric": "height_vs_lidar_max",
            "model": total_h,
            "reference": lidar_max,
            "abs_error_m": round(abs(total_h - lidar_max), 2),
            "pct_error": round(pct, 1),
            "tier": _tier(pct),
        })
        errors.append(pct)

    if total_h and lidar_avg:
        pct = _pct_error(total_h, lidar_avg)
        comparisons.append({
            "metric": "height_vs_lidar_avg",
            "model": total_h,
            "reference": lidar_avg,
            "abs_error_m": round(abs(total_h - lidar_avg), 2),
            "pct_error": round(pct, 1),
            "tier": _tier(pct),
        })
        errors.append(pct)

    # --- Width ---
    facade_w = params.get("facade_width_m")
    lot_w_ft = city.get("lot_width_ft")
    if facade_w and lot_w_ft:
        lot_w_m = lot_w_ft * FT_TO_M
        pct = _pct_error(facade_w, lot_w_m)
        comparisons.append({
            "metric": "width_vs_lot_width",
            "model": facade_w,
            "reference": round(lot_w_m, 2),
            "abs_error_m": round(abs(facade_w - lot_w_m), 2),
            "pct_error": round(pct, 1),
            "tier": _tier(pct),
        })
        errors.append(pct)

    # --- Depth ---
    facade_d = params.get("facade_depth_m")
    lot_d_ft = city.get("lot_depth_ft")
    if facade_d and lot_d_ft:
        lot_d_m = lot_d_ft * FT_TO_M
        pct = _pct_error(facade_d, lot_d_m)
        comparisons.append({
            "metric": "depth_vs_lot_depth",
            "model": facade_d,
            "reference": round(lot_d_m, 2),
            "abs_error_m": round(abs(facade_d - lot_d_m), 2),
            "pct_error": round(pct, 1),
            "tier": _tier(pct),
        })
        errors.append(pct)

    # --- Floor count ---
    floors = params.get("floors")
    expected_floors = _expected_floors_from_typology(params)
    if floors and expected_floors:
        matches = floors == expected_floors
        comparisons.append({
            "metric": "floors_vs_typology",
            "model": floors,
            "reference": expected_floors,
            "abs_error": abs(floors - expected_floors),
            "matches": matches,
            "tier": "accurate" if matches else ("moderate" if abs(floors - expected_floors) == 1 else "poor"),
        })
        if not matches:
            floor_pct = abs(floors - expected_floors) / expected_floors * 100
            errors.append(floor_pct)

    # --- Window consistency ---
    win_check = _window_count_consistency(params)
    if win_check is not None:
        result["window_consistency"] = win_check

    # --- Overall ---
    result["comparisons"] = comparisons
    if errors:
        avg_err = sum(errors) / len(errors)
        result["avg_pct_error"] = round(avg_err, 1)
        result["overall_tier"] = _tier(avg_err)
    else:
        result["avg_pct_error"] = None
        result["overall_tier"] = "no_data"
    result["metrics_available"] = len(comparisons)

    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Geometric accuracy analysis for parametric models")
    parser.add_argument("--params", type=Path, default=REPO_ROOT / "params")
    parser.add_argument("--output", type=Path, default=REPO_ROOT / "outputs" / "geometric_analysis")
    parser.add_argument("--limit", type=int, default=0, help="Limit number of buildings (0 = all)")
    args = parser.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)

    print(f"Loading params from {args.params} ...")
    buildings = _load_params(args.params)
    print(f"  {len(buildings)} active buildings")

    results: list[dict] = []
    for i, params in enumerate(buildings):
        if args.limit and i >= args.limit:
            break
        result = analyze_building(params)
        results.append(result)

    # Aggregate
    errors_all = [r["avg_pct_error"] for r in results if r["avg_pct_error"] is not None]
    tier_counts = defaultdict(int)
    for r in results:
        tier_counts[r["overall_tier"]] += 1

    per_metric: dict[str, list[float]] = defaultdict(list)
    for r in results:
        for c in r.get("comparisons", []):
            if "pct_error" in c:
                per_metric[c["metric"]].append(c["pct_error"])

    metric_stats = {}
    for metric, vals in per_metric.items():
        arr = np.array(vals)
        metric_stats[metric] = {
            "count": len(vals),
            "mean_pct_error": round(float(arr.mean()), 1),
            "median_pct_error": round(float(np.median(arr)), 1),
            "std_pct_error": round(float(arr.std()), 1),
            "max_pct_error": round(float(arr.max()), 1),
        }

    worst = sorted(
        [{"address": r["address"], "avg_pct_error": r["avg_pct_error"], "tier": r["overall_tier"]}
         for r in results if r["avg_pct_error"] is not None],
        key=lambda x: -x["avg_pct_error"],
    )[:20]

    summary = {
        "total_analyzed": len(results),
        "with_comparison_data": len(errors_all),
        "avg_pct_error": round(sum(errors_all) / len(errors_all), 1) if errors_all else None,
        "median_pct_error": round(float(np.median(errors_all)), 1) if errors_all else None,
        "tier_distribution": dict(tier_counts),
        "per_metric_stats": metric_stats,
        "worst_offenders_top20": worst,
    }

    report = {"summary": summary, "buildings": results}
    out_path = args.output / "geometric_accuracy_report.json"
    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nReport written to {out_path}")
    print(f"  Analyzed: {len(results)} | With data: {len(errors_all)}")
    if errors_all:
        print(f"  Avg error: {summary['avg_pct_error']}% | Tiers: {dict(tier_counts)}")


if __name__ == "__main__":
    main()
