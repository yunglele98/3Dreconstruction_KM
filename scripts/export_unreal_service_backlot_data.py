#!/usr/bin/env python3
from __future__ import annotations
import csv, json
from pathlib import Path
import psycopg2, psycopg2.extras
from db_config import DB_CONFIG, get_connection
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'outputs'/'service_backlot'
ORIGIN_X=312672.94; ORIGIN_Y=4834994.86

def classify(t:str,c:str)->str:
 s=(t or '').lower()+' '+(c or '').lower()
 if 'loading' in s: return 'service_loading_dock'
 if 'vent' in s or 'exhaust' in s: return 'service_exhaust_vent'
 if 'gate' in s or 'service' in s: return 'service_entry_door'
 return 'service_utility_conduit'

def main()->int:
 OUT.mkdir(parents=True,exist_ok=True)
 conn=get_connection()
 try:
  cur=conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
  cur.execute("SELECT id::text sid, COALESCE(type_voie,'') t, COALESCE(nom_ruelle,'') n, ST_X(ST_Transform(geom,2952)) x, ST_Y(ST_Transform(geom,2952)) y FROM field_alleys WHERE geom IS NOT NULL ORDER BY id")
  rows_db=cur.fetchall()
 finally:
  conn.close()
 rows=[]
 for i,r in enumerate(rows_db,start=1):
  k=classify(r['t'],r['n'])
  rows.append({'instance_id':f'sb_{i:04d}','source_table':'field_alleys','source_id':r['sid'],'service_key':k,'asset_path':f'/Game/Street/Service/SM_{k}_A_standard','x_cm':f'{(float(r["x"])-ORIGIN_X)*100:.1f}','y_cm':f'{(float(r["y"])-ORIGIN_Y)*100:.1f}','z_cm':'0.0','yaw_deg':'0.0','uniform_scale':'1.000','metadata_json':json.dumps({'type_voie':r['t'],'nom_ruelle':r['n']},ensure_ascii=False)})
 out=OUT/'service_backlot_instances_unreal_cm.csv'
 with out.open('w',encoding='utf-8',newline='') as f:
  w=csv.DictWriter(f,fieldnames=list(rows[0].keys()) if rows else []); w.writeheader(); w.writerows(rows)
 print('[OK] Wrote',out); return 0
if __name__=='__main__': raise SystemExit(main())

