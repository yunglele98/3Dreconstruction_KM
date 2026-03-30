#!/usr/bin/env python3
"""
Script to fix structural inconsistencies in building parameter files.
Automatically adjusts 'total_height_m' if it differs significantly from 'sum(floor_heights_m)'.
Also reports discrepancies in 'floors' count and average floor height outside a specified range.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PARAMS_DIR = ROOT / "params"

HEIGHT_DIFFERENCE_THRESHOLD = 0.75 # meters
MIN_AVG_FLOOR_HEIGHT = 2.4 # meters
MAX_AVG_FLOOR_HEIGHT = 4.8 # meters

def fix_structural_consistency():
    print("Starting structural consistency fix...")
    param_files = sorted(PARAMS_DIR.glob("*.json"))
    
    modified_total_height_files = []
    floor_count_discrepancies = []
    avg_floor_height_warnings = []

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

            # --- Check 1: len(floor_heights_m) vs floors ---
            if isinstance(floors, (int, float)) and isinstance(floor_heights_m, list):
                if int(floors) != len(floor_heights_m):
                    floor_count_discrepancies.append({
                        'address': filename_stem,
                        'floors_param': floors,
                        'floor_heights_list_len': len(floor_heights_m),
                        'file': str(param_file.relative_to(ROOT))
                    })
            elif not isinstance(floors, (int, float)):
                # print(f"Warning: 'floors' is not a number in {filename_stem}")
                pass
            elif not isinstance(floor_heights_m, list):
                # print(f"Warning: 'floor_heights_m' is not a list in {filename_stem}")
                pass

            # --- Check 2: sum(floor_heights_m) vs total_height_m ---
            # Only proceed if floor_heights_m is a valid list and total_height_m is a number
            if isinstance(floor_heights_m, list) and all(isinstance(h, (int, float)) for h in floor_heights_m) and isinstance(total_height_m, (int, float)):
                calculated_total_height = sum(floor_heights_m)
                
                if abs(calculated_total_height - total_height_m) > HEIGHT_DIFFERENCE_THRESHOLD:
                    # Automatically adjust total_height_m to match the sum of floor_heights_m
                    old_total_height = params['total_height_m']
                    params['total_height_m'] = round(calculated_total_height, 2) # Round to 2 decimal places

                    modified_total_height_files.append({
                        'address': filename_stem,
                        'old_total_height': old_total_height,
                        'new_total_height': params['total_height_m'],
                        'calculated_sum_floor_heights': calculated_total_height,
                        'file': str(param_file.relative_to(ROOT))
                    })

                    # Write back the modified JSON
                    with open(param_file, 'w', encoding='utf-8') as f:
                        json.dump(params, f, indent=2, ensure_ascii=False)
            
            # --- QA Gate Check: 2.4 <= total_height_m / floors <= 4.8 ---
            # Use the potentially modified total_height_m for this check
            current_total_height = params.get('total_height_m')
            if isinstance(floors, (int, float)) and int(floors) > 0 and isinstance(current_total_height, (int, float)):
                avg_floor_height = current_total_height / int(floors)
                if not (MIN_AVG_FLOOR_HEIGHT <= avg_floor_height <= MAX_AVG_FLOOR_HEIGHT):
                    avg_floor_height_warnings.append({
                        'address': filename_stem,
                        'avg_floor_height': avg_floor_height,
                        'floors': floors,
                        'total_height_m': current_total_height,
                        'file': str(param_file.relative_to(ROOT))
                    })

        except json.JSONDecodeError:
            print(f"Warning: Could not decode JSON from {param_file.name}")
        except Exception as e:
            print(f"Error processing {param_file.name}: {e}")

    print(f"\n--- Structural Consistency Fix Report ---")

    if modified_total_height_files:
        print(f"Modified 'total_height_m' in {len(modified_total_height_files)} files:")
        for mod in modified_total_height_files:
            print(f"  Address: {mod['address']}")
            print(f"    File: {mod['file']}")
            print(f"    Original total_height_m: {mod['old_total_height']:.2f}m")
            print(f"    Calculated sum of floor_heights_m: {mod['calculated_sum_floor_heights']:.2f}m")
            print(f"    New total_height_m: {mod['new_total_height']:.2f}m\n")
    else:
        print("No 'total_height_m' values needed adjustment (abs difference > 0.75m from sum of floor heights).")

    if floor_count_discrepancies:
        print(f"\nFound {len(floor_count_discrepancies)} floor count discrepancies (len(floor_heights_m) != floors):")
        for disc in floor_count_discrepancies:
            print(f"  Address: {disc['address']}")
            print(f"    File: {disc['file']}")
            print(f"    'floors': {disc['floors_param']}, len('floor_heights_m'): {disc['floor_heights_list_len']}\n")
        print("These discrepancies were NOT automatically fixed and require manual review.")
    else:
        print("\nNo floor count discrepancies found.")

    if avg_floor_height_warnings:
        print(f"\nFound {len(avg_floor_height_warnings)} warnings for average floor height outside range [{MIN_AVG_FLOOR_HEIGHT}m, {MAX_AVG_FLOOR_HEIGHT}m]:")
        for warn in avg_floor_height_warnings:
            print(f"  Address: {warn['address']}")
            print(f"    File: {warn['file']}")
            print(f"    Average floor height: {warn['avg_floor_height']:.2f}m ('floors': {warn['floors']}, 'total_height_m': {warn['total_height_m']:.2f}m)\n")
        print("These are warnings ONLY and were NOT automatically fixed.")
    else:
        print("\nNo average floor height warnings found.")

    print("Fix complete.")

if __name__ == "__main__":
    fix_structural_consistency()
