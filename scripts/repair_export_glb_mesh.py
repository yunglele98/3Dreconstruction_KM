"""
Targeted GLB mesh repair utility for exported buildings.

Repairs are conservative and focused on validation failures:
- remove degenerate faces
- remove duplicate faces
- remove unreferenced vertices
- optional hole filling

Usage:
  python scripts/repair_export_glb_mesh.py --address "10 Hickory St" --apply
  python scripts/repair_export_glb_mesh.py --address-csv outputs/session_runs/logs/<run>_degenerate_addresses.csv --apply
"""

from __future__ import annotations

import argparse
import csv
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

import trimesh
from trimesh import Trimesh


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EXPORTS_DIR = REPO_ROOT / "outputs" / "exports"


@dataclass
class RepairResult:
    address: str
    glb_path: str
    exists: bool
    faces_before: int
    faces_after: int
    verts_before: int
    verts_after: int
    degenerate_removed: int
    duplicate_removed: int
    unreferenced_removed: int
    hole_faces_added: int
    would_write: bool
    wrote: bool
    error: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Repair exported GLB meshes")
    parser.add_argument("--exports-dir", type=Path, default=DEFAULT_EXPORTS_DIR, help="Exports root path")
    parser.add_argument("--address", action="append", default=[], help="Address to repair (repeatable)")
    parser.add_argument("--address-csv", type=Path, help="CSV with `address` column")
    parser.add_argument("--apply", action="store_true", help="Write repaired GLB files")
    parser.add_argument("--fill-holes", action="store_true", help="Attempt hole filling")
    parser.add_argument("--report", type=Path, help="Optional JSON report path")
    return parser.parse_args()


def sanitize_address(address: str) -> str:
    safe = "".join(ch if (ch.isalnum() or ch == "-") else "_" for ch in address.strip())
    while "__" in safe:
        safe = safe.replace("__", "_")
    return safe.strip("_")


def iter_addresses(args: argparse.Namespace) -> Iterable[str]:
    yielded = set()
    for addr in args.address:
        a = addr.strip()
        if a and a not in yielded:
            yielded.add(a)
            yield a
    if args.address_csv and args.address_csv.exists():
        with args.address_csv.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                a = (row.get("address") or "").strip()
                if a and a not in yielded:
                    yielded.add(a)
                    yield a


def _to_single_mesh(obj) -> Trimesh:
    if isinstance(obj, Trimesh):
        return obj.copy()
    if isinstance(obj, trimesh.Scene):
        meshes = []
        for geom in obj.geometry.values():
            if isinstance(geom, Trimesh):
                meshes.append(geom)
        if not meshes:
            raise ValueError("No mesh geometry in scene")
        return trimesh.util.concatenate(meshes)
    raise TypeError(f"Unsupported trimesh object type: {type(obj)}")


def repair_glb(glb_path: Path, apply: bool, fill_holes: bool) -> RepairResult:
    result = RepairResult(
        address=glb_path.stem.replace("_", " "),
        glb_path=str(glb_path),
        exists=glb_path.exists(),
        faces_before=0,
        faces_after=0,
        verts_before=0,
        verts_after=0,
        degenerate_removed=0,
        duplicate_removed=0,
        unreferenced_removed=0,
        hole_faces_added=0,
        would_write=False,
        wrote=False,
        error="",
    )
    if not glb_path.exists():
        return result
    try:
        loaded = trimesh.load(str(glb_path), process=False)
        mesh = _to_single_mesh(loaded)

        result.faces_before = int(len(mesh.faces))
        result.verts_before = int(len(mesh.vertices))

        # Degenerates (version-safe)
        faces_mid = int(len(mesh.faces))
        if hasattr(mesh, "remove_degenerate_faces"):
            mesh.remove_degenerate_faces()  # older trimesh versions
        else:
            if hasattr(mesh, "nondegenerate_faces"):
                # Match validator threshold: area < 1e-10 is considered degenerate.
                nd_mask = mesh.nondegenerate_faces(height=1e-10)
                mesh.update_faces(nd_mask)
        result.degenerate_removed = max(0, faces_mid - int(len(mesh.faces)))

        # Duplicates (version-safe)
        faces_mid = int(len(mesh.faces))
        if hasattr(mesh, "remove_duplicate_faces"):
            mesh.remove_duplicate_faces()  # older trimesh versions
        else:
            if hasattr(mesh, "unique_faces"):
                uniq_mask = mesh.unique_faces()
                mesh.update_faces(uniq_mask)
        result.duplicate_removed = max(0, faces_mid - int(len(mesh.faces)))

        # Unreferenced verts
        verts_mid = int(len(mesh.vertices))
        mesh.remove_unreferenced_vertices()
        result.unreferenced_removed = max(0, verts_mid - int(len(mesh.vertices)))

        # Optional hole fill
        if fill_holes:
            faces_pre_fill = int(len(mesh.faces))
            try:
                mesh.fill_holes()
            except Exception:
                pass
            result.hole_faces_added = max(0, int(len(mesh.faces)) - faces_pre_fill)

        result.faces_after = int(len(mesh.faces))
        result.verts_after = int(len(mesh.vertices))
        changed = (
            result.faces_after != result.faces_before
            or result.verts_after != result.verts_before
            or result.hole_faces_added > 0
        )
        result.would_write = changed

        if apply and changed:
            mesh.export(str(glb_path))
            result.wrote = True
    except Exception as exc:
        result.error = str(exc)
    return result


def main() -> None:
    args = parse_args()
    addresses = list(iter_addresses(args))
    if not addresses:
        raise SystemExit("No addresses provided. Use --address and/or --address-csv.")

    exports_dir = args.exports_dir.resolve()
    results: list[RepairResult] = []
    for address in addresses:
        safe = sanitize_address(address)
        glb = exports_dir / safe / f"{safe}.glb"
        r = repair_glb(glb, apply=args.apply, fill_holes=args.fill_holes)
        r.address = address
        results.append(r)
        if r.error:
            print(f"error: {address} -> {r.error}")
        else:
            print(
                f"{'wrote' if r.wrote else 'checked'}: {address} "
                f"(faces {r.faces_before}->{r.faces_after}, verts {r.verts_before}->{r.verts_after}, "
                f"deg_removed={r.degenerate_removed}, dup_removed={r.duplicate_removed}, "
                f"unref_removed={r.unreferenced_removed}, hole_added={r.hole_faces_added})"
            )

    payload = {
        "summary": {
            "total": len(results),
            "errors": sum(1 for r in results if r.error),
            "would_write": sum(1 for r in results if r.would_write),
            "wrote": sum(1 for r in results if r.wrote),
        },
        "results": [asdict(r) for r in results],
    }

    report_path = args.report
    if report_path is not None:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
