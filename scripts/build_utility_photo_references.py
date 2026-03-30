#!/usr/bin/env python3
"""Extract utility box photos from photo index for reference and categorization.

Usage:
    python scripts/build_utility_photo_references.py

Reads: PHOTOS KENSINGTON/csv/photo_address_index.csv
Writes: outputs/utility/utility_photo_references.csv,
        outputs/utility/utility_photo_references.json
"""
from __future__ import annotations
import csv, json, re
from collections import Counter
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
IDX=ROOT/'PHOTOS KENSINGTON'/'csv'/'photo_address_index.csv'
OUT=ROOT/'outputs'/'utility'
KEYS=['utility box','hydro box','electrical box','cabinet','transformer','meter']
COORD=re.compile(r'(-?\d+\.\d+)\s*,\s*(-?\d+\.\d+)')

def cls(t:str)->str:
 s=(t or '').lower()
 if 'transformer' in s: return 'utility_transformer_box'
 if 'meter' in s: return 'utility_meter_box'
 return 'utility_street_cabinet'

def main()->int:
 OUT.mkdir(parents=True,exist_ok=True); rows=[]; c=Counter(); wc=0
 for r in csv.DictReader(IDX.open('r',encoding='utf-8',newline='')):
  txt=r.get('address_or_location') or ''; t=txt.lower()
  if not any(k in t for k in KEYS): continue
  m=COORD.search(txt); lat,lon=('','') if not m else (m.group(1),m.group(2)); wc+=1 if m else 0
  cat=cls(txt); c[cat]+=1
  rows.append({'filename':r.get('filename') or '','address_or_location':txt,'category':cat,'lat':lat,'lon':lon,'has_coords':'yes' if m else 'no'})
 p=OUT/'utility_photo_references.csv'
 with p.open('w',encoding='utf-8',newline='') as f:
  w=csv.DictWriter(f,fieldnames=list(rows[0].keys()) if rows else ['filename','address_or_location','category','lat','lon','has_coords']); w.writeheader(); w.writerows(rows)
 (OUT/'utility_photo_references.json').write_text(json.dumps({'count':len(rows),'with_coords':wc,'categories':dict(c)},indent=2),encoding='utf-8')
 print('[OK] Wrote',p); return 0
if __name__=='__main__': raise SystemExit(main())
