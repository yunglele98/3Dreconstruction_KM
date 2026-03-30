#!/usr/bin/env python3
"""Assign extracted printable decals onto printable targets."""

from __future__ import annotations

import csv
import hashlib
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IN_DEC = ROOT / "outputs" / "printable_features" / "printable_decal_catalog.csv"
IN_TGT = ROOT / "outputs" / "printable_features" / "printable_targets_unreal_cm.csv"
OUT = ROOT / "outputs" / "printable_features" / "unreal_printable_decal_placements.csv"

MAP = {
    'street_sign_face': {'street_sign'},
    'warning_sign_face': {'street_sign'},
    'regulatory_sign_face': {'street_sign'},
    'shop_sign_band': {'shop_sign', 'awning_sign'},
    'mural_wall_panel': {'mural_or_graffiti', 'poster_panel'},
}


def u(seed: str) -> float:
    h = hashlib.sha1(seed.encode('utf-8')).hexdigest()
    return int(h[:8], 16) / 0xFFFFFFFF


def pick(pool, seed):
    if not pool:
        return None
    return pool[int(u(seed) * len(pool)) % len(pool)]


def main() -> int:
    dec = list(csv.DictReader(IN_DEC.open('r', encoding='utf-8', newline='')))
    tgt = list(csv.DictReader(IN_TGT.open('r', encoding='utf-8', newline='')))

    by_cat = defaultdict(list)
    for d in dec:
        by_cat[(d.get('category') or '').strip()].append(d)

    out = []
    for t in tgt:
        key = t['target_surface_key']
        cats = MAP.get(key, {'other_printable'})
        pool = []
        for c in cats:
            pool.extend(by_cat.get(c, []))
        if not pool:
            pool = dec
        p = pick(pool, t['target_id'])
        if not p:
            continue
        layers = 1
        if key in {'shop_sign_band', 'mural_wall_panel'}:
            layers = 1 + int(u(t['target_id']+'_layers')*2)
        for i in range(layers):
            out.append({
                'target_id': t['target_id'],
                'target_surface_key': key,
                'source_table': t['source_table'],
                'source_id': t['source_id'],
                'decal_layer': i+1,
                'decal_id': p['decal_id'],
                'decal_texture_path': p['decal_texture_path'],
                'decal_material': '/Game/Street/Decals/MI_decal_printable_projection',
                'x_cm': f"{float(t['x_cm']) + (u(t['target_id']+str(i)+'x')-0.5)*60:.1f}",
                'y_cm': f"{float(t['y_cm']) + (u(t['target_id']+str(i)+'y')-0.5)*40:.1f}",
                'z_cm': f"{float(t['z_cm']) + i*12.0:.1f}",
                'yaw_deg': f"{u(t['target_id']+str(i)+'yaw')*360:.1f}",
                'uniform_scale': f"{float(t['uniform_scale']) * (0.7 + u(t['target_id']+str(i)+'s')*0.9):.3f}",
                'opacity': f"{0.6 + u(t['target_id']+str(i)+'o')*0.35:.3f}",
            })

    with OUT.open('w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(out[0].keys()) if out else [])
        w.writeheader(); w.writerows(out)

    print(f'[OK] Wrote {OUT}')
    print(f'[INFO] placements={len(out)}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
