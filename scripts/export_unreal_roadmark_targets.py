#!/usr/bin/env python3
from __future__ import annotations
import csv, json
from pathlib import Path
import psycopg2, psycopg2.extras
from db_config import DB_CONFIG, get_connection
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'outputs'/'road_markings'
ORIGIN_X=312672.94; ORIGIN_Y=4834994.86

def main()->int:
 OUT.mkdir(parents=True,exist_ok=True)
 conn=get_connection()
 try:
  cur=conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
  cur.execute("SELECT 'intersection' src, id::text sid, ST_X(ST_Transform(geom,2952)) x, ST_Y(ST_Transform(geom,2952)) y FROM field_intersections WHERE geom IS NOT NULL UNION ALL SELECT 'parking' src, id::text sid, ST_X(ST_Transform(geom,2952)) x, ST_Y(ST_Transform(geom,2952)) y FROM field_parking WHERE geom IS NOT NULL")
  pts=cur.fetchall()
 finally:
  conn.close()
 rows=[]
 for i,p in enumerate(pts,start=1):
  key='marking_crosswalk' if p['src']=='intersection' else 'marking_lane_text'
  rows.append({'target_id':f'rm_{i:04d}','source_table':p['src'],'source_id':p['sid'],'marking_key':key,'x_cm':f'{(float(p["x"])-ORIGIN_X)*100:.1f}','y_cm':f'{(float(p["y"])-ORIGIN_Y)*100:.1f}','z_cm':'1.0','yaw_deg':'0.0','uniform_scale':'1.000','metadata_json':json.dumps({},ensure_ascii=False)})
 out=OUT/'roadmark_targets_unreal_cm.csv'
 with out.open('w',encoding='utf-8',newline='') as f:
  w=csv.DictWriter(f,fieldnames=list(rows[0].keys()) if rows else []); w.writeheader(); w.writerows(rows)
 print('[OK] Wrote',out); return 0
if __name__=='__main__': raise SystemExit(main())

