#!/usr/bin/env python3
"""
Fix inflated total_height_m values from agent handoff TASK-20260327-017.

Reads findings from the handoff JSON where GIS massing height disagrees with
the current param value. Resets total_height_m to the GIS "expected" value
and redistributes floor_heights_m proportionally to preserve existing ratios.

Dry-run by default; pass --apply to write changes.
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PARAMS_DIR = ROOT / "params"
HANDOFF_FILE = ROOT / "agent_ops" / "30_handoffs" / "TASK-20260327-017__gemini-1.json"

TOLERANCE = 0.05  # metres — skip if already within tolerance


def address_to_filename(address: str) -> str:
    """Convert an address string to the expected param filename."""
    return address.replace(" ", "_") + ".json"


def load_handoff(path: Path) -> list:
    """Load findings from the handoff JSON."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return data.get("findings", [])


def redistribute_floor_heights(floor_heights: list, new_total: float) -> list:
    """Redistribute floor heights proportionally so they sum to new_total."""
    old_total = sum(floor_heights)
    if old_total <= 0:
        # Uniform distribution fallback
        n = len(floor_heights)
        if n == 0:
            return []
        h = round(new_total / n, 2)
        heights = [h] * n
        # Adjust last floor for rounding
        heights[-1] = round(new_total - sum(heights[:-1]), 2)
        return heights

    ratio = new_total / old_total
    heights = [round(h * ratio, 2) for h in floor_heights]
    # Fix rounding drift on the last floor
    heights[-1] = round(new_total - sum(heights[:-1]), 2)
    return heights


def process(apply: bool = False) -> None:
    findings = load_handoff(HANDOFF_FILE)
    print(f"Loaded {len(findings)} findings from {HANDOFF_FILE.name}")

    stats = {"applied": 0, "skipped_match": 0, "skipped_missing": 0, "errors": 0}

    for finding in findings:
        address = finding.get("address", "")
        field = finding.get("field", "")
        expected = finding.get("expected")
        status = finding.get("status", "")

        # Only process total_height_m modifications
        if field != "total_height_m" or status != "modified":
            continue

        filename = address_to_filename(address)
        param_path = PARAMS_DIR / filename

        if not param_path.exists():
            print(f"  SKIP (file not found): {filename}")
            stats["skipped_missing"] += 1
            continue

        with open(param_path, encoding="utf-8") as f:
            params = json.load(f)

        current_height = params.get("total_height_m")
        if current_height is None:
            print(f"  SKIP (no total_height_m): {filename}")
            stats["skipped_missing"] += 1
            continue

        # Skip if already within tolerance
        if abs(current_height - expected) <= TOLERANCE:
            print(f"  SKIP (within tolerance): {filename}  current={current_height}  expected={expected}")
            stats["skipped_match"] += 1
            continue

        # Compute new floor heights
        floor_heights = params.get("floor_heights_m", [])
        new_floor_heights = redistribute_floor_heights(floor_heights, expected)

        action = "APPLY" if apply else "DRY-RUN"
        print(f"  {action}: {filename}  total_height_m {current_height} -> {expected}"
              f"  floors: {floor_heights} -> {new_floor_heights}")

        if apply:
            params["total_height_m"] = expected
            if new_floor_heights:
                params["floor_heights_m"] = new_floor_heights

            # Stamp _meta
            meta = params.setdefault("_meta", {})
            fixes = meta.setdefault("handoff_fixes_applied", [])
            fixes.append({
                "fix": "fix_height_from_handoff",
                "task_id": "TASK-20260327-017",
                "field": "total_height_m",
                "old_value": current_height,
                "new_value": expected,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

            with open(param_path, "w", encoding="utf-8") as f:
                json.dump(params, f, indent=2, ensure_ascii=False)
                f.write("\n")

        stats["applied"] += 1

    print(f"\nSummary: {stats['applied']} {'applied' if apply else 'would apply'}, "
          f"{stats['skipped_match']} already match, "
          f"{stats['skipped_missing']} missing files, "
          f"{stats['errors']} errors")


def main():
    parser = argparse.ArgumentParser(description="Fix inflated total_height_m from handoff findings")
    parser.add_argument("--apply", action="store_true", help="Write changes (default: dry-run)")
    args = parser.parse_args()
    process(apply=args.apply)


if __name__ == "__main__":
    main()
