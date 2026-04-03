import bpy
import os
import sys
import random

# --- CONFIG ---
SOURCE_FILE = str(Path(__file__).resolve().parent.parent / "outputs" / "demos" / "fire_station_315_geometry_extracted.blend")
PHOTO_DIR = str(Path(__file__).resolve().parent.parent / "PHOTOS KENSINGTON sorted" / "Toronto Fire Station 315")
FINAL_FILE = str(Path(__file__).resolve().parent.parent / "outputs" / "demos" / "fire_station_315_picture_perfect_FINAL.blend")

def create_advanced_photo_material(name, photo_path, scale=0.08):
    mat = bpy.data.materials.new(name=name)
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()
    
    node_out = nodes.new(type='ShaderNodeOutputMaterial')
    node_bsdf = nodes.new(type='ShaderNodeBsdfPrincipled')
    node_tex = nodes.new(type='ShaderNodeTexImage')
    node_coord = nodes.new(type='ShaderNodeTexCoord')
    node_mapping = nodes.new(type='ShaderNodeMapping')
    
    img = bpy.data.images.load(photo_path)
    node_tex.image = img
    node_tex.projection = 'BOX'
    node_tex.projection_blend = 0.5
    
    node_mapping.inputs['Scale'].default_value = (scale, scale, scale)
    
    links.new(node_coord.outputs['Object'], node_mapping.inputs['Vector'])
    links.new(node_mapping.outputs['Vector'], node_tex.inputs['Vector'])
    links.new(node_tex.outputs['Color'], node_bsdf.inputs['Base Color'])
    links.new(node_bsdf.outputs['BSDF'], node_out.inputs['Surface'])
    
    node_bsdf.inputs['Roughness'].default_value = 0.8
    return mat

def apply_final_texturing():
    if not os.path.exists(SOURCE_FILE):
        print(f"Error: Source file not found: {SOURCE_FILE}")
        return

    bpy.ops.wm.open_mainfile(filepath=SOURCE_FILE)
    print(f"Opened geometry: {SOURCE_FILE}")

    photos = [os.path.join(PHOTO_DIR, f) for f in os.listdir(PHOTO_DIR) if f.lower().endswith(('.jpg', '.jpeg'))]
    if not photos:
        print("Error: No photos found.")
        return

    # Create several materials from different photos for variety
    photo_mats = []
    for i in range(min(5, len(photos))):
        photo_mats.append(create_advanced_photo_material(f"PhotoMat_{i}", photos[i]))

    # Material classification
    brick_keywords = ['brick', 'facade', 'tower', 'hall', 'parapet', 'modern', 'bulkhead', 'dormer_wall', 'voussoir', 'stone', 'lintel', 'coping', 'surround']
    roof_keywords = ['roof', 'droof']

    print("Texturing all 145 objects...")
    
    replacement_count = 0
    for obj in bpy.data.objects:
        if obj.type != 'MESH': continue
        
        for slot in obj.material_slots:
            if not slot.material: continue
            
            mat_name = slot.material.name.lower()
            
            # Replace building exterior parts with photos
            if any(k in mat_name for k in brick_keywords):
                # Pick a photo mat based on object name hash for consistency
                idx = hash(obj.name) % len(photo_mats)
                slot.material = photo_mats[idx]
                replacement_count += 1
            
            # Ensure roof is dark
            elif any(k in mat_name for k in roof_keywords):
                slot.material.use_nodes = True
                bsdf = slot.material.node_tree.nodes.get("Principled BSDF")
                if bsdf:
                    bsdf.inputs["Base Color"].default_value = (0.05, 0.05, 0.06, 1.0)

    print(f"Applied photo textures to {replacement_count} slots across all building parts.")

    # Save
    os.makedirs(os.path.dirname(FINAL_FILE), exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=FINAL_FILE)
    print(f"PICTURE PERFECT RECONSTRUCTION SAVED TO: {FINAL_FILE}")

if __name__ == "__main__":
    apply_final_texturing()