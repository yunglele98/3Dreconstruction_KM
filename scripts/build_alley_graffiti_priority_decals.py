#!/usr/bin/env python3
"""Build high-priority graffiti placements using extracted photo decals."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IN_INST = ROOT / "outputs" / "alley_garages" / "alley_garage_instances_unreal_refined_cm.csv"
IN_HOT = ROOT / "outputs" / "alley_garages" / "graffiti_hotspots.json"
IN_DECALS = ROOT / "outputs" / "alley_garages" / "graffiti_decal_catalog.csv"
OUT = ROOT / "outputs" / "alley_garages" / "unreal_alley_graffiti_priority_decals.csv"

STYLE_TO_KEYS = {
    "mural_figurative": {"alley_graffiti_wall", "alley_service_corridor"},
    "wall_tag_cluster": {"alley_graffiti_wall", "alley_service_corridor", "alley_shared_surface"},
    "rollup_throwup_cluster": {"garage_row_rollup_tagged", "garage_single_modern", "garage_residential_pair"},
    "tag_linework": {"garage_single_modern", "garage_row_rollup_tagged", "alley_service_corridor"},
    "alley_mixed_surface": {"alley_shared_surface", "alley_service_corridor", "alley_vehicle_concrete", "alley_vehicle_asphalt"},
    "generic_urban_marking": {"alley_service_corridor", "alley_shared_surface", "garage_single_modern"},
}


def u(seed: str) -> float:
    h = hashlib.sha1(seed.encode("utf-8")).hexdigest()
    return int(h[:8], 16) / 0xFFFFFFFF


def choose_decal(catalog: list[dict[str, str]], key: str, seed: str) -> dict[str, str]:
    if not catalog:
        return {}
    key = key.lower()
    filtered = []
    for d in catalog:
        style = (d.get("style") or "generic_urban_marking").strip()
        allowed = STYLE_TO_KEYS.get(style, STYLE_TO_KEYS["generic_urban_marking"])
        if key in allowed:
            filtered.append(d)
    pool = filtered if filtered else catalog
    idx = int(u(seed) * len(pool)) % len(pool)
    return pool[idx]


def main() -> int:
    rows = list(csv.DictReader(IN_INST.open("r", encoding="utf-8", newline="")))
    hotspots = json.loads(IN_HOT.read_text(encoding="utf-8")).get("hotspots", [])
    decals = list(csv.DictReader(IN_DECALS.open("r", encoding="utf-8", newline=""))) if IN_DECALS.exists() else []

    hot_strength = 0.0
    if hotspots:
        top = hotspots[0]
        hot_strength = min(1.0, float(top.get("priority_score", 0)) / 40.0)

    out_rows = []
    for r in rows:
        key = r["alley_garage_key"].lower()
        inst = r["instance_id"]

        is_surface = any(k in key for k in ["graffiti", "garage", "service_corridor", "shared_surface"])
        if not is_surface:
            continue

        prob = 0.30
        if "graffiti" in key:
            prob = 0.86
        elif "garage" in key:
            prob = 0.70
        prob = min(0.97, prob + 0.22 * hot_strength)
        if u(inst + "_p") > prob:
            continue

        x = float(r["x_cm"])
        y = float(r["y_cm"])

        layers = 1 + int(u(inst + "_layers") * 2.9)
        for i in range(layers):
            pick = choose_decal(decals, key, f"{inst}_{i}_pick")
            decal_id = pick.get("decal_id", "")
            tex = pick.get("decal_texture_path", "")
            style = pick.get("style", "generic_urban_marking")
            kind = "decal_graffiti_photo_projection"
            out_rows.append(
                {
                    "instance_id": inst,
                    "alley_garage_key": r["alley_garage_key"],
                    "decal_layer": i + 1,
                    "decal_type": kind,
                    "decal_id": decal_id,
                    "source_style": style,
                    "decal_texture_path": tex,
                    "decal_material": f"/Game/Street/Decals/MI_{kind}",
                    "x_cm": f"{x + (u(inst+str(i)+'x') - 0.5) * 120:.1f}",
                    "y_cm": f"{y + (u(inst+str(i)+'y') - 0.5) * 100:.1f}",
                    "z_cm": f"{10.0 + i * 8.0:.1f}",
                    "yaw_deg": f"{u(inst+str(i)+'yaw') * 360:.1f}",
                    "uniform_scale": f"{0.60 + u(inst+str(i)+'s') * 1.55:.3f}",
                    "opacity": f"{0.52 + u(inst+str(i)+'o') * 0.43:.3f}",
                }
            )

    fieldnames = [
        "instance_id",
        "alley_garage_key",
        "decal_layer",
        "decal_type",
        "decal_id",
        "source_style",
        "decal_texture_path",
        "decal_material",
        "x_cm",
        "y_cm",
        "z_cm",
        "yaw_deg",
        "uniform_scale",
        "opacity",
    ]
    with OUT.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        if out_rows:
            w.writerows(out_rows)

    print(f"[OK] Wrote {OUT}")
    print(f"[INFO] graffiti_priority_decals={len(out_rows)}")
    print(f"[INFO] source_decals_used={len({r['decal_id'] for r in out_rows if r.get('decal_id')})}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
