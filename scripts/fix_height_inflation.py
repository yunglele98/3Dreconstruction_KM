#!/usr/bin/env python3
"""
Script to fix height inflation in building parameter files.
Recalibrates 'total_height_m' for severe outliers based on database 'BLDG_HEIGHT_AVG_M'.
"""
import json
import re
import psycopg2
from pathlib import Path
from db_config import DB_CONFIG, get_connection
from fuzzywuzzy import fuzz
from fuzzywuzzy import process

ROOT = Path(__file__).resolve().parent.parent
PARAMS_DIR = ROOT / "params"

# Define a reasonable roof allowance if total_height_m needs to be re-anchored
DEFAULT_ROOF_ALLOWANCE = 2.0 # meters
FUZZY_MATCH_THRESHOLD = 85 # Minimum score for a fuzzy match

def normalize_address(address):
    """Applies robust normalization rules to an address string."""
    address = str(address).lower() # Convert to string and lowercase
    # Remove parenthetical labels (e.g., "(Urban Catwalk)")
    address = re.sub(r'\s*\(.*\)', '', address)
    # Keep first address when slash-separated (e.g., "A / B" -> "A")
    address = address.split('/')[0].strip()
    # Remove trailing descriptors (e.g., "area", "notes", "St", "Ave", "Pl", "Rd", "Cres")
    address = re.sub(r'\s+(area|notes|st|ave|pl|rd|cres|ter|sq|blvd)\b', '', address, flags=re.IGNORECASE)
    # Remove common extra words that might not be in the DB
    address = re.sub(r'\s+(north|south|east|west|upper|lower|old|new)\b', '', address, flags=re.IGNORECASE)
    address = address.replace('_', ' ') # Replace underscores from filenames with spaces
    address = re.sub(r'\s+', ' ', address).strip() # Replace multiple spaces with single space
    return address

def get_db_height_data():
    """Connects to the database and fetches average building heights."""
    db_height_lookup = {} # {normalized_address: BLDG_HEIGHT_AVG_M}
    db_addresses_normalized_list = [] # List for fuzzy matching
    try:
        conn = get_connection()
        cur = conn.cursor()
        # Fetch all addresses and their average heights
        cur.execute("SELECT \"ADDRESS_FULL\", \"BLDG_HEIGHT_AVG_M\" FROM public.building_assessment;")
        for row in cur.fetchall():
            address_full, avg_height = row
            normalized_address = normalize_address(address_full)
            if normalized_address:
                db_height_lookup[normalized_address] = avg_height # Store original height for lookup
                db_addresses_normalized_list.append(normalized_address)
        cur.close()
        conn.close()
    except Exception as e:
        print(f"Database connection or query failed: {e}")
    return db_height_lookup, db_addresses_normalized_list

def fix_height_inflation():
    print("Starting height inflation fix (with fuzzy matching)...")
    db_height_lookup, db_addresses_normalized_list = get_db_height_data()
    if not db_height_lookup:
        print("Could not retrieve height data from the database. Aborting.")
        return

    param_files = sorted(PARAMS_DIR.glob("*.json"))
    modified_files = []
    matched_and_checked = [] # For reporting all matched files and their ratios

    for param_file in param_files:
        if param_file.name.startswith("_"):
            continue # Skip metadata files

        try:
            with open(param_file, 'r', encoding='utf-8') as f:
                params = json.load(f)
            
            filename_stem = param_file.stem
            param_address_normalized = normalize_address(filename_stem)

            if not param_address_normalized:
                continue # Skip if normalized address is empty

            # Try to find a match for the parameter file's address
            best_match_normalized_address = None
            if param_address_normalized in db_height_lookup: # Exact match
                best_match_normalized_address = param_address_normalized
            else: # Try fuzzy match
                best_match = process.extractOne(param_address_normalized, db_addresses_normalized_list, scorer=fuzz.ratio)
                if best_match and best_match[1] >= FUZZY_MATCH_THRESHOLD:
                    best_match_normalized_address = best_match[0]

            if best_match_normalized_address:
                db_avg_height = db_height_lookup.get(best_match_normalized_address)
                param_total_height = params.get('total_height_m')

                if db_avg_height is not None and param_total_height is not None:
                    try:
                        db_avg_height = float(db_avg_height)
                        param_total_height = float(param_total_height)
                    except (TypeError, ValueError):
                        continue
                    if db_avg_height > 0: # Avoid division by zero
                        ratio = param_total_height / db_avg_height
                        
                        matched_info = {
                            'address': filename_stem,
                            'param_height': param_total_height,
                            'db_avg_height': db_avg_height,
                            'ratio': ratio,
                            'file': str(param_file.relative_to(ROOT)),
                            'fuzzy_score': best_match[1] if best_match_normalized_address != param_address_normalized else 'exact'
                        }
                        matched_and_checked.append(matched_info)

                        if ratio >= 2.5: # Severe outlier
                            new_total_height = db_avg_height + DEFAULT_ROOF_ALLOWANCE
                            
                            old_total_height = params['total_height_m']
                            params['total_height_m'] = round(new_total_height, 2)

                            modified_files.append({
                                'address': filename_stem,
                                'old_height': old_total_height,
                                'new_height': params['total_height_m'],
                                'db_avg_height': db_avg_height,
                                'ratio': ratio,
                                'file': str(param_file.relative_to(ROOT))
                            })

                            with open(param_file, 'w', encoding='utf-8') as f:
                                json.dump(params, f, indent=2, ensure_ascii=False)
                    else:
                        # db_avg_height is 0, cannot calculate ratio for this matched building
                        print(f"Warning: Matched file '{filename_stem}' has DB average height of 0. Skipping ratio check.")
                # else:
                    # One of the height values is missing, cannot check ratio for this matched building
            # else:
                # No match found for param_file
        except json.JSONDecodeError:
            print(f"Warning: Could not decode JSON from {param_file.name}")
        except Exception as e:
            print(f"Error processing {param_file.name}: {e}")

    print(f"\n--- Height Inflation Fix Report ---")
    if matched_and_checked:
        print(f"Total matched parameter files checked for height inflation: {len(matched_and_checked)}\n")
        print("Details of all matched files and their ratios (sorted by ratio descending):")
        
        # Sort by ratio descending to highlight outliers
        matched_and_checked.sort(key=lambda x: x['ratio'], reverse=True)

        for info in matched_and_checked:
            print(f"  Address: {info['address']} (Matched by: {info['fuzzy_score']})")
            print(f"    File: {info['file']}")
            print(f"    Param total_height_m: {info['param_height']:.2f}m")
            print(f"    DB average height: {info['db_avg_height']:.2f}m")
            print(f"    Ratio (Param/DB): {info['ratio']:.2f}\n")
    
    if modified_files:
        print(f"Modified {len(modified_files)} parameter files due to severe height inflation (ratio >= 2.5):")
        for mod in modified_files:
            print(f"  Address: {mod['address']}")
            print(f"    File: {mod['file']}")
            print(f"    Original total_height_m: {mod['old_height']:.2f}m")
            print(f"    DB average height: {mod['db_avg_height']:.2f}m (Ratio: {mod['ratio']:.2f})")
            print(f"    New total_height_m: {mod['new_height']:.2f}m (DB avg + {DEFAULT_ROOF_ALLOWANCE}m allowance)\n")
        print("Note: 'floor_heights_m' were not automatically adjusted and may need manual review.")
    else:
        print("No severe height inflation outliers found (ratio >= 2.5) that required modification.")

    print("Fix complete.")

if __name__ == "__main__":
    fix_height_inflation()

