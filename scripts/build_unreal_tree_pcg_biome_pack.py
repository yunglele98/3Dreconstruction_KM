#!/usr/bin/env python3
"""Build a PCG-ready tree biome pack for Unreal."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TREES = ROOT / "outputs" / "trees"
DEMO_PACK = TREES / "demo_level_pack"

IN_SPECIES = DEMO_PACK / "tree_demo_species_manifest.csv"
IN_REFINED = TREES / "tree_instances_unreal_refined_cm.csv"

OUT_DIR = TREES / "pcg_biome_pack"
OUT_WEIGHTS = OUT_DIR / "tree_pcg_biome_species_weights.csv"
OUT_RULES = OUT_DIR / "tree_pcg_biome_rules.json"
OUT_SEEDS = OUT_DIR / "tree_pcg_seed_points_cm.csv"
OUT_UNREAL = OUT_DIR / "preview_spawn_tree_biomes.py"
OUT_README = OUT_DIR / "README_unreal_tree_pcg_biomes.md"
OUT_SUMMARY = OUT_DIR / "tree_pcg_biome_pack_summary.json"


CONIFER_TOKENS = ("pine", "spruce", "cedar", "fir", "thuja", "picea", "abies", "taxus", "juniper", "pseudotsuga")
COURTYARD_TOKENS = ("malus", "prunus", "syringa", "magnolia", "amelanchier", "cercis", "cotinus", "pyrus")
ALLEY_TOKENS = ("allianthus", "unknown_", "morus", "celtis", "robinia", "gymnocladus")
STREET_TOKENS = ("acer", "gleditsia", "ginkgo", "tilia", "platanus", "quercus", "ulmus", "fraxinus")


def read_csv(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)


def u01(seed: str) -> float:
    h = hashlib.sha1(seed.encode("utf-8")).hexdigest()
    return int(h[:8], 16) / 0xFFFFFFFF


def pick_primary_biome(species_key: str, instances: int) -> str:
    key = species_key.lower()
    if any(t in key for t in COURTYARD_TOKENS):
        return "courtyard"
    if any(t in key for t in ALLEY_TOKENS):
        return "alley_edge"
    if any(t in key for t in CONIFER_TOKENS):
        return "alley_edge" if instances <= 3 else "street_edge"
    if any(t in key for t in STREET_TOKENS):
        return "street_edge"
    if instances >= 8:
        return "street_edge"
    if instances <= 2:
        return "courtyard"
    return "alley_edge"


def biome_base_weight(primary: str, target: str) -> float:
    if primary == target:
        return 1.00
    if {primary, target} == {"street_edge", "alley_edge"}:
        return 0.42
    if {primary, target} == {"street_edge", "courtyard"}:
        return 0.28
    if {primary, target} == {"alley_edge", "courtyard"}:
        return 0.35
    return 0.20


def build_weights(species_rows: list[dict]) -> list[dict]:
    out: list[dict] = []
    biomes = ("street_edge", "alley_edge", "courtyard")
    for row in species_rows:
        species_key = row["species_key"]
        instances = int(row.get("instances") or 0)
        primary = pick_primary_biome(species_key, instances)
        is_conifer = any(t in species_key for t in CONIFER_TOKENS)
        for biome in biomes:
            bw = biome_base_weight(primary, biome)
            rarity = 0.55 + min(instances, 100) / 100.0
            weight = round(max(0.05, bw * rarity), 4)
            min_scale = 0.90 if biome != "courtyard" else 0.78
            max_scale = 1.16 if biome == "street_edge" else (1.04 if biome == "alley_edge" else 0.96)
            if is_conifer:
                max_scale = round(max_scale + 0.06, 2)
            density_factor = 1.10 if biome == "street_edge" else (0.80 if biome == "alley_edge" else 0.62)
            if instances <= 2:
                density_factor *= 0.7
            out.append(
                {
                    "biome": biome,
                    "species_key": species_key,
                    "asset_path": row["asset_path"],
                    "instances_city": instances,
                    "primary_biome": primary,
                    "weight": f"{weight:.4f}",
                    "min_scale": f"{min_scale:.2f}",
                    "max_scale": f"{max_scale:.2f}",
                    "density_factor": f"{density_factor:.3f}",
                    "slope_max_deg": "20" if biome == "street_edge" else ("28" if biome == "alley_edge" else "16"),
                    "notes": "conifer" if is_conifer else "deciduous",
                }
            )
    return out


def assign_seed_biome(species_key: str, x_cm: float, y_cm: float) -> str:
    primary = pick_primary_biome(species_key, 5)
    # small deterministic drift to avoid over-hard boundaries
    r = u01(f"{species_key}:{x_cm:.1f}:{y_cm:.1f}")
    if primary == "street_edge" and r < 0.12:
        return "alley_edge"
    if primary == "alley_edge" and r < 0.15:
        return "courtyard"
    if primary == "courtyard" and r < 0.10:
        return "alley_edge"
    return primary


def build_seed_points(instance_rows: list[dict], limit: int = 420) -> list[dict]:
    out: list[dict] = []
    for row in instance_rows[:limit]:
        x_cm = float(row.get("x_cm") or 0.0)
        y_cm = float(row.get("y_cm") or 0.0)
        species_key = row.get("species_key", "")
        biome = assign_seed_biome(species_key, x_cm, y_cm)
        out.append(
            {
                "instance_id": row.get("instance_id", ""),
                "biome": biome,
                "species_key": species_key,
                "asset_path": row.get("asset_path", ""),
                "x_cm": f"{x_cm:.1f}",
                "y_cm": f"{y_cm:.1f}",
                "z_cm": row.get("z_cm", "0.0"),
                "yaw_deg": row.get("yaw_deg", "0.0"),
                "uniform_scale": row.get("uniform_scale", "1.0"),
            }
        )
    return out


def build_rules_json() -> dict:
    return {
        "biomes": {
            "street_edge": {
                "target_trees_per_100sqm": 0.22,
                "cluster_radius_cm": 420,
                "recommended_pcg_tag": "biome.street_edge",
                "description": "Road frontage and primary sidewalks; larger canopy bias.",
            },
            "alley_edge": {
                "target_trees_per_100sqm": 0.11,
                "cluster_radius_cm": 320,
                "recommended_pcg_tag": "biome.alley_edge",
                "description": "Back lanes, service edges, constrained urban slots.",
            },
            "courtyard": {
                "target_trees_per_100sqm": 0.08,
                "cluster_radius_cm": 260,
                "recommended_pcg_tag": "biome.courtyard",
                "description": "Private/open interior lots and small court pockets.",
            },
        },
        "selection_logic": {
            "source": "weights table",
            "method": "weighted random by biome",
            "asset_key_field": "species_key",
            "asset_path_field": "asset_path",
        },
        "placement_defaults": {
            "align_to_normal": True,
            "random_yaw": True,
            "z_offset_cm": 0.0,
        },
    }


def build_unreal_helper_script() -> str:
    return """# Unreal Editor Python helper: preview tree biomes from CSV seed points.
import csv
import unreal

CSV_PATH = r"tree_pcg_seed_points_cm.csv"  # set absolute path
ONLY_BIOME = ""  # set to 'street_edge', 'alley_edge', or 'courtyard' to filter

actor_subsys = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)

with open(CSV_PATH, "r", encoding="utf-8", newline="") as f:
    for row in csv.DictReader(f):
        biome = row["biome"]
        if ONLY_BIOME and biome != ONLY_BIOME:
            continue
        mesh = unreal.EditorAssetLibrary.load_asset(row["asset_path"])
        if not mesh:
            unreal.log_warning(f"Missing mesh: {row['asset_path']}")
            continue
        loc = unreal.Vector(float(row["x_cm"]), float(row["y_cm"]), float(row["z_cm"]))
        rot = unreal.Rotator(0.0, float(row.get("yaw_deg", "0") or "0"), 0.0)
        actor = actor_subsys.spawn_actor_from_object(mesh, loc, rot)
        if actor:
            s = float(row.get("uniform_scale", "1.0") or "1.0")
            actor.set_actor_scale3d(unreal.Vector(s, s, s))
            actor.tags = [unreal.Name(f"biome.{biome}"), unreal.Name(f"species.{row['species_key']}")]

unreal.log("Biome preview spawn complete.")
"""


def build_readme() -> str:
    return """## Unreal Tree PCG Biome Pack

Files:
- `tree_pcg_biome_species_weights.csv`: weighted species table for PCG selectors.
- `tree_pcg_seed_points_cm.csv`: seed points tagged by biome from real tree instances.
- `tree_pcg_biome_rules.json`: biome density + tuning defaults.
- `preview_spawn_tree_biomes.py`: quick Unreal spawn helper for biome previews.

Suggested use in PCG graph:
1. Import `tree_pcg_biome_species_weights.csv` into a Data Table or custom CSV reader.
2. For each biome branch (`street_edge`, `alley_edge`, `courtyard`), sample by `weight`.
3. Use `density_factor` and biome target density from JSON to scale spawn counts.
4. Apply min/max scale from CSV and slope caps (`slope_max_deg`) as spawn filters.
"""


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    species_rows = read_csv(IN_SPECIES)
    inst_rows = read_csv(IN_REFINED)

    weights = build_weights(species_rows)
    seeds = build_seed_points(inst_rows)
    rules = build_rules_json()

    write_csv(
        OUT_WEIGHTS,
        weights,
        [
            "biome",
            "species_key",
            "asset_path",
            "instances_city",
            "primary_biome",
            "weight",
            "min_scale",
            "max_scale",
            "density_factor",
            "slope_max_deg",
            "notes",
        ],
    )
    write_csv(
        OUT_SEEDS,
        seeds,
        [
            "instance_id",
            "biome",
            "species_key",
            "asset_path",
            "x_cm",
            "y_cm",
            "z_cm",
            "yaw_deg",
            "uniform_scale",
        ],
    )
    OUT_RULES.write_text(json.dumps(rules, indent=2), encoding="utf-8")
    OUT_UNREAL.write_text(build_unreal_helper_script(), encoding="utf-8")
    OUT_README.write_text(build_readme(), encoding="utf-8")

    counts = {}
    for row in seeds:
        counts[row["biome"]] = counts.get(row["biome"], 0) + 1

    summary = {
        "species_count": len(species_rows),
        "weights_rows": len(weights),
        "seed_points": len(seeds),
        "seed_points_by_biome": counts,
        "out_dir": str(OUT_DIR.resolve()),
    }
    OUT_SUMMARY.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(f"[OK] Wrote {OUT_WEIGHTS}")
    print(f"[OK] Wrote {OUT_SEEDS}")
    print(f"[OK] Wrote {OUT_RULES}")
    print(f"[OK] Wrote {OUT_UNREAL}")
    print(f"[OK] Wrote {OUT_README}")
    print(f"[OK] Wrote {OUT_SUMMARY}")
    print(f"[DONE] species={len(species_rows)} seed_points={len(seeds)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
