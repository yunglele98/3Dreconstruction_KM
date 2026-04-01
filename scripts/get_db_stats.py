import sys
import os
from pathlib import Path

ROOT = Path("C:/Users/liam1/blender_buildings")
sys.path.append(str(ROOT / "scripts"))

try:
    from db_config import get_connection
except ImportError:
    print("Could not import get_connection from db_config")
    sys.exit(1)

def get_stats():
    conn = get_connection()
    cur = conn.cursor()
    
    cur.execute("""
        SELECT schemaname, tablename 
        FROM pg_catalog.pg_tables 
        WHERE schemaname IN ('public', 'opendata')
        ORDER BY schemaname, tablename;
    """)
    
    tables = cur.fetchall()
    print(f"{'Schema':<15} | {'Table':<30} | {'Rows':<10}")
    print("-" * 60)
    for schema, table in tables:
        try:
            cur.execute(f"SELECT COUNT(*) FROM {schema}.{table}")
            count = cur.fetchone()[0]
            print(f"{schema:<15} | {table:<30} | {count:<10}")
        except Exception as e:
            print(f"{schema:<15} | {table:<30} | ERROR: {e}")
            conn.rollback()
        
    cur.close()
    conn.close()

if __name__ == "__main__":
    get_stats()
