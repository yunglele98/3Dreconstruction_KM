#!/usr/bin/env python3
"""
Script to audit structural consistency of building parameters.
Verifies 'floors' vs 'floor_heights_m' length and sum of 'floor_heights_m' vs 'total_height_m'.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PARAMS_DIR = ROOT / "params"

def audit_structural_consistency():
    print("Starting structural consistency audit...")
    param_files = sorted(PARAMS_DIR.glob("*.json"))
    
    inconsistencies = []

    for param_file in param_files:
        if param_file.name.startswith("_"):
            continue # Skip metadata files

        try:
            with open(param_file, 'r', encoding='utf-8') as f:
                params = json.load(f)

            filename_stem = param_file.stem
            
            floors = params.get('floors')
            floor_heights_m = params.get('floor_heights_m')
            total_height_m = params.get('total_height_m')

            # Check 1: len(floor_heights_m) vs floors
            if isinstance(floors, (int, float)) and isinstance(floor_heights_m, list):
                if int(floors) != len(floor_heights_m):
                    inconsistencies.append({
                        'address': filename_stem,
                        'type': 'Floor count mismatch',
                        'detail': f" 'floors' ({floors}) != len('floor_heights_m') ({len(floor_heights_m)})",
                        'file': str(param_file.relative_to(ROOT))
                    })
            
            # Check 2: sum(floor_heights_m) vs total_height_m
            if isinstance(floor_heights_m, list) and isinstance(total_height_m, (int, float)):
                sum_floor_heights = sum(floor_heights_m)
                if abs(sum_floor_heights - total_height_m) > 0.75:
                    inconsistencies.append({
                        'address': filename_stem,
                        'type': 'Total height mismatch',
                        'detail': f" sum('floor_heights_m') ({sum_floor_heights:.2f}m) differs from 'total_height_m' ({total_height_m:.2f}m) by more than 0.75m",
                        'file': str(param_file.relative_to(ROOT))
                    })

        except json.JSONDecodeError:
            print(f"Warning: Could not decode JSON from {param_file.name}")
        except Exception as e:
            print(f"Error processing {param_file.name}: {e}")

    print(f"\n--- Structural Consistency Audit Report ---")
    if inconsistencies:
        print(f"Found {len(inconsistencies)} inconsistencies:")
        for inconsistency in inconsistencies:
            print(f"  Address: {inconsistency['address']}")
            print(f"    Type: {inconsistency['type']}")
            print(f"    Detail: {inconsistency['detail']}")
            print(f"    File: {inconsistency['file']}\n")
    else:
        print("No structural inconsistencies found in parameter files.")

    print("Audit complete.")

if __name__ == "__main__":
    audit_structural_consistency()
