#!/usr/bin/env python3
"""Extract transit stop photos from photo index for reference and categorization.

Usage:
    python scripts/build_transit_stop_photo_references.py

Reads: PHOTOS KENSINGTON/csv/photo_address_index.csv
Writes: outputs/transit_stops/transit_stop_photo_references.csv,
        outputs/transit_stops/transit_stop_photo_references.json
"""
from __future__ import annotations
import csv, json, re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
IDX=ROOT/'PHOTOS KENSINGTON'/'csv'/'photo_address_index.csv'
OUT=ROOT/'outputs'/'transit_stops'
KEYS=['bus stop','ttc stop','streetcar stop','transit stop']
COORD=re.compile(r'(-?\d+\.\d+)\s*,\s*(-?\d+\.\d+)')

def main()->int:
 OUT.mkdir(parents=True,exist_ok=True); rows=[]; wc=0
 for r in csv.DictReader(IDX.open('r',encoding='utf-8',newline='')):
  txt=r.get('address_or_location') or ''
  if not any(k in txt.lower() for k in KEYS): continue
  m=COORD.search(txt); lat,lon=('','') if not m else (m.group(1),m.group(2)); wc+=1 if m else 0
  rows.append({'filename':r.get('filename') or '','address_or_location':txt,'category':'transit_stop_pole','lat':lat,'lon':lon,'has_coords':'yes' if m else 'no'})
 p=OUT/'transit_stop_photo_references.csv'
 with p.open('w',encoding='utf-8',newline='') as f:
  import csv as _csv; w=_csv.DictWriter(f,fieldnames=list(rows[0].keys()) if rows else ['filename','address_or_location','category','lat','lon','has_coords']); w.writeheader(); w.writerows(rows)
 (OUT/'transit_stop_photo_references.json').write_text(json.dumps({'count':len(rows),'with_coords':wc},indent=2),encoding='utf-8')
 print('[OK] Wrote',p); return 0
if __name__=='__main__': raise SystemExit(main())
