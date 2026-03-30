#!/usr/bin/env python3
"""Generate procedural fence and gate master models for Unreal.

Usage:
    blender --background --python scripts/create_fence_gate_masters_free.py -- [--out outputs/fence_gates/masters]

Reads: None (procedurally generates meshes in Blender)
Writes: outputs/fence_gates/masters/*.fbx (9 variants),
        outputs/fence_gates/masters/fence_gate_masters_free.blend
"""
import argparse, sys
from pathlib import Path
import bpy
TYPES=['gate_panel','chainlink_fence_segment','security_grille_panel']
def clear(): bpy.ops.object.select_all(action='SELECT'); bpy.ops.object.delete(use_global=False)
def exp(p): bpy.ops.export_scene.fbx(filepath=str(p),use_selection=True,apply_unit_scale=True,bake_space_transform=False,object_types={'MESH'})
def mk(k,s):
 if k=='chainlink_fence_segment': bpy.ops.mesh.primitive_plane_add(size=2.2*s,location=(0,0,0.9*s)); p=bpy.context.active_object; bpy.ops.mesh.primitive_cylinder_add(radius=0.03*s,depth=1.8*s,location=(-1.0*s,0,0.9*s)); a=bpy.context.active_object; bpy.ops.mesh.primitive_cylinder_add(radius=0.03*s,depth=1.8*s,location=(1.0*s,0,0.9*s)); b=bpy.context.active_object; bpy.ops.object.select_all(action='DESELECT'); p.select_set(True); a.select_set(True); b.select_set(True); bpy.context.view_layer.objects.active=p; bpy.ops.object.join(); return bpy.context.view_layer.objects.active
 if k=='security_grille_panel': bpy.ops.mesh.primitive_plane_add(size=2.0*s,location=(0,0,1.1*s)); p=bpy.context.active_object; return p
 bpy.ops.mesh.primitive_cube_add(size=1.0,location=(0,0,1.0*s)); g=bpy.context.active_object; g.scale=(0.9*s,0.05*s,1.0*s); return g

def main():
 p=argparse.ArgumentParser(); p.add_argument('--out',default='outputs/fence_gates/masters'); a=p.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else [])
 out=Path(a.out); out.mkdir(parents=True,exist_ok=True); clear(); n=0
 for k in TYPES:
  for vn,sc in [('A_standard',1.0),('B_compact',0.86),('C_large',1.2)]:
   o=mk(k,sc); o.name=f'SM_{k}_{vn}'; bpy.ops.object.select_all(action='DESELECT'); o.select_set(True); bpy.context.view_layer.objects.active=o; fp=out/f'{o.name}.fbx'; exp(fp); n+=1; print('[OK] exported',fp)
 bpy.ops.wm.save_as_mainfile(filepath=str(out/'fence_gate_masters_free.blend')); print('[DONE] created=',n)
if __name__=='__main__': main()
