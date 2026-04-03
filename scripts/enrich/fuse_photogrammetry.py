"""Mark buildings that have photogrammetric meshes available."""

import json
import os
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
PARAMS_DIR = REPO_ROOT / "params"
MESHES_DIR = REPO_ROOT / "meshes" / "retopo"


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


def run(params_dir=None, meshes_dir=None, limit=None):
    params_dir = Path(params_dir or PARAMS_DIR)
    meshes_dir = Path(meshes_dir or MESHES_DIR)

    if not meshes_dir.exists():
        print(f"No meshes directory at {meshes_dir} -- nothing to fuse")
        return

    mesh_stems = {p.stem.lower() for p in meshes_dir.glob("*.obj")}
    mesh_stems.update(p.stem.lower() for p in meshes_dir.glob("*.fbx"))

    files = sorted(params_dir.glob("*.json"))
    if limit:
        files = files[:limit]

    stats = {"processed": 0, "marked": 0, "skipped": 0}

    for f in files:
        if f.name.startswith("_"):
            continue
        try:
            params = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        if params.get("skipped"):
            stats["skipped"] += 1
            continue

        meta = params.get("_meta", {})
        if meta.get("has_photogrammetric_mesh"):
            stats["skipped"] += 1
            continue

        stem = f.stem.lower()
        if stem in mesh_stems:
            meta = params.setdefault("_meta", {})
            meta["has_photogrammetric_mesh"] = True
            meta["photogrammetric_mesh_path"] = str(meshes_dir / f"{f.stem}.obj")
            fusion = meta.setdefault("fusion_applied", [])
            if "photogrammetry" not in fusion:
                fusion.append("photogrammetry")
            _atomic_write_json(f, params)
            stats["marked"] += 1

        stats["processed"] += 1

    print(f"fuse_photogrammetry: {stats['processed']} processed, "
          f"{stats['marked']} marked with mesh, {stats['skipped']} skipped")


if __name__ == "__main__":
    limit = None
    for i, arg in enumerate(sys.argv):
        if arg == "--limit" and i + 1 < len(sys.argv):
            limit = int(sys.argv[i + 1])
    run(limit=limit)
