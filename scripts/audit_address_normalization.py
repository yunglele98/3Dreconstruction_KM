#!/usr/bin/env python3
"""
Script to audit address normalization.
Identifies parameter files where the address is not found in the database,
and suggests a normalized address that might match.
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

def get_db_addresses():
    """Connects to the database and fetches all ADDRESS_FULL."""
    db_addresses_raw = [] # Store raw for fuzzy matching later
    db_addresses_normalized = set()
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT \"ADDRESS_FULL\" FROM public.building_assessment;")
        for row in cur.fetchall():
            raw_address = row[0]
            normalized_address = normalize_address(raw_address)
            if normalized_address:
                db_addresses_raw.append(raw_address)
                db_addresses_normalized.add(normalized_address)
        cur.close()
        conn.close()
    except Exception as e:
        print(f"Database connection or query failed: {e}")
    return db_addresses_normalized, db_addresses_raw

def audit_address_normalization():
    print("Starting address normalization audit (with fuzzy matching)...")
    db_addresses_normalized, db_addresses_raw = get_db_addresses()
    if not db_addresses_normalized:
        print("Could not retrieve addresses from the database. Aborting.")
        return

    param_files = sorted(PARAMS_DIR.glob("*.json"))
    total_files = len(param_files)
    matched_exact = 0
    matched_fuzzy = []
    unmatched_files = []

    # Prepare a list of all normalized DB addresses for fuzzy matching
    db_address_list = list(db_addresses_normalized)

    for param_file in param_files:
        if param_file.name.startswith("_"):
            continue # Skip metadata files

        filename_stem = param_file.stem
        param_address_normalized = normalize_address(filename_stem)

        if not param_address_normalized: # Skip if normalization results in empty string
            unmatched_files.append((filename_stem, "Normalized to empty string"))
            continue

        # Check for exact match
        if param_address_normalized in db_addresses_normalized:
            matched_exact += 1
        else:
            # Try fuzzy matching against all normalized DB addresses
            # Use process.extractOne to get the best match
            best_match = process.extractOne(param_address_normalized, db_address_list, scorer=fuzz.ratio)
            
            # best_match is (match, score)
            if best_match and best_match[1] >= 85: # Threshold for a good fuzzy match
                matched_fuzzy.append({
                    'original_filename': filename_stem,
                    'param_normalized': param_address_normalized,
                    'db_best_match_normalized': best_match[0],
                    'fuzzy_score': best_match[1],
                    'file': str(param_file.relative_to(ROOT))
                })
            else:
                unmatched_files.append((filename_stem, param_address_normalized))

    print(f"\n--- Address Normalization Audit Report ---")
    print(f"Total param files processed: {total_files}")
    print(f"Files matched exactly: {matched_exact}")
    print(f"Files matched via fuzzy logic (score >= 85): {len(matched_fuzzy)}")
    print(f"Files still unmatched or normalized to empty: {len(unmatched_files)}")

    if matched_fuzzy:
        print("\nFiles that matched via fuzzy logic:")
        for match_info in matched_fuzzy:
            print(f"  File: {match_info['file']}")
            print(f"    Original filename stem: '{match_info['original_filename']}'")
            print(f"    Param (normalized): '{match_info['param_normalized']}'")
            print(f"    DB Best Match (normalized): '{match_info['db_best_match_normalized']}'")
            print(f"    Fuzzy Score: {match_info['fuzzy_score']}\n")

    if unmatched_files:
        print("\nFiles still unmatched or normalized to empty:")
        for original_filename, normalized_value in unmatched_files:
            print(f"  Original filename stem: '{original_filename}' (Normalized: '{normalized_value if normalized_value else 'EMPTY'}')")

    print("\nAudit complete.")

if __name__ == "__main__":
    audit_address_normalization()

