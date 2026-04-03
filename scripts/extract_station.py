import bpy
import os
import sys

# --- CONFIG ---
SOURCE_BLEND = str(Path(__file__).resolve().parent.parent / "archive" / "kensington_pilot.blend")
EXTRACT_FILE = str(Path(__file__).resolve().parent.parent / "outputs" / "demos" / "fire_station_315_geometry_extracted.blend")

def extract_station_geometry():
    if not os.path.exists(SOURCE_BLEND):
        print(f"Error: Source not found at {SOURCE_BLEND}")
        return

    # 1. Open Source
    bpy.ops.wm.open_mainfile(filepath=SOURCE_BLEND)
    print(f"Opened archived pilot: {SOURCE_BLEND}")

    # 2. Identify objects belonging to 132 Bellevue
    # Based on our inventory, they all contain '132_Bellevue' or specific keywords
    station_objs = []
    for obj in bpy.data.objects:
        if '132_Bellevue' in obj.name or obj.name.startswith(('hall_', 'tower_', 'modern_', 'engine_', 'clock_', 'oculus_')):
             station_objs.append(obj)
    
    print(f"Found {len(station_objs)} objects for the Fire Station.")

    # 3. Select only these objects
    bpy.ops.object.select_all(action='DESELECT')
    for obj in station_objs:
        obj.select_set(True)

    # 4. Invert selection and delete everything else
    bpy.ops.object.select_all(action='INVERT')
    bpy.ops.object.delete()

    # 5. Save as a new individual file
    os.makedirs(os.path.dirname(EXTRACT_FILE), exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=EXTRACT_FILE)
    print(f"Extracted geometry saved to: {EXTRACT_FILE}")

if __name__ == "__main__":
    extract_station_geometry()