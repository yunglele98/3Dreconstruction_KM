import os
import sys
import psycopg2

# Try to import DB_CONFIG from scripts/db_config.py
sys.path.append(os.path.dirname(__file__))
try:
    from db_config import DB_CONFIG
except ImportError:
    DB_CONFIG = {
        "host": "localhost",
        "port": 5432,
        "dbname": "kensington",
        "user": "postgres",
        "password": "test123",
    }

def check_health():
    print(f"Connecting to {DB_CONFIG.get('dbname', 'kensington')} at {DB_CONFIG.get('host', 'localhost')}:{DB_CONFIG.get('port', 5432)}...")
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor()
        print("PASS: Connection established.")
        
        cur.execute("SELECT version();")
        print(f"PostgreSQL version: {cur.fetchone()[0]}")
        
        cur.execute("SELECT 1 FROM pg_extension WHERE extname='postgis';")
        res = cur.fetchone()
        if res:
            print("PASS: PostGIS extension found.")
        else:
            print("FAIL: PostGIS extension not found.")
            
        # Check required tables
        tables = [
            ("public", "building_assessment"),
            ("opendata", "building_footprints"),
            ("opendata", "massing_3d"),
            ("opendata", "road_centerlines"),
            ("opendata", "sidewalks")
        ]
        
        for schema, table in tables:
            try:
                cur.execute(f"SELECT COUNT(*) FROM {schema}.{table};")
                count = cur.fetchone()[0]
                print(f"PASS: Table {schema}.{table} exists with {count} rows.")
            except Exception as te:
                print(f"FAIL: Table {schema}.{table} is not queryable: {te}")
                conn.rollback()
        
        cur.close()
        conn.close()
        return True
    except Exception as e:
        print(f"FAIL: Database connectivity/health check failed: {e}")
        return False

if __name__ == '__main__':
    success = check_health()
    sys.exit(0 if success else 1)
