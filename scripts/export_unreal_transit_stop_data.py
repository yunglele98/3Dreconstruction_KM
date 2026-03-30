#!/usr/bin/env python3
from __future__ import annotations
import csv, json
from pathlib import Path
import psycopg2, psycopg2.extras
from db_config import DB_CONFIG, get_connection
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'outputs'/'transit_stops'; REF=OUT/'transit_stop_photo_references.csv'
ORIGIN_X=312672.94; ORIGIN_Y=4834994.86

def project(cur, lon, lat):
 cur.execute("SELECT ST_X(ST_Transform(ST_SetSRID(ST_MakePoint(%s,%s),4326),2952)), ST_Y(ST_Transform(ST_SetSRID(ST_MakePoint(%s,%s),4326),2952))",(lon,lat,lon,lat)); r=cur.fetchone(); return float(r[0]),float(r[1])

def main()->int:
 OUT.mkdir(parents=True,exist_ok=True)
 conn=get_connection()
 try:
  cur=conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
  cur.execute("SELECT id::text sid, ST_X(ST_Transform(geom,2952)) x, ST_Y(ST_Transform(geom,2952)) y FROM field_bus_shelters WHERE geom IS NOT NULL")
  shp=cur.fetchall()
  refs=list(csv.DictReader(REF.open('r',encoding='utf-8',newline=''))) if REF.exists() else []
  rows=[]; i=1
  for r in shp:
   rows.append({'instance_id':f'ts_{i:04d}','source_table':'field_bus_shelters','source_id':r['sid'],'transit_key':'transit_shelter','asset_path':'/Game/Street/Transit/SM_transit_shelter_A_standard','x_cm':f'{(float(r["x"])-ORIGIN_X)*100:.1f}','y_cm':f'{(float(r["y"])-ORIGIN_Y)*100:.1f}','z_cm':'0.0','yaw_deg':'0.0','uniform_scale':'1.000','metadata_json':'{}'}); i+=1
  for r in refs:
   if r.get('has_coords')=='yes' and r.get('lat') and r.get('lon'): x,y=project(cur,float(r['lon']),float(r['lat']))
   elif shp: x,y=float(shp[0]['x'])+i*0.8,float(shp[0]['y'])+i*0.5
   else: x,y=ORIGIN_X,ORIGIN_Y
   rows.append({'instance_id':f'ts_{i:04d}','source_table':'photo_ref','source_id':r.get('filename') or str(i),'transit_key':'transit_stop_pole','asset_path':'/Game/Street/Transit/SM_transit_stop_pole_A_standard','x_cm':f'{(x-ORIGIN_X)*100:.1f}','y_cm':f'{(y-ORIGIN_Y)*100:.1f}','z_cm':'0.0','yaw_deg':'0.0','uniform_scale':'1.000','metadata_json':json.dumps({'address_or_location':r.get('address_or_location','')},ensure_ascii=False)}); i+=1
 finally:
  conn.close()
 out=OUT/'transit_instances_unreal_cm.csv'
 with out.open('w',encoding='utf-8',newline='') as f:
  w=csv.DictWriter(f,fieldnames=list(rows[0].keys()) if rows else []); w.writeheader(); w.writerows(rows)
 print('[OK] Wrote',out); return 0
if __name__=='__main__': raise SystemExit(main())

