#!/usr/bin/env python3
"""Build Unreal material presets for sign assets."""

from __future__ import annotations

import csv
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DIR = ROOT / "outputs" / "signs"
IN_CSV = DIR / "sign_instances_unreal_refined_cm.csv"
OUT_JSON = DIR / "sign_material_presets.json"
OUT_CSV = DIR / "sign_material_presets.csv"


def preset(key: str):
    k = (key or "").lower()
    if "warning" in k:
        return "#F1C232", "#222222", 0.35
    if "restriction" in k:
        return "#D32F2F", "#FFFFFF", 0.32
    if "oneway" in k:
        return "#2E5FA8", "#FFFFFF", 0.34
    if "speed" in k:
        return "#FFFFFF", "#D32F2F", 0.28
    if "info" in k:
        return "#1E73BE", "#FFFFFF", 0.33
    return "#FFFFFF", "#333333", 0.4


def main() -> int:
    with IN_CSV.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    keys = sorted({r["sign_key"] for r in rows})
    presets = []
    for k in keys:
        base, accent, rough = preset(k)
        presets.append(
            {
                "sign_key": k,
                "material_family": "painted_metal_sign",
                "base_color": base,
                "accent_color": accent,
                "roughness": rough,
                "retroreflective_boost": 0.65,
            }
        )
    OUT_JSON.write_text(json.dumps({"presets": presets}, indent=2), encoding="utf-8")
    with OUT_CSV.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(presets[0].keys()) if presets else [])
        w.writeheader(); w.writerows(presets)
    print(f"[OK] Wrote {OUT_JSON}")
    print(f"[OK] Wrote {OUT_CSV}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
