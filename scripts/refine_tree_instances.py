#!/usr/bin/env python3
"""Refine Unreal tree instances for hero assets, QA, and unknown-species split."""

from __future__ import annotations

import csv
import hashlib
import json
import math
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TREES = ROOT / "outputs" / "trees"
IN_CSV = TREES / "tree_instances_unreal_resolved_cm.csv"
OUT_CSV = TREES / "tree_instances_unreal_refined_cm.csv"
HERO_TXT = TREES / "hero_species.txt"
SUMMARY_JSON = TREES / "tree_improvement_summary.json"
QA_MD = TREES / "tree_placement_qa.md"
MASTERS_DIR = TREES / "masters"

CONIFER_TOKENS = ("spruce", "pine", "cedar", "fir", "thuja", "picea", "pinus", "abies", "juniper")


def is_conifer(species_key: str) -> bool:
    key = (species_key or "").lower()
    return any(tok in key for tok in CONIFER_TOKENS)


def deterministic_unit(key: str) -> float:
    h = hashlib.sha1(key.encode("utf-8")).hexdigest()
    return int(h[:8], 16) / 0xFFFFFFFF


def nearest_known_species(rows: list[dict], idx: int, radius_cm: float = 2500.0) -> str | None:
    r = rows[idx]
    if r["species_key"] != "unknown_species":
        return None
    x = float(r["x_cm"])
    y = float(r["y_cm"])
    best = None
    best_d2 = float("inf")
    for j, other in enumerate(rows):
        if j == idx:
            continue
        sk = other["species_key"]
        if sk == "unknown_species":
            continue
        dx = x - float(other["x_cm"])
        dy = y - float(other["y_cm"])
        d2 = dx * dx + dy * dy
        if d2 < best_d2:
            best_d2 = d2
            best = sk
    if best is None:
        return None
    if math.sqrt(best_d2) > radius_cm:
        return None
    return best


def main() -> int:
    with IN_CSV.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    hero_missing_assets = 0

    species_counts = Counter(r["species_key"] for r in rows)
    top_species = [k for k, _ in species_counts.most_common(12)]
    must_include = ["unknown_species", "blue_spruce", "white_spruce", "eastern_white_pine", "white_cedar"]
    for m in must_include:
        if m not in top_species and m in species_counts:
            top_species.append(m)

    unknown_split = Counter()
    for i, row in enumerate(rows):
        if row["species_key"] == "unknown_species":
            near = nearest_known_species(rows, i)
            if near and is_conifer(near):
                row["species_key"] = "unknown_evergreen"
            else:
                row["species_key"] = "unknown_deciduous"
            unknown_split[row["species_key"]] += 1

    # Recompute counts after unknown split.
    species_counts = Counter(r["species_key"] for r in rows)
    top_species = [k for k, _ in species_counts.most_common(14)]
    for m in ["unknown_deciduous", "unknown_evergreen", "blue_spruce", "white_spruce", "eastern_white_pine", "white_cedar"]:
        if m in species_counts and m not in top_species:
            top_species.append(m)

    # Deterministic orientation + subtle scale jitter.
    overlaps = 0
    points = {}
    for row in rows:
        inst = row["instance_id"]
        unit = deterministic_unit(inst)
        yaw = round(unit * 360.0, 2)
        base_scale = float(row.get("uniform_scale", "1.0") or 1.0)
        jitter = 0.92 + deterministic_unit(inst + "_scale") * 0.16  # 0.92..1.08
        scale = round(base_scale * jitter, 3)
        row["yaw_deg"] = f"{yaw:.2f}"
        row["uniform_scale"] = f"{scale:.3f}"

        sk = row["species_key"]
        if sk in top_species:
            hero_fbx = MASTERS_DIR / f"SM_{sk}_HERO.fbx"
            if hero_fbx.exists():
                row["asset_path"] = f"/Game/Foliage/Trees/SM_{sk}_HERO"
            else:
                hero_missing_assets += 1
        else:
            # Keep existing resolved path.
            pass

        key = (round(float(row["x_cm"]), 1), round(float(row["y_cm"]), 1))
        if key in points:
            overlaps += 1
        else:
            points[key] = True

    # Write refined CSV.
    fieldnames = list(rows[0].keys()) if rows else []
    with OUT_CSV.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    HERO_TXT.write_text("\n".join(top_species) + "\n", encoding="utf-8")

    scale_vals = [float(r["uniform_scale"]) for r in rows]
    summary = {
        "instances": len(rows),
        "hero_species_count": len(top_species),
        "hero_species": top_species,
        "hero_asset_missing_instances": hero_missing_assets,
        "unknown_split": dict(unknown_split),
        "scale_min": min(scale_vals) if scale_vals else None,
        "scale_max": max(scale_vals) if scale_vals else None,
        "duplicate_xy_points": overlaps,
    }
    SUMMARY_JSON.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    qa = [
        "# Tree Placement QA",
        f"- Instances checked: {len(rows)}",
        f"- Unknown split: {dict(unknown_split)}",
        f"- HERO reroute skipped (missing HERO FBX): {hero_missing_assets} instances",
        f"- Scale range after jitter: {summary['scale_min']} .. {summary['scale_max']}",
        f"- Duplicate XY points (potential overlaps): {overlaps}",
        "- Yaw values set deterministically per instance_id.",
        "- Top species rerouted to HERO assets.",
    ]
    QA_MD.write_text("\n".join(qa) + "\n", encoding="utf-8")

    print(f"[OK] Wrote {OUT_CSV}")
    print(f"[OK] Wrote {HERO_TXT}")
    print(f"[OK] Wrote {SUMMARY_JSON}")
    print(f"[OK] Wrote {QA_MD}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
