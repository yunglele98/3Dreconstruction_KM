#!/usr/bin/env python3
"""Estimate brick counts and coursing for every brick building.

Toronto heritage brick dimensions vary by era:

- Pre-1889 (hand-pressed): ~215mm L x 100mm W x 65mm H, mortar 10-12mm
- 1889-1903 (machine-pressed): ~215mm L x 100mm W x 63mm H, mortar 10mm
- 1904-1913 (Edwardian standard): ~215mm L x 100mm W x 60mm H, mortar 8-10mm
- 1914-1930 (interwar): ~215mm L x 100mm W x 57mm H, mortar 8mm

This script calculates:
- Brick courses (horizontal rows) per floor and total
- Bricks per course across facade width
- Total visible facade bricks (front face only)
- Brick-to-mortar ratio for texture scale calibration
- Stretcher/header counts by bond pattern
- Course heights for Blender Brick Texture node scale parameter

Usage:
    python scripts/analyze/brick_count.py
    python scripts/analyze/brick_count.py --street "Augusta Ave"
    python scripts/analyze/brick_count.py --address "22 Lippincott St"
    python scripts/analyze/brick_count.py --apply   # write brick_geometry to params
    python scripts/analyze/brick_count.py --csv      # export CSV
"""

import argparse
import csv
import json
import math
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
PARAMS_DIR = ROOT / "params"

# Toronto heritage brick dimensions by era (millimetres)
ERA_BRICK_DIMS = {
    "Pre-1889": {
        "label": "Hand-pressed (pre-1889)",
        "brick_length_mm": 215,
        "brick_width_mm": 100,
        "brick_height_mm": 65,
        "mortar_joint_mm": 11,
        "variation_mm": 3,       # hand-pressed bricks vary more
        "colour_variation": 0.08,  # higher colour variance in older brick
    },
    "1889-1903": {
        "label": "Machine-pressed (Late Victorian)",
        "brick_length_mm": 215,
        "brick_width_mm": 100,
        "brick_height_mm": 63,
        "mortar_joint_mm": 10,
        "variation_mm": 2,
        "colour_variation": 0.05,
    },
    "1904-1913": {
        "label": "Standard (Edwardian)",
        "brick_length_mm": 215,
        "brick_width_mm": 100,
        "brick_height_mm": 60,
        "mortar_joint_mm": 9,
        "variation_mm": 1.5,
        "colour_variation": 0.04,
    },
    "1914-1930": {
        "label": "Standard (Interwar)",
        "brick_length_mm": 215,
        "brick_width_mm": 100,
        "brick_height_mm": 57,
        "mortar_joint_mm": 8,
        "variation_mm": 1,
        "colour_variation": 0.03,
    },
}

# Modern standard (for buildings with unknown era)
DEFAULT_DIMS = ERA_BRICK_DIMS["1889-1903"]

# Bond pattern affects brick count per course
BOND_PATTERNS = {
    "running bond": {
        "stretcher_ratio": 1.0,  # all stretchers (long side visible)
        "header_ratio": 0.0,
        "offset": 0.5,          # half-brick offset each course
    },
    "common bond": {
        "stretcher_ratio": 0.83,  # 5 stretcher courses + 1 header course
        "header_ratio": 0.17,
        "offset": 0.5,
    },
    "flemish bond": {
        "stretcher_ratio": 0.5,   # alternating stretcher/header
        "header_ratio": 0.5,
        "offset": 0.25,
    },
    "header bond": {
        "stretcher_ratio": 0.0,
        "header_ratio": 1.0,
        "offset": 0.5,
    },
    "stretcher bond": {
        "stretcher_ratio": 1.0,
        "header_ratio": 0.0,
        "offset": 0.33,
    },
}


def get_brick_dims(params):
    """Get era-appropriate brick dimensions for a building."""
    hcd = params.get("hcd_data", {})
    era = hcd.get("construction_date", "") if isinstance(hcd, dict) else ""
    dims = ERA_BRICK_DIMS.get(era, DEFAULT_DIMS)
    return dims, era


def get_bond_info(params):
    """Get bond pattern info."""
    fd = params.get("facade_detail", {})
    bp = fd.get("bond_pattern", "running bond") if isinstance(fd, dict) else "running bond"
    bp_clean = bp.lower().strip()
    # Normalize
    for key in BOND_PATTERNS:
        if key in bp_clean:
            return BOND_PATTERNS[key], key
    return BOND_PATTERNS["running bond"], "running bond"


def count_bricks(params):
    """Calculate brick counts for a single building."""
    address = params.get("building_name", "?")
    material = str(params.get("facade_material", "")).lower()
    if "brick" not in material:
        return None

    dims, era = get_brick_dims(params)
    bond, bond_name = get_bond_info(params)

    # Facade dimensions
    width_m = params.get("facade_width_m", 6.0)
    width_mm = width_m * 1000

    floor_heights = params.get("floor_heights_m", [3.0])
    if not isinstance(floor_heights, list) or not floor_heights:
        floor_heights = [3.0]

    total_height_m = sum(max(0.5, float(h)) for h in floor_heights if isinstance(h, (int, float)))
    total_height_mm = total_height_m * 1000

    # Party walls reduce visible brick area
    pw_left = params.get("party_wall_left", False)
    pw_right = params.get("party_wall_right", False)
    depth_m = params.get("facade_depth_m", 10.0)
    depth_mm = depth_m * 1000

    # Course height = brick height + mortar joint
    course_h = dims["brick_height_mm"] + dims["mortar_joint_mm"]

    # Stretcher length = brick length + mortar joint
    stretcher_unit = dims["brick_length_mm"] + dims["mortar_joint_mm"]
    # Header length = brick width + mortar joint
    header_unit = dims["brick_width_mm"] + dims["mortar_joint_mm"]

    # FRONT FACADE
    # Courses on front facade
    front_courses = int(total_height_mm / course_h)

    # Bricks per course (front)
    stretcher_per_course = int(width_mm / stretcher_unit)
    header_per_course = int(width_mm / header_unit)

    # Effective bricks per course based on bond pattern
    effective_per_course = (
        stretcher_per_course * bond["stretcher_ratio"] +
        header_per_course * bond["header_ratio"]
    )

    front_bricks = int(front_courses * effective_per_course)

    # WINDOW/DOOR DEDUCTIONS
    # Estimate opening area from windows_per_floor and door data
    wpf = params.get("windows_per_floor", [])
    win_w = params.get("window_width_m", 0.85)
    win_h = params.get("window_height_m", 1.3)
    total_window_area_mm2 = 0
    for count in wpf:
        if isinstance(count, (int, float)) and count > 0:
            total_window_area_mm2 += count * (win_w * 1000) * (win_h * 1000)

    door_count = params.get("door_count", 1) or 1
    door_w = 900  # mm
    door_h = 2200  # mm
    total_door_area_mm2 = door_count * door_w * door_h

    # Storefront deduction
    if params.get("has_storefront"):
        sf = params.get("storefront", {})
        sf_w = (sf.get("width_m", width_m * 0.85) if isinstance(sf, dict) else width_m * 0.85) * 1000
        sf_h = (sf.get("height_m", 3.5) if isinstance(sf, dict) else 3500)
        if isinstance(sf_h, (int, float)):
            sf_h = sf_h * 1000 if sf_h < 10 else sf_h
        total_window_area_mm2 += sf_w * sf_h

    # Brick area per brick face
    brick_face_area = dims["brick_length_mm"] * dims["brick_height_mm"]  # stretcher face
    opening_area = total_window_area_mm2 + total_door_area_mm2

    # Deduct openings
    bricks_in_openings = int(opening_area / brick_face_area) if brick_face_area > 0 else 0
    front_net = max(0, front_bricks - bricks_in_openings)

    # SIDE WALLS (only if no party wall)
    side_bricks = 0
    visible_sides = 0
    if not pw_left:
        visible_sides += 1
        side_courses = front_courses
        side_per_course = int(depth_mm / stretcher_unit) * bond["stretcher_ratio"] + \
                          int(depth_mm / header_unit) * bond["header_ratio"]
        side_bricks += int(side_courses * side_per_course)
    if not pw_right:
        visible_sides += 1
        side_courses = front_courses
        side_per_course = int(depth_mm / stretcher_unit) * bond["stretcher_ratio"] + \
                          int(depth_mm / header_unit) * bond["header_ratio"]
        side_bricks += int(side_courses * side_per_course)

    total_visible = front_net + side_bricks

    # TEXTURE SCALE (for Blender Brick Texture node)
    # The Brick Texture node scale parameter maps to real-world brick coursing
    # Scale = facade_height_in_blender_units / (number_of_courses * course_height_in_blender_units)
    blender_brick_scale = total_height_m / (front_courses * course_h / 1000) if front_courses > 0 else 1.0

    # Per-floor breakdown
    per_floor = []
    for i, fh in enumerate(floor_heights):
        if not isinstance(fh, (int, float)):
            continue
        fh_mm = fh * 1000
        fl_courses = int(fh_mm / course_h)
        fl_bricks = int(fl_courses * effective_per_course)
        # Deduct windows for this floor
        fl_win_count = wpf[i] if i < len(wpf) and isinstance(wpf[i], (int, float)) else 0
        fl_win_area = fl_win_count * (win_w * 1000) * (win_h * 1000)
        fl_deduct = int(fl_win_area / brick_face_area) if brick_face_area > 0 else 0
        fl_net = max(0, fl_bricks - fl_deduct)
        per_floor.append({
            "floor": i + 1,
            "height_m": round(fh, 2),
            "courses": fl_courses,
            "gross_bricks": fl_bricks,
            "window_deductions": fl_deduct,
            "net_bricks": fl_net,
        })

    return {
        "address": address,
        "era": era,
        "brick_dims": {
            "label": dims["label"],
            "length_mm": dims["brick_length_mm"],
            "width_mm": dims["brick_width_mm"],
            "height_mm": dims["brick_height_mm"],
            "mortar_joint_mm": dims["mortar_joint_mm"],
            "course_height_mm": course_h,
            "variation_mm": dims["variation_mm"],
            "colour_variation": dims["colour_variation"],
        },
        "bond_pattern": bond_name,
        "facade_width_m": width_m,
        "wall_height_m": round(total_height_m, 2),
        "front_facade": {
            "total_courses": front_courses,
            "bricks_per_course": round(effective_per_course, 1),
            "gross_bricks": front_bricks,
            "opening_deductions": bricks_in_openings,
            "net_bricks": front_net,
        },
        "side_walls": {
            "visible_sides": visible_sides,
            "total_bricks": side_bricks,
        },
        "total_visible_bricks": total_visible,
        "per_floor": per_floor,
        "texture_params": {
            "blender_brick_scale": round(blender_brick_scale, 4),
            "courses_per_metre": round(1000 / course_h, 2),
            "stretchers_per_metre": round(1000 / stretcher_unit, 2),
        },
        "party_walls": {
            "left": pw_left,
            "right": pw_right,
        },
    }


def main():
    parser = argparse.ArgumentParser(description="Brick count estimator")
    parser.add_argument("--street", help="Filter by street")
    parser.add_argument("--address", help="Single building address")
    parser.add_argument("--apply", action="store_true",
                        help="Write brick_geometry to param files")
    parser.add_argument("--csv", action="store_true",
                        help="Export CSV report")
    args = parser.parse_args()

    results = []
    files = []

    for f in sorted(PARAMS_DIR.glob("*.json")):
        if f.name.startswith("_"):
            continue
        data = json.loads(f.read_text(encoding="utf-8"))
        if data.get("skipped"):
            continue

        if args.address:
            name = data.get("building_name", "")
            if args.address.lower() not in name.lower():
                continue

        if args.street:
            street = data.get("site", {}).get("street", "")
            if args.street.lower() not in street.lower():
                continue

        result = count_bricks(data)
        if result:
            results.append(result)
            files.append((f, data))

    if not results:
        print("No brick buildings found matching criteria.")
        return

    # Apply to params
    if args.apply:
        applied = 0
        for (fpath, data), result in zip(files, results):
            fd = data.setdefault("facade_detail", {})
            if not isinstance(fd, dict):
                fd = {}
                data["facade_detail"] = fd

            fd["brick_length_mm"] = result["brick_dims"]["length_mm"]
            fd["brick_height_mm"] = result["brick_dims"]["height_mm"]
            fd["brick_width_mm"] = result["brick_dims"]["width_mm"]
            fd["mortar_joint_width_mm"] = result["brick_dims"]["mortar_joint_mm"]
            fd["course_height_mm"] = result["brick_dims"]["course_height_mm"]
            fd["brick_variation_mm"] = result["brick_dims"]["variation_mm"]
            fd["brick_colour_variation"] = result["brick_dims"]["colour_variation"]

            data["brick_geometry"] = {
                "total_visible_bricks": result["total_visible_bricks"],
                "front_net_bricks": result["front_facade"]["net_bricks"],
                "front_courses": result["front_facade"]["total_courses"],
                "bricks_per_course": result["front_facade"]["bricks_per_course"],
                "courses_per_metre": result["texture_params"]["courses_per_metre"],
                "blender_brick_scale": result["texture_params"]["blender_brick_scale"],
            }

            fpath.write_text(
                json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8"
            )
            applied += 1
        print(f"Applied brick geometry to {applied} buildings")

    # CSV export
    if args.csv:
        csv_path = ROOT / "outputs" / "brick_counts.csv"
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        with open(csv_path, "w", newline="", encoding="utf-8") as cf:
            w = csv.writer(cf)
            w.writerow([
                "address", "era", "width_m", "height_m", "bond",
                "brick_L_mm", "brick_H_mm", "mortar_mm",
                "front_courses", "per_course", "front_gross",
                "openings_deducted", "front_net", "side_bricks",
                "total_visible", "courses_per_m", "blender_scale"
            ])
            for r in results:
                w.writerow([
                    r["address"], r["era"], r["facade_width_m"], r["wall_height_m"],
                    r["bond_pattern"],
                    r["brick_dims"]["length_mm"], r["brick_dims"]["height_mm"],
                    r["brick_dims"]["mortar_joint_mm"],
                    r["front_facade"]["total_courses"],
                    r["front_facade"]["bricks_per_course"],
                    r["front_facade"]["gross_bricks"],
                    r["front_facade"]["opening_deductions"],
                    r["front_facade"]["net_bricks"],
                    r["side_walls"]["total_bricks"],
                    r["total_visible_bricks"],
                    r["texture_params"]["courses_per_metre"],
                    r["texture_params"]["blender_brick_scale"],
                ])
        print(f"CSV saved: {csv_path}")

    # Summary
    total_bricks = sum(r["total_visible_bricks"] for r in results)
    total_front = sum(r["front_facade"]["net_bricks"] for r in results)
    avg_per_building = total_bricks / len(results)
    avg_courses = sum(r["front_facade"]["total_courses"] for r in results) / len(results)

    print(f"\n=== Brick Count Estimate ===")
    print(f"Buildings analyzed: {len(results)}")
    print(f"Total visible bricks: {total_bricks:,}")
    print(f"  Front facades: {total_front:,}")
    print(f"  Side walls: {total_bricks - total_front:,}")
    print(f"Average per building: {avg_per_building:,.0f}")
    print(f"Average front courses: {avg_courses:.0f}")

    # By era
    print(f"\nBy era:")
    by_era = defaultdict(list)
    for r in results:
        by_era[r["era"] or "Unknown"].append(r)
    for era in sorted(by_era):
        era_results = by_era[era]
        era_total = sum(r["total_visible_bricks"] for r in era_results)
        era_avg = era_total / len(era_results)
        dims = era_results[0]["brick_dims"]
        print(f"  {era:15s}: {len(era_results):3d} buildings, "
              f"{era_total:>10,} bricks (avg {era_avg:,.0f}/bldg), "
              f"brick {dims['length_mm']}x{dims['height_mm']}mm + "
              f"{dims['mortar_joint_mm']}mm mortar")

    # Show a sample
    if args.address and results:
        r = results[0]
        print(f"\n--- Detail: {r['address']} ---")
        print(f"  Era: {r['era']} ({r['brick_dims']['label']})")
        print(f"  Brick: {r['brick_dims']['length_mm']}L x "
              f"{r['brick_dims']['height_mm']}H x "
              f"{r['brick_dims']['width_mm']}W mm")
        print(f"  Mortar: {r['brick_dims']['mortar_joint_mm']}mm")
        print(f"  Course height: {r['brick_dims']['course_height_mm']}mm")
        print(f"  Bond: {r['bond_pattern']}")
        print(f"  Facade: {r['facade_width_m']}m x {r['wall_height_m']}m")
        print(f"  Front: {r['front_facade']['total_courses']} courses x "
              f"{r['front_facade']['bricks_per_course']} bricks/course")
        print(f"  Front gross: {r['front_facade']['gross_bricks']:,}")
        print(f"  Opening deductions: {r['front_facade']['opening_deductions']:,}")
        print(f"  Front net: {r['front_facade']['net_bricks']:,}")
        print(f"  Side walls: {r['side_walls']['total_bricks']:,} "
              f"({r['side_walls']['visible_sides']} visible)")
        print(f"  TOTAL visible: {r['total_visible_bricks']:,}")
        print(f"\n  Blender texture scale: {r['texture_params']['blender_brick_scale']}")
        print(f"  Courses/metre: {r['texture_params']['courses_per_metre']}")
        print(f"  Stretchers/metre: {r['texture_params']['stretchers_per_metre']}")
        print(f"\n  Per floor:")
        for fl in r["per_floor"]:
            print(f"    Floor {fl['floor']}: {fl['height_m']}m, "
                  f"{fl['courses']} courses, "
                  f"{fl['net_bricks']} net bricks "
                  f"(-{fl['window_deductions']} windows)")

    # Save JSON report
    out = ROOT / "outputs" / "brick_counts.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nReport saved: {out}")


if __name__ == "__main__":
    main()
