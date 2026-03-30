#!/usr/bin/env python3
"""Generate procedural accessibility street furniture master models for Unreal.

Usage:
    blender --background --python scripts/create_accessibility_masters_free.py -- [--out outputs/accessibility/masters]

Reads: None (procedurally generates meshes in Blender)
Writes: outputs/accessibility/masters/*.fbx (9 variants),
        outputs/accessibility/masters/accessibility_masters_free.blend
"""
import argparse, sys
from pathlib import Path
import bpy
TYPES=['access_curb_ramp','access_tactile_paving','access_accessible_bay_marking']
def clear(): bpy.ops.object.select_all(action='SELECT'); bpy.ops.object.delete(use_global=False)
def exp(p): bpy.ops.export_scene.fbx(filepath=str(p),use_selection=True,apply_unit_scale=True,bake_space_transform=False,object_types={'MESH'})
def mk(k,s):
 if k=='access_curb_ramp': bpy.ops.mesh.primitive_cube_add(size=1.0,location=(0,0,0.08*s)); o=bpy.context.active_object; o.scale=(1.0*s,0.8*s,0.08*s); return o
 if k=='access_tactile_paving': bpy.ops.mesh.primitive_plane_add(size=1.2*s,location=(0,0,0.01)); o=bpy.context.active_object; return o
 bpy.ops.mesh.primitive_plane_add(size=2.4*s,location=(0,0,0.01)); return bpy.context.active_object

def main():
 p=argparse.ArgumentParser(); p.add_argument('--out',default='outputs/accessibility/masters'); a=p.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else [])
 out=Path(a.out); out.mkdir(parents=True,exist_ok=True); clear(); n=0
 for k in TYPES:
  for vn,sc in [('A_standard',1.0),('B_compact',0.86),('C_large',1.2)]:
   o=mk(k,sc); o.name=f'SM_{k}_{vn}'; bpy.ops.object.select_all(action='DESELECT'); o.select_set(True); bpy.context.view_layer.objects.active=o; fp=out/f'{o.name}.fbx'; exp(fp); n+=1; print('[OK] exported',fp)
 bpy.ops.wm.save_as_mainfile(filepath=str(out/'accessibility_masters_free.blend')); print('[DONE] created=',n)
if __name__=='__main__': main()
