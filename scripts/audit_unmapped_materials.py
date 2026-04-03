import json
import os
from pathlib import Path
from collections import Counter

ROOT = Path(__file__).resolve().parent.parent
PARAMS_DIR = ROOT / "params"

def find_unmapped_materials():
    # Load the mapping we already generated
    mapping_file = ROOT / "outputs" / "exports" / "megascans_mapping.csv"
    mapped_addresses = set()
    if mapping_file.exists():
        with open(mapping_file, "r", encoding="utf-8") as f:
            for line in f:
                mapped_addresses.add(line.split(",")[0].strip('"'))

    files = list(PARAMS_DIR.glob("*.json"))
    unmapped_types = []
    targets = []

    for pf in files:
        if pf.name.startswith("_") or "supplementary" in str(pf):
            continue
            
        with open(pf, encoding="utf-8") as f:
            try:
                data = json.load(f)
                addr = data.get("address", pf.stem)
                if addr not in mapped_addresses:
                    mat = data.get("facade_material", "unknown")
                    unmapped_types.append(mat)
                    targets.append({"address": addr, "material": mat})
            except Exception:
                continue

    print(f"--- Material Coverage Report ---")
    print(f"Total Unmapped Buildings: {len(targets)}")
    print("\nMost Common Unmapped Material Labels:")
    for mat, count in Counter(unmapped_types).most_common(10):
        print(f" - '{mat}': {count} buildings")
        
    # Save the list for the next step
    with open(ROOT / "outputs" / "unmapped_materials.json", "w", encoding="utf-8") as f:
        json.dump(targets, f, indent=2)

if __name__ == "__main__":
    find_unmapped_materials()
