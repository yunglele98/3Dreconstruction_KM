#!/usr/bin/env python3
"""Refine pole placements, hero routing, QA summary."""

from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
POLES = ROOT / "outputs" / "poles"
IN_CSV = POLES / "pole_instances_unreal_resolved_cm.csv"
OUT_CSV = POLES / "pole_instances_unreal_refined_cm.csv"
HERO_TXT = POLES / "hero_pole_types.txt"
SUMMARY = POLES / "pole_improvement_summary.json"
QA = POLES / "pole_placement_qa.md"


def unit(key: str) -> float:
    h = hashlib.sha1(key.encode("utf-8")).hexdigest()
    return int(h[:8], 16) / 0xFFFFFFFF


def main() -> int:
    with IN_CSV.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    counts = Counter(r["pole_key"] for r in rows)
    hero = [k for k, _ in counts.most_common(4)]

    dup = 0
    seen = set()
    for r in rows:
        inst = r["instance_id"]
        yaw = round(unit(inst) * 360.0, 2)
        scl = round(0.94 + unit(inst + "_s") * 0.12, 3)
        r["yaw_deg"] = f"{yaw:.2f}"
        r["uniform_scale"] = f"{scl:.3f}"
        if r["pole_key"] in hero:
            r["asset_path"] = f"/Game/Street/Pole/SM_{r['pole_key']}_HERO"
            r["lod_profile"] = "HERO"
        else:
            r["lod_profile"] = "STANDARD"
        key = (round(float(r["x_cm"]), 1), round(float(r["y_cm"]), 1))
        if key in seen:
            dup += 1
        seen.add(key)

    with OUT_CSV.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else [])
        w.writeheader()
        w.writerows(rows)

    HERO_TXT.write_text("\n".join(hero) + "\n", encoding="utf-8")
    summary = {"instances": len(rows), "hero_pole_types": hero, "duplicate_xy_points": dup}
    SUMMARY.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    QA.write_text(
        "\n".join(
            [
                "# Pole Placement QA",
                f"- Instances checked: {len(rows)}",
                f"- Hero pole types: {hero}",
                f"- Duplicate XY points (potential overlaps): {dup}",
                "- Deterministic yaw + scale jitter applied.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"[OK] Wrote {OUT_CSV}")
    print(f"[OK] Wrote {HERO_TXT}")
    print(f"[OK] Wrote {SUMMARY}")
    print(f"[OK] Wrote {QA}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
