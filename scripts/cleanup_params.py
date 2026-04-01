import os
import shutil
from pathlib import Path

ROOT = Path("C:/Users/liam1/blender_buildings")
PARAMS_DIR = ROOT / "params"
ARCHIVE_DIR = ROOT / "params" / "archive"

def cleanup():
    if not ARCHIVE_DIR.exists():
        ARCHIVE_DIR.mkdir(parents=True)
        
    files = list(PARAMS_DIR.glob("*.json"))
    moved = 0
    
    for pf in files:
        # Identify backups and variants
        is_backup = ".backup_" in pf.name or "_backup" in pf.name
        is_variant = "_v1.json" in pf.name or "_v2.json" in pf.name or "_custom" in pf.name
        is_temp = pf.name.startswith("_") or pf.name == ".json"
        
        if is_backup or is_variant or is_temp:
            shutil.move(pf, ARCHIVE_DIR / pf.name)
            moved += 1
            
    print(f"Moved {moved} files to {ARCHIVE_DIR}")
    
    # Recount remaining
    remaining = len(list(PARAMS_DIR.glob("*.json")))
    print(f"Remaining active param files: {remaining}")

if __name__ == "__main__":
    cleanup()
