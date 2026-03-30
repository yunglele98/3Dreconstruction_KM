#!/usr/bin/env python3
"""Run printable feature extraction + placement pipeline."""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(cmd):
    print('[RUN]', ' '.join(cmd))
    subprocess.run(cmd, cwd=ROOT, check=True)


def main() -> int:
    run(['python','scripts/build_printable_reference_shortlist.py'])
    run(['python','scripts/extract_printable_decals_from_photos.py'])
    run(['python','scripts/export_unreal_printable_targets.py'])
    run(['python','scripts/build_unreal_printable_decal_placements.py'])
    print('[DONE] printable projection pipeline complete')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
