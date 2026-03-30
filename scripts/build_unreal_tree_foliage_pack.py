#!/usr/bin/env python3
"""Build Unreal foliage-type setup pack for tree assets."""

from __future__ import annotations

import csv
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TREES = ROOT / "outputs" / "trees"
DEMO_PACK = TREES / "demo_level_pack"
OUT_DIR = TREES / "foliage_pack"

SPECIES_MANIFEST = DEMO_PACK / "tree_demo_species_manifest.csv"
OUT_FOLIAGE_CSV = OUT_DIR / "tree_foliage_types_manifest.csv"
OUT_UNREAL_PY = OUT_DIR / "create_tree_foliage_types.py"
OUT_README = OUT_DIR / "README_unreal_tree_foliage_pack.md"
OUT_SUMMARY = OUT_DIR / "tree_foliage_pack_summary.json"


CONIFER_HINTS = ("pine", "spruce", "cedar", "fir", "thuja", "picea", "abies", "taxus", "juniper")


def read_csv(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)


def is_conifer(species_key: str) -> bool:
    key = (species_key or "").lower()
    return any(h in key for h in CONIFER_HINTS)


def build_foliage_rows(species_rows: list[dict]) -> list[dict]:
    out = []
    for row in species_rows:
        sk = row["species_key"]
        asset_path = row["asset_path"]
        conifer = is_conifer(sk)
        out.append(
            {
                "species_key": sk,
                "asset_path": asset_path,
                "foliage_type_asset": f"/Game/Foliage/Types/FT_{sk}",
                "radius_cm": "80" if conifer else "95",
                "shade_radius_cm": "120" if conifer else "140",
                "scale_x_min": "0.90",
                "scale_x_max": "1.15",
                "scale_y_min": "0.90",
                "scale_y_max": "1.15",
                "scale_z_min": "0.95" if conifer else "0.90",
                "scale_z_max": "1.20" if conifer else "1.18",
                "align_to_normal": "true",
                "random_yaw": "true",
                "ground_slope_min": "0",
                "ground_slope_max": "35",
                "height_min_cm": "-200",
                "height_max_cm": "4000",
                "cull_start_cm": "12000" if conifer else "10000",
                "cull_end_cm": "22000" if conifer else "20000",
                "cast_shadow": "true",
                "receives_decals": "false",
                "mobility": "Static",
                "wind_profile": "conifer_soft" if conifer else "broadleaf_medium",
            }
        )
    return out


def build_unreal_script() -> str:
    return """# Unreal Editor Python: create/update FoliageType assets from CSV.
import csv
import unreal

CSV_PATH = r"tree_foliage_types_manifest.csv"  # set absolute path
DEST_PATH = "/Game/Foliage/Types"

asset_tools = unreal.AssetToolsHelpers.get_asset_tools()


def as_bool(v: str) -> bool:
    return str(v).strip().lower() in {"1", "true", "yes", "y"}


def get_or_create_foliage_type(asset_name: str):
    full = f"{DEST_PATH}/{asset_name}"
    if unreal.EditorAssetLibrary.does_asset_exist(full):
        return unreal.EditorAssetLibrary.load_asset(full)
    factory = unreal.FoliageType_InstancedStaticMeshFactory()
    return asset_tools.create_asset(asset_name, DEST_PATH, unreal.FoliageType_InstancedStaticMesh, factory)


def apply_row(ft, mesh, row):
    ft.set_editor_property("mesh", mesh)
    ft.set_editor_property("radius", float(row["radius_cm"]))
    ft.set_editor_property("shade_radius", float(row["shade_radius_cm"]))
    ft.set_editor_property("align_to_normal", as_bool(row["align_to_normal"]))
    ft.set_editor_property("random_yaw", as_bool(row["random_yaw"]))
    ft.set_editor_property("ground_slope_angle", unreal.FloatInterval(float(row["ground_slope_min"]), float(row["ground_slope_max"])))
    ft.set_editor_property("height", unreal.FloatInterval(float(row["height_min_cm"]), float(row["height_max_cm"])))
    ft.set_editor_property("scale_x", unreal.FloatInterval(float(row["scale_x_min"]), float(row["scale_x_max"])))
    ft.set_editor_property("scale_y", unreal.FloatInterval(float(row["scale_y_min"]), float(row["scale_y_max"])))
    ft.set_editor_property("scale_z", unreal.FloatInterval(float(row["scale_z_min"]), float(row["scale_z_max"])))
    ft.set_editor_property("cull_distance", unreal.Int32Interval(int(float(row["cull_start_cm"])), int(float(row["cull_end_cm"]))))
    ft.set_editor_property("cast_shadow", as_bool(row["cast_shadow"]))
    ft.set_editor_property("receives_decals", as_bool(row["receives_decals"]))


with open(CSV_PATH, "r", encoding="utf-8", newline="") as f:
    for row in csv.DictReader(f):
        mesh = unreal.EditorAssetLibrary.load_asset(row["asset_path"])
        if not mesh:
            unreal.log_warning(f"Missing mesh: {row['asset_path']}")
            continue
        asset_name = row["foliage_type_asset"].split("/")[-1]
        ft = get_or_create_foliage_type(asset_name)
        if not ft:
            unreal.log_warning(f"Failed to create foliage type: {asset_name}")
            continue
        apply_row(ft, mesh, row)
        unreal.EditorAssetLibrary.save_asset(row["foliage_type_asset"])
        unreal.log(f"Updated {row['foliage_type_asset']}")

unreal.log("Tree foliage type generation complete.")
"""


def write_readme(count: int) -> str:
    return f"""## Unreal Tree Foliage Pack

Contains settings to create/update `FoliageType` assets for {count} species.

Files:
- `tree_foliage_types_manifest.csv`
- `create_tree_foliage_types.py`

Usage:
1. Ensure tree meshes are imported in `/Game/Foliage/Trees`.
2. Open `create_tree_foliage_types.py` in Unreal Python.
3. Set `CSV_PATH` to the absolute path of `tree_foliage_types_manifest.csv`.
4. Run script to create/update `/Game/Foliage/Types/FT_*` assets.
"""


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    species_rows = read_csv(SPECIES_MANIFEST)
    foliage_rows = build_foliage_rows(species_rows)
    write_csv(
        OUT_FOLIAGE_CSV,
        foliage_rows,
        [
            "species_key",
            "asset_path",
            "foliage_type_asset",
            "radius_cm",
            "shade_radius_cm",
            "scale_x_min",
            "scale_x_max",
            "scale_y_min",
            "scale_y_max",
            "scale_z_min",
            "scale_z_max",
            "align_to_normal",
            "random_yaw",
            "ground_slope_min",
            "ground_slope_max",
            "height_min_cm",
            "height_max_cm",
            "cull_start_cm",
            "cull_end_cm",
            "cast_shadow",
            "receives_decals",
            "mobility",
            "wind_profile",
        ],
    )
    OUT_UNREAL_PY.write_text(build_unreal_script(), encoding="utf-8")
    OUT_README.write_text(write_readme(len(foliage_rows)), encoding="utf-8")
    OUT_SUMMARY.write_text(
        json.dumps(
            {
                "species_count": len(foliage_rows),
                "out_dir": str(OUT_DIR.resolve()),
                "manifest": str(OUT_FOLIAGE_CSV.resolve()),
                "script": str(OUT_UNREAL_PY.resolve()),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"[OK] Wrote {OUT_FOLIAGE_CSV}")
    print(f"[OK] Wrote {OUT_UNREAL_PY}")
    print(f"[OK] Wrote {OUT_README}")
    print(f"[OK] Wrote {OUT_SUMMARY}")
    print(f"[DONE] species={len(foliage_rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
