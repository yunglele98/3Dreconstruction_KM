#!/usr/bin/env python3
"""Refine ground instances with deterministic orientation, hero routing, QA."""

from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DIR = ROOT / "outputs" / "ground"
IN_CSV = DIR / "ground_instances_unreal_resolved_cm.csv"
OUT_CSV = DIR / "ground_instances_unreal_refined_cm.csv"
HERO_TXT = DIR / "hero_ground_types.txt"
SUMMARY = DIR / "ground_improvement_summary.json"
QA = DIR / "ground_placement_qa.md"


def u(s: str) -> float:
    h = hashlib.sha1(s.encode("utf-8")).hexdigest()
    return int(h[:8], 16) / 0xFFFFFFFF


def main() -> int:
    with IN_CSV.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    counts = Counter(r["ground_key"] for r in rows)
    hero = [k for k, _ in counts.most_common(8)]
    seen = set()
    dup = 0
    for r in rows:
        inst = r["instance_id"]
        g = r["ground_key"]
        if "decal" in g:
            yaw = u(inst) * 360.0
        elif g in {"manhole_cover", "storm_drain"}:
            yaw = round(u(inst) * 4) * 90.0
        else:
            yaw = round(u(inst) * 2) * 180.0
        r["yaw_deg"] = f"{yaw:.2f}"
        base = float(r.get("uniform_scale", "1") or 1)
        r["uniform_scale"] = f"{base*(0.92 + u(inst+'_s')*0.18):.3f}"
        if g in hero:
            r["asset_path"] = f"/Game/Ground/SM_{g}_HERO"
            r["lod_profile"] = "HERO"
        else:
            r["lod_profile"] = "STANDARD"
        xy = (round(float(r["x_cm"]), 1), round(float(r["y_cm"]), 1), g)
        if xy in seen:
            dup += 1
        seen.add(xy)

    with OUT_CSV.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else [])
        w.writeheader(); w.writerows(rows)
    HERO_TXT.write_text("\n".join(hero) + "\n", encoding="utf-8")
    SUMMARY.write_text(json.dumps({"instances": len(rows), "hero_ground_types": hero, "duplicate_points_same_type": dup}, indent=2), encoding="utf-8")
    QA.write_text(f"# Ground Placement QA\n- Instances checked: {len(rows)}\n- Hero ground types: {hero}\n- Duplicate same-type points: {dup}\n- Deterministic yaw/scale applied.\n", encoding="utf-8")
    print(f"[OK] Wrote {OUT_CSV}")
    print(f"[OK] Wrote {HERO_TXT}")
    print(f"[OK] Wrote {SUMMARY}")
    print(f"[OK] Wrote {QA}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
