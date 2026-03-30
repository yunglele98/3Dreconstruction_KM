#!/usr/bin/env python3
"""Resolve pole instance asset paths against available master FBX files."""

from __future__ import annotations

import csv
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
POLES = ROOT / "outputs" / "poles"
IN_CSV = POLES / "pole_instances_unreal_cm.csv"
MASTERS = POLES / "masters"
OUT_MANIFEST = POLES / "unreal_pole_import_manifest.csv"
OUT_RESOLVED = POLES / "pole_instances_unreal_resolved_cm.csv"
OUT_STEPS = POLES / "unreal_pole_import_steps.md"


def resolve(pole_key: str) -> tuple[str, str, str]:
    preferred = f"SM_{pole_key}_A_standard.fbx"
    if (MASTERS / preferred).exists():
        return f"/Game/Street/Pole/SM_{pole_key}_A_standard", preferred, "exact_master"
    fallback = "SM_generic_pole_A_standard.fbx"
    return "/Game/Street/Pole/SM_generic_pole_A_standard", fallback, "fallback"


def main() -> int:
    with IN_CSV.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))

    keys = sorted({r["pole_key"] for r in rows})
    manifest = []
    for k in keys:
        path, src, st = resolve(k)
        manifest.append(
            {
                "pole_key": k,
                "resolved_asset_path": path,
                "source_fbx": str((MASTERS / src).resolve()),
                "resolution_status": st,
            }
        )
    idx = {m["pole_key"]: m for m in manifest}

    with OUT_MANIFEST.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(manifest[0].keys()) if manifest else [])
        w.writeheader()
        w.writerows(manifest)

    out_rows = []
    for r in rows:
        m = idx[r["pole_key"]]
        rr = dict(r)
        rr["asset_path"] = m["resolved_asset_path"]
        rr["resolution_status"] = m["resolution_status"]
        out_rows.append(rr)

    with OUT_RESOLVED.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out_rows[0].keys()) if out_rows else [])
        w.writeheader()
        w.writerows(out_rows)

    exact = sum(1 for m in manifest if m["resolution_status"] == "exact_master")
    fallback = len(manifest) - exact
    OUT_STEPS.write_text(
        "\n".join(
            [
                "## Unreal Pole Import Steps",
                "1. Import FBX assets in outputs/poles/masters to /Game/Street/Pole/",
                f"2. Use {OUT_RESOLVED} for placement.",
                f"- Pole types exact: {exact}",
                f"- Pole types fallback: {fallback}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    print(f"[OK] Wrote {OUT_MANIFEST}")
    print(f"[OK] Wrote {OUT_RESOLVED}")
    print(f"[OK] Wrote {OUT_STEPS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
