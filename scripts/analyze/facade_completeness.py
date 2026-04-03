#!/usr/bin/env python3
"""Facade completeness scoring for photorealistic generation readiness.

Scores each building (0-100) on how complete its parameter set is for
producing a photorealistic 3D model.  Outputs per-building scores,
histogram, per-street averages, and a bottom-20 priority list.

Usage:
    python scripts/analyze/facade_completeness.py
    python scripts/analyze/facade_completeness.py --params params/ --output outputs/facade_completeness/
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


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
    # Heuristic: everything after the first number token
    for i, p in enumerate(parts):
        if p.isdigit() and i < len(parts) - 1:
            return " ".join(parts[i + 1:])
    return addr


# ---------------------------------------------------------------------------
# Scoring rubric
# ---------------------------------------------------------------------------

def _score_facade_material(params: dict) -> tuple[float, list[str]]:
    """10 pts: has facade_material + hex colour."""
    pts = 0.0
    detail = []
    if params.get("facade_material"):
        pts += 4.0
    else:
        detail.append("missing facade_material")

    facade_detail = params.get("facade_detail") or {}
    colour_palette = params.get("colour_palette") or {}
    has_hex = bool(
        facade_detail.get("brick_colour_hex")
        or params.get("facade_colour")
        or colour_palette.get("facade")
    )
    if has_hex:
        pts += 4.0
    else:
        detail.append("missing facade colour hex")

    if facade_detail.get("bond_pattern"):
        pts += 1.0
    if facade_detail.get("mortar_colour"):
        pts += 1.0

    return min(10.0, pts), detail


def _score_windows(params: dict) -> tuple[float, list[str]]:
    """15 pts: per-floor counts, types, dimensions, frame colour."""
    pts = 0.0
    detail = []
    wd = params.get("windows_detail")
    wpf = params.get("windows_per_floor")

    if wd and len(wd) > 0:
        pts += 5.0
        # Check quality of detail
        has_types = any(
            w.get("type") for floor in wd for w in floor.get("windows", [])
        )
        has_dims = any(
            w.get("width_m") and w.get("height_m")
            for floor in wd
            for w in floor.get("windows", [])
        )
        has_frame = any(
            w.get("frame_colour")
            for floor in wd
            for w in floor.get("windows", [])
        )
        if has_types:
            pts += 3.0
        else:
            detail.append("windows_detail missing types")
        if has_dims:
            pts += 4.0
        else:
            detail.append("windows_detail missing dimensions")
        if has_frame:
            pts += 3.0
        else:
            detail.append("windows_detail missing frame_colour")
    elif wpf:
        pts += 3.0
        detail.append("has windows_per_floor but no windows_detail")
    else:
        detail.append("missing windows data entirely")

    return min(15.0, pts), detail


def _score_doors(params: dict) -> tuple[float, list[str]]:
    """10 pts: count, type, position, transom."""
    pts = 0.0
    detail = []
    dd = params.get("doors_detail")
    dc = params.get("door_count")

    if dd and len(dd) > 0:
        pts += 4.0
        has_type = any(d.get("type") for d in dd)
        has_pos = any(d.get("position") for d in dd)
        has_transom = any(d.get("transom") for d in dd)
        if has_type:
            pts += 2.0
        else:
            detail.append("doors_detail missing type")
        if has_pos:
            pts += 2.0
        else:
            detail.append("doors_detail missing position")
        if has_transom:
            pts += 2.0
    elif dc:
        pts += 2.0
        detail.append("has door_count but no doors_detail")
    else:
        detail.append("missing door data")

    return min(10.0, pts), detail


def _score_roof(params: dict) -> tuple[float, list[str]]:
    """10 pts: type, pitch, colour, eave overhang."""
    pts = 0.0
    detail = []

    if params.get("roof_type"):
        pts += 3.0
    else:
        detail.append("missing roof_type")

    if params.get("roof_pitch_deg"):
        pts += 2.0

    if params.get("roof_colour") or (params.get("colour_palette") or {}).get("roof"):
        pts += 2.0
    else:
        detail.append("missing roof colour")

    rd = params.get("roof_detail") or {}
    if rd.get("eave_overhang_mm"):
        pts += 1.5

    if rd.get("gable_window", {}).get("present"):
        pts += 1.5

    return min(10.0, pts), detail


def _score_decorative(params: dict) -> tuple[float, list[str]]:
    """15 pts: string courses, quoins, cornice, voussoirs, bargeboard, etc."""
    de = params.get("decorative_elements") or {}
    detail = []
    pts = 0.0

    elements = [
        "string_courses", "quoins", "cornice", "stone_voussoirs",
        "stone_lintels", "bargeboard", "decorative_brickwork",
        "ornamental_shingles", "gable_brackets",
    ]
    present_count = 0
    for elem in elements:
        entry = de.get(elem)
        if isinstance(entry, dict) and entry.get("present"):
            present_count += 1
            # Bonus for having colour/dimensions
            if entry.get("colour_hex"):
                pts += 0.5
            if entry.get("projection_mm") or entry.get("width_mm") or entry.get("height_mm"):
                pts += 0.5

    if present_count == 0 and not de:
        detail.append("no decorative_elements section")
    pts += present_count * 1.0

    return min(15.0, pts), detail


def _score_storefront(params: dict) -> tuple[float, list[str]]:
    """10 pts (only if has_storefront)."""
    if not params.get("has_storefront"):
        return 10.0, []  # N/A — full marks

    pts = 0.0
    detail = []
    sf = params.get("storefront") or {}

    if sf.get("type"):
        pts += 2.5
    else:
        detail.append("storefront missing type")
    if sf.get("width_m"):
        pts += 2.5
    else:
        detail.append("storefront missing width_m")
    if sf.get("entrance"):
        pts += 2.5
    else:
        detail.append("storefront missing entrance")
    if sf.get("entrance", {}).get("awning") if isinstance(sf.get("entrance"), dict) else False:
        pts += 2.5

    return min(10.0, pts), detail


def _score_colour_palette(params: dict) -> tuple[float, list[str]]:
    """10 pts: facade, trim, roof, accent all specified."""
    cp = params.get("colour_palette") or {}
    detail = []
    pts = 0.0
    for key in ("facade", "trim", "roof", "accent"):
        if cp.get(key):
            pts += 2.5
        else:
            detail.append(f"colour_palette missing {key}")
    return min(10.0, pts), detail


def _score_photo_observations(params: dict) -> tuple[float, list[str]]:
    """10 pts: has photo_observations or deep_facade_analysis."""
    pts = 0.0
    detail = []
    if params.get("deep_facade_analysis"):
        pts += 10.0
    elif params.get("photo_observations"):
        pts += 6.0
        detail.append("has photo_observations but no deep_facade_analysis")
    else:
        detail.append("no photo analysis data")
    return min(10.0, pts), detail


def _score_hcd(params: dict) -> tuple[float, list[str]]:
    """10 pts: typology, construction_date, contributing, features."""
    hcd = params.get("hcd_data") or {}
    pts = 0.0
    detail = []

    if hcd.get("typology"):
        pts += 3.0
    else:
        detail.append("hcd missing typology")
    if hcd.get("construction_date"):
        pts += 3.0
    else:
        detail.append("hcd missing construction_date")
    if hcd.get("contributing"):
        pts += 2.0
    if hcd.get("building_features") and len(hcd["building_features"]) > 0:
        pts += 2.0
    else:
        detail.append("hcd missing building_features")

    return min(10.0, pts), detail


SCORERS = [
    ("facade_material_colour", _score_facade_material),
    ("windows_detail", _score_windows),
    ("doors_detail", _score_doors),
    ("roof_detail", _score_roof),
    ("decorative_elements", _score_decorative),
    ("storefront", _score_storefront),
    ("colour_palette", _score_colour_palette),
    ("photo_observations", _score_photo_observations),
    ("hcd_data", _score_hcd),
]


def score_building(params: dict) -> dict:
    addr = _address(params)
    street = _street(params)
    breakdown: dict[str, dict] = {}
    total = 0.0

    for name, scorer in SCORERS:
        pts, gaps = scorer(params)
        breakdown[name] = {"score": round(pts, 1), "gaps": gaps}
        total += pts

    return {
        "address": addr,
        "street": street,
        "total_score": round(total, 1),
        "breakdown": breakdown,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Facade completeness scoring")
    parser.add_argument("--params", type=Path, default=REPO_ROOT / "params")
    parser.add_argument("--output", type=Path, default=REPO_ROOT / "outputs" / "facade_completeness")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)

    print(f"Loading params from {args.params} ...")
    buildings = _load_params(args.params)
    print(f"  {len(buildings)} active buildings")

    results = []
    for i, params in enumerate(buildings):
        if args.limit and i >= args.limit:
            break
        results.append(score_building(params))

    scores = [r["total_score"] for r in results]
    arr = np.array(scores) if scores else np.array([0.0])

    # Per-street averages
    street_scores: dict[str, list[float]] = defaultdict(list)
    for r in results:
        street_scores[r["street"]].append(r["total_score"])
    street_avgs = {
        s: round(sum(v) / len(v), 1)
        for s, v in sorted(street_scores.items())
    }

    # Bottom 20 for priority enrichment
    bottom20 = sorted(results, key=lambda r: r["total_score"])[:20]
    bottom20_brief = [{"address": r["address"], "score": r["total_score"]} for r in bottom20]

    # Category averages
    cat_totals: dict[str, list[float]] = defaultdict(list)
    for r in results:
        for cat, info in r["breakdown"].items():
            cat_totals[cat].append(info["score"])
    cat_avgs = {
        cat: round(sum(v) / len(v), 1) for cat, v in cat_totals.items()
    }

    summary = {
        "total_buildings": len(results),
        "avg_score": round(float(arr.mean()), 1),
        "median_score": round(float(np.median(arr)), 1),
        "min_score": round(float(arr.min()), 1),
        "max_score": round(float(arr.max()), 1),
        "std_dev": round(float(arr.std()), 1),
        "score_histogram": {
            "0-20": int(np.sum(arr < 20)),
            "20-40": int(np.sum((arr >= 20) & (arr < 40))),
            "40-60": int(np.sum((arr >= 40) & (arr < 60))),
            "60-80": int(np.sum((arr >= 60) & (arr < 80))),
            "80-100": int(np.sum(arr >= 80)),
        },
        "category_averages": cat_avgs,
        "per_street_averages": street_avgs,
        "bottom_20_priority": bottom20_brief,
    }

    report = {"summary": summary, "buildings": results}
    out_path = args.output / "facade_completeness_report.json"
    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\nReport written to {out_path}")
    print(f"  Buildings: {len(results)} | Avg: {summary['avg_score']} | Median: {summary['median_score']}")
    print(f"  Score range: {summary['min_score']} - {summary['max_score']}")
    print(f"  Category averages:")
    for cat, avg in cat_avgs.items():
        print(f"    {cat}: {avg}")


if __name__ == "__main__":
    main()
