"""Placeholder: fuse iPad LiDAR scan data into building params.

Will be activated when Montreal scanning data arrives (Week 2 of sprint).
Currently a no-op that validates the interface.
"""

import json
import os
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
PARAMS_DIR = REPO_ROOT / "params"
LIDAR_DIR = REPO_ROOT / "data" / "ipad_scans"


def _atomic_write_json(filepath, data):
    filepath = Path(filepath)
    with tempfile.NamedTemporaryFile(
        mode="w", dir=filepath.parent, delete=False,
        suffix=".tmp", encoding="utf-8",
    ) as tmp:
        json.dump(data, tmp, indent=2, ensure_ascii=False)
        tmp.write("\n")
        tmp_path = Path(tmp.name)
    os.replace(str(tmp_path), str(filepath))


def run(params_dir=None, lidar_dir=None, limit=None):
    params_dir = Path(params_dir or PARAMS_DIR)
    lidar_dir = Path(lidar_dir or LIDAR_DIR)

    if not lidar_dir.exists():
        print(f"fuse_lidar: No LiDAR data at {lidar_dir} -- placeholder, nothing to do")
        return

    scans = list(lidar_dir.glob("**/*.ply")) + list(lidar_dir.glob("**/*.obj"))
    if not scans:
        print(f"fuse_lidar: No .ply/.obj scans found in {lidar_dir}")
        return

    print(f"fuse_lidar: Found {len(scans)} scans -- processing not yet implemented")
    print("  This script will be completed when Montreal iPad scanning data arrives.")
    print("  Expected workflow:")
    print("    1. Match scan to building by address/typology")
    print("    2. Extract dimensions from scan bounding box")
    print("    3. Validate against existing params (height, width)")
    print("    4. Update roof_pitch_deg from scan geometry")
    print("    5. Flag scan availability in _meta")


if __name__ == "__main__":
    limit = None
    for i, arg in enumerate(sys.argv):
        if arg == "--limit" and i + 1 < len(sys.argv):
            limit = int(sys.argv[i + 1])
    run(limit=limit)
