#!/usr/bin/env python3
"""
Batch Storefront Sync Script
============================
Syncs 'has_storefront' parameter with DB record to resolve audit conflicts.
"""

import json
import re
import psycopg2
from pathlib import Path
from db_config import DB_CONFIG, get_connection

ROOT = Path(__file__).resolve().parent.parent
PARAMS_DIR = ROOT / "params"

def normalize_address(address):
    address = re.sub(r'\s*\(.*\)', '', address)
    address = address.split('/')[0].strip()
    address = re.sub(r'\s+(area|notes|St|Ave|Pl)$', '', address, flags=re.IGNORECASE)
    address = address.replace('_', ' ').strip()
    return address

def get_db_storefront_data():
    db_storefront_data = {}
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT \"ADDRESS_FULL\", \"ba_storefront_status\" FROM public.building_assessment;")
        for row in cur.fetchall():
            address_full, storefront_status = row
            normalized_address = normalize_address(address_full)
            if storefront_status == 'Yes':
                db_storefront_data[normalized_address] = True
            elif storefront_status == 'No':
                db_storefront_data[normalized_address] = False
        cur.close()
        conn.close()
    except Exception as e:
        print(f"Database connection or query failed: {e}")
    return db_storefront_data

def sync_storefronts():
    print("Starting storefront sync...")
    db_storefront_data = get_db_storefront_data()
    if not db_storefront_data:
        return

    param_files = sorted(PARAMS_DIR.glob("*.json"))
    fixed_count = 0
    
    for param_file in param_files:
        if param_file.name.startswith(("_", ".")) or "backup" in param_file.name:
            continue

        try:
            with open(param_file, 'r', encoding='utf-8') as f:
                params = json.load(f)
            
            param_address = normalize_address(param_file.stem)
            db_has_storefront = db_storefront_data.get(param_address)

            if db_has_storefront is not None:
                if params.get('has_storefront') != db_has_storefront:
                    params['has_storefront'] = db_has_storefront
                    # Also ensure storefront object exists if true
                    if db_has_storefront and not params.get('storefront'):
                        params['storefront'] = {
                            "type": "Commercial ground floor",
                            "status": "synced_from_db"
                        }
                    elif not db_has_storefront and 'storefront' in params:
                        del params['storefront']

                    with open(param_file, 'w', encoding='utf-8') as f:
                        json.dump(params, f, indent=2, ensure_ascii=False)
                        f.write("\n")
                    fixed_count += 1
                    print(f"  [SYNC] {param_file.name}: set has_storefront={db_has_storefront}")
        except Exception as e:
            print(f"Error processing {param_file.name}: {e}")

    print(f"\nDone: {fixed_count} files synced with database storefront status.")

if __name__ == "__main__":
    sync_storefronts()

