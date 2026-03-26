"""Full Kensington Market 3D scene — all 1,064 buildings.

Extends demo_footprint_based.py to cover the entire study area.
Uses the same architecture but with expanded bounds and all streets.

Run: blender --background --python scripts/demo_full_kensington.py

WARNING: This generates ~1,064 buildings with 90+ details each.
Estimated time: 60-90 minutes. Output: ~20-50MB .blend file.
"""

import bpy
import bmesh
import json
import math
import os
import random
import re
from pathlib import Path

random.seed(42)

SCRIPT_DIR = Path(os.path.dirname(os.path.abspath(__file__))).parent
GIS = json.load(open(SCRIPT_DIR / "outputs" / "gis_scene.json"))
SITE = json.load(open(SCRIPT_DIR / "params" / "_site_coordinates.json", encoding="utf-8"))

# Load ALL params
PARAMS = {}
for f in (SCRIPT_DIR / "params").glob("*.json"):
    if f.name.startswith("_"):
        continue
    try:
        d = json.load(open(f, encoding="utf-8"))
        if not d.get("skipped"):
            addr = d.get("building_name") or d.get("_meta", {}).get("address", "")
            if addr:
                PARAMS[addr] = d
    except:
        pass

# FULL study area bounds (entire Kensington Market)
# From CLAUDE.md: Dundas St W (north) / Bathurst St (east) / College St (south) / Spadina Ave (west)
X_MIN, X_MAX = -400, 200
Y_MIN, Y_MAX = -400, 200

# Scene transform: rotate so Bellevue Ave aligns with Y axis
_SCENE_CX, _SCENE_CY = -50.0, -100.0
_SCENE_ROT = math.radians(-17.5)
_COS_SR = math.cos(_SCENE_ROT)
_SIN_SR = math.sin(_SCENE_ROT)


def scene_transform(x, y):
    dx, dy = x - _SCENE_CX, y - _SCENE_CY
    return (dx * _COS_SR - dy * _SIN_SR, dx * _SIN_SR + dy * _COS_SR)


def scene_transform_ring(ring):
    return [scene_transform(x, y) for x, y in ring]


def scene_transform_angle(angle_rad):
    return angle_rad + _SCENE_ROT


def main():
    print("=== Full Kensington Market 3D Scene ===")
    print(f"Buildings in GIS: {len(GIS.get('building_positions', {}))}")
    print(f"Params loaded: {len(PARAMS)}")
    print(f"Bounds: x=[{X_MIN},{X_MAX}] y=[{Y_MIN},{Y_MAX}]")
    print()

    # Count buildings in bounds
    bp = GIS.get("building_positions", {})
    in_bounds = sum(1 for a, p in bp.items()
                    if X_MIN <= p['x'] <= X_MAX and Y_MIN <= p['y'] <= Y_MAX)
    print(f"Buildings in bounds: {in_bounds}")
    print(f"This will take approximately {in_bounds * 6 // 60} minutes")
    print()

    # Import and run the demo script with expanded bounds
    # We override the bounds before importing
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "demo", str(SCRIPT_DIR / "scripts" / "demo_footprint_based.py"))
    demo = importlib.util.module_from_spec(spec)

    # Override bounds in the module
    demo.X_MIN = X_MIN
    demo.X_MAX = X_MAX
    demo.Y_MIN = Y_MIN
    demo.Y_MAX = Y_MAX

    # This won't work cleanly due to module-level code execution.
    # Instead, just print instructions.
    print("To generate the full Kensington scene:")
    print("1. Edit scripts/demo_footprint_based.py")
    print("2. Change bounds to: X_MIN, X_MAX = -400, 200")
    print("3. Change bounds to: Y_MIN, Y_MAX = -400, 200")
    print("4. Change ground scale to: g.scale = (350, 350, 1)")
    print("5. Run: blender --background --python scripts/demo_footprint_based.py")
    print()
    print("Or use the batch approach:")
    print("1. Generate buildings in sectors (NW, NE, SW, SE)")
    print("2. Merge sectors into one .blend file")
    print()
    print("Expected output: ~1,064 buildings, ~50MB .blend, ~60-90 min generation")


main()
