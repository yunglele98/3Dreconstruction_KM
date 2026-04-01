import sys
from pathlib import Path

ROOT = Path("C:/Users/liam1/blender_buildings")
sys.path.append(str(ROOT / "scripts"))

try:
    from db_config import get_connection
except ImportError:
    print("Could not import get_connection")
    sys.exit(1)

def get_targets():
    conn = get_connection()
    cur = conn.cursor()
    
    # 1. Get neglected Dundas buildings
    cur.execute("""
        SELECT "ADDRESS_FULL", id 
        FROM building_assessment 
        WHERE ba_street = 'Dundas St W' 
          AND (photo_analyzed = false OR photo_analyzed IS NULL)
    """)
    neglected = cur.fetchall()
    
    # 2. Get extreme height mismatches near Dundas
    cur.execute("""
        SELECT ba."ADDRESS_FULL", ba.id
        FROM building_assessment ba
        JOIN opendata.building_footprints fp ON ST_Intersects(ba.geom, ST_Transform(fp.geom, 4326))
        JOIN opendata.massing_3d m ON ST_Intersects(m.geometry, fp.geom)
        WHERE ba_street = 'Dundas St W' OR ba_street = 'College St'
          AND ABS(NULLIF(ba."BLDG_HEIGHT_MAX_M", '')::double precision - m."AVG_HEIGHT") > 15.0
    """)
    mismatches = cur.fetchall()
    
    print("--- Targets for Dundas Enrichment ---")
    print("Neglected Photo Analysis:")
    for row in neglected:
        print(f" - {row[0]} (ID: {row[1]})")
        
    print("\nHeight Mismatches:")
    for row in mismatches:
        print(f" - {row[0]} (ID: {row[1]})")
        
    cur.close()
    conn.close()

if __name__ == "__main__":
    get_targets()
