import bpy
import sys
import os

def inspect_blend_file(filepath):
    """
    Opens a blend file in the background and prints a summary of its contents.
    """
    if not os.path.exists(filepath):
        print(f"Error: File not found at {filepath}")
        return

    try:
        bpy.ops.wm.open_mainfile(filepath=filepath)
    except Exception as e:
        print(f"Error opening file: {e}")
        return

    print(f"\n--- Inspection Report for: {os.path.basename(filepath)} ---")

    # List Collections
    collections = bpy.data.collections
    if collections:
        print(f"\nCollections ({len(collections)}):")
        for c in collections:
            print(f"- {c.name} (Objects: {len(c.objects)})")

    # List Objects
    objects = bpy.data.objects
    if objects:
        print(f"\nObjects ({len(objects)}):")
        obj_types = {}
        for o in objects:
            obj_types[o.type] = obj_types.get(o.type, 0) + 1
        for obj_type, count in obj_types.items():
            print(f"- {obj_type}: {count}")

    # List Materials
    materials = bpy.data.materials
    if materials:
        print(f"\nMaterials ({len(materials)}):")
        for m in materials:
            print(f"- {m.name}")

    print("\n--- End of Report ---")

if __name__ == "__main__":
    # Get the file path from command line arguments
    # blender --background --python inspect_script.py -- C:\path\to\your.blend
    try:
        args = sys.argv
        blend_file_path = args[args.index("--") + 1]
        inspect_blend_file(blend_file_path)
    except (ValueError, IndexError):
        print("Error: Please provide a .blend file path after '--'")
        print("Usage: blender --background --python inspect.py -- <path_to_blend_file>")
