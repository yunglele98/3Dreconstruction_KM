#!/usr/bin/env python3
"""Apply material corrections from gemini material reconciliation handoff.

Only applies changes where the photo observation material is more specific
than the current param value (e.g. "mixed" -> "brick" or "clapboard" -> "vinyl_siding").

Usage:
    python scripts/apply_handoff_material_fixes.py --dry-run
    python scripts/apply_handoff_material_fixes.py --apply
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PARAMS_DIR = REPO_ROOT / "params"
HANDOFF = REPO_ROOT / "agent_ops" / "30_handoffs" / "TASK-20260327-MATERIAL-AUDIT__gemini-1.json"

# Materials ordered by specificity (more specific = higher priority)
MATERIAL_PRIORITY = {
    "brick": 5,
    "stone": 5,
    "concrete": 4,
    "stucco": 4,
    "clapboard": 4,
    "vinyl_siding": 3,
    "vinyl siding": 3,
    "glass": 3,
    "mixed masonry": 2,
    "mixed": 1,
    "": 0,
}


def find_param_file(address: str, params_dir: Path) -> Path | None:
    stem = address.replace(" ", "_")
    candidate = params_dir / f"{stem}.json"
    if candidate.exists():
        return candidate
    for f in params_dir.glob("*.json"):
        if f.name.startswith("_"):
            continue
        try:
            p = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if p.get("_meta", {}).get("address") == address:
            return f
    return None


def main():
    parser = argparse.ArgumentParser(description="Apply material corrections from handoff.")
    parser.add_argument("--handoff", type=Path, default=HANDOFF)
    parser.add_argument("--params", type=Path, default=PARAMS_DIR)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--min-confidence", type=float, default=0.7)
    args = parser.parse_args()

    if not args.apply and not args.dry_run:
        print("Specify --dry-run or --apply")
        return

    data = json.loads(args.handoff.read_text(encoding="utf-8"))
    findings = [f for f in data.get("findings", [])
                if f.get("field") == "facade_material"
                and f.get("confidence", 0) >= args.min_confidence]

    print(f"Material findings: {len(findings)}")

    applied = 0
    skipped = 0
    not_found = 0

    for finding in findings:
        address = finding["address"]
        expected = (finding.get("expected") or "").strip().lower()
        actual = (finding.get("actual") or "").strip().lower()

        if not expected or expected == actual:
            skipped += 1
            continue

        # Only upgrade specificity (don't replace "brick" with "mixed")
        exp_pri = MATERIAL_PRIORITY.get(expected, 2)
        act_pri = MATERIAL_PRIORITY.get(actual, 2)
        if exp_pri <= act_pri:
            skipped += 1
            continue

        pf = find_param_file(address, args.params)
        if not pf:
            not_found += 1
            continue

        params = json.loads(pf.read_text(encoding="utf-8"))
        current = (params.get("facade_material") or "").strip().lower()

        # Only fix if current matches the "actual" (not already corrected)
        if current != actual:
            skipped += 1
            continue

        params["facade_material"] = expected
        meta = params.setdefault("_meta", {})
        fixes = meta.setdefault("handoff_fixes", [])
        fixes.append(f"material:{actual}->{expected}")

        if args.apply:
            content = json.dumps(params, indent=2, ensure_ascii=False) + "\n"
            fd, tmp = tempfile.mkstemp(dir=pf.parent, suffix=".tmp")
            os.write(fd, content.encode("utf-8"))
            os.close(fd)
            os.replace(tmp, str(pf))

        applied += 1
        if applied <= 10:
            print(f"  {address}: {actual} -> {expected}")

    mode = "APPLIED" if args.apply else "DRY-RUN"
    print(f"\n[{mode}] Applied: {applied}, Skipped: {skipped}, Not found: {not_found}")


if __name__ == "__main__":
    main()
