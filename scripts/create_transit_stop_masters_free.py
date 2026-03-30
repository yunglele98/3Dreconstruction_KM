#!/usr/bin/env python3
"""Generate procedural transit stop master models for Unreal.

Usage:
    blender --background --python scripts/create_transit_stop_masters_free.py -- [--out outputs/transit_stops/masters]

Reads: None (procedurally generates meshes in Blender)
Writes: outputs/transit_stops/masters/*.fbx (6 variants),
        outputs/transit_stops/masters/transit_masters_free.blend
"""
import argparse, sys
from pathlib import Path
import bpy
TYPES=['transit_shelter','transit_stop_pole']
def clear(): bpy.ops.object.select_all(action='SELECT'); bpy.ops.object.delete(use_global=False)
def exp(p): bpy.ops.export_scene.fbx(filepath=str(p),use_selection=True,apply_unit_scale=True,bake_space_transform=False,object_types={'MESH'})
def mk(k,s):
 if k=='transit_shelter': bpy.ops.mesh.primitive_cube_add(size=1.0,location=(0,0,1.0*s)); roof=bpy.context.active_object; roof.scale=(1.6*s,0.8*s,0.08*s); bpy.ops.mesh.primitive_cube_add(size=1.0,location=(-1.1*s,0,0.6*s)); a=bpy.context.active_object; a.scale=(0.06*s,0.06*s,0.6*s); bpy.ops.mesh.primitive_cube_add(size=1.0,location=(1.1*s,0,0.6*s)); b=bpy.context.active_object; b.scale=(0.06*s,0.06*s,0.6*s); bpy.ops.object.select_all(action='DESELECT'); roof.select_set(True); a.select_set(True); b.select_set(True); bpy.context.view_layer.objects.active=roof; bpy.ops.object.join(); return bpy.context.view_layer.objects.active
 bpy.ops.mesh.primitive_cylinder_add(radius=0.06*s,depth=2.2*s,location=(0,0,1.1*s)); p=bpy.context.active_object; bpy.ops.mesh.primitive_plane_add(size=0.45*s,location=(0,0,2.0*s)); sign=bpy.context.active_object; bpy.ops.object.select_all(action='DESELECT'); p.select_set(True); sign.select_set(True); bpy.context.view_layer.objects.active=p; bpy.ops.object.join(); return bpy.context.view_layer.objects.active

def main():
 p=argparse.ArgumentParser(); p.add_argument('--out',default='outputs/transit_stops/masters'); a=p.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else [])
 out=Path(a.out); out.mkdir(parents=True,exist_ok=True); clear(); n=0
 for k in TYPES:
  for vn,sc in [('A_standard',1.0),('B_compact',0.86),('C_large',1.2)]:
   o=mk(k,sc); o.name=f'SM_{k}_{vn}'; bpy.ops.object.select_all(action='DESELECT'); o.select_set(True); bpy.context.view_layer.objects.active=o; fp=out/f'{o.name}.fbx'; exp(fp); n+=1; print('[OK] exported',fp)
 bpy.ops.wm.save_as_mainfile(filepath=str(out/'transit_masters_free.blend')); print('[DONE] created=',n)
if __name__=='__main__': main()
