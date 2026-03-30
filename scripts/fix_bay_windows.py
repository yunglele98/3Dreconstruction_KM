#!/usr/bin/env python3
"""Clamp impossible bay-window geometry values in params files."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
PARAMS_DIR = ROOT / "params"


def _to_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _clamp_bay(data: dict[str, Any]) -> tuple[int, list[str]]:
    changes = 0
    notes: list[str] = []
    width = _to_float(data.get("facade_width_m"))
    depth = _to_float(data.get("facade_depth_m"))
    if not width or not depth:
        return 0, notes

    bays: list[dict[str, Any]] = []
    top = data.get("bay_window")
    if isinstance(top, dict):
        bays.append(top)
    de = data.get("decorative_elements")
    if isinstance(de, dict):
        if isinstance(de.get("bay_window"), dict):
            bays.append(de["bay_window"])
        if isinstance(de.get("bay_windows"), list):
            bays.extend([item for item in de["bay_windows"] if isinstance(item, dict)])

    if not bays:
        return 0, notes

    max_projection = depth * 0.4
    safe_projection = round(depth * 0.3, 3)
    max_width = width * 0.5

    for bay in bays:
        projection = _to_float(bay.get("projection_m"))
        if projection is not None and projection > max_projection:
            bay["projection_m"] = safe_projection
            changes += 1
            notes.append(f"projection_m {projection} -> {safe_projection}")

        bw = _to_float(bay.get("width_m"))
        if bw is not None and bw > max_width:
            new_width = round(max_width, 3)
            bay["width_m"] = new_width
            changes += 1
            notes.append(f"width_m {bw} -> {new_width}")

    return changes, notes


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Clamp bay window projection/width to safe geometry bounds.")
    parser.add_argument("--params-dir", default=str(PARAMS_DIR))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--fix", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    params_dir = Path(args.params_dir)
    affected = 0
    change_count = 0

    for path in sorted(params_dir.glob("*.json")):
        if path.name.startswith("_"):
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if data.get("skipped"):
            continue

        changes, notes = _clamp_bay(data)
        if changes == 0:
            continue
        affected += 1
        change_count += changes
        print(f"[bay] {path.name}: {changes} changes")
        for note in notes:
            print(f"  - {note}")

        if args.fix and not args.dry_run:
            meta = data.get("_meta") if isinstance(data.get("_meta"), dict) else {}
            meta["bay_window_clamped"] = True
            data["_meta"] = meta
            path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"[bay] Buildings affected: {affected}")
    print(f"[bay] Total clamp operations: {change_count}")
    mode = "dry-run" if args.dry_run else ("fix" if args.fix else "scan")
    print(f"[bay] Mode: {mode}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
