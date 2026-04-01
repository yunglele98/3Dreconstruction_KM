import json
import os
from pathlib import Path

ROOT = Path("C:/Users/liam1/blender_buildings")
PARAMS_DIR = ROOT / "params"

def audit_depth():
    files = list(PARAMS_DIR.glob("*.json"))
    total = 0
    with_windows = 0
    with_doors = 0
    with_decorative = 0
    with_storefront = 0
    
    for pf in files:
        if pf.name.startswith("_") or "supplementary" in str(pf):
            continue
            
        with open(pf, "r", encoding="utf-8") as f:
            try:
                data = json.load(f)
                if data.get("skipped"): continue
            except: continue
            
        total += 1
        # Check all possible locations for detailed data
        deep = data.get("deep_facade_analysis", {})
        obs = data.get("photo_observations", {})
        
        has_win = (deep.get("windows_detail") or 
                   obs.get("windows_detail") or 
                   data.get("windows") or 
                   len(data.get("windows_detail", [])) > 0)
                   
        has_door = (deep.get("doors_observed") or 
                    obs.get("doors_observed") or 
                    data.get("doors_detail") or 
                    len(data.get("doors_detail", [])) > 0)
                    
        has_deco = (deep.get("decorative_elements_observed") or 
                    obs.get("decorative_elements_observed") or 
                    data.get("decorative_elements"))
                    
        has_store = (deep.get("storefront_observed") or 
                     obs.get("storefront_observed") or 
                     data.get("storefront"))
        
        if has_win: with_windows += 1
        if has_door: with_doors += 1
        if has_deco: with_decorative += 1
        if has_store: with_storefront += 1
        
    print(f"--- Photo Analysis Depth Audit ---")
    print(f"Total Canonical Buildings: {total}")
    print(f"Buildings with detailed window data: {with_windows} ({with_windows/total*100:.1f}%)")
    print(f"Buildings with detailed door data:   {with_doors} ({with_doors/total*100:.1f}%)")
    print(f"Buildings with decorative detail:    {with_decorative} ({with_decorative/total*100:.1f}%)")
    print(f"Buildings with storefront detail:    {with_storefront} ({with_storefront/total*100:.1f}%)")

if __name__ == "__main__":
    audit_depth()
