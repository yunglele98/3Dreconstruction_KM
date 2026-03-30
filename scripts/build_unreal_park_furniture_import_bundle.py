#!/usr/bin/env python3
"""Resolve park furniture asset paths and create Unreal import manifest.

Usage:
    python scripts/build_unreal_park_furniture_import_bundle.py

Reads: outputs/park_furniture/park_furniture_instances_unreal_cm.csv
Writes: outputs/park_furniture/unreal_park_furniture_import_manifest.csv,
        outputs/park_furniture/park_furniture_instances_unreal_resolved_cm.csv
"""
from __future__ import annotations
import csv
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
DIR=ROOT/'outputs'/'park_furniture'; IN=DIR/'park_furniture_instances_unreal_cm.csv'; MA=DIR/'masters'; MAN=DIR/'unreal_park_furniture_import_manifest.csv'; RES=DIR/'park_furniture_instances_unreal_resolved_cm.csv'
def main()->int:
 rows=list(csv.DictReader(IN.open('r',encoding='utf-8',newline=''))); keys=sorted({r['park_key'] for r in rows}); man=[]
 for k in keys:
  f=f'SM_{k}_A_standard.fbx'; st='exact_master' if (MA/f).exists() else 'fallback'; rk=k if st=='exact_master' else 'park_bench_module'
  man.append({'park_key':k,'resolved_asset_path':f'/Game/Street/Park/SM_{rk}_A_standard','source_fbx':str((MA/f'SM_{rk}_A_standard.fbx').resolve()),'resolution_status':st})
 idx={m['park_key']:m for m in man}
 with MAN.open('w',encoding='utf-8',newline='') as f:
  w=csv.DictWriter(f,fieldnames=list(man[0].keys()) if man else []); w.writeheader(); w.writerows(man)
 out=[]
 for r in rows:
  m=idx[r['park_key']]; rr=dict(r); rr['asset_path']=m['resolved_asset_path']; rr['resolution_status']=m['resolution_status']; out.append(rr)
 with RES.open('w',encoding='utf-8',newline='') as f:
  w=csv.DictWriter(f,fieldnames=list(out[0].keys()) if out else []); w.writeheader(); w.writerows(out)
 print('[OK] Wrote',MAN); print('[OK] Wrote',RES); return 0
if __name__=='__main__': raise SystemExit(main())
