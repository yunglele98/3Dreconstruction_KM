#!/usr/bin/env python3
"""Apply height corrections from gemini height validation handoff.

Reads handoff findings where total_height_m deviates from GIS massing data
and corrects the param files. Only applies high-confidence corrections.

Usage:
    python scripts/apply_handoff_height_fixes.py --dry-run
    python scripts/apply_handoff_height_fixes.py --apply
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PARAMS_DIR = REPO_ROOT / "params"
HANDOFF = REPO_ROOT / "agent_ops" / "30_handoffs" / "TASK-20260327-017__gemini-1.json"


def find_param_file(address: str, params_dir: Path) -> Path | None:
    """Find a param file matching an address."""
    stem = address.replace(" ", "_")
    candidate = params_dir / f"{stem}.json"
    if candidate.exists():
        return candidate
    # Fuzzy: try without suffix variants
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
    parser = argparse.ArgumentParser(description="Apply height corrections from handoff.")
    parser.add_argument("--handoff", type=Path, default=HANDOFF)
    parser.add_argument("--params", type=Path, default=PARAMS_DIR)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--min-confidence", type=float, default=0.9)
    parser.add_argument("--max-delta-pct", type=float, default=50,
                        help="Skip if correction would change height by more than this %")
    args = parser.parse_args()

    if not args.apply and not args.dry_run:
        print("Specify --dry-run or --apply")
        return

    data = json.loads(args.handoff.read_text(encoding="utf-8"))
    findings = data.get("findings", [])

    height_findings = [f for f in findings
                       if f.get("field") == "total_height_m"
                       and f.get("confidence", 0) >= args.min_confidence
                       and f.get("expected") is not None]

    print(f"Height findings: {len(height_findings)} (of {len(findings)} total)")

    applied = 0
    skipped = 0
    not_found = 0

    for finding in height_findings:
        address = finding["address"]
        expected = float(finding["expected"])
        actual = float(finding.get("actual", 0))

        if expected <= 0:
            skipped += 1
            continue

        # Skip extreme corrections
        if actual > 0:
            delta_pct = abs(expected - actual) / actual * 100
            if delta_pct > args.max_delta_pct:
                skipped += 1
                continue

        pf = find_param_file(address, args.params)
        if not pf:
            not_found += 1
            continue

        params = json.loads(pf.read_text(encoding="utf-8"))
        current_h = params.get("total_height_m", 0) or 0

        # Only fix if current height matches the "actual" from the finding
        # (otherwise the param has already been corrected by another process)
        if abs(current_h - actual) > 0.5:
            skipped += 1
            continue

        # Apply correction
        params["total_height_m"] = expected
        floors = params.get("floors", 1) or 1
        fh = [expected / floors] * floors
        params["floor_heights_m"] = fh

        meta = params.setdefault("_meta", {})
        applied_list = meta.setdefault("handoff_fixes", [])
        applied_list.append(f"height_from_gis:{expected}")

        if args.apply:
            content = json.dumps(params, indent=2, ensure_ascii=False) + "\n"
            fd, tmp = tempfile.mkstemp(dir=pf.parent, suffix=".tmp")
            os.write(fd, content.encode("utf-8"))
            os.close(fd)
            os.replace(tmp, str(pf))

        applied += 1
        if applied <= 10:
            print(f"  {address}: {actual} -> {expected} m")

    mode = "APPLIED" if args.apply else "DRY-RUN"
    print(f"\n[{mode}] Applied: {applied}, Skipped: {skipped}, Not found: {not_found}")


if __name__ == "__main__":
    main()
