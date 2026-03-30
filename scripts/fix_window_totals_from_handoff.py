#!/usr/bin/env python3
"""
Fix window count mismatches from agent handoff TASK-20260327-016.

Reads findings where photo_observations total window count disagrees with the
windows_detail sum. Updates per-floor window counts using photo_observations
windows_per_floor if available, otherwise redistributes the expected total
proportionally across floors.

Skips city_data findings (log only).
Dry-run by default; pass --apply to write changes.
"""
import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PARAMS_DIR = ROOT / "params"
HANDOFF_FILE = ROOT / "agent_ops" / "30_handoffs" / "TASK-20260327-016__gemini-1.json"

FLOOR_LABELS = [
    "Ground floor", "Second floor", "Third floor", "Fourth floor",
    "Fifth floor", "Sixth floor",
]


def address_to_filename(address: str) -> str:
    """Convert an address string to the expected param filename."""
    return address.replace(" ", "_") + ".json"


def load_handoff(path: Path) -> list:
    """Load findings from the handoff JSON."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return data.get("findings", [])


def redistribute_windows(expected_total: int, num_floors: int, existing_counts: list) -> list:
    """Redistribute expected total windows across floors proportionally.

    Uses existing per-floor ratios if available, otherwise distributes evenly.
    """
    if num_floors <= 0:
        return []

    old_total = sum(existing_counts) if existing_counts else 0

    if old_total > 0 and len(existing_counts) == num_floors:
        # Proportional redistribution preserving ratios
        ratios = [c / old_total for c in existing_counts]
        new_counts = [max(0, round(expected_total * r)) for r in ratios]
        # Fix rounding: adjust the floor with the largest ratio
        diff = expected_total - sum(new_counts)
        if diff != 0:
            max_idx = ratios.index(max(ratios))
            new_counts[max_idx] = max(0, new_counts[max_idx] + diff)
        return new_counts
    else:
        # Even distribution
        base = expected_total // num_floors
        remainder = expected_total % num_floors
        counts = [base] * num_floors
        # Give remainder to upper floors first
        for i in range(1, remainder + 1):
            idx = min(i, num_floors - 1)
            counts[idx] += 1
        return counts


def update_windows_detail(params: dict, new_counts: list) -> None:
    """Update windows_detail per-floor window counts."""
    windows_detail = params.get("windows_detail", [])
    num_floors = params.get("floors", len(new_counts))

    if not windows_detail:
        # Create windows_detail from scratch
        params["windows_detail"] = []
        for i, count in enumerate(new_counts):
            label = FLOOR_LABELS[i] if i < len(FLOOR_LABELS) else f"Floor {i + 1}"
            params["windows_detail"].append({
                "floor": label,
                "windows": [{"count": count}] if count > 0 else [],
            })
        return

    # Update existing windows_detail entries
    for i, count in enumerate(new_counts):
        if i < len(windows_detail):
            floor_entry = windows_detail[i]
            windows_list = floor_entry.get("windows", [])
            if windows_list:
                # Update the count on the first window spec
                windows_list[0]["count"] = count
            elif count > 0:
                floor_entry["windows"] = [{"count": count}]
        else:
            # Add a new floor entry
            label = FLOOR_LABELS[i] if i < len(FLOOR_LABELS) else f"Floor {i + 1}"
            windows_detail.append({
                "floor": label,
                "windows": [{"count": count}] if count > 0 else [],
            })

    # Also update the top-level windows_per_floor array
    params["windows_per_floor"] = new_counts


def process(apply: bool = False) -> None:
    findings = load_handoff(HANDOFF_FILE)
    print(f"Loaded {len(findings)} findings from {HANDOFF_FILE.name}")

    stats = {"applied": 0, "skipped_city_data": 0, "skipped_missing": 0, "skipped_other": 0}

    for finding in findings:
        address = finding.get("address", "")
        field = finding.get("field", "")
        expected = finding.get("expected")
        status = finding.get("status", "")

        # Skip city_data findings (log only)
        if field == "city_data":
            print(f"  LOG ONLY (city_data): {address} — {finding.get('note', '')}")
            stats["skipped_city_data"] += 1
            continue

        # Only process windows_detail.count mismatches
        if field != "windows_detail.count" or status != "mismatch":
            stats["skipped_other"] += 1
            continue

        filename = address_to_filename(address)
        param_path = PARAMS_DIR / filename

        if not param_path.exists():
            print(f"  SKIP (file not found): {filename}")
            stats["skipped_missing"] += 1
            continue

        with open(param_path, encoding="utf-8") as f:
            params = json.load(f)

        num_floors = params.get("floors", 2)
        expected_total = int(expected)

        # Try to use photo_observations.windows_per_floor
        photo_obs = params.get("photo_observations", {})
        photo_wpf = photo_obs.get("windows_per_floor")

        if photo_wpf and isinstance(photo_wpf, list) and sum(photo_wpf) == expected_total:
            new_counts = photo_wpf
            source = "photo_observations.windows_per_floor"
        else:
            # Get existing per-floor counts from windows_detail
            existing_counts = []
            for floor_entry in params.get("windows_detail", []):
                floor_total = sum(
                    w.get("count", 0) for w in floor_entry.get("windows", [])
                )
                existing_counts.append(floor_total)

            new_counts = redistribute_windows(expected_total, num_floors, existing_counts)
            source = "proportional redistribution"

        # Get current counts for display
        current_wpf = params.get("windows_per_floor", [])
        action = "APPLY" if apply else "DRY-RUN"
        print(f"  {action}: {filename}  windows total {finding.get('actual')} -> {expected_total}"
              f"  per-floor: {current_wpf} -> {new_counts}  ({source})")

        if apply:
            update_windows_detail(params, new_counts)

            # Stamp _meta
            meta = params.setdefault("_meta", {})
            fixes = meta.setdefault("handoff_fixes_applied", [])
            fixes.append({
                "fix": "fix_window_totals_from_handoff",
                "task_id": "TASK-20260327-016",
                "field": "windows_detail.count",
                "old_total": finding.get("actual"),
                "new_total": expected_total,
                "new_per_floor": new_counts,
                "source": source,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

            with open(param_path, "w", encoding="utf-8") as f:
                json.dump(params, f, indent=2, ensure_ascii=False)
                f.write("\n")

        stats["applied"] += 1

    print(f"\nSummary: {stats['applied']} {'applied' if apply else 'would apply'}, "
          f"{stats['skipped_city_data']} city_data (log only), "
          f"{stats['skipped_missing']} missing files, "
          f"{stats['skipped_other']} non-window findings skipped")


def main():
    parser = argparse.ArgumentParser(description="Fix window count totals from handoff findings")
    parser.add_argument("--apply", action="store_true", help="Write changes (default: dry-run)")
    args = parser.parse_args()
    process(apply=args.apply)


if __name__ == "__main__":
    main()
