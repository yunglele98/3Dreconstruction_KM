#!/usr/bin/env python3
"""
Auto-fix placement metadata issues from outputs/window_roof_placement_audit.json.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def infer_floor_index(label: str) -> int | None:
    t = (label or "").strip().lower()
    if "ground" in t:
        return 1
    if "second" in t:
        return 2
    if "third" in t:
        return 3
    if "fourth" in t:
        return 4
    if "fifth" in t:
        return 5
    if "attic" in t or "gable" in t or "roof" in t:
        return None
    return None


def count_windows(entry: dict) -> int:
    windows = entry.get("windows") or []
    total = 0
    if isinstance(windows, list):
        for win in windows:
            if not isinstance(win, dict):
                continue
            c = win.get("count")
            if isinstance(c, int):
                total += c
    return total


def rebuild_from_windows_detail(data: dict) -> tuple[int, list[int]]:
    detail = data.get("windows_detail") or []
    floor_counts: dict[int, int] = {}
    inferred_max = 0
    if isinstance(detail, list):
        for entry in detail:
            if not isinstance(entry, dict):
                continue
            idx = infer_floor_index(str(entry.get("floor") or ""))
            if idx is None:
                continue
            inferred_max = max(inferred_max, idx)
            floor_counts[idx] = max(floor_counts.get(idx, 0), count_windows(entry))

    floors = int(data.get("floors") or 0)
    floors = max(floors, inferred_max)
    if floors <= 0:
        floors = 1
    windows_per_floor = [0] * floors
    for i in range(1, floors + 1):
        windows_per_floor[i - 1] = int(floor_counts.get(i, 0))
    return floors, windows_per_floor


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audit", default="outputs/window_roof_placement_audit.json")
    parser.add_argument("--params-dir", default="params")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    audit_path = Path(args.audit)
    params_dir = Path(args.params_dir)
    report = json.loads(audit_path.read_text(encoding="utf-8"))
    targets = sorted(report.get("results", {}).keys())

    updated = 0
    for name in targets:
        p = params_dir / name
        if not p.exists():
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        old_floors = int(data.get("floors") or 0)
        old_wpf = data.get("windows_per_floor")
        floors, wpf = rebuild_from_windows_detail(data)
        changed = (old_floors != floors) or (old_wpf != wpf)
        if not changed:
            continue
        data["floors"] = floors
        data["windows_per_floor"] = wpf
        meta = data.setdefault("_meta", {})
        if isinstance(meta, dict):
            fixes = meta.setdefault("placement_fixes_applied", [])
            if isinstance(fixes, list):
                fixes.append("fix_window_roof_placements")
        if not args.dry_run:
            p.write_text(json.dumps(data, indent=2), encoding="utf-8")
        updated += 1

    print(f"targets={len(targets)} updated={updated} dry_run={args.dry_run}")


if __name__ == "__main__":
    main()
