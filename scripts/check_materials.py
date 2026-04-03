import bpy

print("\n=== MATERIAL CHECK ===")
print(f"Total materials in file: {len(bpy.data.materials)}")
for mat in bpy.data.materials:
    print(f"  Material: {mat.name}, use_nodes={mat.use_nodes}, users={mat.users}")
    if mat.use_nodes and mat.node_tree:
        for node in mat.node_tree.nodes:
            print(f"    Node: {node.type} ({node.name})")

print(f"\n=== OBJECT MATERIALS ===")
for obj in bpy.data.objects:
    if obj.type == 'MESH':
        mats = [slot.material.name if slot.material else "NONE" for slot in obj.material_slots]
        if mats:
            print(f"  {obj.name}: {mats}")
        else:
            print(f"  {obj.name}: NO MATERIAL SLOTS")
