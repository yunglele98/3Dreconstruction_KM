#!/usr/bin/env python3
import argparse, sys
from pathlib import Path
import bpy
TYPES=['utility_street_cabinet','utility_transformer_box','utility_meter_box']
def clear(): bpy.ops.object.select_all(action='SELECT'); bpy.ops.object.delete(use_global=False)
def exp(p): bpy.ops.export_scene.fbx(filepath=str(p),use_selection=True,apply_unit_scale=True,bake_space_transform=False,object_types={'MESH'})
def mk(k,s):
    bpy.ops.mesh.primitive_cube_add(size=1.0,location=(0,0,0.65*s)); o=bpy.context.active_object
    if k=='utility_transformer_box': o.scale=(0.65*s,0.42*s,0.65*s)
    elif k=='utility_meter_box': o.scale=(0.26*s,0.18*s,0.32*s); bpy.ops.mesh.primitive_cylinder_add(radius=0.05*s,depth=0.1*s,location=(0.18*s,0.2*s,0.35*s)); m=bpy.context.active_object; bpy.ops.object.select_all(action='DESELECT');o.select_set(True);m.select_set(True); bpy.context.view_layer.objects.active=o; bpy.ops.object.join(); o=bpy.context.view_layer.objects.active
    else: o.scale=(0.45*s,0.30*s,0.55*s)
    return o

def main():
 p=argparse.ArgumentParser(); p.add_argument('--out',default='outputs/utility/masters'); a=p.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else [])
 out=Path(a.out); out.mkdir(parents=True,exist_ok=True); clear(); n=0
 for k in TYPES:
  for vn,sc in [('A_standard',1.0),('B_compact',0.86),('C_large',1.2)]:
   o=mk(k,sc); o.name=f'SM_{k}_{vn}'; bpy.ops.object.select_all(action='DESELECT'); o.select_set(True); bpy.context.view_layer.objects.active=o; fp=out/f'{o.name}.fbx'; exp(fp); n+=1; print('[OK] exported',fp)
 bpy.ops.wm.save_as_mainfile(filepath=str(out/'utility_masters_free.blend')); print('[DONE] created=',n)
if __name__=='__main__': main()
