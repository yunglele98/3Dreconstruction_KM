"""Fast FBX batch export — runs INSIDE Blender, iterates blends without restart.

Usage (from command line):
  blender --background --python scripts/fast_fbx_export.py -- --chunk outputs/fbx_chunk_1.txt
"""
import sys, json, time
from pathlib import Path

# Parse args after --
argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
chunk_file = None
for i, arg in enumerate(argv):
    if arg == "--chunk" and i + 1 < len(argv):
        chunk_file = argv[i + 1]

if not chunk_file:
    print("Usage: blender --background --python scripts/fast_fbx_export.py -- --chunk <file>")
    sys.exit(1)

import bpy

blend_files = Path(chunk_file).read_text(encoding="utf-8").strip().split("\n")
exports_dir = Path("outputs/exports")
exports_dir.mkdir(parents=True, exist_ok=True)

done = 0
failed = 0
t0 = time.time()

for blend_path in blend_files:
    blend_path = Path(blend_path.strip())
    if not blend_path.exists():
        continue
    addr = blend_path.stem
    out_dir = exports_dir / addr
    if out_dir.exists():
        continue  # skip existing

    try:
        bpy.ops.wm.open_mainfile(filepath=str(blend_path))
        out_dir.mkdir(parents=True, exist_ok=True)
        fbx_path = out_dir / f"{addr}.fbx"
        bpy.ops.export_scene.fbx(
            filepath=str(fbx_path),
            use_selection=False,
            apply_scale_options='FBX_SCALE_ALL',
            path_mode='COPY',
            embed_textures=False,
        )
        done += 1
        if done % 20 == 0:
            elapsed = time.time() - t0
            rate = done / elapsed * 60
            remaining = (len(blend_files) - done) / (rate / 60) if rate > 0 else 0
            print(f"  {done}/{len(blend_files)} exported ({rate:.0f}/min, ~{remaining:.0f}s remaining)", flush=True)
    except Exception as e:
        failed += 1
        print(f"  FAIL {addr}: {e}", flush=True)

elapsed = time.time() - t0
print(f"DONE: {done} exported, {failed} failed in {elapsed:.0f}s ({done/elapsed*60:.0f}/min)" if elapsed > 0 else "DONE", flush=True)
