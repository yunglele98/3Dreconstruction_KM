#!/usr/bin/env python3
from __future__ import annotations
import subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def run(cmd):
 print('[RUN]',' '.join(cmd)); subprocess.run(cmd,cwd=ROOT,check=True)

def main()->int:
 # 1 waste
 run(['python','scripts/build_waste_photo_references.py']); run(['python','scripts/export_unreal_waste_data.py']); run(['blender','--background','--python','scripts/create_waste_masters_free.py']); run(['python','scripts/build_unreal_waste_import_bundle.py'])
 # 2 utility
 run(['python','scripts/build_utility_photo_references.py']); run(['python','scripts/export_unreal_utility_data.py']); run(['blender','--background','--python','scripts/create_utility_masters_free.py']); run(['python','scripts/build_unreal_utility_import_bundle.py'])
 # 3 fences/gates
 run(['python','scripts/build_fence_gate_photo_references.py']); run(['python','scripts/export_unreal_fence_gate_data.py']); run(['blender','--background','--python','scripts/create_fence_gate_masters_free.py']); run(['python','scripts/build_unreal_fence_gate_import_bundle.py'])
 # 4 accessibility
 run(['python','scripts/export_unreal_accessibility_data.py']); run(['blender','--background','--python','scripts/create_accessibility_masters_free.py']); run(['python','scripts/build_unreal_accessibility_import_bundle.py'])
 # 5 road markings decals
 run(['python','scripts/build_roadmark_photo_references.py']); run(['python','scripts/extract_roadmark_decals_from_photos.py']); run(['python','scripts/export_unreal_roadmark_targets.py']); run(['python','scripts/build_unreal_roadmark_decal_placements.py'])
 # 6 transit stops
 run(['python','scripts/build_transit_stop_photo_references.py']); run(['python','scripts/export_unreal_transit_stop_data.py']); run(['blender','--background','--python','scripts/create_transit_stop_masters_free.py']); run(['python','scripts/build_unreal_transit_stop_import_bundle.py'])
 # 7 park furniture
 run(['python','scripts/export_unreal_park_furniture_data.py']); run(['blender','--background','--python','scripts/create_park_furniture_masters_free.py']); run(['python','scripts/build_unreal_park_furniture_import_bundle.py'])
 # 8 service/backlot
 run(['python','scripts/export_unreal_service_backlot_data.py']); run(['blender','--background','--python','scripts/create_service_backlot_masters_free.py']); run(['python','scripts/build_unreal_service_backlot_import_bundle.py'])
 print('[DONE] all 8 untreated element families complete')
 return 0

if __name__=='__main__': raise SystemExit(main())
