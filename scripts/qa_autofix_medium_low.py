#!/usr/bin/env python3
"""Autofix medium/low QA issues from qa_fail_list report.

Fixes:
- medium: floor_height_sum_mismatch -> rebalance floor_heights_m to total_height_m
- low: storefront_conflict -> align has_storefront with DB signal
"""

from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PARAMS_DIR = ROOT / "params"
OUT_DIR = ROOT / "outputs"


def coerce_float(v: Any) -> float | None:
    try:
        if v is None or v == "":
            return None
        return float(v)
    except Exception:
        return None


def rebalance(total_h: float, n: int) -> list[float]:
    n = max(1, int(n))
    if n == 1:
        return [round(total_h, 2)]
    base = round(total_h / n, 2)
    vals = [base] * n
    vals[-1] = round(total_h - sum(vals[:-1]), 2)
    return vals


def parse_storefront_reason(reason: str) -> bool | None:
    # storefront_conflict:param=True,db=False
    m = re.match(r"storefront_conflict:param=(True|False),db=(True|False)", reason)
    if not m:
        return None
    return True if m.group(2) == "True" else False


def main() -> None:
    parser = argparse.ArgumentParser(description="Autofix medium/low QA failures")
    parser.add_argument("--qa-report", required=True, help="Path to qa_fail_list_*.json")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    apply = bool(args.apply)

    qa = json.loads(Path(args.qa_report).read_text(encoding="utf-8"))
    failed = qa.get("failed_files", [])

    changed = []
    skipped = []

    for row in failed:
        sev = row.get("severity")
        if sev not in {"medium", "low"}:
            continue
        file = row["file"]
        p = PARAMS_DIR / file
        if not p.exists():
            skipped.append({"file": file, "reason": "missing_file"})
            continue
        d = json.loads(p.read_text(encoding="utf-8"))
        reasons = row.get("reasons", [])
        local_changes = []

        if any(str(r).startswith("floor_height_sum_mismatch") for r in reasons):
            total_h = coerce_float(d.get("total_height_m"))
            fh = d.get("floor_heights_m")
            if total_h and isinstance(fh, list) and len(fh) > 0:
                d["floor_heights_m"] = rebalance(total_h, len(fh))
                local_changes.append("floor_heights_m:rebalance_to_total")
            else:
                skipped.append({"file": file, "reason": "cannot_rebalance_floor_heights"})

        sf_reason = next((r for r in reasons if str(r).startswith("storefront_conflict")), None)
        if sf_reason:
            db_sf = parse_storefront_reason(str(sf_reason))
            if db_sf is not None:
                d["has_storefront"] = db_sf
                local_changes.append(f"has_storefront:set_{db_sf}")
            else:
                skipped.append({"file": file, "reason": "storefront_reason_parse_failed"})

        if local_changes:
            meta = d.get("_meta") if isinstance(d.get("_meta"), dict) else {}
            d["_meta"] = meta
            meta["qa_autofix_medium_low"] = {
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "changes": local_changes,
            }
            if apply:
                p.write_text(json.dumps(d, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            changed.append({"file": file, "changes": local_changes})

    summary = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "mode": "apply" if apply else "dry-run",
        "qa_report": str(Path(args.qa_report).resolve()),
        "changed_count": len(changed),
        "skipped_count": len(skipped),
        "changed_files": changed,
        "skipped": skipped,
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"qa_autofix_medium_low_{time.strftime('%Y%m%d_%H%M%S')}.json"
    out.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print("=== QA Autofix Medium/Low ===")
    print(f"Mode: {summary['mode']}")
    print(f"Changed: {summary['changed_count']}")
    print(f"Skipped: {summary['skipped_count']}")
    print(f"Report: {out}")


if __name__ == "__main__":
    main()
