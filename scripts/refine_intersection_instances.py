#!/usr/bin/env python3
"""Refine intersection instances with deterministic yaw/scale and HERO routing."""

from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DIR = ROOT / "outputs" / "intersections"
IN_CSV = DIR / "intersection_instances_unreal_resolved_cm.csv"
OUT_CSV = DIR / "intersection_instances_unreal_refined_cm.csv"
HERO_TXT = DIR / "hero_intersection_types.txt"
SUMMARY = DIR / "intersection_improvement_summary.json"
QA = DIR / "intersection_placement_qa.md"


def u(s: str) -> float:
    h = hashlib.sha1(s.encode("utf-8")).hexdigest()
    return int(h[:8], 16) / 0xFFFFFFFF


def main() -> int:
    with IN_CSV.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))

    counts = Counter(r["intersection_key"] for r in rows)
    hero = [k for k, _ in counts.most_common(3)]

    dup = 0
    seen = set()
    for r in rows:
        inst = r["instance_id"]
        r["yaw_deg"] = f"{(u(inst) * 360.0):.2f}"
        base = float(r.get("uniform_scale", "1") or 1.0)
        r["uniform_scale"] = f"{base * (0.92 + u(inst + '_s') * 0.16):.3f}"

        if r["intersection_key"] in hero:
            r["asset_path"] = f"/Game/Street/Intersections/SM_{r['intersection_key']}_HERO"
            r["lod_profile"] = "HERO"
        else:
            r["lod_profile"] = "STANDARD"

        xy = (round(float(r["x_cm"]), 1), round(float(r["y_cm"]), 1))
        if xy in seen:
            dup += 1
        seen.add(xy)

    with OUT_CSV.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else [])
        w.writeheader()
        w.writerows(rows)

    HERO_TXT.write_text("\n".join(hero) + "\n", encoding="utf-8")
    SUMMARY.write_text(
        json.dumps(
            {
                "instances": len(rows),
                "hero_types": hero,
                "duplicate_xy_points": dup,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    QA.write_text(
        "\n".join(
            [
                "# Intersection QA",
                f"- Instances checked: {len(rows)}",
                f"- Hero types: {hero}",
                f"- Duplicate XY points: {dup}",
                "- Deterministic yaw/scale applied.",
                "",
            ]
        ),
        encoding="utf-8",
    )

    print(f"[OK] Wrote {OUT_CSV}")
    print(f"[OK] Wrote {HERO_TXT}")
    print(f"[OK] Wrote {SUMMARY}")
    print(f"[OK] Wrote {QA}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
