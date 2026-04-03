"""Fast collision mesh generation — runs INSIDE Blender.

For each building: load .blend, decimate to 10%, convex hull, export as collision FBX.

Usage:
  blender --background --python scripts/fast_collision_generate.py -- --chunk outputs/lod_chunk_1.txt
"""
import sys, time
from pathlib import Path

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
chunk_file = None
for i, arg in enumerate(argv):
    if arg == "--chunk" and i + 1 < len(argv):
        chunk_file = argv[i + 1]

if not chunk_file:
    print("Usage: blender --background --python scripts/fast_collision_generate.py -- --chunk <file>")
    sys.exit(1)

import bpy

addresses = Path(chunk_file).read_text(encoding="utf-8").strip().split("\n")
exports_dir = Path("outputs/exports")
full_dir = Path("outputs/full")

done = 0
failed = 0
t0 = time.time()

for addr in addresses:
    addr = addr.strip()
    blend_path = full_dir / f"{addr}.blend"
    if not blend_path.exists():
        continue
    out_dir = exports_dir / addr
    if not out_dir.is_dir():
        continue
    collision_path = out_dir / f"{addr}_collision.fbx"
    if collision_path.exists():
        continue

    try:
        bpy.ops.wm.open_mainfile(filepath=str(blend_path))

        # Select all meshes
        bpy.ops.object.select_all(action='DESELECT')
        meshes = [o for o in bpy.data.objects if o.type == 'MESH']
        if not meshes:
            continue

        for obj in meshes:
            obj.select_set(True)
        bpy.context.view_layer.objects.active = meshes[0]

        # Join all meshes
        if len(meshes) > 1:
            bpy.ops.object.join()

        obj = bpy.context.active_object

        # Decimate to 10%
        mod = obj.modifiers.new(name="Decimate", type='DECIMATE')
        mod.ratio = 0.1
        bpy.ops.object.modifier_apply(modifier="Decimate")

        # Convex hull via bmesh
        import bmesh
        bm = bmesh.new()
        bm.from_mesh(obj.data)
        result = bmesh.ops.convex_hull(bm, input=bm.verts)
        # Remove interior geometry
        interior = set()
        for elem in result.get("geom_interior", []):
            if isinstance(elem, bmesh.types.BMVert):
                interior.add(elem)
        bmesh.ops.delete(bm, geom=[v for v in bm.verts if v in interior], context='VERTS')
        bm.to_mesh(obj.data)
        bm.free()

        # Export
        bpy.ops.object.select_all(action='DESELECT')
        obj.select_set(True)
        bpy.ops.export_scene.fbx(filepath=str(collision_path), use_selection=True,
                                  apply_scale_options='FBX_SCALE_ALL')
        done += 1
        if done % 20 == 0:
            elapsed = time.time() - t0
            rate = done / elapsed * 60
            print(f"  {done}/{len(addresses)} collisions ({rate:.0f}/min)", flush=True)
    except Exception as e:
        failed += 1
        if failed <= 5:
            print(f"  FAIL {addr}: {e}", flush=True)

elapsed = time.time() - t0
print(f"DONE: {done} collision meshes, {failed} failed in {elapsed:.0f}s", flush=True)
