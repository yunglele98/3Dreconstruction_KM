#!/usr/bin/env python3
"""Build Unreal import manifest for extracted graffiti texture decals."""

from __future__ import annotations

import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IN_CSV = ROOT / "outputs" / "alley_garages" / "graffiti_decal_catalog.csv"
OUT_CSV = ROOT / "outputs" / "alley_garages" / "unreal_graffiti_texture_import_manifest.csv"
OUT_MD = ROOT / "outputs" / "alley_garages" / "unreal_graffiti_projection_integration.md"


def main() -> int:
    rows = list(csv.DictReader(IN_CSV.open("r", encoding="utf-8", newline="")))
    uniq = {}
    for r in rows:
        decal_id = r["decal_id"]
        src = r["decal_texture_path"]
        if decal_id in uniq:
            continue
        uniq[decal_id] = {
            "decal_id": decal_id,
            "source_texture_path": src,
            "target_texture_asset": f"/Game/Street/Decals/Graffiti/T_{decal_id}",
            "target_material_instance": f"/Game/Street/Decals/Graffiti/MI_{decal_id}",
            "master_decal_material": "/Game/Street/Decals/M_GraffitiProjection_Master",
            "compression": "Default (sRGB ON)",
            "alpha_usage": "Opacity Mask",
        }

    out_rows = list(uniq.values())
    with OUT_CSV.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out_rows[0].keys()) if out_rows else [])
        w.writeheader()
        if out_rows:
            w.writerows(out_rows)

    OUT_MD.write_text(
        "\n".join(
            [
                "## Unreal Graffiti Projection Integration",
                "",
                "### Inputs",
                "- Extracted textures: `outputs/alley_garages/graffiti_decals/extracted/*.png`",
                "- Texture import manifest: `outputs/alley_garages/unreal_graffiti_texture_import_manifest.csv`",
                "- Wall projection placements: `outputs/alley_garages/unreal_alley_graffiti_priority_decals.csv`",
                "",
                "### Import Steps",
                "1. Bulk import all extracted PNGs to `/Game/Street/Decals/Graffiti/Textures/`.",
                "2. Create one material instance per decal using `M_GraffitiProjection_Master`.",
                "3. In each MI set:",
                "   - `Texture` = imported decal texture",
                "   - `BlendMode` = Translucent or Masked (based on master)",
                "   - `Opacity` from alpha",
                "4. Spawn decal actors using `unreal_alley_graffiti_priority_decals.csv`:",
                "   - `x_cm,y_cm,z_cm` world placement",
                "   - `yaw_deg,uniform_scale,opacity` per actor",
                "   - `decal_id` resolves the MI",
                "5. Optional: route hero-zone decals first (from `graffiti_zone_presets.json`).",
                "",
                "### Runtime Blend",
                "- Combine with `unreal_alley_runtime_overrides.csv` for wetness/grime/decal intensity.",
                "- Suggested scalar chain in master:",
                "  `FinalOpacity = Alpha * OpacityParam * DecalIntensityOverride`.",
                "",
            ]
        ),
        encoding="utf-8",
    )

    print(f"[OK] Wrote {OUT_CSV}")
    print(f"[OK] Wrote {OUT_MD}")
    print(f"[INFO] unique_textures={len(out_rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
