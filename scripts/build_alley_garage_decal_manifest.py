#!/usr/bin/env python3
"""Build decal placement manifest for alley+garage scene detailing."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IN_CSV = ROOT / "outputs" / "alley_garages" / "alley_garage_instances_unreal_refined_cm.csv"
OUT_CSV = ROOT / "outputs" / "alley_garages" / "unreal_alley_garage_decal_manifest.csv"


def u(seed: str) -> float:
    h = hashlib.sha1(seed.encode("utf-8")).hexdigest()
    return int(h[:8], 16) / 0xFFFFFFFF


def pick_decal(key: str, metadata: str) -> str:
    k = (key or "").lower()
    m = (metadata or "").lower()
    if "graffiti" in k or "graffiti" in m:
        return "decal_graffiti_tag_pack"
    if "degraded" in k or "critique" in m or "mauvais" in m:
        return "decal_crack_patch_pack"
    if "garage" in k:
        return "decal_oilstain_tiremark_pack"
    if "chainlink" in k:
        return "decal_rust_streak_pack"
    return "decal_wet_grime_pack"


def main() -> int:
    rows = list(csv.DictReader(IN_CSV.open("r", encoding="utf-8", newline="")))
    out_rows = []

    for r in rows:
        inst = r["instance_id"]
        key = r["alley_garage_key"]
        meta = r.get("metadata_json") or ""

        # Keep density controlled but richer on target types.
        p = u(inst + key)
        threshold = 0.38
        if "garage" in key or "graffiti" in key:
            threshold = 0.72
        elif "degraded" in key:
            threshold = 0.62
        if p > threshold:
            continue

        x = float(r["x_cm"])
        y = float(r["y_cm"])
        d = pick_decal(key, meta)
        out_rows.append(
            {
                "instance_id": inst,
                "alley_garage_key": key,
                "decal_type": d,
                "decal_material": f"/Game/Street/Decals/MI_{d}",
                "x_cm": f"{x + (u(inst + 'x') - 0.5) * 140:.1f}",
                "y_cm": f"{y + (u(inst + 'y') - 0.5) * 140:.1f}",
                "z_cm": "1.0",
                "yaw_deg": f"{u(inst + 'yaw') * 360.0:.1f}",
                "uniform_scale": f"{0.8 + u(inst + 's') * 1.2:.3f}",
            }
        )

    with OUT_CSV.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out_rows[0].keys()) if out_rows else [])
        w.writeheader()
        w.writerows(out_rows)

    print(f"[OK] Wrote {OUT_CSV}")
    print(f"[INFO] decal_count={len(out_rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
