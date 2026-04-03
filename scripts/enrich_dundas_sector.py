import sys
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(ROOT / "scripts"))

try:
    from db_config import get_connection
except ImportError:
    print("Could not import get_connection")
    sys.exit(1)

def enrich_dundas():
    conn = get_connection()
    cur = conn.cursor()
    
    print("=== Enriching Neglected Dundas Sector ===")
    
    # 1. Fetch correct heights from massing for all mismatches
    cur.execute("""
        SELECT ba."ADDRESS_FULL", m."AVG_HEIGHT"
        FROM building_assessment ba
        JOIN opendata.building_footprints fp ON ST_Intersects(ba.geom, ST_Transform(fp.geom, 4326))
        JOIN opendata.massing_3d m ON ST_Intersects(m.geometry, fp.geom)
        WHERE ba_street = 'Dundas St W' OR ba_street = 'College St'
    """)
    rows = cur.fetchall()
    
    updated = 0
    for addr, h in rows:
        # Convert address to filename
        fname = addr.replace(" ", "_") + ".json"
        p_path = ROOT / "params" / fname
        
        if p_path.exists():
            with open(p_path, "r", encoding="utf-8") as f:
                try:
                    data = json.load(f)
                except: continue
            
            # Update height
            data["total_height_m"] = round(float(h), 2)
            # Redistribute floors if they exist
            if "floor_heights_m" in data and data["floor_heights_m"]:
                n = len(data["floor_heights_m"])
                h_per = round(float(h) / n, 2)
                data["floor_heights_m"] = [h_per] * n
            
            # Mark as fixed
            data["handoff_fixes_applied"] = True
            data["notes"] = data.get("notes", "") + " [AUTO-ENRICH: Neglected Sector Priority Fix]"
            
            with open(p_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            updated += 1
            
    print(f"Successfully enriched {updated} param files in the Dundas sector.")
    cur.close()
    conn.close()

if __name__ == "__main__":
    enrich_dundas()
