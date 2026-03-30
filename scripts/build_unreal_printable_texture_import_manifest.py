#!/usr/bin/env python3
"""Build Unreal import manifest for printable feature decal textures."""

from __future__ import annotations

import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IN_DEC = ROOT / "outputs" / "printable_features" / "printable_decal_catalog.csv"
IN_PLACE = ROOT / "outputs" / "printable_features" / "unreal_printable_decal_placements.csv"
OUT_CSV = ROOT / "outputs" / "printable_features" / "unreal_printable_texture_import_manifest.csv"
OUT_MD = ROOT / "outputs" / "printable_features" / "unreal_printable_projection_integration.md"


def main() -> int:
    dec = list(csv.DictReader(IN_DEC.open("r", encoding="utf-8", newline="")))
    placements = list(csv.DictReader(IN_PLACE.open("r", encoding="utf-8", newline="")))

    uniq = {}
    for d in dec:
        decal_id = d["decal_id"]
        if decal_id in uniq:
            continue
        uniq[decal_id] = {
            "decal_id": decal_id,
            "category": d.get("category", "other_printable"),
            "source_texture_path": d["decal_texture_path"],
            "target_texture_asset": f"/Game/Street/Decals/Printable/T_{decal_id}",
            "target_material_instance": f"/Game/Street/Decals/Printable/MI_{decal_id}",
            "master_decal_material": "/Game/Street/Decals/M_PrintableProjection_Master",
            "alpha_usage": "Opacity Mask",
        }

    rows = list(uniq.values())
    with OUT_CSV.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else [])
        w.writeheader()
        if rows:
            w.writerows(rows)

    OUT_MD.write_text(
        "\n".join(
            [
                "## Unreal Printable Projection Integration",
                "",
                "Inputs:",
                "- Decal textures: outputs/printable_features/decals/extracted/*.png",
                "- Texture manifest: outputs/printable_features/unreal_printable_texture_import_manifest.csv",
                "- Placement manifest: outputs/printable_features/unreal_printable_decal_placements.csv",
                "",
                "Steps:",
                "1. Import textures into /Game/Street/Decals/Printable/Textures/.",
                "2. Create MI per decal from M_PrintableProjection_Master.",
                "3. Spawn decals using placement CSV fields (x_cm,y_cm,z_cm,yaw_deg,uniform_scale,opacity).",
                "4. Use target_surface_key to separate street sign vs shop sign vs mural pipelines.",
                "",
                f"Stats: {len(rows)} unique textures, {len(placements)} placements.",
                "",
            ]
        ),
        encoding="utf-8",
    )

    print(f"[OK] Wrote {OUT_CSV}")
    print(f"[OK] Wrote {OUT_MD}")
    print(f"[INFO] unique_textures={len(rows)} placements={len(placements)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
