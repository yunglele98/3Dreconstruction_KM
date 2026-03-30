#!/usr/bin/env python3
"""Render one PNG demo per tree species key."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

import bpy
from mathutils import Vector


def parse_args() -> argparse.Namespace:
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", default="outputs/trees/tree_catalog.json")
    parser.add_argument("--manifest", default="outputs/trees/unreal_import_manifest.csv")
    parser.add_argument("--masters-dir", default="outputs/trees/masters")
    parser.add_argument("--out-dir", default="outputs/trees/demos/species")
    parser.add_argument("--limit", type=int, default=0)
    return parser.parse_args(argv)


def species_from_catalog(path: Path) -> list[str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    items = data.get("catalog") or []
    keys = [str(i.get("species_key", "")).strip() for i in items]
    return sorted({k for k in keys if k})


def manifest_source_map(path: Path) -> dict[str, Path]:
    if not path.exists():
        return {}
    out: dict[str, Path] = {}
    with path.open("r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            key = (row.get("species_key") or "").strip()
            src = (row.get("source_fbx") or "").strip()
            if key and src:
                out[key] = Path(src)
    return out


def clear_scene() -> None:
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)


def resolve_source(species_key: str, masters: Path, mapped: dict[str, Path]) -> Path:
    for p in (
        masters / f"SM_{species_key}_A_mature.fbx",
        mapped.get(species_key),
        masters / "SM_acer_A_mature.fbx",
    ):
        if p and Path(p).exists():
            return Path(p)
    raise FileNotFoundError(f"Missing source FBX for {species_key}")


def import_joined_mesh(path: Path, name: str):
    before = {o.name for o in bpy.data.objects}
    bpy.ops.import_scene.fbx(filepath=str(path))
    meshes = [o for o in bpy.data.objects if o.name not in before and o.type == "MESH"]
    if not meshes:
        return None
    if len(meshes) == 1:
        obj = meshes[0]
    else:
        bpy.ops.object.select_all(action="DESELECT")
        for m in meshes:
            m.select_set(True)
        bpy.context.view_layer.objects.active = meshes[0]
        bpy.ops.object.join()
        obj = bpy.context.view_layer.objects.active
    obj.name = name
    return obj


def fit_camera(obj, camera):
    corners = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
    mins = Vector((min(c.x for c in corners), min(c.y for c in corners), min(c.z for c in corners)))
    maxs = Vector((max(c.x for c in corners), max(c.y for c in corners), max(c.z for c in corners)))
    center = (mins + maxs) * 0.5
    radius = max((maxs - mins).x, (maxs - mins).y, (maxs - mins).z, 1.0)
    bpy.ops.mesh.primitive_plane_add(size=max(6.0, radius * 5.0), location=(0.0, 0.0, mins.z - 0.02))
    camera.location = Vector((center.x + radius * 1.9, center.y - radius * 1.9, center.z + radius * 1.2))
    direction = (center + Vector((0, 0, radius * 0.15))) - camera.location
    camera.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


def main() -> int:
    args = parse_args()
    catalog = Path(args.catalog)
    manifest = Path(args.manifest)
    masters = Path(args.masters_dir)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    species = species_from_catalog(catalog)
    if args.limit > 0:
        species = species[: args.limit]
    src_map = manifest_source_map(manifest)

    clear_scene()
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.render.image_settings.file_format = "PNG"
    scene.render.resolution_x = 1024
    scene.render.resolution_y = 1024
    if scene.world is None:
        scene.world = bpy.data.worlds.new("DemoWorld")
    scene.world.color = (0.93, 0.95, 0.98)

    cam_data = bpy.data.cameras.new("DemoCamera")
    cam = bpy.data.objects.new("DemoCamera", cam_data)
    scene.collection.objects.link(cam)
    scene.camera = cam
    sun_data = bpy.data.lights.new("DemoSun", "SUN")
    sun = bpy.data.objects.new("DemoSun", sun_data)
    scene.collection.objects.link(sun)
    sun.rotation_euler = (0.9, 0.0, 0.6)

    rows: list[dict[str, str]] = []
    for idx, key in enumerate(species, start=1):
        for obj in list(bpy.data.objects):
            if obj.name not in {"DemoCamera", "DemoSun"}:
                bpy.data.objects.remove(obj, do_unlink=True)
        try:
            source = resolve_source(key, masters, src_map)
            mesh = import_joined_mesh(source, f"SM_{key}_DEMO")
            if mesh is None:
                raise RuntimeError("No mesh imported")
            fit_camera(mesh, cam)
            png = out_dir / f"{idx:03d}_{key}.png"
            scene.render.filepath = str(png)
            bpy.ops.render.render(write_still=True)
            rows.append({"species_key": key, "source_fbx": str(source.resolve()), "demo_png": str(png.resolve()), "status": "ok", "error": ""})
            print(f"[OK] {key}")
        except Exception as exc:
            rows.append({"species_key": key, "source_fbx": "", "demo_png": "", "status": "failed", "error": str(exc)})
            print(f"[WARN] {key}: {exc}")

    manifest_csv = out_dir / "tree_species_demos_manifest.csv"
    with manifest_csv.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["species_key", "source_fbx", "demo_png", "status", "error"])
        writer.writeheader()
        writer.writerows(rows)

    summary = {
        "species_total": len(rows),
        "rendered_ok": sum(1 for r in rows if r["status"] == "ok"),
        "failed": sum(1 for r in rows if r["status"] != "ok"),
    }
    (out_dir / "tree_species_demos_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"[DONE] {summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
