#!/usr/bin/env python3
"""Prepare ordered list of unresolved species keys for bulk master generation."""

from __future__ import annotations

import csv
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TREES_DIR = ROOT / "outputs" / "trees"
MANIFEST = TREES_DIR / "unreal_import_manifest.csv"
CATALOG = TREES_DIR / "tree_catalog.json"
OUT_KEYS = TREES_DIR / "missing_species_keys.txt"
MASTERS_DIR = TREES_DIR / "masters"


def main() -> int:
    exact_masters = {
        p.stem.removeprefix("SM_").removesuffix("_A_mature")
        for p in MASTERS_DIR.glob("SM_*_A_mature.fbx")
    }

    with MANIFEST.open("r", encoding="utf-8", newline="") as f:
        manifest_rows = list(csv.DictReader(f))
    unresolved = {
        row["species_key"]
        for row in manifest_rows
        if row["species_key"] not in exact_masters
        or row["resolution_status"] in {"fallback_deciduous", "fallback_evergreen", "fallback_missing_source"}
    }

    catalog = json.loads(CATALOG.read_text(encoding="utf-8")).get("catalog", [])
    counts = {item["species_key"]: int(item.get("instances", 0)) for item in catalog}
    ordered = sorted(unresolved, key=lambda k: counts.get(k, 0), reverse=True)

    OUT_KEYS.write_text("\n".join(ordered) + ("\n" if ordered else ""), encoding="utf-8")
    print(f"[OK] Wrote {OUT_KEYS} ({len(ordered)} species)")
    if ordered:
        print("[TOP]", ", ".join(ordered[:12]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
