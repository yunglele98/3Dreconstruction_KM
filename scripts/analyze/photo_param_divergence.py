#!/usr/bin/env python3
"""Compare parametric model data against field photo observations.

The field photos (PHOTOS KENSINGTON/) are ground truth. This script finds
every place where the generator params diverge from what the photos show,
producing a per-building fidelity report and an actionable fix queue.

Compares:
- Facade material: param vs photo_observations vs deep_facade_analysis
- Brick colour: facade_detail.brick_colour_hex vs DFA daylight-corrected
- Window counts per floor: windows_per_floor vs DFA observed counts
- Floor count: floors vs DFA storeys_observed
- Roof type: roof_type vs DFA roof_type_observed
- Door count: door_count vs DFA doors_observed count
- Condition: condition vs DFA condition_observed
- Storefront: has_storefront vs DFA storefront_observed
- Bay window: bay_window.present vs DFA bay_window_observed
- Decorative elements: decorative_elements vs DFA observed elements

Each divergence is scored by severity (high = visible at street level,
medium = visible up close, low = subtle detail).

Usage:
    python scripts/analyze/photo_param_divergence.py
    python scripts/analyze/photo_param_divergence.py --street "Augusta Ave"
    python scripts/analyze/photo_param_divergence.py --apply  # patch params from photo data
    python scripts/analyze/photo_param_divergence.py --top 20  # worst 20 buildings
"""

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
PARAMS_DIR = ROOT / "params"


def _norm(val):
    """Normalize a string value for comparison."""
    if val is None:
        return ""
    return str(val).strip().lower()


def _colour_similar(hex1, hex2, threshold=0.12):
    """Check if two hex colours are perceptually similar."""
    import colorsys
    if not hex1 or not hex2:
        return True  # can't compare
    try:
        hex1 = hex1.lstrip("#")
        hex2 = hex2.lstrip("#")
        r1, g1, b1 = int(hex1[0:2], 16), int(hex1[2:4], 16), int(hex1[4:6], 16)
        r2, g2, b2 = int(hex2[0:2], 16), int(hex2[2:4], 16), int(hex2[4:6], 16)
        h1, s1, v1 = colorsys.rgb_to_hsv(r1/255, g1/255, b1/255)
        h2, s2, v2 = colorsys.rgb_to_hsv(r2/255, g2/255, b2/255)
        dh = min(abs(h1-h2), 1-abs(h1-h2))
        dist = (dh**2 + (s1-s2)**2 + (v1-v2)**2) ** 0.5
        return dist < threshold
    except (ValueError, IndexError):
        return True


def compare_building(params):
    """Compare one building's params against its photo observations."""
    address = params.get("building_name", "?")
    po = params.get("photo_observations", {})
    dfa = params.get("deep_facade_analysis", {})
    if not isinstance(po, dict):
        po = {}
    if not isinstance(dfa, dict):
        dfa = {}

    photo = po.get("photo") or dfa.get("source_photo")
    if not photo:
        return None  # no photo reference

    divergences = []

    # 1. FACADE MATERIAL
    param_mat = _norm(params.get("facade_material"))
    photo_mat = _norm(po.get("facade_material_observed") or dfa.get("facade_material_observed"))
    if photo_mat and param_mat and photo_mat != param_mat:
        # Allow close matches
        if not (param_mat in photo_mat or photo_mat in param_mat):
            divergences.append({
                "field": "facade_material",
                "param_value": params.get("facade_material"),
                "photo_value": po.get("facade_material_observed") or dfa.get("facade_material_observed"),
                "severity": "high",
                "detail": f"Param says '{params.get('facade_material')}', "
                          f"photo shows '{po.get('facade_material_observed') or dfa.get('facade_material_observed')}'",
                "fix_field": "facade_material",
                "fix_value": po.get("facade_material_observed") or dfa.get("facade_material_observed"),
            })

    # 2. BRICK COLOUR
    fd = params.get("facade_detail", {})
    param_hex = fd.get("brick_colour_hex", "") if isinstance(fd, dict) else ""
    photo_hex = dfa.get("brick_colour_hex", "")
    if param_hex and photo_hex and not _colour_similar(param_hex, photo_hex):
        divergences.append({
            "field": "facade_detail.brick_colour_hex",
            "param_value": param_hex,
            "photo_value": photo_hex,
            "severity": "high",
            "detail": f"Param colour {param_hex} differs from photo-observed {photo_hex}",
            "fix_field": "facade_detail.brick_colour_hex",
            "fix_value": photo_hex,
        })

    # 3. FLOOR COUNT
    param_floors = params.get("floors")
    photo_floors = dfa.get("storeys_observed") or po.get("storeys_observed")
    if isinstance(param_floors, (int, float)) and isinstance(photo_floors, (int, float)):
        pf = int(param_floors)
        of = int(photo_floors)
        if pf != of and abs(pf - of) >= 1:
            # Half-storey difference (2 vs 2.5) is acceptable
            if abs(param_floors - float(photo_floors)) >= 0.9:
                divergences.append({
                    "field": "floors",
                    "param_value": param_floors,
                    "photo_value": photo_floors,
                    "severity": "high",
                    "detail": f"Param says {param_floors} floors, photo shows {photo_floors}",
                    "fix_field": None,  # floors is protected
                    "fix_value": None,
                })

    # 4. ROOF TYPE
    param_roof = _norm(params.get("roof_type"))
    photo_roof = _norm(dfa.get("roof_type_observed"))
    if param_roof and photo_roof:
        # Normalize common variants
        pr = param_roof.replace("-", "").replace("_", "")
        or_ = photo_roof.split("(")[0].strip().replace("-", "").replace("_", "")
        if pr != or_ and pr not in or_ and or_ not in pr:
            divergences.append({
                "field": "roof_type",
                "param_value": params.get("roof_type"),
                "photo_value": dfa.get("roof_type_observed"),
                "severity": "medium",
                "detail": f"Param roof '{params.get('roof_type')}' vs photo '{dfa.get('roof_type_observed')}'",
                "fix_field": None,  # needs manual review
                "fix_value": None,
            })

    # 5. WINDOW COUNTS PER FLOOR
    param_wpf = params.get("windows_per_floor", [])
    dfa_windows = dfa.get("windows_detail", [])
    if isinstance(dfa_windows, list) and isinstance(param_wpf, list):
        for i, wd in enumerate(dfa_windows):
            if not isinstance(wd, dict):
                continue
            photo_count = wd.get("count")
            if photo_count is None or not isinstance(photo_count, (int, float)):
                continue
            if i < len(param_wpf):
                param_count = param_wpf[i]
                if isinstance(param_count, (int, float)) and abs(param_count - photo_count) >= 2:
                    floor_label = wd.get("floor", f"floor {i+1}")
                    divergences.append({
                        "field": f"windows_per_floor[{i}]",
                        "param_value": param_count,
                        "photo_value": int(photo_count),
                        "severity": "medium",
                        "detail": f"{floor_label}: param has {param_count} windows, "
                                  f"photo shows {int(photo_count)}",
                        "fix_field": None,
                        "fix_value": None,
                    })

    # 6. CONDITION
    param_cond = _norm(params.get("condition"))
    photo_cond = _norm(dfa.get("condition_observed") or po.get("condition"))
    if param_cond and photo_cond and param_cond != photo_cond:
        divergences.append({
            "field": "condition",
            "param_value": params.get("condition"),
            "photo_value": dfa.get("condition_observed") or po.get("condition"),
            "severity": "low",
            "detail": f"Param condition '{params.get('condition')}' vs photo '{dfa.get('condition_observed')}'",
            "fix_field": "condition",
            "fix_value": dfa.get("condition_observed") or po.get("condition"),
        })

    # 7. STOREFRONT
    param_sf = bool(params.get("has_storefront"))
    dfa_sf = dfa.get("storefront_observed", {})
    photo_has_sf = False
    if isinstance(dfa_sf, dict) and dfa_sf.get("width_pct"):
        photo_has_sf = True
    elif isinstance(dfa_sf, bool):
        photo_has_sf = dfa_sf
    if param_sf != photo_has_sf:
        divergences.append({
            "field": "has_storefront",
            "param_value": param_sf,
            "photo_value": photo_has_sf,
            "severity": "high",
            "detail": f"Param has_storefront={param_sf}, photo shows {'storefront' if photo_has_sf else 'no storefront'}",
            "fix_field": "has_storefront",
            "fix_value": photo_has_sf,
        })

    # 8. BAY WINDOW
    param_bay = params.get("bay_window", {})
    param_has_bay = isinstance(param_bay, dict) and param_bay.get("present", False)
    dfa_bay = dfa.get("bay_window_observed", {})
    photo_has_bay = False
    if isinstance(dfa_bay, dict) and dfa_bay.get("present"):
        photo_has_bay = True
    if param_has_bay != photo_has_bay:
        divergences.append({
            "field": "bay_window.present",
            "param_value": param_has_bay,
            "photo_value": photo_has_bay,
            "severity": "high" if photo_has_bay else "medium",
            "detail": f"Param bay_window={param_has_bay}, photo shows "
                      f"{'bay window' if photo_has_bay else 'no bay window'}",
            "fix_field": None,
            "fix_value": None,
        })

    # 9. DOOR COUNT
    param_doors = params.get("door_count", 0)
    dfa_doors = dfa.get("doors_observed", [])
    if isinstance(dfa_doors, list) and isinstance(param_doors, (int, float)):
        photo_door_count = len(dfa_doors)
        if abs(param_doors - photo_door_count) >= 2:
            divergences.append({
                "field": "door_count",
                "param_value": param_doors,
                "photo_value": photo_door_count,
                "severity": "medium",
                "detail": f"Param has {param_doors} doors, photo shows {photo_door_count}",
                "fix_field": None,
                "fix_value": None,
            })

    # 10. ROOF PITCH
    param_pitch = params.get("roof_pitch_deg")
    photo_pitch = dfa.get("roof_pitch_deg")
    if (isinstance(param_pitch, (int, float)) and isinstance(photo_pitch, (int, float))
            and abs(param_pitch - photo_pitch) > 10):
        divergences.append({
            "field": "roof_pitch_deg",
            "param_value": param_pitch,
            "photo_value": photo_pitch,
            "severity": "medium",
            "detail": f"Param pitch {param_pitch}° vs photo {photo_pitch}° (Δ{abs(param_pitch-photo_pitch):.0f}°)",
            "fix_field": "roof_pitch_deg",
            "fix_value": photo_pitch,
        })

    # 11. COLOUR PALETTE (trim, roof, accent)
    param_cp = params.get("colour_palette", {})
    photo_cp = dfa.get("colour_palette_observed", {})
    if isinstance(param_cp, dict) and isinstance(photo_cp, dict):
        for key in ("trim", "roof", "accent"):
            p_val = param_cp.get(key, "")
            o_val = photo_cp.get(key, "")
            if p_val and o_val and not _colour_similar(p_val, o_val, threshold=0.15):
                divergences.append({
                    "field": f"colour_palette.{key}",
                    "param_value": p_val,
                    "photo_value": o_val,
                    "severity": "medium" if key == "trim" else "low",
                    "detail": f"Param {key} {p_val} vs photo {o_val}",
                    "fix_field": f"colour_palette.{key}",
                    "fix_value": o_val,
                })

    # Compute fidelity score
    high = sum(1 for d in divergences if d["severity"] == "high")
    med = sum(1 for d in divergences if d["severity"] == "medium")
    low = sum(1 for d in divergences if d["severity"] == "low")
    fidelity = max(0, 100 - high * 15 - med * 8 - low * 3)

    return {
        "address": address,
        "photo": photo,
        "fidelity_score": fidelity,
        "divergence_count": len(divergences),
        "by_severity": {"high": high, "medium": med, "low": low},
        "divergences": divergences,
    }


def apply_fixes(params, divergences):
    """Apply safe auto-fixes from photo data to params. Returns list of applied fixes."""
    applied = []
    for div in divergences:
        fix_field = div.get("fix_field")
        fix_value = div.get("fix_value")
        if not fix_field or fix_value is None:
            continue

        # Apply nested field (e.g. "facade_detail.brick_colour_hex")
        parts = fix_field.split(".")
        target = params
        for part in parts[:-1]:
            if part not in target or not isinstance(target[part], dict):
                target[part] = {}
            target = target[part]

        old_val = target.get(parts[-1])
        target[parts[-1]] = fix_value
        applied.append({
            "field": fix_field,
            "old": old_val,
            "new": fix_value,
        })

    return applied


def main():
    parser = argparse.ArgumentParser(description="Photo vs params divergence analysis")
    parser.add_argument("--street", help="Analyze single street")
    parser.add_argument("--top", type=int, default=0, help="Show top N worst buildings")
    parser.add_argument("--apply", action="store_true",
                        help="Apply safe auto-fixes from photo data")
    parser.add_argument("--severity", choices=["high", "medium", "low"],
                        help="Filter by minimum severity")
    args = parser.parse_args()

    results = []
    files_to_fix = []

    for f in sorted(PARAMS_DIR.glob("*.json")):
        if f.name.startswith("_"):
            continue
        data = json.loads(f.read_text(encoding="utf-8"))
        if data.get("skipped"):
            continue

        street = data.get("site", {}).get("street", "Unknown")
        if args.street and street != args.street:
            continue

        result = compare_building(data)
        if result is None:
            continue

        result["street"] = street
        result["param_file"] = f.name
        results.append(result)

        if args.apply and result["divergences"]:
            fixable = [d for d in result["divergences"] if d.get("fix_field")]
            if fixable:
                files_to_fix.append((f, data, fixable))

    # Apply fixes
    if args.apply and files_to_fix:
        total_fixes = 0
        for fpath, data, divs in files_to_fix:
            applied = apply_fixes(data, divs)
            if applied:
                meta = data.setdefault("_meta", {})
                prev = meta.get("photo_divergence_fixes", [])
                meta["photo_divergence_fixes"] = prev + applied
                fpath.write_text(
                    json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8"
                )
                total_fixes += len(applied)
        print(f"Applied {total_fixes} auto-fixes to {len(files_to_fix)} files")
        print()

    # Summary
    total_div = sum(r["divergence_count"] for r in results)
    high_total = sum(r["by_severity"]["high"] for r in results)
    med_total = sum(r["by_severity"]["medium"] for r in results)
    low_total = sum(r["by_severity"]["low"] for r in results)
    avg_fidelity = sum(r["fidelity_score"] for r in results) / max(1, len(results))
    perfect = sum(1 for r in results if r["fidelity_score"] == 100)

    print("=== Photo vs Params Divergence Analysis ===")
    print(f"Buildings with photos: {len(results)}")
    print(f"Average fidelity: {avg_fidelity:.1f}/100")
    print(f"Perfect match: {perfect} ({perfect/max(1,len(results)):.0%})")
    print(f"Total divergences: {total_div} (high:{high_total} med:{med_total} low:{low_total})")
    print()

    # By divergence type
    field_counts = Counter(
        d["field"] for r in results for d in r["divergences"]
        if not args.severity or d["severity"] == args.severity
    )
    print("Divergences by field:")
    for field, count in field_counts.most_common(15):
        pct = count / len(results) * 100
        print(f"  {field:40s} {count:4d} ({pct:.0f}%)")

    # By street
    print()
    by_street = defaultdict(list)
    for r in results:
        by_street[r["street"]].append(r)
    print("Fidelity by street:")
    for street in sorted(by_street, key=lambda s: sum(r["fidelity_score"] for r in by_street[s]) / len(by_street[s])):
        scores = [r["fidelity_score"] for r in by_street[street]]
        avg = sum(scores) / len(scores)
        divs = sum(r["divergence_count"] for r in by_street[street])
        print(f"  {street:25s} avg={avg:5.1f}  divergences={divs:4d}  buildings={len(scores):3d}")

    # Show worst buildings
    show_n = args.top or 15
    worst = sorted(results, key=lambda r: r["fidelity_score"])[:show_n]
    print(f"\n--- Lowest fidelity buildings (top {show_n}) ---")
    for r in worst:
        if r["fidelity_score"] >= 85 and not args.top:
            break
        print(f"\n  {r['address']} (fidelity {r['fidelity_score']}, photo: {r['photo']})")
        for d in r["divergences"]:
            sev = {"high": "!!!", "medium": " ! ", "low": "   "}[d["severity"]]
            fix = f" → fix: {d['fix_value']}" if d.get("fix_value") else ""
            print(f"    [{sev}] {d['detail']}{fix}")

    # Save
    out = ROOT / "outputs" / "photo_param_divergence.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nReport saved: {out}")


if __name__ == "__main__":
    main()
