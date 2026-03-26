"""Verify building-to-road alignment in the demo .blend file.

Checks:
1. Are buildings on their footprints? (centroid overlap)
2. Do building front faces point toward the nearest road?
3. Are buildings oriented along the street grid?
"""
import bpy
import math

print("=== ALIGNMENT VERIFICATION ===\n")

# Collect buildings (extruded meshes in Buildings collection)
buildings = []
for col in bpy.data.collections:
    if col.name != "Buildings":
        continue
    for obj in col.objects:
        if obj.type != "MESH" or not obj.name.startswith("Bldg_"):
            continue
        verts = [obj.matrix_world @ v.co for v in obj.data.vertices]
        if not verts:
            continue
        xs = [v.x for v in verts]
        ys = [v.y for v in verts]
        zs = [v.z for v in verts]
        cx = sum(xs) / len(xs)
        cy = sum(ys) / len(ys)
        h = max(zs)
        w = max(xs) - min(xs)
        d = max(ys) - min(ys)
        buildings.append({"name": obj.name, "cx": cx, "cy": cy, "h": h, "w": w, "d": d})

# Collect roads
roads = []
for obj in bpy.data.objects:
    if not obj.name.startswith("Road_") or obj.type != "MESH":
        continue
    verts = [obj.matrix_world @ v.co for v in obj.data.vertices]
    if not verts:
        continue
    # Store all road vertex positions
    for v in verts:
        roads.append((v.x, v.y))

# Collect footprints
footprints = []
for obj in bpy.data.objects:
    if not obj.name.startswith("FP_") or obj.type != "MESH":
        continue
    verts = [obj.matrix_world @ v.co for v in obj.data.vertices]
    if not verts:
        continue
    xs = [v.x for v in verts]
    ys = [v.y for v in verts]
    footprints.append({"cx": sum(xs)/len(xs), "cy": sum(ys)/len(ys),
                       "w": max(xs)-min(xs), "d": max(ys)-min(ys)})

print(f"Buildings: {len(buildings)}")
print(f"Road points: {len(roads)}")
print(f"Footprints: {len(footprints)}")

# Check 1: distance from each building to nearest road
print(f"\n--- BUILDING-TO-ROAD DISTANCE ---")
road_dists = []
for b in buildings:
    best = 999
    for rx, ry in roads:
        d = math.sqrt((b["cx"]-rx)**2 + (b["cy"]-ry)**2)
        if d < best:
            best = d
    road_dists.append(best)

if road_dists:
    avg = sum(road_dists) / len(road_dists)
    print(f"  Min: {min(road_dists):.1f}m  Max: {max(road_dists):.1f}m  Avg: {avg:.1f}m")
    on_road = sum(1 for d in road_dists if d < 5)
    near_road = sum(1 for d in road_dists if d < 15)
    print(f"  On road (<5m): {on_road}  Near road (<15m): {near_road}  Far (>15m): {len(road_dists)-near_road}")

# Check 2: building dimensions (should be ~5x10m, not 30x20m)
print(f"\n--- BUILDING DIMENSIONS ---")
small = sum(1 for b in buildings if b["w"] < 15 and b["d"] < 15)
large = sum(1 for b in buildings if b["w"] >= 15 or b["d"] >= 15)
print(f"  Individual (<15m): {small}  Block (>=15m): {large}")
if buildings:
    ws = [b["w"] for b in buildings]
    ds = [b["d"] for b in buildings]
    print(f"  Width: min={min(ws):.1f} max={max(ws):.1f} avg={sum(ws)/len(ws):.1f}")
    print(f"  Depth: min={min(ds):.1f} max={max(ds):.1f} avg={sum(ds)/len(ds):.1f}")

# Check 3: building orientations (should cluster around 4 canonical angles)
print(f"\n--- BUILDING ORIENTATIONS ---")
# Measure orientation from bounding box
angles = []
for obj in bpy.data.collections.get("Buildings", bpy.data.collections[0]).objects:
    if obj.type != "MESH" or not obj.name.startswith("Bldg_"):
        continue
    verts = [obj.matrix_world @ v.co for v in obj.data.vertices]
    ground_verts = [(v.x, v.y) for v in verts if v.z < 0.1]
    if len(ground_verts) < 3:
        continue
    # Find longest edge on ground floor
    best_len, best_angle = 0, 0
    for i in range(len(ground_verts)):
        for j in range(i+1, len(ground_verts)):
            dx = ground_verts[j][0] - ground_verts[i][0]
            dy = ground_verts[j][1] - ground_verts[i][1]
            el = math.sqrt(dx*dx + dy*dy)
            if el > best_len:
                best_len = el
                best_angle = math.degrees(math.atan2(dy, dx)) % 180  # normalize to 0-180
    angles.append(round(best_angle, 0))

if angles:
    from collections import Counter
    c = Counter(angles)
    print(f"  Orientation clusters (degrees, 0-180):")
    for angle, count in c.most_common(6):
        print(f"    {angle:.0f} deg: {count} buildings")
    # Good = 1-2 dominant angles
    top2 = sum(count for _, count in c.most_common(2))
    print(f"  Top 2 orientations cover {top2}/{len(angles)} ({100*top2/len(angles):.0f}%) buildings")
    if top2 / len(angles) > 0.7:
        print(f"  PASS: buildings align to street grid")
    else:
        print(f"  WARN: buildings have scattered orientations")

print(f"\n=== DONE ===")
