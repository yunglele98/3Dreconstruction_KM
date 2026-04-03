#!/usr/bin/env python3
"""Diff two versions of a building param file or two param directories.

Shows field-level changes between versions, useful for verifying
enrichment pipeline changes or scenario modifications.

Usage:
    python scripts/diff_params.py params/22_Lippincott_St.json params_backup/22_Lippincott_St.json
    python scripts/diff_params.py --dir-a params/ --dir-b outputs/scenarios/gentle_density/
    python scripts/diff_params.py --dir-a params/ --dir-b params_backup/ --summary
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def diff_dicts(a: dict, b: dict, path: str = "") -> list[dict]:
    """Recursively diff two dicts. Returns list of change records."""
    changes = []
    all_keys = sorted(set(list(a.keys()) + list(b.keys())))

    for key in all_keys:
        full_path = f"{path}.{key}" if path else key
        va = a.get(key)
        vb = b.get(key)

        if va == vb:
            continue
        if key in a and key not in b:
            changes.append({"path": full_path, "type": "removed", "old": va})
        elif key not in a and key in b:
            changes.append({"path": full_path, "type": "added", "new": vb})
        elif isinstance(va, dict) and isinstance(vb, dict):
            changes.extend(diff_dicts(va, vb, full_path))
        elif isinstance(va, list) and isinstance(vb, list):
            if va != vb:
                changes.append({"path": full_path, "type": "changed", "old": va, "new": vb})
        else:
            changes.append({"path": full_path, "type": "changed", "old": va, "new": vb})

    return changes


def diff_files(path_a: Path, path_b: Path) -> dict:
    """Diff two param JSON files."""
    a = json.loads(path_a.read_text(encoding="utf-8"))
    b = json.loads(path_b.read_text(encoding="utf-8"))
    changes = diff_dicts(a, b)
    return {
        "file_a": str(path_a),
        "file_b": str(path_b),
        "change_count": len(changes),
        "changes": changes,
    }


def diff_dirs(dir_a: Path, dir_b: Path, summary_only: bool = False) -> dict:
    """Diff two param directories."""
    files_a = {f.name for f in dir_a.glob("*.json") if not f.name.startswith("_")}
    files_b = {f.name for f in dir_b.glob("*.json") if not f.name.startswith("_")}

    only_a = files_a - files_b
    only_b = files_b - files_a
    common = files_a & files_b

    per_file = []
    total_changes = 0

    for fname in sorted(common):
        result = diff_files(dir_a / fname, dir_b / fname)
        if result["change_count"] > 0:
            total_changes += result["change_count"]
            if summary_only:
                per_file.append({
                    "file": fname,
                    "changes": result["change_count"],
                    "fields": [c["path"] for c in result["changes"][:5]],
                })
            else:
                per_file.append(result)

    return {
        "dir_a": str(dir_a),
        "dir_b": str(dir_b),
        "only_in_a": sorted(only_a),
        "only_in_b": sorted(only_b),
        "common_files": len(common),
        "files_with_changes": len(per_file),
        "total_changes": total_changes,
        "per_file": per_file,
    }


def main():
    parser = argparse.ArgumentParser(description="Diff param files or directories")
    parser.add_argument("file_a", type=Path, nargs="?", default=None)
    parser.add_argument("file_b", type=Path, nargs="?", default=None)
    parser.add_argument("--dir-a", type=Path, default=None)
    parser.add_argument("--dir-b", type=Path, default=None)
    parser.add_argument("--summary", action="store_true", help="Summary only (no full diffs)")
    parser.add_argument("--json-output", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    if args.dir_a and args.dir_b:
        result = diff_dirs(args.dir_a, args.dir_b, args.summary)
        if args.json_output:
            print(json.dumps(result, indent=2, default=str))
        else:
            print(f"Diff: {result['dir_a']} vs {result['dir_b']}")
            print(f"  Common: {result['common_files']}, Changed: {result['files_with_changes']}")
            print(f"  Only in A: {len(result['only_in_a'])}, Only in B: {len(result['only_in_b'])}")
            print(f"  Total field changes: {result['total_changes']}")
            for pf in result["per_file"][:20]:
                if args.summary:
                    print(f"  {pf['file']}: {pf['changes']} changes ({', '.join(pf['fields'][:3])})")
                else:
                    print(f"\n  {pf.get('file_a', pf.get('file', '?'))}:")
                    for c in pf.get("changes", [])[:10]:
                        if c["type"] == "changed":
                            print(f"    ~ {c['path']}: {c['old']} -> {c['new']}")
                        elif c["type"] == "added":
                            print(f"    + {c['path']}: {c['new']}")
                        elif c["type"] == "removed":
                            print(f"    - {c['path']}")

    elif args.file_a and args.file_b:
        result = diff_files(args.file_a, args.file_b)
        if args.json_output:
            print(json.dumps(result, indent=2, default=str))
        else:
            print(f"Diff: {result['file_a']} vs {result['file_b']}")
            print(f"  {result['change_count']} changes:")
            for c in result["changes"]:
                if c["type"] == "changed":
                    print(f"  ~ {c['path']}: {c['old']} -> {c['new']}")
                elif c["type"] == "added":
                    print(f"  + {c['path']}: {c['new']}")
                elif c["type"] == "removed":
                    print(f"  - {c['path']}")
    else:
        parser.error("Provide two files or --dir-a/--dir-b")


if __name__ == "__main__":
    main()
