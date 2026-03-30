#!/usr/bin/env python3
"""Resolve alley assets and build Unreal import bundle."""

from __future__ import annotations

import csv
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DIR = ROOT / "outputs" / "alleys"
IN_CSV = DIR / "alley_instances_unreal_cm.csv"
MASTERS = DIR / "masters"
OUT_MANIFEST = DIR / "unreal_alley_import_manifest.csv"
OUT_RESOLVED = DIR / "alley_instances_unreal_resolved_cm.csv"
OUT_STEPS = DIR / "unreal_alley_import_steps.md"


FALLBACK_KEY = "alley_vehicle_asphalt"


def resolve(key: str) -> tuple[str, str, str]:
    f = f"SM_{key}_A_standard.fbx"
    if (MASTERS / f).exists():
        return f"/Game/Street/Alleys/SM_{key}_A_standard", f, "exact_master"
    fb = f"SM_{FALLBACK_KEY}_A_standard.fbx"
    return f"/Game/Street/Alleys/SM_{FALLBACK_KEY}_A_standard", fb, "fallback"


def main() -> int:
    with IN_CSV.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))

    keys = sorted({r["alley_key"] for r in rows})
    manifest = []
    for k in keys:
        p, src, st = resolve(k)
        manifest.append(
            {
                "alley_key": k,
                "resolved_asset_path": p,
                "source_fbx": str((MASTERS / src).resolve()),
                "resolution_status": st,
            }
        )

    idx = {m["alley_key"]: m for m in manifest}
    with OUT_MANIFEST.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(manifest[0].keys()) if manifest else [])
        w.writeheader()
        w.writerows(manifest)

    out = []
    for r in rows:
        m = idx[r["alley_key"]]
        rr = dict(r)
        rr["asset_path"] = m["resolved_asset_path"]
        rr["resolution_status"] = m["resolution_status"]
        out.append(rr)

    with OUT_RESOLVED.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0].keys()) if out else [])
        w.writeheader()
        w.writerows(out)

    exact = sum(1 for m in manifest if m["resolution_status"] == "exact_master")
    OUT_STEPS.write_text(
        "\n".join(
            [
                "## Unreal Alley Import Steps",
                "1. Import outputs/alleys/masters to /Game/Street/Alleys/",
                f"2. Place with {OUT_RESOLVED}",
                f"- alley types exact: {exact}",
                f"- alley types fallback: {len(manifest) - exact}",
                "",
            ]
        ),
        encoding="utf-8",
    )

    print(f"[OK] Wrote {OUT_MANIFEST}")
    print(f"[OK] Wrote {OUT_RESOLVED}")
    print(f"[OK] Wrote {OUT_STEPS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
