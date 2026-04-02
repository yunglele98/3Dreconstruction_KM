#!/usr/bin/env python3
"""Generate per-building Megascans material assignments for UE5.

Reads building params and the Megascans material map to produce:
- Per-building material instance assignments
- Material Instance Dynamic (MID) parameter overrides for colour tinting
- LAB colour distance scores for quality checking

Uses the existing map_megascans_materials.py library mapping and extends it
with UE5-specific Material Instance configuration.

Usage:
    python scripts/unreal/assign_megascans.py
    python scripts/unreal/assign_megascans.py --output outputs/unreal/megascans_assignments.json
"""
import argparse
import json
import math
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).parent.parent.parent
PARAMS_DIR = REPO / "params"

# Import the existing Megascans map
import sys
sys.path.insert(0, str(REPO / "scripts"))
try:
    from map_megascans_materials import MEGASCANS_MATERIALS
except ImportError:
    MEGASCANS_MATERIALS = {}


def hex_to_lab(hex_str):
    """Convert hex colour to CIE LAB for perceptual distance."""
    hex_str = hex_str.lstrip("#")
    if len(hex_str) != 6:
        return (50, 0, 0)
    r = int(hex_str[0:2], 16) / 255.0
    g = int(hex_str[2:4], 16) / 255.0
    b = int(hex_str[4:6], 16) / 255.0

    # sRGB to linear
    def linearize(c):
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = linearize(r), linearize(g), linearize(b)

    # Linear RGB to XYZ (D65)
    x = 0.4124564 * r + 0.3575761 * g + 0.1804375 * b
    y = 0.2126729 * r + 0.7151522 * g + 0.0721750 * b
    z = 0.0193339 * r + 0.1191920 * g + 0.9503041 * b

    # XYZ to LAB
    xn, yn, zn = 0.95047, 1.0, 1.08883

    def f(t):
        return t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116

    fx, fy, fz = f(x / xn), f(y / yn), f(z / zn)
    L = 116 * fy - 16
    a = 500 * (fx - fy)
    b_val = 200 * (fy - fz)
    return (L, a, b_val)


def lab_distance(lab1, lab2):
    """CIE76 colour distance (Delta E)."""
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(lab1, lab2)))


def find_best_megascans(facade_hex, material_type="brick"):
    """Find closest Megascans surface by LAB distance."""
    if not MEGASCANS_MATERIALS:
        return None, 999

    target_lab = hex_to_lab(facade_hex)
    best_id = None
    best_dist = float("inf")

    for mat_id, mat_info in MEGASCANS_MATERIALS.items():
        if material_type and mat_info.get("category", "") != material_type:
            continue
        mat_lab = hex_to_lab(mat_info["colour_hex"])
        dist = lab_distance(target_lab, mat_lab)
        if dist < best_dist:
            best_dist = dist
            best_id = mat_id

    # Fallback: search all categories if no match in target category
    if best_dist > 50:
        for mat_id, mat_info in MEGASCANS_MATERIALS.items():
            mat_lab = hex_to_lab(mat_info["colour_hex"])
            dist = lab_distance(target_lab, mat_lab)
            if dist < best_dist:
                best_dist = dist
                best_id = mat_id

    return best_id, best_dist


def generate_assignments(params_dir):
    """Generate per-building Megascans material assignments."""
    assignments = []

    for pf in sorted(params_dir.glob("*.json")):
        if pf.name.startswith("_"):
            continue
        try:
            params = json.loads(pf.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if params.get("skipped"):
            continue

        address = params.get("_meta", {}).get("address", pf.stem.replace("_", " "))
        facade_material = (params.get("facade_material") or "brick").lower()
        cp = params.get("colour_palette", {})
        if not isinstance(cp, dict):
            cp = {}
        primary = cp.get("primary", {})
        facade_hex = primary.get("hex_approx", "#B85A3A") if isinstance(primary, dict) else "#B85A3A"
        roof_val = cp.get("roof", {})
        roof_hex = roof_val.get("hex_approx", "#4A4A4A") if isinstance(roof_val, dict) else "#4A4A4A"

        # Map facade material to Megascans category
        category_map = {
            "brick": "brick",
            "stone": "stone",
            "stucco": "stucco",
            "clapboard": "wood",
            "vinyl": "painted",
            "wood": "wood",
            "concrete": "concrete",
        }
        category = category_map.get(facade_material, "brick")

        facade_match, facade_dist = find_best_megascans(facade_hex, category)
        roof_match, roof_dist = find_best_megascans(roof_hex, "")

        facade_info = MEGASCANS_MATERIALS.get(facade_match, {}) if facade_match else {}
        roof_info = MEGASCANS_MATERIALS.get(roof_match, {}) if roof_match else {}

        assignment = {
            "address": address,
            "facade": {
                "source_material": facade_material,
                "source_hex": facade_hex,
                "megascans_id": facade_match,
                "megascans_name": facade_info.get("name", ""),
                "megascans_surface_id": facade_info.get("surface_id", ""),
                "delta_e": round(facade_dist, 1),
                "quality": "exact" if facade_dist < 10 else "close" if facade_dist < 25 else "approximate",
                "ue_material_instance": f"/Game/Materials/MI_{facade_match}" if facade_match else None,
                "tint_override": facade_hex if facade_dist > 15 else None,
            },
            "roof": {
                "source_hex": roof_hex,
                "megascans_id": roof_match,
                "megascans_name": roof_info.get("name", ""),
                "delta_e": round(roof_dist, 1),
                "ue_material_instance": f"/Game/Materials/MI_{roof_match}" if roof_match else None,
            },
        }
        assignments.append(assignment)

    return assignments


def main():
    parser = argparse.ArgumentParser(description="Assign Megascans materials for UE5")
    parser.add_argument("--params", type=Path, default=PARAMS_DIR)
    parser.add_argument("--output", type=Path,
                        default=REPO / "outputs" / "unreal" / "megascans_assignments.json")
    args = parser.parse_args()

    assignments = generate_assignments(args.params)

    # Quality stats
    qualities = {"exact": 0, "close": 0, "approximate": 0}
    for a in assignments:
        q = a["facade"]["quality"]
        qualities[q] = qualities.get(q, 0) + 1

    config = {
        "_meta": {
            "generator": "kensington-pipeline",
            "generated_at": datetime.now().isoformat(),
            "megascans_library_size": len(MEGASCANS_MATERIALS),
        },
        "stats": {
            "total_buildings": len(assignments),
            "facade_quality": qualities,
            "avg_delta_e": round(sum(a["facade"]["delta_e"] for a in assignments) / max(len(assignments), 1), 1),
        },
        "assignments": assignments,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(config, indent=2), encoding="utf-8")
    print(f"Megascans assignments: {args.output}")
    print(f"  Buildings: {len(assignments)}")
    print(f"  Quality: exact={qualities['exact']}, close={qualities['close']}, approx={qualities['approximate']}")
    print(f"  Avg Delta-E: {config['stats']['avg_delta_e']}")


if __name__ == "__main__":
    main()
