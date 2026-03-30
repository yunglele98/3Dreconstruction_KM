#!/usr/bin/env python3
from __future__ import annotations
import csv, json
from pathlib import Path
import psycopg2, psycopg2.extras
from db_config import DB_CONFIG, get_connection
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'outputs'/'utility'; REF=OUT/'utility_photo_references.csv'
ORIGIN_X=312672.94; ORIGIN_Y=4834994.86

def project(cur, lon, lat):
 cur.execute("SELECT ST_X(ST_Transform(ST_SetSRID(ST_MakePoint(%s,%s),4326),2952)), ST_Y(ST_Transform(ST_SetSRID(ST_MakePoint(%s,%s),4326),2952))",(lon,lat,lon,lat)); r=cur.fetchone(); return float(r[0]),float(r[1])

def main()->int:
 OUT.mkdir(parents=True,exist_ok=True)
 conn=get_connection()
 try:
  cur=conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
  cur.execute("SELECT id::text sid, ST_X(ST_Transform(geom,2952)) x, ST_Y(ST_Transform(geom,2952)) y FROM field_poles WHERE geom IS NOT NULL ORDER BY id")
  anchors=cur.fetchall() or [{'sid':'0','x':ORIGIN_X,'y':ORIGIN_Y}]
  refs=list(csv.DictReader(REF.open('r',encoding='utf-8',newline='')))
  rows=[]
  for i,r in enumerate(refs,start=1):
    if r.get('has_coords')=='yes' and r.get('lat') and r.get('lon'): x,y=project(cur,float(r['lon']),float(r['lat'])); src='photo_ref'
    else:
      a=anchors[(i-1)%len(anchors)]; x=float(a['x'])+((i%7)-3)*1.3; y=float(a['y'])+(((i//7)%7)-3)*1.1; src='photo_ref_inferred'
    k=r['category']
    rows.append({'instance_id':f'ut_{i:04d}','source_table':src,'source_id':r.get('filename') or str(i),'utility_key':k,'asset_path':f'/Game/Street/Utility/SM_{k}_A_standard','x_cm':f'{(x-ORIGIN_X)*100:.1f}','y_cm':f'{(y-ORIGIN_Y)*100:.1f}','z_cm':'0.0','yaw_deg':'0.0','uniform_scale':'1.000','metadata_json':json.dumps({'address_or_location':r.get('address_or_location','')},ensure_ascii=False)})
  out=OUT/'utility_instances_unreal_cm.csv'
  with out.open('w',encoding='utf-8',newline='') as f:
    w=csv.DictWriter(f,fieldnames=list(rows[0].keys()) if rows else []); w.writeheader(); w.writerows(rows)
  print('[OK] Wrote',out)
 finally:
  conn.close()
 return 0
if __name__=='__main__': raise SystemExit(main())

