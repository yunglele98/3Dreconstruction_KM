#!/usr/bin/env python3
from __future__ import annotations
import subprocess
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]

def run(cmd):
    print('[RUN]', ' '.join(cmd))
    subprocess.run(cmd, cwd=ROOT, check=True)

def main() -> int:
    run(['python','scripts/build_roadmark_photo_references.py'])
    run(['python','scripts/extract_roadmark_decals_from_photos.py'])
    run(['python','scripts/generate_roadmark_synthetic_decals.py'])
    run(['python','scripts/merge_roadmark_decal_catalogs.py'])
    run(['python','scripts/export_unreal_roadmark_targets.py'])
    run(['python','scripts/build_unreal_roadmark_decal_placements.py'])
    print('[DONE] roadmark deepen pipeline complete')
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
