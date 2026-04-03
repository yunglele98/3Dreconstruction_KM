import bpy
import os
import glob

def search_objects_in_blends(directory):
    blend_files = glob.glob(os.path.join(directory, "*.blend"))
    print(f"Searching {len(blend_files)} files in {directory}...")
    
    for blend_file in blend_files:
        try:
            # We don't need to fully open the file, we can use bpy.utils.blend_paths?
            # No, easiest is to open in background
            bpy.ops.wm.open_mainfile(filepath=blend_file)
            for obj in bpy.data.objects:
                if "tower" in obj.name.lower() or "hangar" in obj.name.lower() or "vol" in obj.name.lower():
                    print(f"MATCH: '{obj.name}' in file '{os.path.basename(blend_file)}'")
        except:
            pass

if __name__ == "__main__":
    search_objects_in_blends(str(Path(__file__).resolve().parent.parent / "outputs" / "demos"))
    search_objects_in_blends(str(Path(__file__).resolve().parent.parent / "outputs" / "full"))
    search_objects_in_blends(str(Path(__file__).resolve().parent.parent / "outputs" / "full_backup"))