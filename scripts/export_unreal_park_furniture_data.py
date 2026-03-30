#!/usr/bin/env python3
from __future__ import annotations
import csv, json
from pathlib import Path
import psycopg2, psycopg2.extras
from db_config import DB_CONFIG, get_connection
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'outputs'/'park_furniture'
ORIGIN_X=312672.94; ORIGIN_Y=4834994.86

def classify(name:str, typ:str)->str:
 t=(name or '').lower()+' '+(typ or '').lower()
 if 'jeux' in t or 'play' in t: return 'park_play_element'
 if 'square' in t: return 'park_planter_module'
 return 'park_bench_module'

def main()->int:
 OUT.mkdir(parents=True,exist_ok=True)
 conn=get_connection()
 try:
  cur=conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
  cur.execute("SELECT id::text sid, COALESCE(nom,'') nom, COALESCE(type_aire,'') typ, ST_X(ST_Transform(geom,2952)) x, ST_Y(ST_Transform(geom,2952)) y FROM field_parks WHERE geom IS NOT NULL ORDER BY id")
  pts=cur.fetchall()
 finally:
  conn.close()
 rows=[]
 for i,p in enumerate(pts,start=1):
  k=classify(p['nom'],p['typ'])
  rows.append({'instance_id':f'pkf_{i:04d}','source_table':'field_parks','source_id':p['sid'],'park_key':k,'asset_path':f'/Game/Street/Park/SM_{k}_A_standard','x_cm':f'{(float(p["x"])-ORIGIN_X)*100:.1f}','y_cm':f'{(float(p["y"])-ORIGIN_Y)*100:.1f}','z_cm':'0.0','yaw_deg':'0.0','uniform_scale':'1.000','metadata_json':json.dumps({'nom':p['nom'],'type_aire':p['typ']},ensure_ascii=False)})
 out=OUT/'park_furniture_instances_unreal_cm.csv'
 with out.open('w',encoding='utf-8',newline='') as f:
  w=csv.DictWriter(f,fieldnames=list(rows[0].keys()) if rows else []); w.writeheader(); w.writerows(rows)
 print('[OK] Wrote',out); return 0
if __name__=='__main__': raise SystemExit(main())

