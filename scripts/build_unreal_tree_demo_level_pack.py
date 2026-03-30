#!/usr/bin/env python3
"""Build an Unreal-ready tree demo level pack."""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TREES_DIR = ROOT / "outputs" / "trees"
PACK_DIR = TREES_DIR / "demo_level_pack"

CATALOG_JSON = TREES_DIR / "tree_catalog.json"
IMPORT_MANIFEST_CSV = TREES_DIR / "unreal_import_manifest.csv"
DEMOS_MANIFEST_CSV = TREES_DIR / "demos" / "species" / "tree_species_demos_manifest.csv"
REFINED_INSTANCES_CSV = TREES_DIR / "tree_instances_unreal_refined_cm.csv"

OUT_SPECIES_MANIFEST = PACK_DIR / "tree_demo_species_manifest.csv"
OUT_GRID_LAYOUT = PACK_DIR / "tree_demo_grid_layout_cm.csv"
OUT_REAL_SAMPLE = PACK_DIR / "tree_demo_real_sample_cm.csv"
OUT_METADATA = PACK_DIR / "tree_demo_level_metadata.json"
OUT_UNREAL_SCRIPT = PACK_DIR / "spawn_tree_demo_level.py"
OUT_STEPS = PACK_DIR / "README_unreal_tree_demo_level.md"


def read_csv(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)


def build_species_manifest() -> list[dict]:
    catalog_data = json.loads(CATALOG_JSON.read_text(encoding="utf-8"))
    catalog = {x["species_key"]: x for x in catalog_data.get("catalog", [])}
    import_manifest = {x["species_key"]: x for x in read_csv(IMPORT_MANIFEST_CSV)}
    demos_manifest = {x["species_key"]: x for x in read_csv(DEMOS_MANIFEST_CSV)}

    out = []
    for species_key in sorted(catalog.keys()):
        c = catalog[species_key]
        im = import_manifest.get(species_key, {})
        dm = demos_manifest.get(species_key, {})
        out.append(
            {
                "species_key": species_key,
                "scientific_name": c.get("scientific_name", ""),
                "instances": int(c.get("instances", 0)),
                "asset_path": im.get("resolved_asset_path", ""),
                "resolution_status": im.get("resolution_status", ""),
                "source_fbx": im.get("source_fbx", ""),
                "demo_png": dm.get("demo_png", ""),
                "demo_status": dm.get("status", ""),
            }
        )
    return out


def build_grid_layout(species_rows: list[dict]) -> list[dict]:
    ordered = sorted(
        species_rows,
        key=lambda r: (-int(r["instances"]), r["species_key"]),
    )
    n = len(ordered)
    cols = max(1, math.ceil(math.sqrt(n)))
    spacing_cm = 1800.0
    start_x = 0.0
    start_y = 0.0

    out = []
    for idx, row in enumerate(ordered):
        col = idx % cols
        r = idx // cols
        x_cm = start_x + col * spacing_cm
        y_cm = start_y + r * spacing_cm
        out.append(
            {
                "species_key": row["species_key"],
                "asset_path": row["asset_path"],
                "x_cm": f"{x_cm:.1f}",
                "y_cm": f"{y_cm:.1f}",
                "z_cm": "0.0",
                "yaw_deg": f"{(idx * 17) % 360:.1f}",
                "pitch_deg": "0.0",
                "roll_deg": "0.0",
                "uniform_scale": "1.000",
                "demo_label": row["scientific_name"] or row["species_key"],
            }
        )
    return out


def build_real_sample(limit: int = 220) -> list[dict]:
    rows = read_csv(REFINED_INSTANCES_CSV)
    rows = sorted(rows, key=lambda r: r.get("instance_id", ""))[:limit]
    out = []
    for r in rows:
        out.append(
            {
                "instance_id": r.get("instance_id", ""),
                "species_key": r.get("species_key", ""),
                "asset_path": r.get("asset_path", ""),
                "x_cm": r.get("x_cm", ""),
                "y_cm": r.get("y_cm", ""),
                "z_cm": r.get("z_cm", ""),
                "yaw_deg": r.get("yaw_deg", "0"),
                "pitch_deg": r.get("pitch_deg", "0"),
                "roll_deg": r.get("roll_deg", "0"),
                "uniform_scale": r.get("uniform_scale", "1.0"),
            }
        )
    return out


def write_unreal_script() -> None:
    script = """# Unreal Editor Python helper for spawning demo trees from CSV.
# Usage in UE Python console:
#   exec(open(r\"<this_file_path>\", \"r\", encoding=\"utf-8\").read())

import csv
import unreal

CSV_PATH = r\"tree_demo_grid_layout_cm.csv\"  # set absolute path if needed
DESTINATION_PATH = \"/Game/Foliage/Trees\"
Z_OFFSET_CM = 0.0


def load_mesh(asset_path: str):
    return unreal.EditorAssetLibrary.load_asset(asset_path)


def spawn_from_csv(csv_path: str):
    actor_subsys = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    with open(csv_path, \"r\", encoding=\"utf-8\", newline=\"\") as f:
        for row in csv.DictReader(f):
            mesh = load_mesh(row[\"asset_path\"])
            if not mesh:
                unreal.log_warning(f\"Missing asset: {row['asset_path']}\")
                continue
            loc = unreal.Vector(float(row[\"x_cm\"]), float(row[\"y_cm\"]), float(row[\"z_cm\"]) + Z_OFFSET_CM)
            rot = unreal.Rotator(float(row[\"pitch_deg\"]), float(row[\"yaw_deg\"]), float(row[\"roll_deg\"]))
            actor = actor_subsys.spawn_actor_from_object(mesh, loc, rot)
            if actor:
                s = float(row.get(\"uniform_scale\", \"1.0\") or \"1.0\")
                actor.set_actor_scale3d(unreal.Vector(s, s, s))


spawn_from_csv(CSV_PATH)
unreal.log(\"Tree demo level spawn complete.\")
"""
    OUT_UNREAL_SCRIPT.write_text(script, encoding="utf-8")


def write_steps(species_count: int, real_sample_count: int) -> None:
    text = f"""## Unreal Tree Demo Level Pack

Files:
- `{OUT_SPECIES_MANIFEST.name}`: per-species asset + demo image manifest.
- `{OUT_GRID_LAYOUT.name}`: one clean showcase placement per species.
- `{OUT_REAL_SAMPLE.name}`: subset of real Kensington placements.
- `{OUT_UNREAL_SCRIPT.name}`: UE Python helper to spawn actors from CSV.

Recommended workflow:
1. Import tree meshes from `outputs/trees/masters/` into `/Game/Foliage/Trees/`.
2. Open `spawn_tree_demo_level.py` in Unreal Python.
3. Set `CSV_PATH` to either:
   - `tree_demo_grid_layout_cm.csv` for showcase grid ({species_count} species), or
   - `tree_demo_real_sample_cm.csv` for real-scene sample ({real_sample_count} instances).
4. Run script, then save the level as `LV_TreeDemo`.
"""
    OUT_STEPS.write_text(text, encoding="utf-8")


def main() -> int:
    PACK_DIR.mkdir(parents=True, exist_ok=True)

    species_rows = build_species_manifest()
    grid_rows = build_grid_layout(species_rows)
    real_rows = build_real_sample()

    write_csv(
        OUT_SPECIES_MANIFEST,
        species_rows,
        [
            "species_key",
            "scientific_name",
            "instances",
            "asset_path",
            "resolution_status",
            "source_fbx",
            "demo_png",
            "demo_status",
        ],
    )
    write_csv(
        OUT_GRID_LAYOUT,
        grid_rows,
        [
            "species_key",
            "asset_path",
            "x_cm",
            "y_cm",
            "z_cm",
            "yaw_deg",
            "pitch_deg",
            "roll_deg",
            "uniform_scale",
            "demo_label",
        ],
    )
    write_csv(
        OUT_REAL_SAMPLE,
        real_rows,
        [
            "instance_id",
            "species_key",
            "asset_path",
            "x_cm",
            "y_cm",
            "z_cm",
            "yaw_deg",
            "pitch_deg",
            "roll_deg",
            "uniform_scale",
        ],
    )
    write_unreal_script()
    write_steps(len(species_rows), len(real_rows))

    metadata = {
        "species_count": len(species_rows),
        "grid_rows": len(grid_rows),
        "real_sample_rows": len(real_rows),
        "pack_dir": str(PACK_DIR.resolve()),
    }
    OUT_METADATA.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    print(f"[OK] Wrote {OUT_SPECIES_MANIFEST}")
    print(f"[OK] Wrote {OUT_GRID_LAYOUT}")
    print(f"[OK] Wrote {OUT_REAL_SAMPLE}")
    print(f"[OK] Wrote {OUT_UNREAL_SCRIPT}")
    print(f"[OK] Wrote {OUT_STEPS}")
    print(f"[OK] Wrote {OUT_METADATA}")
    print(f"[DONE] species={len(species_rows)} real_sample={len(real_rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
