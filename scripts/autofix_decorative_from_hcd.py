#!/usr/bin/env python3
"""Autofix decorative elements gap by cross-referencing HCD building_features.

Parses hcd_data.building_features and hcd_data.statement_of_contribution for
decorative element keywords and creates missing decorative_elements entries.
Only adds elements that don't already exist.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
PARAMS_DIR = REPO_ROOT / "params"
OUT_DIR = REPO_ROOT / "outputs"

# Keyword → decorative element template
# Each entry: (regex_pattern, element_key, default_value)
KEYWORD_MAP: list[tuple[str, str, dict]] = [
    (r"decorative.?brick", "decorative_brickwork", {"present": True}),
    (r"string.?course", "string_courses", {
        "present": True, "width_mm": 100, "projection_mm": 30,
    }),
    (r"quoin", "quoins", {
        "present": True, "strip_width_mm": 200, "projection_mm": 30,
    }),
    (r"voussoir", "stone_voussoirs", {"present": True}),
    (r"cornice", "cornice", {
        "present": True, "projection_mm": 150, "height_mm": 200,
    }),
    (r"bargeboard", "bargeboard", {
        "present": True, "style": "ornate",
    }),
    (r"bracket", "gable_brackets", {
        "type": "scroll", "count": 2, "projection_mm": 100,
    }),
    (r"shingle", "ornamental_shingles", {"present": True}),
    (r"polychromatic", "polychromatic_brick", {"present": True}),
    (r"dentil", "dentil_course", {"present": True}),
    (r"keystone", "keystones", {"present": True}),
    (r"lintel", "stone_lintels", {"present": True}),
    (r"pilaster", "pilasters", {"present": True}),
    (r"parapet", "decorative_parapet", {"present": True}),
    (r"transom", "decorative_transoms", {"present": True}),
]


def _get_hcd_text(params: dict) -> str:
    """Collect all searchable HCD text into a single lowercase string."""
    hcd = params.get("hcd_data")
    if not isinstance(hcd, dict):
        return ""

    parts: list[str] = []

    # building_features (list of strings)
    features = hcd.get("building_features")
    if isinstance(features, list):
        parts.extend(str(f) for f in features)
    elif isinstance(features, str):
        parts.append(features)

    # statement_of_contribution (string)
    soc = hcd.get("statement_of_contribution")
    if isinstance(soc, str):
        parts.append(soc)

    # Also check building_features as a comma-separated field
    arch_style = hcd.get("architectural_style")
    if isinstance(arch_style, str):
        parts.append(arch_style)

    return " ".join(parts).lower()


def atomic_write(path: Path, data: dict) -> None:
    """Write JSON atomically via temp file + os.replace."""
    content = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        os.write(fd, content.encode("utf-8"))
        os.close(fd)
        os.replace(tmp, path)
    except Exception:
        os.close(fd) if not os.get_inheritable(fd) else None
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def process_file(path: Path, apply: bool) -> dict:
    """Process a single param file. Returns change record."""
    data = json.loads(path.read_text(encoding="utf-8"))

    if data.get("skipped"):
        return {"file": path.name, "status": "skipped", "reason": "skipped_file"}

    hcd_text = _get_hcd_text(data)
    if not hcd_text:
        return {"file": path.name, "status": "skipped", "reason": "no_hcd_data"}

    # Ensure decorative_elements dict exists
    dec = data.get("decorative_elements")
    if not isinstance(dec, dict):
        dec = {}
        data["decorative_elements"] = dec

    changes: list[dict] = []
    for pattern, element_key, default_val in KEYWORD_MAP:
        if re.search(pattern, hcd_text) and element_key not in dec:
            dec[element_key] = dict(default_val)  # copy
            changes.append({
                "field": f"decorative_elements.{element_key}",
                "old_value": "(absent)",
                "new_value": default_val,
                "keyword_matched": pattern,
                "source": "hcd_data.building_features/statement_of_contribution",
            })

    if not changes:
        return {"file": path.name, "status": "skipped", "reason": "no_new_elements"}

    # Record in _meta
    meta = data.get("_meta") if isinstance(data.get("_meta"), dict) else {}
    data["_meta"] = meta
    dec_list = meta.get("autofix_decorative_applied", [])
    dec_list.append({
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "script": "autofix_decorative_from_hcd",
        "elements_added": len(changes),
        "elements": [c["field"] for c in changes],
    })
    meta["autofix_decorative_applied"] = dec_list

    if apply:
        atomic_write(path, data)

    address = (meta.get("address") or path.stem.replace("_", " "))
    return {
        "file": path.name,
        "address": address,
        "status": "changed",
        "changes": changes,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Autofix decorative elements from HCD building_features"
    )
    parser.add_argument("--params", default=str(PARAMS_DIR),
                        help="Path to params directory")
    parser.add_argument("--dry-run", action="store_true",
                        help="Report what would change without writing")
    parser.add_argument("--apply", action="store_true",
                        help="Actually write changes to param files")
    parser.add_argument("--report", default=None,
                        help="Path for output report JSON")
    args = parser.parse_args()

    params_dir = Path(args.params)
    apply = args.apply and not args.dry_run

    param_files = sorted(
        p for p in params_dir.glob("*.json")
        if not p.name.startswith("_")
    )

    results: list[dict] = []
    for pf in param_files:
        result = process_file(pf, apply)
        results.append(result)

    changed = [r for r in results if r["status"] == "changed"]
    skipped = [r for r in results if r["status"] == "skipped"]

    # Per-element stats
    element_stats: dict[str, int] = {}
    for r in changed:
        for c in r.get("changes", []):
            element_stats[c["field"]] = element_stats.get(c["field"], 0) + 1

    summary = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "mode": "apply" if apply else "dry-run",
        "params_dir": str(params_dir.resolve()),
        "total_files": len(param_files),
        "changed_count": len(changed),
        "skipped_count": len(skipped),
        "total_elements_added": sum(element_stats.values()),
        "element_stats": dict(sorted(element_stats.items(), key=lambda x: -x[1])),
        "changed_files": changed,
        "skipped_files": skipped,
    }

    report_path = Path(args.report) if args.report else (
        OUT_DIR / f"autofix_decorative_report_{time.strftime('%Y%m%d_%H%M%S')}.json"
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    print("=== Autofix Decorative From HCD ===")
    print(f"Mode:           {summary['mode']}")
    print(f"Files:          {summary['total_files']}")
    print(f"Changed:        {summary['changed_count']}")
    print(f"Skipped:        {summary['skipped_count']}")
    print(f"Elements added: {summary['total_elements_added']}")
    print(f"--- Per-element additions ---")
    for elem, count in sorted(element_stats.items(), key=lambda x: -x[1]):
        print(f"  {elem}: {count}")
    print(f"Report:         {report_path}")


if __name__ == "__main__":
    main()
