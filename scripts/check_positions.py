import bpy
from mathutils import Vector

print("\n=== ALL OBJECTS POSITIONS ===")
for obj in bpy.data.objects:
    if obj.type == 'MESH':
        # World-space bounding box
        corners = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
        min_x = min(c.x for c in corners)
        max_x = max(c.x for c in corners)
        min_y = min(c.y for c in corners)
        max_y = max(c.y for c in corners)
        print(f"  {obj.name:40s} loc=({obj.location.x:8.1f},{obj.location.y:8.1f},{obj.location.z:8.1f})  bbox_x=[{min_x:8.1f},{max_x:8.1f}]  bbox_y=[{min_y:8.1f},{max_y:8.1f}]")

print("\n=== COLLECTIONS ===")
for col in bpy.data.collections:
    obj_count = len([o for o in col.objects if o.type == 'MESH'])
    print(f"  {col.name}: {obj_count} mesh objects")
