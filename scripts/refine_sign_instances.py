#!/usr/bin/env python3
"""Refine sign instances: deterministic yaw/scale, hero routing, QA."""

from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DIR = ROOT / "outputs" / "signs"
IN_CSV = DIR / "sign_instances_unreal_resolved_cm.csv"
OUT_CSV = DIR / "sign_instances_unreal_refined_cm.csv"
HERO_TXT = DIR / "hero_sign_types.txt"
SUMMARY = DIR / "sign_improvement_summary.json"
QA = DIR / "sign_placement_qa.md"


def u(s: str) -> float:
    h = hashlib.sha1(s.encode("utf-8")).hexdigest()
    return int(h[:8], 16) / 0xFFFFFFFF


def main() -> int:
    with IN_CSV.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    counts = Counter(r["sign_key"] for r in rows)
    hero = [k for k, _ in counts.most_common(4)]
    dup = 0
    seen = set()
    for r in rows:
        inst = r["instance_id"]
        r["yaw_deg"] = f"{(round(u(inst) * 4) * 90.0):.2f}"
        base = float(r.get("uniform_scale", "1") or 1.0)
        r["uniform_scale"] = f"{base*(0.93 + u(inst+'_s')*0.14):.3f}"
        if r["sign_key"] in hero:
            r["asset_path"] = f"/Game/Street/Signs/SM_{r['sign_key']}_HERO"
            r["lod_profile"] = "HERO"
        else:
            r["lod_profile"] = "STANDARD"
        xy = (round(float(r["x_cm"]), 1), round(float(r["y_cm"]), 1))
        if xy in seen:
            dup += 1
        seen.add(xy)
    with OUT_CSV.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else [])
        w.writeheader(); w.writerows(rows)
    HERO_TXT.write_text("\n".join(hero) + "\n", encoding="utf-8")
    SUMMARY.write_text(json.dumps({"instances": len(rows), "hero_sign_types": hero, "duplicate_xy_points": dup}, indent=2), encoding="utf-8")
    QA.write_text(f"# Sign Placement QA\n- Instances checked: {len(rows)}\n- Hero sign types: {hero}\n- Duplicate XY points: {dup}\n- Deterministic yaw/scale applied.\n", encoding="utf-8")
    print(f"[OK] Wrote {OUT_CSV}")
    print(f"[OK] Wrote {HERO_TXT}")
    print(f"[OK] Wrote {SUMMARY}")
    print(f"[OK] Wrote {QA}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
