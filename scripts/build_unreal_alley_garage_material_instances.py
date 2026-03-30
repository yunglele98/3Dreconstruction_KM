#!/usr/bin/env python3
"""Build Unreal material-instance assignment manifest for alley+garage assets."""

from __future__ import annotations

import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REFINED_CSV = ROOT / "outputs" / "alley_garages" / "alley_garage_instances_unreal_refined_cm.csv"
PROFILES_JSON = ROOT / "outputs" / "alley_garages" / "alley_garage_texture_profiles.json"
OUT_CSV = ROOT / "outputs" / "alley_garages" / "unreal_alley_garage_material_instances.csv"
OUT_MD = ROOT / "outputs" / "alley_garages" / "unreal_alley_garage_material_steps.md"


def key_to_profile(key: str) -> str:
    k = (key or "").lower()
    if "structured" in k:
        return "concrete_garage"
    if "garage" in k:
        return "rollup_metal_graffiti"
    if "graffiti" in k:
        return "graffiti_wall_masonry"
    if "chainlink" in k:
        return "chainlink_utility"
    if "green" in k:
        return "green_edge_planter"
    return "asphalt_wet_lane"


def main() -> int:
    rows = list(csv.DictReader(REFINED_CSV.open("r", encoding="utf-8", newline="")))
    prof_payload = json.loads(PROFILES_JSON.read_text(encoding="utf-8"))
    prof_idx = {p["profile"]: p for p in prof_payload["profiles"]}

    out_rows = []
    seen = set()
    for r in rows:
        key = r["alley_garage_key"]
        if key in seen:
            continue
        seen.add(key)
        profile = key_to_profile(key)
        p = prof_idx[profile]
        out_rows.append(
            {
                "alley_garage_key": key,
                "material_instance": f"MI_{key}_Kensington",
                "master_material": "/Game/Materials/M_Master_AlleyGarage",
                "texture_profile": profile,
                "base_color": p["base_color"],
                "accent_color": p["accent_color"],
                "roughness": p["roughness"],
                "metallic": p["metallic"],
                "normal_intensity": p["normal_intensity"],
                "grime_amount": p["grime_amount"],
                "wetness": p["wetness"],
                "decal_density": p["decal_density"],
            }
        )

    with OUT_CSV.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out_rows[0].keys()) if out_rows else [])
        w.writeheader()
        w.writerows(out_rows)

    OUT_MD.write_text(
        "\n".join(
            [
                "## Unreal Alley+Garage Material Steps",
                "1. Import or create `M_Master_AlleyGarage` with scalar/vector params listed in CSV.",
                "2. Create one material instance per `alley_garage_key` from the CSV rows.",
                "3. Assign each instance to matching static meshes in `/Game/Street/AlleyGarage/`.",
                "4. Use `wetness` + `grime_amount` as runtime blend controls for weather variants.",
                f"5. Source file: {OUT_CSV}",
                "",
            ]
        ),
        encoding="utf-8",
    )

    print(f"[OK] Wrote {OUT_CSV}")
    print(f"[OK] Wrote {OUT_MD}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
