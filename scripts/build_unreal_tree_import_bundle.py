#!/usr/bin/env python3
"""Build Unreal import bundle from exported tree data + generated FBX masters.

Outputs:
- outputs/trees/unreal_import_manifest.csv
- outputs/trees/tree_instances_unreal_resolved_cm.csv
- outputs/trees/unreal_import_steps.md
"""

from __future__ import annotations

import csv
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TREES_DIR = ROOT / "outputs" / "trees"
MASTERS_DIR = TREES_DIR / "masters"

INPUT_INSTANCES = TREES_DIR / "tree_instances_unreal_cm.csv"
OUT_MANIFEST = TREES_DIR / "unreal_import_manifest.csv"
OUT_RESOLVED = TREES_DIR / "tree_instances_unreal_resolved_cm.csv"
OUT_STEPS = TREES_DIR / "unreal_import_steps.md"


ALIAS_TO_MASTER = {
    # Existing exact masters.
    "tilia_cordata": "tilia",
    "ulmus_americana": "ulmus",
    "ulmus_pumila": "ulmus",
    "gleditsia_triacanthos_f_inermis_skyline": "gleditsia_triacanthos",
    "gleditsia_triacanthos_f_inermis_ruby_lace": "gleditsia_triacanthos",
    "acer_platanoides_crimson_king": "acer_platanoides",
    "acer_platanoides_columnare": "acer_platanoides",
    "acer_platanoides_emerald_queen": "acer_platanoides",
    "acer_platanoides_schwedleri": "acer_platanoides",
    "acer_x_freemanii_a_rubrum_x_saccharinum_autumn_blaze": "acer_saccharinum",
    "pinus_nigra": "eastern_white_pine",
}


GENUS_TO_MASTER = {
    "acer_": "acer_platanoides",
    "ulmus_": "ulmus",
    "tilia_": "tilia",
    "gleditsia_": "gleditsia_triacanthos",
    "platanus_": "platanus_x_acerifolia",
    "quercus_": "quercus_rubra",
    "pinus_": "eastern_white_pine",
    "picea_": "white_spruce",
    "thuja_": "white_cedar",
}


def resolve_asset_path(species_key: str) -> tuple[str, str, str]:
    """Return (resolved_asset_path, source_fbx_name, resolution_status)."""
    preferred = f"SM_{species_key}_A_mature.fbx"
    if (MASTERS_DIR / preferred).exists():
        return f"/Game/Foliage/Trees/SM_{species_key}_A_mature", preferred, "exact_master"

    alias_key = ALIAS_TO_MASTER.get(species_key, species_key)
    if alias_key != species_key:
        preferred = f"SM_{alias_key}_A_mature.fbx"
        if (MASTERS_DIR / preferred).exists():
            return f"/Game/Foliage/Trees/SM_{alias_key}_A_mature", preferred, "alias_master"

    for prefix, master in GENUS_TO_MASTER.items():
        if species_key.startswith(prefix):
            preferred = f"SM_{master}_A_mature.fbx"
            if (MASTERS_DIR / preferred).exists():
                return f"/Game/Foliage/Trees/SM_{master}_A_mature", preferred, "alias_genus"

    # Fallback groupings for now.
    evergreen_fallback = "SM_white_spruce_B_medium.fbx"
    deciduous_fallback = "SM_acer_A_mature.fbx"
    if any(k in species_key for k in ("spruce", "pine", "cedar", "fir", "thuja")):
        return "/Game/Foliage/Trees/SM_white_spruce_B_medium", evergreen_fallback, "fallback_evergreen"
    return "/Game/Foliage/Trees/SM_acer_A_mature", deciduous_fallback, "fallback_deciduous"


def build_manifest(species_keys: list[str]) -> list[dict]:
    out = []
    for species_key in sorted(set(species_keys)):
        resolved_asset_path, fbx_name, status = resolve_asset_path(species_key)
        source_path = (MASTERS_DIR / fbx_name).resolve()
        if not source_path.exists():
            resolved_asset_path = "/Game/Foliage/Trees/SM_acer_A_mature"
            fbx_name = "SM_acer_A_mature.fbx"
            source_path = (MASTERS_DIR / fbx_name).resolve()
            status = "fallback_missing_source"
        out.append(
            {
                "species_key": species_key,
                "resolved_asset_path": resolved_asset_path,
                "source_fbx": str(source_path),
                "resolution_status": status,
            }
        )
    return out


def main() -> int:
    if not INPUT_INSTANCES.exists():
        raise FileNotFoundError(f"Missing input: {INPUT_INSTANCES}")

    with INPUT_INSTANCES.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))

    species_keys = [r.get("species_key", "").strip() for r in rows if r.get("species_key")]
    manifest = build_manifest(species_keys)
    manifest_index = {m["species_key"]: m for m in manifest}

    with OUT_MANIFEST.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["species_key", "resolved_asset_path", "source_fbx", "resolution_status"],
        )
        writer.writeheader()
        writer.writerows(manifest)

    resolved_rows = []
    for row in rows:
        species_key = row.get("species_key", "").strip()
        resolved = manifest_index.get(species_key)
        out = dict(row)
        out["asset_path"] = resolved["resolved_asset_path"] if resolved else row.get("asset_path", "")
        out["resolution_status"] = resolved["resolution_status"] if resolved else "unresolved"
        resolved_rows.append(out)

    fieldnames = list(rows[0].keys()) + ["resolution_status"] if rows else []
    with OUT_RESOLVED.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(resolved_rows)

    exact_count = sum(1 for m in manifest if m["resolution_status"] == "exact_master")
    alias_master_count = sum(1 for m in manifest if m["resolution_status"] == "alias_master")
    alias_genus_count = sum(1 for m in manifest if m["resolution_status"] == "alias_genus")
    fallback_count = sum(
        1
        for m in manifest
        if m["resolution_status"] in {"fallback_deciduous", "fallback_evergreen", "fallback_missing_source"}
    )
    mapped_total = exact_count + alias_master_count + alias_genus_count

    steps = f"""## Unreal Import Steps (Generated)

1. In Unreal Content Browser, create folder: `/Game/Foliage/Trees/`.
2. Import FBX files listed in:
   - `{OUT_MANIFEST}`
3. Keep imported asset names matching `resolved_asset_path` basenames.
4. Create foliage types for those meshes.
5. Spawn instances using:
   - `{OUT_RESOLVED}`

Resolution summary:
- species with exact masters: {exact_count}
- species mapped via alias masters: {alias_master_count}
- species mapped via genus masters: {alias_genus_count}
- species still using fallback masters: {fallback_count}
- total mapped without fallback: {mapped_total}
"""
    OUT_STEPS.write_text(steps, encoding="utf-8")

    print(f"[OK] Wrote {OUT_MANIFEST}")
    print(f"[OK] Wrote {OUT_RESOLVED}")
    print(f"[OK] Wrote {OUT_STEPS}")
    print(f"      species total: {len(manifest)}")
    print(
        "      exact: {0}, alias_master: {1}, alias_genus: {2}, fallback: {3}".format(
            exact_count, alias_master_count, alias_genus_count, fallback_count
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
