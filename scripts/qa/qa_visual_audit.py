import json
import os
import subprocess
from pathlib import Path

ROOT = Path("C:/Users/liam1/blender_buildings")
PARAMS_DIR = ROOT / "params"
PHOTO_DIR = ROOT / "PHOTOS KENSINGTON"
OUTPUT_DIR = ROOT / "outputs" / "qa_visual_audit"
BLENDER_EXE = "C:/Program Files/Blender Foundation/Blender 5.1/blender.exe"

def run_visual_audit(address):
    print(f"--- Visual Audit: {address} ---")
    
    param_file = PARAMS_DIR / (address.replace(" ", "_") + ".json")
    if not param_file.exists():
        print(f"Error: Param file not found for {address}")
        return
        
    render_path = OUTPUT_DIR / f"{address}_render.png"
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    
    cmd = [
        BLENDER_EXE,
        "--background",
        "--python", str(ROOT / "generate_building.py"),
        "--",
        "--params", str(param_file),
        "--render",
        "--output-dir", str(OUTPUT_DIR)
    ]
    
    print(f"  Generating render...")
    subprocess.run(cmd, capture_output=True)
    
    photo_name = None
    with open(param_file, "r", encoding="utf-8") as f:
        data = json.load(f)
        obs = data.get("photo_observations", {})
        photo_name = obs.get("source_photo") or obs.get("photo") or data.get("source_photo")
        
    if photo_name:
        print(f"  Field Photo: {photo_name}")
        # Check if photo exists
        photo_path = PHOTO_DIR / photo_name
        if not photo_path.exists():
            print(f"  Warning: Photo {photo_name} not found in PHOTOS KENSINGTON.")
    else:
        print("  Warning: No source photo linked in params.")

    print(f"  Done. Results: {OUTPUT_DIR}")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--address", required=True)
    args = parser.parse_args()
    run_visual_audit(args.address)
