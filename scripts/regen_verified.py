#!/usr/bin/env python3
"""Regenerate only photo-verified and tall-building-fixed .blend files."""
import json
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PARAMS = ROOT / "params"
OUTPUT = ROOT / "outputs" / "full"

regen = []
for f in sorted(PARAMS.glob("*.json")):
    if f.name.startswith("_"):
        continue
    d = json.load(open(f, encoding="utf-8"))
    if d.get("skipped"):
        continue
    meta = d.get("_meta", {})
    if meta.get("qa_tall_fixes"):
        regen.append(f)
    elif meta.get("qa_photo_fixes"):
        fixes = meta["qa_photo_fixes"]
        if any("Photo:" in fix or "Hospital" in fix or "Nassau" in fix
               or "Semi-detached" in fix or "Residential" in fix
               or "Coordinate" in fix for fix in fixes):
            regen.append(f)

print(f"Regenerating {len(regen)} buildings...", flush=True)

failed = []
for i, f in enumerate(regen, 1):
    # Delete existing blend so it gets regenerated
    blend = OUTPUT / f"{f.stem}.blend"
    if blend.exists():
        blend.unlink()
    manifest = OUTPUT / f"{f.stem}.manifest.json"
    if manifest.exists():
        manifest.unlink()

    print(f"[{i}/{len(regen)}] {f.stem}", end="", flush=True)
    t0 = time.time()
    try:
        r = subprocess.run(
            ["blender", "--background", "--python", str(ROOT / "generate_building.py"),
             "--", "--params", str(f), "--batch-individual", "--output-dir", str(OUTPUT)],
            capture_output=True, text=True, timeout=120,
            encoding="utf-8", errors="replace"
        )
        elapsed = time.time() - t0
        if blend.exists():
            print(f" OK ({elapsed:.1f}s)", flush=True)
        else:
            print(f" FAILED ({elapsed:.1f}s)", flush=True)
            failed.append(f.stem)
    except subprocess.TimeoutExpired:
        print(" TIMEOUT", flush=True)
        failed.append(f.stem)
    except Exception as e:
        print(f" ERROR: {e}", flush=True)
        failed.append(f.stem)

print(f"\nDone: {len(regen) - len(failed)} OK, {len(failed)} failed", flush=True)
if failed:
    for name in failed:
        print(f"  FAILED: {name}", flush=True)
