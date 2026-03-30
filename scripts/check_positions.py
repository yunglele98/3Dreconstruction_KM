"""Inspect and report garage object positions and dimensions in Blender.

Usage:
    blender --background <file.blend> --python scripts/check_positions.py

Reads: Blender scene objects (MESH type, garage/shed prefix)
Writes: Console output (garage positions, dimensions, rotation)
"""
import math
import re

import bpy


GARAGE_KEY_RE = re.compile(r"(?:garage|Garage)(?:Roof|Door|_roof|_door)?[_-](\d{3})")


def is_garage_body(name: str) -> bool:
    n = name.lower()
    if "garage" not in n and not n.startswith("shed_"):
        return False
    if "roof" in n or "door" in n:
        return False
    return True


def bbox_world(obj):
    pts = [obj.matrix_world @ v.co for v in obj.data.vertices]
    xs = [p.x for p in pts]
    ys = [p.y for p in pts]
    zs = [p.z for p in pts]
    return {
        "xmin": min(xs),
        "xmax": max(xs),
        "ymin": min(ys),
        "ymax": max(ys),
        "zmin": min(zs),
        "zmax": max(zs),
        "cx": sum(xs) / len(xs),
        "cy": sum(ys) / len(ys),
    }


print("=== GARAGE POSITIONS ===")
garages = [o for o in bpy.data.objects if o.type == "MESH" and is_garage_body(o.name)]
rows = []
for obj in garages:
    bb = bbox_world(obj)
    rot = math.degrees(obj.rotation_euler.z)
    key = GARAGE_KEY_RE.search(obj.name)
    gid = key.group(1) if key else "???"
    rows.append((gid, obj.name, bb, rot))

for gid, name, bb, rot in sorted(rows, key=lambda r: r[0]):
    print(
        f"GAR {gid} {name:34s} "
        f"cx={bb['cx']:8.2f} cy={bb['cy']:8.2f} "
        f"w={bb['xmax']-bb['xmin']:5.2f} d={bb['ymax']-bb['ymin']:5.2f} "
        f"zmin={bb['zmin']:5.2f} rot={rot:7.2f}"
    )

print("\n=== GARAGE OVERLAPS (AABB) ===")
issues = 0
for i in range(len(rows)):
    _, name_a, a, _ = rows[i]
    for j in range(i + 1, len(rows)):
        _, name_b, b, _ = rows[j]
        ox = min(a["xmax"], b["xmax"]) - max(a["xmin"], b["xmin"])
        oy = min(a["ymax"], b["ymax"]) - max(a["ymin"], b["ymin"])
        oz = min(a["zmax"], b["zmax"]) - max(a["zmin"], b["zmin"])
        if ox > 0.05 and oy > 0.05 and oz > 0.20:
            issues += 1
            print(f"OVERLAP {name_a} <-> {name_b} (dx={ox:.2f}, dy={oy:.2f}, dz={oz:.2f})")

if issues == 0:
    print("No garage overlaps detected.")
else:
    print(f"Detected overlaps: {issues}")
