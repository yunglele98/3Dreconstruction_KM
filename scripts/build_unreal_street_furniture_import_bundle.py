#!/usr/bin/env python3
"""Resolve street furniture asset paths and build Unreal import bundle."""

from __future__ import annotations

import csv
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DIR = ROOT / "outputs" / "street_furniture"
IN_CSV = DIR / "street_furniture_instances_unreal_cm.csv"
MASTERS = DIR / "masters"
OUT_MANIFEST = DIR / "unreal_street_furniture_import_manifest.csv"
OUT_RESOLVED = DIR / "street_furniture_instances_unreal_resolved_cm.csv"
OUT_STEPS = DIR / "unreal_street_furniture_import_steps.md"


def resolve(key: str) -> tuple[str, str, str]:
    f = f"SM_{key}_A_standard.fbx"
    if (MASTERS / f).exists():
        return f"/Game/Street/Furniture/SM_{key}_A_standard", f, "exact_master"
    fb = "SM_terrace_module_A_standard.fbx"
    return "/Game/Street/Furniture/SM_terrace_module_A_standard", fb, "fallback"


def main() -> int:
    with IN_CSV.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    keys = sorted({r["furniture_key"] for r in rows})
    manifest = []
    for k in keys:
        p, src, st = resolve(k)
        manifest.append({"furniture_key": k, "resolved_asset_path": p, "source_fbx": str((MASTERS / src).resolve()), "resolution_status": st})
    idx = {m["furniture_key"]: m for m in manifest}
    with OUT_MANIFEST.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(manifest[0].keys()) if manifest else [])
        w.writeheader(); w.writerows(manifest)
    out = []
    for r in rows:
        m = idx[r["furniture_key"]]
        rr = dict(r); rr["asset_path"] = m["resolved_asset_path"]; rr["resolution_status"] = m["resolution_status"]
        out.append(rr)
    with OUT_RESOLVED.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0].keys()) if out else [])
        w.writeheader(); w.writerows(out)
    exact = sum(1 for m in manifest if m["resolution_status"] == "exact_master")
    OUT_STEPS.write_text(
        f"## Unreal Street Furniture Import Steps\n1. Import outputs/street_furniture/masters to /Game/Street/Furniture/\n2. Place with {OUT_RESOLVED}\n- furniture types exact: {exact}\n- furniture types fallback: {len(manifest)-exact}\n",
        encoding="utf-8",
    )
    print(f"[OK] Wrote {OUT_MANIFEST}")
    print(f"[OK] Wrote {OUT_RESOLVED}")
    print(f"[OK] Wrote {OUT_STEPS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
