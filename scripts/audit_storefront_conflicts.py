#!/usr/bin/env python3
"""
Script to audit storefront conflicts.
Finds buildings where the 'has_storefront' parameter conflicts with the database record.
"""
import json
import re
import psycopg2
from pathlib import Path
from db_config import DB_CONFIG, get_connection

ROOT = Path(__file__).resolve().parent.parent
PARAMS_DIR = ROOT / "params"

def normalize_address(address):
    """Applies normalization rules to an address string for matching."""
    address = re.sub(r'\s*\(.*\)', '', address)
    address = address.split('/')[0].strip()
    address = re.sub(r'\s+(area|notes|St|Ave|Pl)$', '', address, flags=re.IGNORECASE)
    address = address.replace('_', ' ').strip()
    return address

def get_db_storefront_data():
    """Connects to the database and fetches storefront status for all buildings."""
    db_storefront_data = {} # {normalized_address: has_storefront_bool}
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT \"ADDRESS_FULL\", \"ba_storefront_status\" FROM public.building_assessment;")
        for row in cur.fetchall():
            address_full, storefront_status = row
            normalized_address = normalize_address(address_full)
            # Convert 'Yes'/'No'/'' to True/False/None
            if storefront_status == 'Yes':
                db_storefront_data[normalized_address] = True
            elif storefront_status == 'No':
                db_storefront_data[normalized_address] = False
            else:
                db_storefront_data[normalized_address] = None # Unknown or not specified
        cur.close()
        conn.close()
    except Exception as e:
        print(f"Database connection or query failed: {e}")
    return db_storefront_data

def audit_storefront_conflicts():
    print("Starting storefront conflict audit...")
    db_storefront_data = get_db_storefront_data()
    if not db_storefront_data:
        print("Could not retrieve storefront data from the database. Aborting.")
        return

    param_files = sorted(PARAMS_DIR.glob("*.json"))
    conflicts = []
    
    for param_file in param_files:
        if param_file.name.startswith("_"):
            continue # Skip metadata files

        try:
            with open(param_file, 'r', encoding='utf-8') as f:
                params = json.load(f)
            
            filename_stem = param_file.stem
            param_address = normalize_address(filename_stem)
            
            # Skip if no DB entry for this address
            if param_address not in db_storefront_data:
                continue

            db_has_storefront = db_storefront_data.get(param_address)
            param_has_storefront = params.get('has_storefront')

            # Only report if both are defined and conflict
            if db_has_storefront is not None and param_has_storefront is not None:
                # Direct conflict: DB says True, JSON says False, or vice versa
                if bool(db_has_storefront) != bool(param_has_storefront):
                    conflicts.append({
                        'address': filename_stem,
                        'db_value': db_has_storefront,
                        'param_value': param_has_storefront,
                        'file': str(param_file.relative_to(ROOT))
                    })
        except json.JSONDecodeError:
            print(f"Warning: Could not decode JSON from {param_file.name}")
        except Exception as e:
            print(f"Error processing {param_file.name}: {e}")

    print(f"\n--- Storefront Conflict Audit Report ---")
    if conflicts:
        print(f"Found {len(conflicts)} conflicts:")
        for conflict in conflicts:
            print(f"  Address: {conflict['address']}")
            print(f"    DB has_storefront: {conflict['db_value']}")
            print(f"    Param has_storefront: {conflict['param_value']}")
            print(f"    File: {conflict['file']}\n")
    else:
        print("No storefront conflicts found between parameters and database records.")

    print("Audit complete.")

if __name__ == "__main__":
    audit_storefront_conflicts()

