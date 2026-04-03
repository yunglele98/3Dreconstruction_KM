#!/usr/bin/env python3
"""Detect where building params have drifted from field-photo evidence.

Compares parametric values (floors, material, roof type, condition, windows,
storefront, brick colour) against photo_observations and deep_facade_analysis
sections.  Produces a per-building mismatch report with severity ratings and
recommended actions.

Usage:
    python scripts/analyze/photo_param_drift.py
    python scripts/analyze/photo_param_drift.py --params params/ --output outputs/photo_drift/
"""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# ---------------------------------------------------------------------------
# Colour helpers
# ---------------------------------------------------------------------------

def _hex_to_rgb(h: str) -> tuple[int, int, int] | None:
    h = (h or "").strip().lstrip("#")
    if len(h) != 6:
        return None
    try:
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    except ValueError:
        return None


def _srgb_to_linear(c: float) -> float:
    return ((c + 0.055) / 1.055) ** 2.4 if c > 0.04045 else c / 12.92


def _rgb_to_lab(r: int, g: int, b: int) -> tuple[float, float, float]:
    rl, gl, bl = (_srgb_to_linear(c / 255.0) for c in (r, g, b))
    x = rl * 0.4124564 + gl * 0.3575761 + bl * 0.1804375
    y = rl * 0.2126729 + gl * 0.7151522 + bl * 0.0721750
    z = rl * 0.0193339 + gl * 0.1191920 + bl * 0.9503041
    xn, yn, zn = 0.95047, 1.0, 1.08883

    def f(t: float) -> float:
        return t ** (1.0 / 3.0) if t > 0.008856 else 7.787 * t + 16.0 / 116.0

    fx, fy, fz = f(x / xn), f(y / yn), f(z / zn)
    L = 116.0 * fy - 16.0
    a = 500.0 * (fx - fy)
    b_val = 200.0 * (fy - fz)
    return (L, a, b_val)


def _delta_e(hex1: str, hex2: str) -> float | None:
    rgb1 = _hex_to_rgb(hex1)
    rgb2 = _hex_to_rgb(hex2)
    if rgb1 is None or rgb2 is None:
        return None
    lab1 = _rgb_to_lab(*rgb1)
    lab2 = _rgb_to_lab(*rgb2)
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(lab1, lab2)))


# ---------------------------------------------------------------------------
# Comparison helpers
# ---------------------------------------------------------------------------

SEVERITY_HIGH = "high"
SEVERITY_MEDIUM = "medium"
SEVERITY_LOW = "low"


def _normalise(val: object) -> str:
    """Lowercase string representation for loose comparison."""
    if val is None:
        return ""
    if isinstance(val, bool):
        return str(val).lower()
    return str(val).strip().lower()


def _compare_floors(params: dict, dfa: dict | None) -> dict | None:
    param_val = params.get("floors")
    photo_val = (dfa or {}).get("storeys_observed")
    if param_val is None or photo_val is None:
        return None
    if int(param_val) == int(photo_val):
        return None
    return {
        "field": "floors",
        "param_value": param_val,
        "photo_value": photo_val,
        "severity": SEVERITY_HIGH,
        "action": "update param" if abs(int(param_val) - int(photo_val)) == 1 else "verify",
    }


def _compare_material(params: dict, dfa: dict | None, po: dict | None) -> dict | None:
    param_val = _normalise(params.get("facade_material"))
    photo_val = _normalise((dfa or {}).get("facade_material_observed") or (po or {}).get("facade_material_observed"))
    if not param_val or not photo_val:
        return None
    if param_val == photo_val:
        return None
    return {
        "field": "facade_material",
        "param_value": params.get("facade_material"),
        "photo_value": (dfa or {}).get("facade_material_observed") or (po or {}).get("facade_material_observed"),
        "severity": SEVERITY_HIGH,
        "action": "update param",
    }


def _compare_roof(params: dict, dfa: dict | None) -> dict | None:
    param_val = _normalise(params.get("roof_type"))
    photo_val = _normalise((dfa or {}).get("roof_type_observed"))
    if not param_val or not photo_val:
        return None
    if param_val == photo_val:
        return None
    # Normalise common aliases
    aliases = {"flat": "flat", "gable": "gable", "cross-gable": "cross-gable",
               "cross_gable": "cross-gable", "hip": "hip", "mansard": "mansard"}
    if aliases.get(param_val) == aliases.get(photo_val):
        return None
    return {
        "field": "roof_type",
        "param_value": params.get("roof_type"),
        "photo_value": (dfa or {}).get("roof_type_observed"),
        "severity": SEVERITY_HIGH,
        "action": "update param",
    }


def _compare_condition(params: dict, dfa: dict | None, po: dict | None) -> dict | None:
    param_val = _normalise(params.get("condition"))
    photo_val = _normalise((dfa or {}).get("condition_observed") or (po or {}).get("condition"))
    if not param_val or not photo_val:
        return None
    if param_val == photo_val:
        return None
    return {
        "field": "condition",
        "param_value": params.get("condition"),
        "photo_value": (dfa or {}).get("condition_observed") or (po or {}).get("condition"),
        "severity": SEVERITY_LOW,
        "action": "verify",
    }


def _compare_windows(params: dict, dfa: dict | None) -> dict | None:
    param_wpf = params.get("windows_per_floor")
    if not param_wpf or not dfa:
        return None
    # Extract window counts from deep_facade_analysis.windows_detail
    dfa_wd = dfa.get("windows_detail")
    if not dfa_wd or not isinstance(dfa_wd, list):
        return None
    photo_counts = []
    for floor_entry in dfa_wd:
        windows = floor_entry.get("windows", [])
        total = sum(w.get("count", 0) for w in windows) if isinstance(windows, list) else 0
        photo_counts.append(total)
    if not photo_counts:
        return None
    # Compare lengths and values
    param_list = list(param_wpf) if isinstance(param_wpf, list) else [param_wpf]
    if param_list == photo_counts:
        return None
    return {
        "field": "windows_per_floor",
        "param_value": param_list,
        "photo_value": photo_counts,
        "severity": SEVERITY_MEDIUM,
        "action": "update param",
    }


def _compare_storefront(params: dict, dfa: dict | None) -> dict | None:
    param_val = params.get("has_storefront")
    photo_sf = (dfa or {}).get("storefront_observed")
    if param_val is None or photo_sf is None:
        return None
    photo_has = bool(photo_sf) if isinstance(photo_sf, bool) else isinstance(photo_sf, dict)
    if bool(param_val) == photo_has:
        return None
    return {
        "field": "has_storefront",
        "param_value": param_val,
        "photo_value": photo_has,
        "severity": SEVERITY_MEDIUM,
        "action": "update param",
    }


def _compare_brick_colour(params: dict, dfa: dict | None) -> dict | None:
    fd = params.get("facade_detail") or {}
    param_hex = fd.get("brick_colour_hex")
    photo_hex = (dfa or {}).get("brick_colour_hex")
    if not param_hex or not photo_hex:
        return None
    de = _delta_e(param_hex, photo_hex)
    if de is None:
        return None
    if de < 10.0:  # perceptually close
        return None
    return {
        "field": "facade_detail.brick_colour_hex",
        "param_value": param_hex,
        "photo_value": photo_hex,
        "severity": SEVERITY_MEDIUM if de < 25.0 else SEVERITY_HIGH,
        "delta_e": round(de, 1),
        "action": "update param" if de > 15.0 else "verify",
    }


# ---------------------------------------------------------------------------
# Main analysis
# ---------------------------------------------------------------------------

def analyse_building(params: dict) -> dict | None:
    """Return drift record for a single building, or None if no photo data."""
    dfa = params.get("deep_facade_analysis")
    po = params.get("photo_observations")
    if not dfa and not po:
        return None

    address = params.get("building_name") or (params.get("_meta") or {}).get("address", "unknown")
    mismatches: list[dict] = []

    comparisons = [
        _compare_floors(params, dfa),
        _compare_material(params, dfa, po),
        _compare_roof(params, dfa),
        _compare_condition(params, dfa, po),
        _compare_windows(params, dfa),
        _compare_storefront(params, dfa),
        _compare_brick_colour(params, dfa),
    ]
    for result in comparisons:
        if result is not None:
            mismatches.append(result)

    if not mismatches:
        return None

    return {
        "address": address,
        "mismatch_count": len(mismatches),
        "mismatches": mismatches,
    }


def run(params_dir: Path, output_dir: Path) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)

    buildings: list[dict] = []
    field_counts: Counter = Counter()
    severity_counts: Counter = Counter()
    total_with_photos = 0
    total_with_drift = 0

    for pf in sorted(params_dir.glob("*.json")):
        if pf.name.startswith("_"):
            continue
        try:
            params = json.loads(pf.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if params.get("skipped"):
            continue
        dfa = params.get("deep_facade_analysis")
        po = params.get("photo_observations")
        if not dfa and not po:
            continue
        total_with_photos += 1

        result = analyse_building(params)
        if result is None:
            continue
        total_with_drift += 1
        buildings.append(result)
        for m in result["mismatches"]:
            field_counts[m["field"]] += 1
            severity_counts[m["severity"]] += 1

    # Sort by mismatch count descending
    buildings.sort(key=lambda b: b["mismatch_count"], reverse=True)

    top_20 = buildings[:20]

    report = {
        "generated": datetime.now().isoformat(),
        "total_buildings_with_photos": total_with_photos,
        "total_buildings_with_drift": total_with_drift,
        "drift_rate_pct": round(100.0 * total_with_drift / max(total_with_photos, 1), 1),
        "severity_histogram": dict(severity_counts.most_common()),
        "field_mismatch_rates": {
            k: {"count": v, "pct": round(100.0 * v / max(total_with_photos, 1), 1)}
            for k, v in field_counts.most_common()
        },
        "top_20_worst_drift": top_20,
        "all_buildings": buildings,
    }

    out_path = output_dir / "photo_param_drift_report.json"
    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Drift report: {out_path}")
    print(f"  Buildings with photo data: {total_with_photos}")
    print(f"  Buildings with drift:      {total_with_drift} ({report['drift_rate_pct']}%)")
    print(f"  Severity: {dict(severity_counts.most_common())}")
    print(f"  Field mismatch counts: {dict(field_counts.most_common())}")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Detect param drift from photo evidence")
    parser.add_argument("--params", type=Path, default=REPO_ROOT / "params",
                        help="Directory of building param JSON files")
    parser.add_argument("--output", type=Path, default=REPO_ROOT / "outputs" / "photo_drift",
                        help="Output directory for drift report")
    args = parser.parse_args()
    run(args.params, args.output)


if __name__ == "__main__":
    main()
