#!/usr/bin/env python3
import argparse, sys
from pathlib import Path
import bpy
TYPES=['waste_garbage_bin','waste_recycling_bin','waste_dumpster']

def clear(): bpy.ops.object.select_all(action='SELECT'); bpy.ops.object.delete(use_global=False)
def exp(p): bpy.ops.export_scene.fbx(filepath=str(p),use_selection=True,apply_unit_scale=True,bake_space_transform=False,object_types={'MESH'})
def mk(k,s):
    if k=='waste_dumpster': bpy.ops.mesh.primitive_cube_add(size=1.0,location=(0,0,0.7*s));o=bpy.context.active_object;o.scale=(0.8*s,0.45*s,0.7*s);return o
    bpy.ops.mesh.primitive_cube_add(size=1.0,location=(0,0,0.55*s));o=bpy.context.active_object;o.scale=(0.24*s,0.24*s,0.55*s);bpy.ops.mesh.primitive_cube_add(size=1.0,location=(0,0,1.12*s));l=bpy.context.active_object;l.scale=(0.25*s,0.24*s,0.06*s);bpy.ops.object.select_all(action='DESELECT');o.select_set(True);l.select_set(True);bpy.context.view_layer.objects.active=o;bpy.ops.object.join();return bpy.context.view_layer.objects.active

def main():
    p=argparse.ArgumentParser();p.add_argument('--out',default='outputs/waste/masters');a=p.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else [])
    out=Path(a.out);out.mkdir(parents=True,exist_ok=True);clear();n=0
    for k in TYPES:
      for vn,sc in [('A_standard',1.0),('B_compact',0.86),('C_large',1.2)]:
        o=mk(k,sc);o.name=f'SM_{k}_{vn}';bpy.ops.object.select_all(action='DESELECT');o.select_set(True);bpy.context.view_layer.objects.active=o;fp=out/f'{o.name}.fbx';exp(fp);n+=1;print('[OK] exported',fp)
    bpy.ops.wm.save_as_mainfile(filepath=str(out/'waste_masters_free.blend'));print('[DONE] created=',n)
if __name__=='__main__': main()
