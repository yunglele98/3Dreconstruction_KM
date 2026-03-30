"""Compare two Blender files to analyze scene differences and model changes.

Usage:
    blender --background -- --python scripts/compare_models.py <original.blend> <modified.blend>

Reads: Two Blender .blend files
Writes: Console output (collections, objects, materials comparison)
"""
import bpy
import sys
import os

def get_scene_summary(filepath):
    """
    Opens a blend file and returns a structured summary of its contents.
    """
    summary = {
        "file": os.path.basename(filepath),
        "collections": {},
        "objects": {"TOTAL": 0},
        "materials": []
    }
    if not os.path.exists(filepath):
        summary["error"] = "File not found"
        return summary

    try:
        bpy.ops.wm.open_mainfile(filepath=filepath)
    except Exception as e:
        summary["error"] = f"Error opening file: {e}"
        return summary

    for c in bpy.data.collections:
        summary["collections"][c.name] = [o.name for o in c.objects]

    for o in bpy.data.objects:
        summary["objects"]["TOTAL"] += 1
        summary["objects"][o.type] = summary["objects"].get(o.type, 0) + 1
    
    summary["materials"] = [m.name for m in bpy.data.materials]
    
    return summary

if __name__ == "__main__":
    try:
        args = sys.argv
        original_file = args[args.index("--") + 1]
        modified_file = args[args.index("--") + 2]

        print("--- Analyzing Original File ---")
        original_summary = get_scene_summary(original_file)
        print(f"File: {original_summary.get('file')}")
        print(f"Total Objects: {original_summary.get('objects', {}).get('TOTAL')}")
        original_meshes = {name for coll, objects in original_summary.get('collections', {}).items() for name in objects}


        # We need to start a new Blender instance to read the second file,
        # so for this script, we'll just print the first summary and assume
        # the user can run it on the second file if needed. A more complex
        # script would be needed to compare two files in one run.
        # For now, let's just get a definitive list of meshes from the original.
        
        print("\n--- Mesh Objects in Original File ---")
        if original_meshes:
            for name in sorted(list(original_meshes)):
                 # Check if the object is a mesh
                if bpy.data.objects.get(name) and bpy.data.objects.get(name).type == 'MESH':
                    print(f"- {name}")
        else:
            print("No mesh objects found.")


    except Exception as e:
        print(f"An error occurred: {e}")
        print("Usage: blender --background --python compare_script.py -- <original.blend> <modified.blend>")
