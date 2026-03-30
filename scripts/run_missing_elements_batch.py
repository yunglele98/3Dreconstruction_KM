#!/usr/bin/env python3
from __future__ import annotations
import subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def run(cmd):
 print('[RUN]',' '.join(cmd)); subprocess.run(cmd,cwd=ROOT,check=True)

def main()->int:
 # Waste
 run(['python','scripts/build_waste_photo_references.py'])
 run(['python','scripts/export_unreal_waste_data.py'])
 run(['blender','--background','--python','scripts/create_waste_masters_free.py'])
 run(['python','scripts/build_unreal_waste_import_bundle.py'])
 # Utility
 run(['python','scripts/build_utility_photo_references.py'])
 run(['python','scripts/export_unreal_utility_data.py'])
 run(['blender','--background','--python','scripts/create_utility_masters_free.py'])
 run(['python','scripts/build_unreal_utility_import_bundle.py'])
 # Road markings decals
 run(['python','scripts/build_roadmark_photo_references.py'])
 run(['python','scripts/extract_roadmark_decals_from_photos.py'])
 run(['python','scripts/export_unreal_roadmark_targets.py'])
 run(['python','scripts/build_unreal_roadmark_decal_placements.py'])
 # Service/backlot
 run(['python','scripts/export_unreal_service_backlot_data.py'])
 run(['blender','--background','--python','scripts/create_service_backlot_masters_free.py'])
 run(['python','scripts/build_unreal_service_backlot_import_bundle.py'])
 print('[DONE] missing-elements batch complete')
 return 0

if __name__=='__main__': raise SystemExit(main())
