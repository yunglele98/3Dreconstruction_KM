#!/usr/bin/env python3
"""Generate procedural service backlot master models for Unreal.

Usage:
    blender --background --python scripts/create_service_backlot_masters_free.py -- [--out outputs/service_backlot/masters]

Reads: None (procedurally generates meshes in Blender)
Writes: outputs/service_backlot/masters/*.fbx (12 variants),
        outputs/service_backlot/masters/service_backlot_masters_free.blend
"""
import argparse, sys
from pathlib import Path
import bpy
TYPES=['service_loading_dock','service_exhaust_vent','service_entry_door','service_utility_conduit']
def clear(): bpy.ops.object.select_all(action='SELECT'); bpy.ops.object.delete(use_global=False)
def exp(p): bpy.ops.export_scene.fbx(filepath=str(p),use_selection=True,apply_unit_scale=True,bake_space_transform=False,object_types={'MESH'})
def mk(k,s):
 if k=='service_loading_dock': bpy.ops.mesh.primitive_cube_add(size=1.0,location=(0,0,0.35*s)); o=bpy.context.active_object; o.scale=(1.2*s,0.6*s,0.35*s); return o
 if k=='service_exhaust_vent': bpy.ops.mesh.primitive_cylinder_add(radius=0.2*s,depth=1.2*s,location=(0,0,0.6*s)); return bpy.context.active_object
 if k=='service_entry_door': bpy.ops.mesh.primitive_cube_add(size=1.0,location=(0,0,1.0*s)); o=bpy.context.active_object; o.scale=(0.45*s,0.06*s,1.0*s); return o
 bpy.ops.mesh.primitive_cylinder_add(radius=0.07*s,depth=2.0*s,location=(0,0,1.0*s)); return bpy.context.active_object

def main():
 p=argparse.ArgumentParser(); p.add_argument('--out',default='outputs/service_backlot/masters'); a=p.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else [])
 out=Path(a.out); out.mkdir(parents=True,exist_ok=True); clear(); n=0
 for k in TYPES:
  for vn,sc in [('A_standard',1.0),('B_compact',0.86),('C_large',1.2)]:
   o=mk(k,sc); o.name=f'SM_{k}_{vn}'; bpy.ops.object.select_all(action='DESELECT'); o.select_set(True); bpy.context.view_layer.objects.active=o; fp=out/f'{o.name}.fbx'; exp(fp); n+=1; print('[OK] exported',fp)
 bpy.ops.wm.save_as_mainfile(filepath=str(out/'service_backlot_masters_free.blend')); print('[DONE] created=',n)
if __name__=='__main__': main()
