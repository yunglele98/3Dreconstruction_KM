#!/usr/bin/env python3
"""Build zone-level graffiti/detail presets from hotspot clusters."""

from __future__ import annotations

import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IN_HOT = ROOT / "outputs" / "alley_garages" / "graffiti_hotspots.json"
IN_SEM = ROOT / "outputs" / "alley_garages" / "graffiti_semantic_catalog.json"
OUT_JSON = ROOT / "outputs" / "alley_garages" / "graffiti_zone_presets.json"
OUT_CSV = ROOT / "outputs" / "alley_garages" / "graffiti_zone_presets.csv"


def zone_tier(priority: float) -> str:
    if priority >= 20:
        return "hero"
    if priority >= 8:
        return "high"
    if priority >= 3:
        return "medium"
    return "baseline"


def params_for_tier(tier: str):
    if tier == "hero":
        return dict(graffiti_density=0.92, decal_layers=4, grime_boost=0.22, roughness_shift=-0.06)
    if tier == "high":
        return dict(graffiti_density=0.78, decal_layers=3, grime_boost=0.16, roughness_shift=-0.03)
    if tier == "medium":
        return dict(graffiti_density=0.55, decal_layers=2, grime_boost=0.10, roughness_shift=0.00)
    return dict(graffiti_density=0.32, decal_layers=1, grime_boost=0.04, roughness_shift=0.03)


def main() -> int:
    hot = json.loads(IN_HOT.read_text(encoding="utf-8")).get("hotspots", [])
    sem = json.loads(IN_SEM.read_text(encoding="utf-8"))
    style_counts = sem.get("style_counts", {})

    dominant_style = sorted(style_counts.items(), key=lambda kv: kv[1], reverse=True)[0][0] if style_counts else "alley_mixed_surface"

    rows = []
    for i, h in enumerate(hot, start=1):
        p = float(h.get("priority_score", 0))
        tier = zone_tier(p)
        params = params_for_tier(tier)
        rows.append(
            {
                "zone_id": f"GZ_{i:02d}",
                "lat": h.get("lat"),
                "lon": h.get("lon"),
                "tier": tier,
                "priority_score": p,
                "dominant_style": dominant_style,
                "photo_count": h.get("photo_count"),
                **params,
                "sample_files": h.get("sample_files", ""),
            }
        )

    OUT_JSON.write_text(json.dumps({"zones": rows}, indent=2), encoding="utf-8")

    with OUT_CSV.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else ["zone_id", "lat", "lon", "tier", "priority_score", "dominant_style", "photo_count", "graffiti_density", "decal_layers", "grime_boost", "roughness_shift", "sample_files"])
        w.writeheader()
        if rows:
            w.writerows(rows)

    print(f"[OK] Wrote {OUT_JSON}")
    print(f"[OK] Wrote {OUT_CSV}")
    print(f"[INFO] zones={len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
