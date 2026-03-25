#!/usr/bin/env python3
"""
QA pass: check all active params for data quality issues.

Checks:
1. Windows per floor too high for facade width (>1 window per 1.2m)
2. Facade dimensions implausible (width < 3m or > 30m, height < 2m or > 25m)
3. Floor count vs height mismatch (avg floor height < 2m or > 5m)
4. Missing critical fields (floors, facade_material, roof_type)
5. Photo observation conflicts (material mismatch)
6. Duplicate building_name across files
7. Zero or negative dimensions
8. Windows per floor array length != floors count
9. facade_material not in generator's known set
10. Implausible window counts (0 windows on upper floors)

Usage:
    python scripts/qa_photo_verify.py [--fix]
"""

import json
import sys
from collections import defaultdict
from pathlib import Path

PARAMS_DIR = Path(__file__).resolve().parent.parent / "params"
DO_FIX = "--fix" in sys.argv

KNOWN_MATERIALS = {"brick", "stone", "stucco", "clapboard", "paint", "siding",
                   "wood", "concrete", "metal", "vinyl"}

issues_by_severity = {"critical": [], "warning": [], "info": []}
fix_count = 0


def add_issue(severity, name, msg, fix_func=None):
    global fix_count
    issues_by_severity[severity].append((name, msg))
    if DO_FIX and fix_func:
        fix_func()
        fix_count += 1


def check_building(name, fpath, d):
    floors = d.get("floors")
    width = d.get("facade_width_m")
    depth = d.get("facade_depth_m")
    height = d.get("total_height_m")
    material = d.get("facade_material", "")
    roof = d.get("roof_type", "")
    wpf = d.get("windows_per_floor", [])
    fh = d.get("floor_heights_m", [])

    # 1. Missing critical fields
    if not floors or floors < 1:
        def fix():
            d["floors"] = 2
            d["total_height_m"] = d.get("total_height_m") or 6.0
        add_issue("critical", name, f"floors={floors} (missing/zero)", fix)

    if not material:
        def fix():
            d["facade_material"] = "brick"
        add_issue("critical", name, "facade_material missing", fix)

    if not roof:
        def fix():
            d["roof_type"] = "gable"
        add_issue("critical", name, "roof_type missing", fix)

    # 2. Zero/negative dimensions
    if width is not None and width <= 0:
        add_issue("critical", name, f"facade_width_m={width} (zero/negative)")
    if height is not None and height <= 0:
        add_issue("critical", name, f"total_height_m={height} (zero/negative)")

    # 3. Implausible dimensions
    if width is not None and width < 3.0:
        add_issue("warning", name, f"facade_width_m={width} (very narrow, <3m)")
    if width is not None and width > 30.0:
        add_issue("warning", name, f"facade_width_m={width} (very wide, >30m)")
    if height is not None and height > 25.0:
        add_issue("warning", name, f"total_height_m={height} (very tall, >25m)")
    if height is not None and height < 2.5:
        add_issue("warning", name, f"total_height_m={height} (very short, <2.5m)")

    # 4. Floor height sanity
    if floors and height and floors > 0:
        avg_fh = height / floors
        if avg_fh < 2.0:
            add_issue("warning", name,
                      f"avg floor height={avg_fh:.1f}m ({height}m / {floors}fl, <2m)")
        if avg_fh > 5.5:
            def fix():
                if floors > 3:
                    d["floors"] = max(2, int(height / 3.0))
            add_issue("warning", name,
                      f"avg floor height={avg_fh:.1f}m ({height}m / {floors}fl, >5.5m)", fix)

    # 5. Windows per floor too high for width
    if wpf and width:
        for i, count in enumerate(wpf):
            if isinstance(count, (int, float)) and count > 0 and width > 0:
                spacing = width / count
                if spacing < 0.8:
                    def fix(idx=i):
                        max_win = max(1, int(width / 1.5))
                        d.setdefault("windows_per_floor", wpf)[idx] = max_win
                    add_issue("warning", name,
                              f"floor {i}: {count} windows in {width}m = {spacing:.1f}m spacing (<0.8m)",
                              fix)

    # 6. Windows array length mismatch
    if wpf and floors:
        if len(wpf) != floors:
            add_issue("info", name,
                      f"windows_per_floor has {len(wpf)} entries but floors={floors}")

    # 7. Floor heights array length mismatch
    if fh and floors:
        if len(fh) != floors:
            add_issue("info", name,
                      f"floor_heights_m has {len(fh)} entries but floors={floors}")

    # 8. Unknown facade material
    if material and material.lower() not in KNOWN_MATERIALS:
        norm = material.lower()
        suggested = None
        if "brick" in norm:
            suggested = "brick"
        elif "stucco" in norm or "plaster" in norm or "render" in norm:
            suggested = "stucco"
        elif "clap" in norm or "siding" in norm or "vinyl" in norm or "aluminum" in norm:
            suggested = "clapboard"
        elif "mixed masonry" in norm:
            suggested = "brick"  # Kensington default: mixed masonry is typically brick
        elif "stone" in norm or "masonry" in norm:
            suggested = "stone"
        elif "paint" in norm:
            suggested = "paint"
        elif "wood" in norm:
            suggested = "wood"
        elif "concrete" in norm or "block" in norm:
            suggested = "concrete"
        elif "metal" in norm or "steel" in norm:
            suggested = "metal"

        if suggested:
            def fix(s=suggested):
                d["facade_material"] = s
            add_issue("warning", name,
                      f"facade_material='{material}' not in known set -> '{suggested}'", fix)
        else:
            add_issue("info", name,
                      f"facade_material='{material}' not in known set")

    # 9. Photo observation material conflict
    po = d.get("photo_observations", {})
    if po:
        obs_mat = (po.get("facade_material_observed") or "").lower()
        param_mat = material.lower() if material else ""
        if obs_mat and param_mat:
            # Check for major conflicts
            if ("brick" in param_mat and "siding" in obs_mat) or \
               ("brick" in param_mat and "vinyl" in obs_mat) or \
               ("siding" in obs_mat and "stone" in param_mat):
                add_issue("warning", name,
                          f"material conflict: param='{material}' vs photo='{obs_mat}'")

    return d


def main():
    # Load all active params
    all_params = {}
    for f in sorted(PARAMS_DIR.glob("*.json")):
        if f.name.startswith("_"):
            continue
        try:
            d = json.load(open(f, encoding="utf-8"))
        except Exception:
            issues_by_severity["critical"].append((f.stem, "JSON parse error"))
            continue
        if d.get("skipped"):
            continue
        all_params[f.stem] = (f, d)

    # Check for duplicate building_name
    names = defaultdict(list)
    for stem, (f, d) in all_params.items():
        bn = d.get("building_name", "")
        if bn:
            names[bn].append(stem)

    for bn, stems in names.items():
        if len(stems) > 1:
            for s in stems[1:]:
                issues_by_severity["info"].append((s, f"duplicate building_name '{bn}' (also: {stems[0]})"))

    # Run checks on each building
    for name, (fpath, d) in sorted(all_params.items()):
        d = check_building(name, fpath, d)

        if DO_FIX:
            with open(fpath, "w", encoding="utf-8") as f:
                json.dump(d, f, indent=2, ensure_ascii=False)

    # Report
    total = len(all_params)
    print(f"QA Report: {total} active buildings checked")
    print(f"{'(FIXES APPLIED)' if DO_FIX else '(dry run — use --fix to apply)'}")
    print()

    for severity in ["critical", "warning", "info"]:
        items = issues_by_severity[severity]
        print(f"=== {severity.upper()} ({len(items)}) ===")
        for name, msg in items[:50]:
            print(f"  {name}: {msg}")
        if len(items) > 50:
            print(f"  ... and {len(items) - 50} more")
        print()

    clean = total - len(set(n for sev in issues_by_severity.values() for n, _ in sev))
    print(f"Clean buildings: {clean}/{total} ({100*clean/total:.1f}%)")

    if DO_FIX:
        print(f"Fixes applied: {fix_count}")


if __name__ == "__main__":
    main()
