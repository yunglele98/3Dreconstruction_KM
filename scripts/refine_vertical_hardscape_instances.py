#!/usr/bin/env python3
"""Refine vertical hardscape instances with deterministic orientation and QA."""

from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DIR = ROOT / "outputs" / "vertical_hardscape"
IN_CSV = DIR / "vertical_hardscape_instances_unreal_resolved_cm.csv"
OUT_CSV = DIR / "vertical_hardscape_instances_unreal_refined_cm.csv"
HERO_TXT = DIR / "hero_vertical_hardscape_types.txt"
SUMMARY = DIR / "vertical_hardscape_improvement_summary.json"
QA = DIR / "vertical_hardscape_placement_qa.md"


def u(s: str) -> float:
    h = hashlib.sha1(s.encode("utf-8")).hexdigest()
    return int(h[:8], 16) / 0xFFFFFFFF


def main() -> int:
    with IN_CSV.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    counts = Counter(r["hardscape_key"] for r in rows)
    hero = [k for k, _ in counts.most_common(5)]
    seen = set()
    dup = 0
    for r in rows:
        inst = r["instance_id"]
        r["yaw_deg"] = f"{(round(u(inst) * 4) * 90.0):.2f}"
        b = float(r.get("uniform_scale", "1") or 1)
        r["uniform_scale"] = f"{b*(0.93 + u(inst+'_s')*0.14):.3f}"
        if r["hardscape_key"] in hero:
            r["asset_path"] = f"/Game/Hardscape/Vertical/SM_{r['hardscape_key']}_HERO"
            r["lod_profile"] = "HERO"
        else:
            r["lod_profile"] = "STANDARD"
        key = (round(float(r["x_cm"]), 1), round(float(r["y_cm"]), 1), r["hardscape_key"])
        if key in seen:
            dup += 1
        seen.add(key)
    with OUT_CSV.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else [])
        w.writeheader(); w.writerows(rows)
    HERO_TXT.write_text("\n".join(hero) + "\n", encoding="utf-8")
    SUMMARY.write_text(json.dumps({"instances": len(rows), "hero_types": hero, "duplicate_same_type_points": dup}, indent=2), encoding="utf-8")
    QA.write_text(f"# Vertical Hardscape QA\n- Instances checked: {len(rows)}\n- Hero types: {hero}\n- Duplicate same-type points: {dup}\n- Deterministic yaw/scale applied.\n", encoding="utf-8")
    print(f"[OK] Wrote {OUT_CSV}")
    print(f"[OK] Wrote {HERO_TXT}")
    print(f"[OK] Wrote {SUMMARY}")
    print(f"[OK] Wrote {QA}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
