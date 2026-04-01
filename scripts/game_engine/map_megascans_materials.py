import json
import csv
import os
from pathlib import Path

ROOT = Path("C:/Users/liam1/blender_buildings")
PARAMS_DIR = ROOT / "params"
OUTPUT_FILE = ROOT / "outputs" / "exports" / "megascans_mapping.csv"

# Extended PBR Library Mapping
MATERIAL_LIBRARY = {
    "brick": "smbpbg3fw",      # Red Brick
    "brick_buff": "se1gbfyfw", # Buff Brick (Historic)
    "stone": "scuofid",        # Rough Stone
    "stucco": "vbmkeat",       # White Stucco
    "wood": "vbeidca",         # Weathered Wood
    "clapboard": "vhkidca",    # Painted Wood Siding
    "concrete": "vdbidfa",     # Industrial Concrete
    "masonry": "vbjidba"       # Mixed Masonry
}

def infer_material(params):
    """Predict material based on history and typology if 'unknown'."""
    typology = (params.get("typology") or "").lower()
    year_str = (params.get("hcd_data", {}).get("construction_date") or "").lower()
    
    if "house" in typology or "victorian" in year_str or "18" in year_str:
        return "brick_buff"
    if "commercial" in typology or "shop" in typology:
        return "brick"
    if "modern" in year_str or "197" in year_str:
        return "concrete"
    return "brick" # Default Kensington fallback

def run_unity_mapping():
    results = []
    files = list(PARAMS_DIR.glob("*.json"))
    
    print(f"Processing {len(files)} buildings for Material Unity...")
    
    for pf in files:
        if pf.name.startswith("_") or "supplementary" in str(pf):
            continue
            
        with open(pf, "r", encoding="utf-8") as f:
            try:
                data = json.load(f)
            except: continue
            
        addr = data.get("address", pf.stem)
        raw_mat = (data.get("facade_material") or "unknown").lower().strip()
        
        # Apply Inference
        if raw_mat == "unknown" or raw_mat == "":
            final_mat = infer_material(data)
        elif "brick" in raw_mat:
            final_mat = "brick"
        elif "stone" in raw_mat:
            final_mat = "stone"
        elif "stucco" in raw_mat:
            final_mat = "stucco"
        elif "wood" in raw_mat or "siding" in raw_mat or "clapboard" in raw_mat:
            final_mat = "wood"
        elif "concrete" in raw_mat:
            final_mat = "concrete"
        else:
            final_mat = "brick"

        surface_id = MATERIAL_LIBRARY.get(final_mat, MATERIAL_LIBRARY["brick"])
        results.append([addr, final_mat, surface_id, pf.name])

    # Write the high-fidelity mapping
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["address", "material_class", "megascans_id", "param_file"])
        writer.writerows(results)
        
    print(f"Material Unity Complete: {len(results)} buildings mapped to PBR library.")

if __name__ == "__main__":
    run_unity_mapping()
