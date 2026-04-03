#!/usr/bin/env python3
"""Stage 10 — MONITOR: Sprint progress tracker.

Reads the coverage matrix and test counts to report progress against
the 3-week sprint targets. Day 1 = April 2, 2026.

Usage:
    python scripts/monitor/sprint_progress.py              # human-readable
    python scripts/monitor/sprint_progress.py --json        # JSON output
"""

import argparse
import json
import sys
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
SPRINT_START = date(2026, 4, 2)
SPRINT_DAYS = 21

# Cumulative targets per sprint day
# Keys: renders, tests, fbx_exported, depth_fused, seg_fused, colmap_blocks,
#        scenarios_computed, web_deployed
DAY_TARGETS = {
    1: {
        "tests": 1700,
        "renders": 500,
    },
    2: {
        "tests": 1720,
        "renders": 800,
        "depth_fused": 200,
    },
    3: {
        "tests": 1730,
        "renders": 1000,
        "depth_fused": 500,
        "seg_fused": 200,
    },
    4: {
        "tests": 1740,
        "renders": 1064,
        "depth_fused": 800,
        "seg_fused": 500,
    },
    5: {
        "tests": 1750,
        "renders": 1064,
        "depth_fused": 1000,
        "seg_fused": 800,
        "fbx_exported": 200,
    },
    6: {
        "tests": 1760,
        "renders": 1064,
        "depth_fused": 1064,
        "seg_fused": 1000,
        "fbx_exported": 500,
    },
    7: {
        "tests": 1770,
        "renders": 1064,
        "depth_fused": 1064,
        "seg_fused": 1064,
        "fbx_exported": 800,
        "colmap_blocks": 2,
    },
    8: {
        "tests": 1780,
        "fbx_exported": 900,
        "colmap_blocks": 4,
    },
    9: {
        "tests": 1790,
        "fbx_exported": 1000,
        "colmap_blocks": 6,
    },
    10: {
        "tests": 1800,
        "fbx_exported": 1064,
        "colmap_blocks": 8,
    },
    11: {
        "tests": 1810,
        "colmap_blocks": 10,
        "scenarios_computed": 1,
    },
    12: {
        "tests": 1820,
        "colmap_blocks": 12,
        "scenarios_computed": 3,
    },
    13: {
        "tests": 1830,
        "colmap_blocks": 14,
        "scenarios_computed": 5,
    },
    14: {
        "tests": 1840,
        "scenarios_computed": 5,
        "web_deployed": True,
    },
    15: {
        "tests": 1850,
        "web_deployed": True,
    },
    16: {
        "tests": 1860,
    },
    17: {
        "tests": 1870,
    },
    18: {
        "tests": 1880,
    },
    19: {
        "tests": 1890,
    },
    20: {
        "tests": 1900,
    },
    21: {
        "tests": 1961,
    },
}


def get_actuals() -> dict:
    """Read current actuals from coverage matrix and filesystem."""
    actuals = {}

    # Coverage matrix
    cm_path = REPO / "outputs" / "coverage_matrix.json"
    if cm_path.exists():
        cm = json.loads(cm_path.read_text(encoding="utf-8"))
        summary = cm.get("summary", {})

        if "rendered" in summary:
            actuals["renders"] = summary["rendered"].get("count", 0)
        if "blended" in summary:
            actuals["blended"] = summary["blended"].get("count", 0)
        if "depth_fused" in summary:
            actuals["depth_fused"] = summary["depth_fused"].get("count", 0)
        if "seg_fused" in summary:
            actuals["seg_fused"] = summary["seg_fused"].get("count", 0)
        if "sig_fused" in summary:
            actuals["sig_fused"] = summary["sig_fused"].get("count", 0)
        if "exported" in summary:
            actuals["fbx_exported"] = summary["exported"].get("count", 0)

    # Test count
    tests_dir = REPO / "tests"
    if tests_dir.is_dir():
        actuals["test_files"] = len(list(tests_dir.glob("test_*.py")))

    return actuals


def classify_status(target, actual) -> str:
    """Classify progress as on_track, behind, or ahead."""
    if isinstance(target, bool):
        if actual == target:
            return "on_track"
        return "behind" if target else "ahead"

    if actual >= target * 1.1:
        return "ahead"
    elif actual >= target:
        return "on_track"
    return "behind"


def generate_report(sprint_day: int, today: date) -> dict:
    """Generate the sprint progress report."""
    targets = DAY_TARGETS.get(sprint_day, {})
    actuals = get_actuals()

    status_entries = []
    for metric, target in targets.items():
        actual = actuals.get(metric, 0)
        status_entries.append({
            "metric": metric,
            "target": target,
            "actual": actual,
            "status": classify_status(target, actual),
        })

    return {
        "sprint_day": sprint_day,
        "date": today.isoformat(),
        "sprint_start": SPRINT_START.isoformat(),
        "targets": targets,
        "actuals": actuals,
        "status": status_entries,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Sprint progress tracker")
    parser.add_argument("--json", action="store_true", help="JSON output")
    args = parser.parse_args()

    today = date.today()
    sprint_day = (today - SPRINT_START).days + 1

    if sprint_day < 1 or sprint_day > SPRINT_DAYS:
        if args.json:
            print(json.dumps({"error": f"Outside sprint window (day {sprint_day})"}))
        else:
            print(f"Outside sprint window: day {sprint_day}")
        return

    report = generate_report(sprint_day, today)

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"Sprint Day {report['sprint_day']} ({report['date']})")
        print("=" * 50)
        for entry in report["status"]:
            icon = {"on_track": "OK", "ahead": "++", "behind": "!!"}[entry["status"]]
            print(f"  [{icon}] {entry['metric']}: {entry['actual']}/{entry['target']} ({entry['status']})")
        print()
        behind = [e for e in report["status"] if e["status"] == "behind"]
        if behind:
            print(f"  {len(behind)} metric(s) behind target")
        else:
            print("  All metrics on track or ahead")


if __name__ == "__main__":
    main()
