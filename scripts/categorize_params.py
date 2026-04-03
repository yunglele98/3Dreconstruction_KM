import os
import json
import sys
import shutil
from pathlib import Path

# Setup paths
ROOT = Path("C:/Users/liam1/blender_buildings")
PARAMS_DIR = ROOT / "params"
sys.path.append(str(ROOT / "scripts" / "db"))

try:
    from db_config import get_connection
except ImportError as e:
    print(f"Could not import get_connection from db_config: {e}")
    sys.exit(1)

def categorize():
    try:
        conn = get_connection()
    except Exception as e:
        print(f"Connection failed: {e}")
        sys.exit(1)
        
    cur = conn.cursor()
    
    # Get all valid IDs and Addresses from DB
    cur.execute("SELECT id, UPPER(\"ADDRESS_FULL\") FROM building_assessment")
    db_data = cur.fetchall()
    db_ids = {row[0] for row in db_data}
    db_addrs = {row[1] for row in db_data if row[1]}
    
    print(f"Database has {len(db_ids)} records.")
    
    supp_dir = PARAMS_DIR / "supplementary"
    supp_dir.mkdir(parents=True, exist_ok=True)
    
    files = list(PARAMS_DIR.glob("*.json"))
    canonical = 0
    matched = 0
    supplementary = 0
    
    for pf in files:
        if pf.name.startswith("_") or pf.name == ".json":
            continue
            
        with open(pf, encoding="utf-8") as f:
            try:
                data = json.load(f)
            except Exception:
                continue
        
        # Check if canonical (has valid ID)
        b_id = data.get("building_id") or data.get("id")
        if b_id and b_id in db_ids:
            canonical += 1
            continue
            
        # Check if matched by address
        addr = data.get("address") or data.get("building_name") or pf.stem.replace("_", " ")
        if addr.upper() in db_addrs:
            matched += 1
            continue
            
        # Otherwise, move to supplementary
        try:
            shutil.move(str(pf), str(supp_dir / pf.name))
            supplementary += 1
        except Exception as e:
            print(f"Failed to move {pf.name}: {e}")
        
    print(f"Categorization Complete:")
    print(f" - Canonical (ID match): {canonical}")
    print(f" - Matched (Address match): {matched}")
    print(f" - Supplementary (Moved): {supplementary}")
    
    cur.close()
    conn.close()

if __name__ == "__main__":
    categorize()
