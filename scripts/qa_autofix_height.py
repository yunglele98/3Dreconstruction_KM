#!/usr/bin/env python3
"""Autofix high-severity QA issues for height-per-floor consistency.

Policy:
- Target only files failing `height_per_floor_out_of_range`.
- Keep `floors` unchanged.
- Adjust `total_height_m` into [2.4, 4.8] * floors.
- Rebalance `floor_heights_m` to sum exactly to new `total_height_m`.
"""

from __future__ import annotations

import argparse
import json
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


def rebalance_floor_heights(total_h: float, n: int) -> list[float]:
    n = max(1, int(n))
    if n == 1:
        return [round(total_h, 2)]
    base = round(total_h / n, 2)
    vals = [base] * n
    vals[-1] = round(total_h - sum(vals[:-1]), 2)
    return vals


def main() -> None:
    parser = argparse.ArgumentParser(description="Autofix height-per-floor QA failures")
    parser.add_argument("--qa-report", required=True, help="Path to qa_fail_list_*.json")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    apply = bool(args.apply)

    qa_path = Path(args.qa_report)
    qa = json.loads(qa_path.read_text(encoding="utf-8"))
    failed = qa.get("failed_files", [])

    targets = []
    for f in failed:
        if f.get("severity") != "high":
            continue
        reasons = f.get("reasons", [])
        if any(str(r).startswith("height_per_floor_out_of_range") for r in reasons):
            targets.append(f)

    changed = []
    skipped = []
    for t in targets:
        p = PARAMS_DIR / t["file"]
        if not p.exists():
            skipped.append({"file": t["file"], "reason": "missing_file"})
            continue
        d = json.loads(p.read_text(encoding="utf-8"))
        floors = coerce_float(d.get("floors"))
        total_h = coerce_float(d.get("total_height_m"))
        if floors is None or floors <= 0 or total_h is None or total_h <= 0:
            skipped.append({"file": t["file"], "reason": "invalid_floors_or_height"})
            continue

        min_h = 2.4 * floors
        max_h = 4.8 * floors
        new_total = total_h
        if total_h < min_h:
            new_total = round(min_h, 2)
        elif total_h > max_h:
            new_total = round(max_h, 2)
        else:
            skipped.append({"file": t["file"], "reason": "already_in_range"})
            continue

        new_fh = rebalance_floor_heights(new_total, int(round(floors)))
        d["total_height_m"] = new_total
        d["floor_heights_m"] = new_fh

        meta = d.get("_meta") if isinstance(d.get("_meta"), dict) else {}
        d["_meta"] = meta
        meta["qa_autofix_height"] = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "old_total_height_m": total_h,
            "new_total_height_m": new_total,
            "floors": floors,
            "rule": "total_height_m in [2.4, 4.8] * floors",
        }

        if apply:
            p.write_text(json.dumps(d, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

        changed.append(
            {
                "file": t["file"],
                "old_total_height_m": total_h,
                "new_total_height_m": new_total,
                "floors": floors,
            }
        )

    summary = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "mode": "apply" if apply else "dry-run",
        "qa_report": str(qa_path.resolve()),
        "targets": len(targets),
        "changed_count": len(changed),
        "skipped_count": len(skipped),
        "changed_files": changed,
        "skipped": skipped,
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"qa_autofix_height_{time.strftime('%Y%m%d_%H%M%S')}.json"
    out.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print("=== QA Autofix Height ===")
    print(f"Mode: {summary['mode']}")
    print(f"Targets: {summary['targets']}")
    print(f"Changed: {summary['changed_count']}")
    print(f"Skipped: {summary['skipped_count']}")
    print(f"Report: {out}")


if __name__ == "__main__":
    main()
