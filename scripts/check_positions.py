import bpy, math

print("=== BUILDING POSITIONS IN BLENDER ===")
for col in bpy.data.collections:
    # Building collections are named like "20_Bellevue_Ave" etc
    if "Bellevue" not in col.name:
        continue
    # Find the walls object
    for obj in col.objects:
        if "walls" in obj.name.lower() or "wall" in obj.name.lower():
            x, y, z = obj.location.x, obj.location.y, obj.location.z
            rot = math.degrees(obj.rotation_euler.z)
            print(f"BLDG {col.name:40s} x={x:8.1f} y={y:8.1f} rot={rot:7.1f}")
            break

print("\n=== FOOTPRINT POSITIONS ===")
for obj in bpy.data.objects:
    if not obj.name.startswith("FP_"):
        continue
    if obj.type != "MESH":
        continue
    verts = [obj.matrix_world @ v.co for v in obj.data.vertices]
    if not verts:
        continue
    cx = sum(v.x for v in verts) / len(verts)
    cy = sum(v.y for v in verts) / len(verts)
    if -130 < cx < 0 and -200 < cy < 20:
        print(f"FP   {obj.name:40s} cx={cx:8.1f} cy={cy:8.1f}")

print("\n=== ROAD POSITIONS ===")
for obj in bpy.data.objects:
    if not obj.name.startswith("Road_"):
        continue
    if obj.type != "MESH":
        continue
    verts = [obj.matrix_world @ v.co for v in obj.data.vertices]
    if not verts:
        continue
    cx = sum(v.x for v in verts) / len(verts)
    cy = sum(v.y for v in verts) / len(verts)
    if -150 < cx < 50 and -250 < cy < 50:
        print(f"ROAD {obj.name:40s} cx={cx:8.1f} cy={cy:8.1f}")
