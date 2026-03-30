#!/usr/bin/env python3
"""Generate procedural park furniture master models for Unreal.

Usage:
    blender --background --python scripts/create_park_furniture_masters_free.py -- [--out outputs/park_furniture/masters]

Reads: None (procedurally generates meshes in Blender)
Writes: outputs/park_furniture/masters/*.fbx (9 variants),
        outputs/park_furniture/masters/park_furniture_masters_free.blend
"""
import argparse, sys
from pathlib import Path
import bpy
TYPES=['park_bench_module','park_planter_module','park_play_element']
def clear(): bpy.ops.object.select_all(action='SELECT'); bpy.ops.object.delete(use_global=False)
def exp(p): bpy.ops.export_scene.fbx(filepath=str(p),use_selection=True,apply_unit_scale=True,bake_space_transform=False,object_types={'MESH'})
def mk(k,s):
 if k=='park_bench_module': bpy.ops.mesh.primitive_cube_add(size=1.0,location=(0,0,0.25*s)); seat=bpy.context.active_object; seat.scale=(0.9*s,0.25*s,0.08*s); bpy.ops.mesh.primitive_cube_add(size=1.0,location=(0, -0.2*s,0.55*s)); back=bpy.context.active_object; back.scale=(0.9*s,0.05*s,0.35*s); bpy.ops.object.select_all(action='DESELECT'); seat.select_set(True); back.select_set(True); bpy.context.view_layer.objects.active=seat; bpy.ops.object.join(); return bpy.context.view_layer.objects.active
 if k=='park_planter_module': bpy.ops.mesh.primitive_cube_add(size=1.0,location=(0,0,0.25*s)); box=bpy.context.active_object; box.scale=(0.5*s,0.5*s,0.25*s); bpy.ops.mesh.primitive_uv_sphere_add(radius=0.28*s,location=(0,0,0.65*s)); sh=bpy.context.active_object; bpy.ops.object.select_all(action='DESELECT'); box.select_set(True); sh.select_set(True); bpy.context.view_layer.objects.active=box; bpy.ops.object.join(); return bpy.context.view_layer.objects.active
 bpy.ops.mesh.primitive_torus_add(major_radius=0.6*s,minor_radius=0.10*s,location=(0,0,0.9*s)); return bpy.context.active_object

def main():
 p=argparse.ArgumentParser(); p.add_argument('--out',default='outputs/park_furniture/masters'); a=p.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else [])
 out=Path(a.out); out.mkdir(parents=True,exist_ok=True); clear(); n=0
 for k in TYPES:
  for vn,sc in [('A_standard',1.0),('B_compact',0.86),('C_large',1.2)]:
   o=mk(k,sc); o.name=f'SM_{k}_{vn}'; bpy.ops.object.select_all(action='DESELECT'); o.select_set(True); bpy.context.view_layer.objects.active=o; fp=out/f'{o.name}.fbx'; exp(fp); n+=1; print('[OK] exported',fp)
 bpy.ops.wm.save_as_mainfile(filepath=str(out/'park_furniture_masters_free.blend')); print('[DONE] created=',n)
if __name__=='__main__': main()
