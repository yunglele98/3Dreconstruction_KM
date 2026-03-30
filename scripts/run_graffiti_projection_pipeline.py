#!/usr/bin/env python3
"""Run graffiti photo projection pipeline end-to-end."""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(cmd: list[str]) -> None:
    print("[RUN]", " ".join(cmd))
    subprocess.run(cmd, check=True, cwd=ROOT)


def main() -> int:
    run(["python", "scripts/build_graffiti_semantic_catalog.py"])
    run(["python", "scripts/extract_graffiti_decals_from_photos.py"])
    run(["python", "scripts/build_alley_graffiti_priority_decals.py"])
    print("[DONE] graffiti photo projection pipeline complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
