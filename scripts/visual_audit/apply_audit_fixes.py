#!/usr/bin/env python3
"""Apply safe, confidence-gated parameter fixes from merged visual-audit report."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REPORT = REPO_ROOT / "outputs" / "visual_audit" / "audit_report_merged.json"
DEFAULT_PARAMS_DIR = REPO_ROOT / "params"
DEFAULT_LOG = REPO_ROOT / "outputs" / "visual_audit" / "fix_log.json"

PROTECTED_PREFIXES = (
    "total_height_m",
    "facade_width_m",
    "facade_depth_m",
    "site.",
    "city_data.",
    "hcd_data.",
)

ALLOWED_CATEGORIES = {"facade_material", "colour_palette", "storefront", "decorative"}
DISALLOWED_CATEGORIES = {"proportions", "windows"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def atomic_write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name, suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def is_protected(path: str) -> bool:
    return any(path == prefix or path.startswith(prefix) for prefix in PROTECTED_PREFIXES)


def _allowed_category(category: str) -> bool:
    if not category:
        return False
    cat = category.lower()
    if cat in DISALLOWED_CATEGORIES:
        return False
    return cat in ALLOWED_CATEGORIES


def _set_nested(payload: dict, dotted_path: str, value):
    parts = dotted_path.split(".")
    cursor = payload
    for key in parts[:-1]:
        if not isinstance(cursor.get(key), dict):
            cursor[key] = {}
        cursor = cursor[key]
    old_value = cursor.get(parts[-1])
    cursor[parts[-1]] = value
    return old_value


def extract_suggestions(building: dict) -> list[dict]:
    gemini = building.get("gemini_analysis")
    if not isinstance(gemini, dict):
        return []
    raw = gemini.get("param_suggestions")
    out = []
    if isinstance(raw, dict):
        # Simple dict form: {"field.path": value}
        if all(isinstance(k, str) for k in raw.keys()):
            for path, value in raw.items():
                out.append(
                    {
                        "path": path,
                        "value": value,
                        "confidence": float(building.get("gemini_confidence") or 0.0),
                        "category": path.split(".", 1)[0],
                    }
                )
    elif isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict):
                path = item.get("path") or item.get("field")
                if not isinstance(path, str):
                    continue
                out.append(
                    {
                        "path": path,
                        "value": item.get("value"),
                        "confidence": float(item.get("confidence") or building.get("gemini_confidence") or 0.0),
                        "category": str(item.get("category") or path.split(".", 1)[0]),
                    }
                )
    return out


def apply_fixes(report: dict, params_dir: Path, dry_run: bool = False) -> dict:
    buildings = report.get("buildings") if isinstance(report, dict) else []
    if not isinstance(buildings, list):
        buildings = []

    log_entries = []
    applied = 0
    skipped = 0

    for building in buildings:
        if not isinstance(building, dict):
            continue
        address = str(building.get("address") or "")
        if not address:
            continue
        suggestions = extract_suggestions(building)
        if not suggestions:
            continue

        param_path = params_dir / f"{address.replace(' ', '_').replace(',', '')}.json"
        if not param_path.exists():
            for suggestion in suggestions:
                skipped += 1
                log_entries.append(
                    {
                        "address": address,
                        "path": suggestion["path"],
                        "status": "skip_missing_param_file",
                        "reason": str(param_path),
                    }
                )
            continue

        params = json.loads(param_path.read_text(encoding="utf-8"))
        touched = False
        applied_items = []

        for suggestion in suggestions:
            path = suggestion["path"]
            confidence = float(suggestion.get("confidence") or 0.0)
            category = str(suggestion.get("category") or "")

            if is_protected(path):
                skipped += 1
                log_entries.append(
                    {"address": address, "path": path, "status": "skip_protected", "confidence": confidence}
                )
                continue
            if confidence < 0.80:
                skipped += 1
                log_entries.append(
                    {"address": address, "path": path, "status": "skip_low_confidence", "confidence": confidence}
                )
                continue
            if not _allowed_category(category):
                skipped += 1
                log_entries.append(
                    {
                        "address": address,
                        "path": path,
                        "status": "skip_disallowed_category",
                        "category": category,
                    }
                )
                continue

            new_value = suggestion.get("value")
            if dry_run:
                # Peek at old value without modifying
                parts = path.split(".")
                cursor = params
                for key in parts:
                    if isinstance(cursor, dict):
                        cursor = cursor.get(key)
                    else:
                        cursor = None
                        break
                old_value = cursor
            else:
                old_value = _set_nested(params, path, new_value)

            if old_value == new_value:
                skipped += 1
                log_entries.append(
                    {"address": address, "path": path, "status": "skip_unchanged", "confidence": confidence}
                )
                continue

            applied += 1
            applied_item = {
                "path": path,
                "old_value": old_value,
                "new_value": new_value,
                "confidence": confidence,
                "category": category,
                "applied_at": _now_iso(),
            }
            applied_items.append(applied_item)
            status = "would_apply" if dry_run else "applied"
            log_entries.append({"address": address, **applied_item, "status": status})
            if not dry_run:
                touched = True

        if touched:
            meta = params.setdefault("_meta", {})
            history = meta.setdefault("audit_fixes_applied", [])
            if not isinstance(history, list):
                history = []
                meta["audit_fixes_applied"] = history
            history.extend(applied_items)
            atomic_write_json(param_path, params)

    return {
        "generated": _now_iso(),
        "total_applied": applied,
        "total_skipped": skipped,
        "entries": log_entries,
    }


def main():
    parser = argparse.ArgumentParser(description="Apply safe visual-audit param fixes.")
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--params-dir", type=Path, default=DEFAULT_PARAMS_DIR)
    parser.add_argument("--log-output", type=Path, default=DEFAULT_LOG)
    parser.add_argument("--dry-run", action="store_true", help="Show what would change without writing")
    args = parser.parse_args()

    report = json.loads(args.report.read_text(encoding="utf-8"))
    result = apply_fixes(report, args.params_dir, dry_run=args.dry_run)
    args.log_output.parent.mkdir(parents=True, exist_ok=True)
    args.log_output.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    mode = "DRY RUN" if args.dry_run else "APPLIED"
    print(
        f"[{mode}] {result['total_applied']} fixes; skipped {result['total_skipped']}. "
        f"Log: {args.log_output}"
    )


if __name__ == "__main__":
    main()
