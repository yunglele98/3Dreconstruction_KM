"""Fast LOD generation — runs INSIDE Blender, iterates exports without restart.

Generates LOD1 (50% faces), LOD2 (15% faces), LOD3 (bounding box).

Usage:
  blender --background --python scripts/fast_lod_generate.py -- --chunk outputs/lod_chunk_1.txt
"""
import sys, time
from pathlib import Path

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
chunk_file = None
for i, arg in enumerate(argv):
    if arg == "--chunk" and i + 1 < len(argv):
        chunk_file = argv[i + 1]

if not chunk_file:
    print("Usage: blender --background --python scripts/fast_lod_generate.py -- --chunk <file>")
    sys.exit(1)

import bpy, bmesh

addresses = Path(chunk_file).read_text(encoding="utf-8").strip().split("\n")
exports_dir = Path("outputs/exports")
full_dir = Path("outputs/full")

done = 0
failed = 0
t0 = time.time()

LOD_RATIOS = {"LOD1": 0.5, "LOD2": 0.15}

for addr in addresses:
    addr = addr.strip()
    # Use .blend (not FBX) to avoid Cycles light reimport bug in 5.1
    blend_path = full_dir / f"{addr}.blend"
    if not blend_path.exists():
        continue
    out_dir = exports_dir / addr
    if not out_dir.is_dir():
        continue
    lod1_path = out_dir / f"{addr}_LOD1.fbx"
    if lod1_path.exists():
        continue  # skip existing

    try:
        bpy.ops.wm.open_mainfile(filepath=str(blend_path))

        for lod_name, ratio in LOD_RATIOS.items():
            # Duplicate all mesh objects
            bpy.ops.object.select_all(action='SELECT')
            bpy.ops.object.duplicate()

            for obj in bpy.context.selected_objects:
                if obj.type == 'MESH':
                    mod = obj.modifiers.new(name="Decimate", type='DECIMATE')
                    mod.ratio = ratio
                    bpy.context.view_layer.objects.active = obj
                    bpy.ops.object.modifier_apply(modifier="Decimate")

            out = out_dir / f"{addr}_{lod_name}.fbx"
            bpy.ops.export_scene.fbx(filepath=str(out), use_selection=True,
                                      apply_scale_options='FBX_SCALE_ALL')

            # Delete duplicates for next LOD
            bpy.ops.object.delete()

        # LOD3: bounding box
        bpy.ops.wm.open_mainfile(filepath=str(blend_path))
        # Get combined bounding box
        min_co = [float('inf')]*3
        max_co = [float('-inf')]*3
        for obj in bpy.data.objects:
            if obj.type == 'MESH':
                for v in obj.bound_box:
                    world_v = obj.matrix_world @ bpy.app.driver_namespace.get('Vector', __import__('mathutils').Vector)(v)
                    for i in range(3):
                        min_co[i] = min(min_co[i], world_v[i])
                        max_co[i] = max(max_co[i], world_v[i])

        bpy.ops.object.select_all(action='SELECT')
        bpy.ops.object.delete()
        from mathutils import Vector
        size = Vector([max_co[i] - min_co[i] for i in range(3)])
        center = Vector([(max_co[i] + min_co[i]) / 2 for i in range(3)])
        bpy.ops.mesh.primitive_cube_add(size=1, location=center)
        cube = bpy.context.active_object
        cube.scale = size
        bpy.ops.object.transform_apply(scale=True)

        out3 = out_dir / f"{addr}_LOD3.fbx"
        bpy.ops.export_scene.fbx(filepath=str(out3), use_selection=False,
                                  apply_scale_options='FBX_SCALE_ALL')

        done += 1
        if done % 20 == 0:
            elapsed = time.time() - t0
            rate = done / elapsed * 60
            print(f"  {done}/{len(addresses)} LODs ({rate:.0f}/min)", flush=True)
    except Exception as e:
        failed += 1
        if failed <= 5:
            print(f"  FAIL {addr}: {e}", flush=True)

elapsed = time.time() - t0
print(f"DONE: {done} LOD sets, {failed} failed in {elapsed:.0f}s", flush=True)
