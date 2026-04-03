#!/usr/bin/env python3
"""Style consistency analysis across buildings on the same street.

Analyzes visual style consistency including color palette, material, era,
height rhythm, setback, and window pattern similarity.  Identifies outlier
buildings that deviate significantly from their street character.

Usage:
    python scripts/analyze/style_consistency.py
    python scripts/analyze/style_consistency.py --params params/ --output outputs/style_analysis/
"""

from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_PARAMS_DIR = REPO_ROOT / "params"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "outputs" / "style_analysis"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _hex_to_rgb(hex_str: str) -> tuple[int, int, int] | None:
    """Convert '#RRGGBB' to (R, G, B) tuple, or None on failure."""
    if not hex_str or not isinstance(hex_str, str):
        return None
    h = hex_str.lstrip("#")
    if len(h) != 6:
        return None
    try:
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    except ValueError:
        return None


def _color_distance(c1: tuple[int, int, int], c2: tuple[int, int, int]) -> float:
    """Euclidean distance in RGB space."""
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(c1, c2)))


def _get_facade_hex(params: dict) -> str | None:
    """Resolve facade colour hex from params."""
    fd = params.get("facade_detail") or {}
    return (
        fd.get("brick_colour_hex")
        or params.get("facade_colour")
        or (params.get("colour_palette") or {}).get("facade")
    )


def _get_street(params: dict) -> str | None:
    """Extract street name from params."""
    site = params.get("site") or {}
    street = site.get("street") or ""
    if not street:
        meta = params.get("_meta") or {}
        addr = meta.get("address") or params.get("building_name") or ""
        # Try to extract street from address (e.g. "22 Lippincott St")
        parts = addr.split()
        if len(parts) >= 2:
            street = " ".join(parts[1:])
    return street if street else None


def _era_midpoint(date_str: str | None) -> float | None:
    """Extract midpoint year from construction_date like '1904-1913'."""
    if not date_str or not isinstance(date_str, str):
        return None
    parts = date_str.replace("pre-", "").replace("Pre-", "").split("-")
    years = []
    for p in parts:
        p = p.strip()
        try:
            y = int(p)
            if 1700 < y < 2100:
                years.append(y)
        except ValueError:
            pass
    return float(np.mean(years)) if years else None


def _windows_vector(params: dict) -> list[int]:
    """Return windows_per_floor as a list of ints."""
    wpf = params.get("windows_per_floor")
    if isinstance(wpf, list):
        return [int(w) for w in wpf if isinstance(w, (int, float))]
    return []


# ---------------------------------------------------------------------------
# Per-street analysis
# ---------------------------------------------------------------------------

def analyze_street(street_name: str, buildings: list[dict]) -> dict:
    """Compute consistency metrics for all buildings on a street."""
    n = len(buildings)
    if n == 0:
        return {"street": street_name, "building_count": 0}

    # --- Color palette consistency ---
    colors = []
    for b in buildings:
        rgb = _hex_to_rgb(_get_facade_hex(b))
        if rgb:
            colors.append(rgb)
    color_distances = []
    if len(colors) >= 2:
        for i in range(len(colors)):
            for j in range(i + 1, len(colors)):
                color_distances.append(_color_distance(colors[i], colors[j]))
    avg_color_dist = float(np.mean(color_distances)) if color_distances else 0.0
    # Score: 0 distance = perfect (1.0), 200+ = very inconsistent (0.0)
    color_score = max(0.0, 1.0 - avg_color_dist / 200.0)

    # --- Material consistency ---
    materials = [(b.get("facade_material") or "unknown").lower() for b in buildings]
    material_counts: dict[str, int] = {}
    for m in materials:
        material_counts[m] = material_counts.get(m, 0) + 1
    dominant_material = max(material_counts, key=material_counts.get) if material_counts else "unknown"
    material_pct = material_counts.get(dominant_material, 0) / n if n > 0 else 0.0
    material_score = material_pct  # 100% same = 1.0

    # --- Era consistency ---
    era_years = []
    for b in buildings:
        hcd = b.get("hcd_data") or {}
        mid = _era_midpoint(hcd.get("construction_date"))
        if mid is not None:
            era_years.append(mid)
    era_std = float(np.std(era_years)) if len(era_years) >= 2 else 0.0
    # Score: std < 5 years = very consistent (1.0), > 30 years = scattered (0.0)
    era_score = max(0.0, 1.0 - era_std / 30.0) if era_years else 0.5

    # --- Height rhythm ---
    heights = [b.get("total_height_m") for b in buildings if isinstance(b.get("total_height_m"), (int, float))]
    height_std = float(np.std(heights)) if len(heights) >= 2 else 0.0
    height_mean = float(np.mean(heights)) if heights else 0.0
    # Coefficient of variation as consistency measure
    height_cv = height_std / height_mean if height_mean > 0 else 0.0
    height_score = max(0.0, 1.0 - height_cv / 0.5)

    # --- Setback consistency ---
    setbacks = []
    for b in buildings:
        site = b.get("site") or {}
        sb = site.get("setback_m")
        if isinstance(sb, (int, float)):
            setbacks.append(float(sb))
    setback_std = float(np.std(setbacks)) if len(setbacks) >= 2 else 0.0
    setback_score = max(0.0, 1.0 - setback_std / 3.0) if setbacks else 0.5

    # --- Window pattern similarity ---
    window_vecs = [_windows_vector(b) for b in buildings]
    window_vecs = [v for v in window_vecs if v]
    window_score = 0.5  # default neutral
    if len(window_vecs) >= 2:
        # Pad to same length and compute pairwise cosine similarity
        max_len = max(len(v) for v in window_vecs)
        padded = [v + [0] * (max_len - len(v)) for v in window_vecs]
        sims = []
        for i in range(len(padded)):
            for j in range(i + 1, len(padded)):
                a = np.array(padded[i], dtype=float)
                b_vec = np.array(padded[j], dtype=float)
                denom = np.linalg.norm(a) * np.linalg.norm(b_vec)
                if denom > 0:
                    sims.append(float(np.dot(a, b_vec) / denom))
        window_score = float(np.mean(sims)) if sims else 0.5

    # --- Overall consistency ---
    overall = (
        color_score * 0.20
        + material_score * 0.20
        + era_score * 0.15
        + height_score * 0.20
        + setback_score * 0.10
        + window_score * 0.15
    )

    # --- Outlier detection ---
    outliers = []
    for b in buildings:
        deviations = []
        name = b.get("building_name") or (b.get("_meta") or {}).get("address") or "unknown"

        # Color outlier
        rgb = _hex_to_rgb(_get_facade_hex(b))
        if rgb and colors:
            avg_dist_to_others = float(np.mean([_color_distance(rgb, c) for c in colors if c != rgb]))
            if avg_dist_to_others > 100:
                deviations.append(f"facade_color_distance={avg_dist_to_others:.0f}")

        # Height outlier
        h = b.get("total_height_m")
        if isinstance(h, (int, float)) and heights and height_std > 0:
            z = abs(h - height_mean) / height_std
            if z > 2.0:
                deviations.append(f"height_zscore={z:.1f}")

        # Material outlier
        mat = (b.get("facade_material") or "unknown").lower()
        if mat != dominant_material and material_pct > 0.7:
            deviations.append(f"material={mat}_vs_dominant={dominant_material}")

        if deviations:
            outliers.append({"building": name, "deviations": deviations})

    return {
        "street": street_name,
        "building_count": n,
        "color_consistency": {
            "avg_pairwise_distance": round(avg_color_dist, 1),
            "score": round(color_score, 3),
        },
        "material_consistency": {
            "dominant_material": dominant_material,
            "dominant_pct": round(material_pct * 100, 1),
            "distribution": material_counts,
            "score": round(material_score, 3),
        },
        "era_consistency": {
            "era_std_years": round(era_std, 1),
            "buildings_with_date": len(era_years),
            "score": round(era_score, 3),
        },
        "height_rhythm": {
            "mean_height_m": round(height_mean, 2),
            "std_height_m": round(height_std, 2),
            "coefficient_of_variation": round(height_cv, 3),
            "score": round(height_score, 3),
        },
        "setback_consistency": {
            "std_setback_m": round(setback_std, 2),
            "buildings_with_setback": len(setbacks),
            "score": round(setback_score, 3),
        },
        "window_pattern_similarity": {
            "buildings_with_data": len(window_vecs),
            "score": round(window_score, 3),
        },
        "overall_consistency_score": round(overall, 3),
        "outliers": outliers,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Style consistency analysis across streets"
    )
    parser.add_argument(
        "--params",
        type=Path,
        default=DEFAULT_PARAMS_DIR,
        help="Directory containing building param JSON files",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Output directory for style analysis report",
    )
    args = parser.parse_args()

    params_dir: Path = args.params
    output_dir: Path = args.output

    if not params_dir.is_dir():
        print(f"Params directory not found: {params_dir}")
        return

    output_dir.mkdir(parents=True, exist_ok=True)

    # Load all building param files
    json_files = sorted(params_dir.glob("*.json"))
    streets: dict[str, list[dict]] = {}
    skipped = 0

    for jf in json_files:
        if jf.name.startswith("_"):
            continue
        try:
            data = json.loads(jf.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if data.get("skipped"):
            skipped += 1
            continue
        street = _get_street(data)
        if street:
            streets.setdefault(street, []).append(data)

    print(f"Loaded {sum(len(v) for v in streets.values())} buildings across {len(streets)} streets (skipped {skipped})")

    street_results = []
    for street_name in sorted(streets.keys()):
        buildings = streets[street_name]
        if len(buildings) < 2:
            continue  # Need at least 2 for consistency analysis
        result = analyze_street(street_name, buildings)
        street_results.append(result)
        print(f"  {street_name}: {len(buildings)} buildings, consistency={result['overall_consistency_score']:.3f}, outliers={len(result['outliers'])}")

    # Sort by consistency score ascending (least consistent first)
    street_results.sort(key=lambda r: r.get("overall_consistency_score", 0))

    # Collect all outliers
    all_outliers = []
    for sr in street_results:
        for o in sr.get("outliers", []):
            all_outliers.append({**o, "street": sr["street"]})

    # Summary
    consistency_scores = [r["overall_consistency_score"] for r in street_results]
    report = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "params_dir": str(params_dir),
        "total_streets_analyzed": len(street_results),
        "avg_consistency_score": round(float(np.mean(consistency_scores)), 3) if consistency_scores else 0.0,
        "most_consistent_street": street_results[-1]["street"] if street_results else None,
        "least_consistent_street": street_results[0]["street"] if street_results else None,
        "total_outliers": len(all_outliers),
        "outliers": all_outliers,
        "streets": street_results,
    }

    report_path = output_dir / "style_consistency_report.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nReport written to {report_path}")
    print(f"  Streets: {len(street_results)}, Avg consistency: {report['avg_consistency_score']}, Outliers: {len(all_outliers)}")


if __name__ == "__main__":
    main()
