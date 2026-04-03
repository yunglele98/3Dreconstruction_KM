import bpy
import os
import sys
import random

# --- CONFIG ---
ORIGINAL_BLEND = str(Path(__file__).resolve().parent.parent / "outputs" / "full_backup" / "No_8_Hose_Station_Bellevue_Ave.blend")
PHOTO_DIR = str(Path(__file__).resolve().parent.parent / "PHOTOS KENSINGTON sorted" / "Toronto Fire Station 315")
OUTPUT_BLEND = str(Path(__file__).resolve().parent.parent / "outputs" / "demos" / "fire_station_315_picture_perfect_FINAL.blend")

def create_perfect_photo_material(photo_dir):
    """Creates a high-quality material using box-projected site photos."""
    photos = [os.path.join(photo_dir, f) for f in os.listdir(photo_dir) if f.lower().endswith(('.jpg', '.jpeg'))]
    if not photos:
        print("Error: No photos found in directory.")
        return None

    # We will use a random primary photo for the box projection
    random.shuffle(photos)
    
    mat = bpy.data.materials.new(name="PicturePerfect_Facade")
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    
    # Clear default nodes
    nodes.clear()
    
    # Create nodes
    node_out = nodes.new(type='ShaderNodeOutputMaterial')
    node_bsdf = nodes.new(type='ShaderNodeBsdfPrincipled')
    node_tex = nodes.new(type='ShaderNodeTexImage')
    node_coord = nodes.new(type='ShaderNodeTexCoord')
    node_mapping = nodes.new(type='ShaderNodeMapping')
    
    # Load Image
    img = bpy.data.images.load(photos[0])
    node_tex.image = img
    node_tex.projection = 'BOX'
    node_tex.projection_blend = 0.5
    
    # Set Mapping (Scale 0.08 as requested)
    node_mapping.inputs['Scale'].default_value = (0.08, 0.08, 0.08)
    
    # Connect
    links.new(node_coord.outputs['Object'], node_mapping.inputs['Vector'])
    links.new(node_mapping.outputs['Vector'], node_tex.inputs['Vector'])
    links.new(node_tex.outputs['Color'], node_bsdf.inputs['Base Color'])
    links.new(node_bsdf.outputs['BSDF'], node_out.inputs['Surface'])
    
    node_bsdf.inputs['Roughness'].default_value = 0.9
    
    return mat

def run_reconstruction():
    print(f"--- Restarting Task: Reconstructing Fire Station 315 ---")
    
    if not os.path.exists(ORIGINAL_BLEND):
        print(f"Error: Base file not found at {ORIGINAL_BLEND}")
        return

    # 1. Open Original File
    bpy.ops.wm.open_mainfile(filepath=ORIGINAL_BLEND)
    print(f"Opened base geometry: {ORIGINAL_BLEND}")

    # 2. Create Photo Material
    photo_mat = create_perfect_photo_material(PHOTO_DIR)
    if not photo_mat:
        return

    # 3. Identify Procedural Materials to replace
    mats_to_replace = [
        'mat_brick_B85A3A',
        'mat_stone_D4C9A8',
        'mat_lintel_D4C9A8',
        'mat_quoins_No_8_Hose_Station_Bellevue_Ave'
    ]

    # 4. Iterate through ALL objects in ALL collections
    # This ensures tower and hangar (which might be in separate collections) are processed
    print(f"Processing all mesh objects...")
    processed_objs = 0
    replacement_count = 0
    
    for obj in bpy.data.objects:
        if obj.type == 'MESH':
            processed_objs += 1
            for slot in obj.material_slots:
                if slot.material and slot.material.name in mats_to_replace:
                    old_name = slot.material.name
                    slot.material = photo_mat
                    replacement_count += 1
                    # print(f"  Replaced {old_name} on {obj.name}")

    print(f"Processed {processed_objs} objects.")
    print(f"Applied photo textures to {replacement_count} material slots.")

    # 5. Final Save
    os.makedirs(os.path.dirname(OUTPUT_BLEND), exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=OUTPUT_BLEND)
    print(f"Final model saved to: {OUTPUT_BLEND}")

if __name__ == "__main__":
    run_reconstruction()