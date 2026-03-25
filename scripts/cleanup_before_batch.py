#!/usr/bin/env python3
"""
Pre-batch cleanup: mark non-buildings and photo-variant duplicates as skipped,
fill missing facade_material and roof_type defaults so the generator won't fail.

Run with --dry-run first to preview changes, then without to apply.

Usage:
    python scripts/cleanup_before_batch.py --dry-run
    python scripts/cleanup_before_batch.py
"""

import json
import glob
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

DRY_RUN = "--dry-run" in sys.argv
PARAMS_DIR = Path(__file__).resolve().parent.parent / "params"

# ---------- 1. Non-building patterns ----------

NON_BUILDING_PATTERNS = re.compile(
    r"(?:alley|mural|graffiti|sign_(?!St)|lane_|parking|fire_escape|"
    r"backyards?|rooftop|streetscape|Chinatown(?:_(?:area|alley))|"
    r"video_sign|striped_awning|dumpster|utility_pole|hydro|"
    r"vacant_lot(?!_)|empty_lot|construction_site|scaffolding|"
    r"blue_wave_mural|devil_mural|tow-away_zone)",
    re.IGNORECASE,
)

# ---------- 2. Duplicate detection ----------

STREET_SUFFIX = re.compile(
    r"(_(?:St|St_W|St_E|Ave|Pl|Ter|Terr|Blvd|Rd|Cres|Dr|Way|Lane|Ct|Cir))"
    r"(?:_|$)"
)


def base_address(name):
    """Return (base, suffix) splitting at the street-type token."""
    m = STREET_SUFFIX.search(name)
    if m:
        base = name[: m.end(1)]
        suffix = name[m.end(1) :]
        return base, suffix
    return name, ""


# ---------- 3. Schema defaults ----------

FACADE_MATERIAL_DEFAULT = "brick"

ROOF_TYPE_DEFAULTS = {
    # Infer from typology keywords
    "bay-and-gable": "gable",
    "ontario cottage": "hip",
    "institutional": "flat",
    "commercial": "flat",
    "apartment": "flat",
}


def infer_roof_type(params):
    """Infer roof_type from typology or floor count."""
    typology = (params.get("hcd_data", {}).get("typology") or "").lower()
    for kw, rt in ROOF_TYPE_DEFAULTS.items():
        if kw in typology:
            return rt
    floors = params.get("floors", 2)
    if isinstance(floors, (int, float)) and floors >= 3:
        return "flat"
    return "gable"  # Kensington Market default for low-rise


# ---------- Main ----------

def main():
    # Load all active params
    active = {}
    for f in sorted(glob.glob(str(PARAMS_DIR / "*.json"))):
        bn = os.path.basename(f)
        if bn.startswith("_"):
            continue
        name = os.path.splitext(bn)[0]
        try:
            d = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        if d.get("skipped"):
            continue
        active[name] = (f, d)

    # Get already-rendered set
    repo = PARAMS_DIR.parent
    rendered = set()
    for d in ["outputs/full", "outputs/batch_50", "outputs/batch_pilot", "outputs/single"]:
        for bf in glob.glob(str(repo / d / "*.blend")):
            rendered.add(os.path.splitext(os.path.basename(bf))[0])

    missing = {n: v for n, v in active.items() if n not in rendered}

    # --- Step 1: Mark non-buildings as skipped ---
    skip_non_building = []
    for name in sorted(missing):
        if NON_BUILDING_PATTERNS.search(name):
            skip_non_building.append(name)

    # --- Step 2: Find duplicate photo-variants ---
    by_base = defaultdict(list)
    for name in active:
        base, suffix = base_address(name)
        by_base[base].append((name, suffix))

    skip_duplicates = []
    for base, entries in sorted(by_base.items()):
        if len(entries) <= 1:
            continue
        # Pick canonical: prefer no suffix + postgis_export source
        canonical = None
        for name, suffix in sorted(entries, key=lambda x: len(x[0])):
            _, d = active[name]
            src = d.get("_meta", {}).get("source", "")
            if not suffix and src == "postgis_export":
                canonical = name
                break
            if not suffix:
                canonical = name
        if not canonical:
            canonical = sorted(entries, key=lambda x: len(x[0]))[0][0]
        for name, suffix in entries:
            if name != canonical and name in missing:
                skip_duplicates.append((name, canonical))

    # --- Step 3: Fill schema gaps on remaining missing ---
    to_skip = set(skip_non_building) | {n for n, _ in skip_duplicates}
    schema_fixes = []
    for name in sorted(missing):
        if name in to_skip:
            continue
        fpath, d = active[name]
        fixes = []
        if not d.get("facade_material"):
            d["facade_material"] = FACADE_MATERIAL_DEFAULT
            fixes.append("facade_material -> brick")
        if not d.get("roof_type"):
            rt = infer_roof_type(d)
            d["roof_type"] = rt
            fixes.append(f"roof_type -> {rt}")
        if not d.get("building_name"):
            d["building_name"] = name.replace("_", " ")
            fixes.append(f"building_name -> {d['building_name']}")
        if fixes:
            schema_fixes.append((name, fpath, d, fixes))

    # --- Report ---
    print(f"{'[DRY RUN] ' if DRY_RUN else ''}Cleanup summary:")
    print(f"  Active params:         {len(active)}")
    print(f"  Already rendered:      {len(rendered)}")
    print(f"  Missing renders:       {len(missing)}")
    print()
    print(f"  Non-buildings to skip: {len(skip_non_building)}")
    for n in skip_non_building:
        print(f"    - {n}")
    print()
    print(f"  Duplicates to skip:    {len(skip_duplicates)}")
    for n, canon in skip_duplicates[:20]:
        print(f"    - {n}  (canonical: {canon})")
    if len(skip_duplicates) > 20:
        print(f"    ... and {len(skip_duplicates) - 20} more")
    print()
    print(f"  Schema fixes needed:   {len(schema_fixes)}")
    for n, _, _, fixes in schema_fixes[:15]:
        print(f"    - {n}: {', '.join(fixes)}")
    if len(schema_fixes) > 15:
        print(f"    ... and {len(schema_fixes) - 15} more")
    print()

    ready = len(missing) - len(to_skip)
    print(f"  Buildings ready to generate after cleanup: {ready}")

    if DRY_RUN:
        print("\nNo changes written. Run without --dry-run to apply.")
        return

    # --- Apply ---
    changed = 0

    # Skip non-buildings
    for name in skip_non_building:
        fpath, d = active[name]
        d["skipped"] = True
        d["skip_reason"] = "Non-building photo (auto-detected by cleanup_before_batch.py)"
        with open(fpath, "w", encoding="utf-8") as f:
            json.dump(d, f, indent=2, ensure_ascii=False)
        changed += 1

    # Skip duplicates
    for name, canonical in skip_duplicates:
        fpath, d = active[name]
        d["skipped"] = True
        d["skip_reason"] = f"Duplicate photo-variant of {canonical} (auto-detected by cleanup_before_batch.py)"
        with open(fpath, "w", encoding="utf-8") as f:
            json.dump(d, f, indent=2, ensure_ascii=False)
        changed += 1

    # Fix schemas
    for name, fpath, d, fixes in schema_fixes:
        meta = d.setdefault("_meta", {})
        applied = meta.get("cleanup_fixes", [])
        applied.extend(fixes)
        meta["cleanup_fixes"] = applied
        with open(fpath, "w", encoding="utf-8") as f:
            json.dump(d, f, indent=2, ensure_ascii=False)
        changed += 1

    print(f"\nDone. Modified {changed} files.")


if __name__ == "__main__":
    main()
