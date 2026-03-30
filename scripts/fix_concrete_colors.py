#!/usr/bin/env python3
"""Batch-fix hex colors for Concrete/Grey buildings in params/*.json."""

import json
from pathlib import Path

PARAMS_DIR = Path(__file__).parent.parent / "params"

COLOR_MAP = {
    "concrete": "#A8A8A8",
    "cement": "#A8A8A8",
    "grey": "#8A8A8A",
    "gray": "#8A8A8A",
    "metal": "#7A7A7A",
    "glass": "#A0C0D0",
}

def fix_file(path: Path):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    
    if data.get("skipped"):
        return False

    material = str(data.get("facade_material", "")).lower()
    colour = str(data.get("facade_colour", "")).lower()
    combined = f"{colour} {material}"
    
    target_hex = None
    # Check for grey/gray first as it's more specific for color than generic 'concrete' material
    if "grey" in combined or "gray" in combined:
        target_hex = "#8A8A8A"
    elif "concrete" in combined or "cement" in combined:
        target_hex = "#A8A8A8"
    elif "metal" in combined:
        target_hex = "#7A7A7A"
    elif "glass" in combined:
        target_hex = "#A0C0D0"
    
    if not target_hex:
        return False
        
    changed = False
    
    # 1. Update colour_palette
    if "colour_palette" in data and isinstance(data["colour_palette"], dict):
        palette = data["colour_palette"]
        if palette.get("facade_hex") == "#B85A3A": # Only fix if it's the wrong default
            palette["facade_hex"] = target_hex
            changed = True
            
    # 2. Update facade_detail
    if "facade_detail" in data and isinstance(data["facade_detail"], dict):
        detail = data["facade_detail"]
        if detail.get("brick_colour_hex") == "#B85A3A":
            detail["brick_colour_hex"] = target_hex
            changed = True

    if changed:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        return True
    
    return False

def main():
    files = sorted(PARAMS_DIR.glob("*.json"))
    files = [f for f in files if not f.name.startswith("_")]
    
    fixed = 0
    for f in files:
        if fix_file(f):
            fixed += 1
            print(f"Fixed: {f.name}")
            
    print(f"\nTotal files fixed: {fixed}")

if __name__ == "__main__":
    main()
