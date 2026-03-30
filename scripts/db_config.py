"""Shared database configuration for the Kensington pipeline."""

import os
import sys

DB_CONFIG = {
    "host": os.environ.get("PGHOST", "localhost"),
    "port": int(os.environ.get("PGPORT", 5432)),
    "dbname": os.environ.get("PGDATABASE", "kensington"),
    "user": os.environ.get("PGUSER", "postgres"),
    "password": os.environ.get("PGPASSWORD", "test123"),
    "connect_timeout": 5,
}

def get_connection():
    """Returns a psycopg2 connection or exits with a clear error."""
    import psycopg2
    try:
        return psycopg2.connect(**DB_CONFIG)
    except psycopg2.OperationalError as e:
        print(f"\n[ERROR] Database connection failed.")
        print(f"Target: {DB_CONFIG['user']}@{DB_CONFIG['host']}:{DB_CONFIG['port']}/{DB_CONFIG['dbname']}")
        print(f"Error: {e}")
        print("\nPossible causes:")
        print("1. PostgreSQL service is not running.")
        print("2. Database 'kensington' does not exist.")
        print("3. Credentials in db_config.py are incorrect.")
        print("4. Network/Firewall blocking port 5432.")
        sys.exit(1)
    except Exception as e:
        print(f"\n[ERROR] Unexpected database error: {e}")
        sys.exit(1)
