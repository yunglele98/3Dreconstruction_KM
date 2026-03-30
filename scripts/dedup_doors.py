#!/usr/bin/env python3
"""Detect and optionally deduplicate near-duplicate doors_detail entries."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
PARAMS_DIR = ROOT / "params"

POSITION_MAP = {
    "left": 0.2,
    "center": 0.5,
    "centre": 0.5,
    "right": 0.8,
}


@dataclass
class DedupResult:
    file: str
    building_name: str
    duplicates_removed: int
    total_before: int
    total_after: int


def _door_position(door: dict[str, Any]) -> float:
    if door.get("position_m") is not None:
        try:
            return float(door.get("position_m"))
        except (TypeError, ValueError):
            pass
    pos = str(door.get("position") or "").lower().strip()
    if pos in POSITION_MAP:
        return POSITION_MAP[pos]
    return 0.5


def _completeness(door: dict[str, Any]) -> int:
    return sum(1 for value in door.values() if value not in (None, "", [], {}))


def dedup_doors_list(doors: list[dict[str, Any]], tolerance: float = 0.3) -> tuple[list[dict[str, Any]], int]:
    if len(doors) <= 1:
        return doors, 0

    kept: list[dict[str, Any]] = []
    removed = 0
    for door in doors:
        dup_idx = None
        for idx, existing in enumerate(kept):
            if abs(_door_position(door) - _door_position(existing)) <= tolerance:
                if str(door.get("type") or "").lower() == str(existing.get("type") or "").lower():
                    dup_idx = idx
                    break
        if dup_idx is None:
            kept.append(door)
            continue

        if _completeness(door) > _completeness(kept[dup_idx]):
            kept[dup_idx] = door
        removed += 1
    return kept, removed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Deduplicate near-identical doors_detail entries.")
    parser.add_argument("--params-dir", default=str(PARAMS_DIR))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--fix", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    params_dir = Path(args.params_dir)
    results: list[DedupResult] = []

    for path in sorted(params_dir.glob("*.json")):
        if path.name.startswith("_"):
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("skipped"):
            continue
        doors = data.get("doors_detail")
        if not isinstance(doors, list) or len(doors) <= 1:
            continue

        deduped, removed = dedup_doors_list(doors)
        if removed <= 0:
            continue

        results.append(
            DedupResult(
                file=path.name,
                building_name=str(data.get("building_name") or path.stem),
                duplicates_removed=removed,
                total_before=len(doors),
                total_after=len(deduped),
            )
        )

        if args.fix and not args.dry_run:
            data["doors_detail"] = deduped
            meta = data.get("_meta") if isinstance(data.get("_meta"), dict) else {}
            meta["doors_deduped"] = True
            meta["doors_dedup_count"] = removed
            data["_meta"] = meta
            path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    building_count = len(results)
    duplicate_count = sum(r.duplicates_removed for r in results)
    print(f"[dedup] Buildings affected: {building_count}")
    print(f"[dedup] Duplicate doors found: {duplicate_count}")
    for row in results[:100]:
        safe_file = row.file.encode("ascii", "backslashreplace").decode("ascii")
        print(f"  - {safe_file}: {row.total_before} -> {row.total_after} (removed {row.duplicates_removed})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
