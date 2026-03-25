#!/usr/bin/env python3
"""Run a GIS-accurate Blender demo scene from live PostGIS data.

This script:
1) exports fresh GIS geometry from PostGIS to `gis_scene.py` + `outputs/gis_scene.json`
2) launches Blender with the generated scene script

Example:
    python scripts/blender_gis_demo.py --headless
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
EXPORT_SCRIPT = REPO_ROOT / "scripts" / "export_gis_scene.py"
DEFAULT_SCENE_SCRIPT = "gis_scene.py"
DEFAULT_BLENDER = Path(r"C:\Program Files\Blender Foundation\Blender 5.0\blender.exe")


def run(cmd: list[str], env: dict[str, str] | None = None) -> None:
    print(">", " ".join(str(c) for c in cmd))
    subprocess.run(cmd, check=True, cwd=str(REPO_ROOT), env=env)


def main() -> int:
    parser = argparse.ArgumentParser(description="GIS-accurate Blender demo launcher")
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", default="5432")
    parser.add_argument("--dbname", default="kensington")
    parser.add_argument("--user", default="postgres")
    parser.add_argument("--password", default="test123")
    parser.add_argument("--blender", default=str(DEFAULT_BLENDER))
    parser.add_argument("--scene-script", default=DEFAULT_SCENE_SCRIPT)
    parser.add_argument("--headless", action="store_true", help="Run Blender in background")
    parser.add_argument("--no-massing", action="store_true", help="Skip 3D massing export for faster demo")
    args = parser.parse_args()

    env = os.environ.copy()
    env["PGHOST"] = args.host
    env["PGPORT"] = str(args.port)
    env["PGDATABASE"] = args.dbname
    env["PGUSER"] = args.user
    env["PGPASSWORD"] = args.password

    export_cmd = [sys.executable, str(EXPORT_SCRIPT), "--output", args.scene_script]
    if args.no_massing:
        export_cmd.append("--no-massing")
    run(export_cmd, env=env)

    blender_exe = Path(args.blender)
    if not blender_exe.exists():
        raise FileNotFoundError(f"Blender not found: {blender_exe}")

    blender_cmd = [str(blender_exe)]
    if args.headless:
        blender_cmd.append("--background")
    blender_cmd.extend(["--python", args.scene_script])
    run(blender_cmd, env=env)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
