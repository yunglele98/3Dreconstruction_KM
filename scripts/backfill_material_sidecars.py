"""
Backfill missing/invalid materials.json sidecars for exported buildings.

The script scans `outputs/exports/<address>/` folders, infers material entries
from texture filenames, and writes a validator-compatible materials.json.

Usage:
  python scripts/backfill_material_sidecars.py --dry-run
  python scripts/backfill_material_sidecars.py --apply
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Tuple


TEXTURE_RE = re.compile(r"^(?P<mat>.+)_(?P<pass>diffuse|normal|roughness|metallic|ao)\.png$", re.IGNORECASE)
REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EXPORTS_DIR = REPO_ROOT / "outputs" / "exports"


@dataclass
class BackfillResult:
    address: str
    reason: str
    action: str
    material_count: int


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill missing/invalid materials.json sidecars")
    parser.add_argument("--exports-dir", type=Path, default=DEFAULT_EXPORTS_DIR, help="Exports root path")
    parser.add_argument("--apply", action="store_true", help="Write materials.json files in-place")
    parser.add_argument("--dry-run", action="store_true", help="Do not write files; report only")
    return parser.parse_args()


def is_valid_sidecar(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(data, dict) or not data:
        return False
    for _mat_name, mat_props in data.items():
        if not isinstance(mat_props, dict):
            return False
        if "base_color" not in mat_props or "roughness" not in mat_props:
            return False
    return True


def find_texture_files(export_dir: Path) -> Iterable[Path]:
    textures_dir = export_dir / "textures"
    if textures_dir.exists():
        yield from textures_dir.glob("*.png")
    yield from export_dir.glob("*.png")


def infer_materials_from_textures(export_dir: Path) -> Dict[str, dict]:
    by_material: Dict[str, Dict[str, str]] = {}
    for tex_path in find_texture_files(export_dir):
        match = TEXTURE_RE.match(tex_path.name)
        if not match:
            continue
        mat_name = match.group("mat")
        tex_pass = match.group("pass").lower()
        mat = by_material.setdefault(mat_name, {})
        rel = tex_path.relative_to(export_dir).as_posix()
        mat[f"{tex_pass}_map"] = rel

    materials: Dict[str, dict] = {}
    for mat_name, maps in by_material.items():
        entry = {
            "base_color": [1.0, 1.0, 1.0, 1.0],
            "roughness": 0.8,
            "metallic": 0.0,
        }
        entry.update(maps)
        materials[mat_name] = entry
    return materials


def building_dirs(exports_dir: Path) -> Iterable[Tuple[str, Path]]:
    for child in sorted(exports_dir.iterdir()):
        if not child.is_dir():
            continue
        safe = child.name
        fbx = child / f"{safe}.fbx"
        if not fbx.exists():
            continue
        address = safe.replace("_", " ")
        yield address, child


def run_backfill(exports_dir: Path, apply: bool) -> list[BackfillResult]:
    results: list[BackfillResult] = []
    for address, export_dir in building_dirs(exports_dir):
        sidecar = export_dir / "materials.json"
        if is_valid_sidecar(sidecar):
            continue

        reason = "missing_or_invalid_sidecar"
        materials = infer_materials_from_textures(export_dir)
        if not materials:
            results.append(
                BackfillResult(
                    address=address,
                    reason="no_inferable_textures",
                    action="skipped",
                    material_count=0,
                )
            )
            continue

        if apply:
            sidecar.write_text(json.dumps(materials, indent=2), encoding="utf-8")
            action = "written"
        else:
            action = "would_write"

        results.append(
            BackfillResult(
                address=address,
                reason=reason,
                action=action,
                material_count=len(materials),
            )
        )
    return results


def main() -> None:
    args = parse_args()
    if args.apply and args.dry_run:
        raise SystemExit("Use either --apply or --dry-run, not both.")
    apply = bool(args.apply and not args.dry_run)

    exports_dir = args.exports_dir.resolve()
    if not exports_dir.exists():
        raise SystemExit(f"Exports directory not found: {exports_dir}")

    results = run_backfill(exports_dir, apply=apply)
    written = sum(1 for r in results if r.action == "written")
    would_write = sum(1 for r in results if r.action == "would_write")
    skipped = sum(1 for r in results if r.action == "skipped")

    mode = "apply" if apply else "dry-run"
    print(f"[backfill_material_sidecars] mode={mode}")
    print(f"[backfill_material_sidecars] candidates={len(results)}")
    print(f"[backfill_material_sidecars] written={written}")
    print(f"[backfill_material_sidecars] would_write={would_write}")
    print(f"[backfill_material_sidecars] skipped={skipped}")
    for row in results:
        print(f"{row.action}: {row.address} ({row.material_count} materials, reason={row.reason})")


if __name__ == "__main__":
    main()
