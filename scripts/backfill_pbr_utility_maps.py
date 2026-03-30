"""
Backfill missing metallic/ao utility textures for export folders.

This reduces `texture_completeness` validator warnings where baked exports
contain diffuse/normal/roughness but omit metallic/ao maps.

Usage:
  python scripts/backfill_pbr_utility_maps.py --dry-run
  python scripts/backfill_pbr_utility_maps.py --apply
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from PIL import Image


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EXPORTS_DIR = REPO_ROOT / "outputs" / "exports"
VALID_TEXTURE_SIZES = (1024, 2048)


@dataclass
class MapBackfillResult:
    address: str
    created_metallic: bool
    created_ao: bool
    size: int
    action: str
    reason: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill missing metallic/ao texture maps")
    parser.add_argument("--exports-dir", type=Path, default=DEFAULT_EXPORTS_DIR, help="Exports root path")
    parser.add_argument("--apply", action="store_true", help="Write maps in-place")
    parser.add_argument("--dry-run", action="store_true", help="Report only; no writes")
    return parser.parse_args()


def iter_export_dirs(exports_dir: Path) -> Iterable[tuple[str, Path]]:
    for child in sorted(exports_dir.iterdir()):
        if not child.is_dir():
            continue
        safe = child.name
        fbx = child / f"{safe}.fbx"
        if not fbx.exists():
            continue
        yield safe.replace("_", " "), child


def choose_texture_size(texture_dir: Path) -> int:
    for tex in sorted(texture_dir.glob("*_diffuse.png")):
        try:
            with Image.open(tex) as img:
                w, h = img.size
            if w == h and w in VALID_TEXTURE_SIZES:
                return w
        except Exception:
            continue
    # Fallback when no diffuse is available/readable.
    return 1024


def has_pass(texture_dir: Path, pass_name: str) -> bool:
    needle = pass_name.lower()
    for tex in texture_dir.glob("*.png"):
        if needle in tex.name.lower():
            return True
    return False


def write_grayscale(path: Path, size: int, value: int) -> None:
    img = Image.new("L", (size, size), color=value)
    img.save(path, format="PNG")


def run_backfill(exports_dir: Path, apply: bool) -> list[MapBackfillResult]:
    results: list[MapBackfillResult] = []
    for address, export_dir in iter_export_dirs(exports_dir):
        texture_dir = export_dir / "textures"
        if not texture_dir.exists():
            results.append(
                MapBackfillResult(
                    address=address,
                    created_metallic=False,
                    created_ao=False,
                    size=0,
                    action="skipped",
                    reason="missing_textures_dir",
                )
            )
            continue

        has_metallic = has_pass(texture_dir, "metallic")
        has_ao = has_pass(texture_dir, "ao")
        if has_metallic and has_ao:
            continue

        size = choose_texture_size(texture_dir)
        created_metallic = False
        created_ao = False
        if apply:
            if not has_metallic:
                write_grayscale(texture_dir / "backfill_metallic.png", size=size, value=0)
                created_metallic = True
            if not has_ao:
                write_grayscale(texture_dir / "backfill_ao.png", size=size, value=255)
                created_ao = True

        results.append(
            MapBackfillResult(
                address=address,
                created_metallic=created_metallic or (not apply and not has_metallic),
                created_ao=created_ao or (not apply and not has_ao),
                size=size,
                action="written" if apply else "would_write",
                reason="missing_passes",
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
    mode = "apply" if apply else "dry-run"
    print(f"[backfill_pbr_utility_maps] mode={mode}")
    print(f"[backfill_pbr_utility_maps] candidates={len(results)}")
    print(f"[backfill_pbr_utility_maps] written={sum(1 for r in results if r.action == 'written')}")
    for row in results:
        needs = []
        if row.created_metallic:
            needs.append("metallic")
        if row.created_ao:
            needs.append("ao")
        needed_str = ",".join(needs) if needs else "none"
        print(f"{row.action}: {row.address} (size={row.size}, passes={needed_str}, reason={row.reason})")


if __name__ == "__main__":
    main()
