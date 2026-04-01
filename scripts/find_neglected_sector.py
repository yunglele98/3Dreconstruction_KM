import sys
import os
from pathlib import Path

ROOT = Path("C:/Users/liam1/blender_buildings")
sys.path.append(str(ROOT / "scripts"))

try:
    from db_config import get_connection
except ImportError as e:
    print(f"Could not import get_connection: {e}")
    sys.exit(1)

def find_neglected():
    try:
        conn = get_connection()
    except Exception as e:
        print(f"Connection failed: {e}")
        sys.exit(1)
        
    cur = conn.cursor()
    
    # Group by street and check photo analysis coverage
    cur.execute("""
        SELECT ba_street, 
               count(*) as total,
               sum(case when photo_analyzed = true then 1 else 0 end) as analyzed,
               sum(case when photo_analyzed = false or photo_analyzed is null then 1 else 0 end) as neglected
        FROM building_assessment
        WHERE ba_street IS NOT NULL
        GROUP BY ba_street
        ORDER BY neglected DESC
        LIMIT 10;
    """)
    
    rows = cur.fetchall()
    print(f"{'Street':<25} | {'Total':<8} | {'Analyzed':<10} | {'Neglected':<10}")
    print("-" * 65)
    for row in rows:
        print(f"{str(row[0]):<25} | {row[1]:<8} | {row[2]:<10} | {row[3]:<10}")
        
    cur.close()
    conn.close()

if __name__ == "__main__":
    find_neglected()
