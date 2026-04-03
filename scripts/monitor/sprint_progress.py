#!/usr/bin/env python3
"""Sprint progress tracker — reports actuals vs targets per sprint day.

Reads coverage_matrix.json and test counts to report daily progress
against the 3-week sprint plan.

Usage:
    python scripts/monitor/sprint_progress.py
    python scripts/monitor/sprint_progress.py --json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
SPRINT_START = date(2026, 4, 2)

# Targets per sprint day (cumulative)
DAY_TARGETS = {
    1: {"tests": 90, "renders": 50, "params_enriched": 1050},
    2: {"tests": 92, "renders": 200, "params_enriched": 1050, "depth_fused": 100},
    3: {"tests": 93, "renders": 400, "depth_fused": 300, "seg_fused": 100},
    4: {"tests": 93, "renders": 600, "depth_fused": 500, "seg_fused": 300},
    5: {"tests": 95, "renders": 800, "depth_fused": 800, "seg_fused": 600},
    6: {"tests": 95, "renders": 900, "depth_fused": 1000, "seg_fused": 800},
    7: {"tests": 95, "renders": 1000, "depth_fused": 1050, "seg_fused": 1000, "fbx_exported": 200},
    8: {"tests": 96, "renders": 1050, "fbx_exported": 400},
    9: {"tests": 96, "renders": 1050, "fbx_exported": 600},
    10: {"tests": 97, "renders": 1050, "fbx_exported": 800},
    11: {"tests": 97, "renders": 1064, "fbx_exported": 900},
    12: {"tests": 98, "renders": 1064, "fbx_exported": 1000},
    13: {"tests": 98, "renders": 1064, "fbx_exported": 1050},
    14: {"tests": 99, "renders": 1064, "fbx_exported": 1064, "scenarios_computed": 2},
    15: {"tests": 100, "fbx_exported": 1064, "scenarios_computed": 3},
    16: {"tests": 100, "fbx_exported": 1064, "scenarios_computed": 4},
    17: {"tests": 100, "fbx_exported": 1064, "scenarios_computed": 5},
    18: {"tests": 100, "fbx_exported": 1064, "scenarios_computed": 5, "web_deployed": True},
    19: {"tests": 100, "web_deployed": True},
    20: {"tests": 100, "web_deployed": True},
    21: {"tests": 100, "web_deployed": True},
}


def get_actuals() -> dict:
    """Read actual progress from coverage matrix and test counts."""
    actuals = {}

    cm_path = REPO / "outputs" / "coverage_matrix.json"
    if cm_path.exists():
        try:
            cm = json.loads(cm_path.read_text(encoding="utf-8"))
            summary = cm.get("summary", {})
            actuals["renders"] = summary.get("rendered", {}).get("count", 0)
            actuals["fbx_exported"] = summary.get("exported", {}).get("count", 0)
            actuals["depth_fused"] = summary.get("depth_fused", {}).get("count", 0)
            actuals["seg_fused"] = summary.get("seg_fused", {}).get("count", 0)
        except (json.JSONDecodeError, OSError):
            pass

    # Count test files
    tests_dir = REPO / "tests"
    if tests_dir.exists():
        actuals["test_files"] = len(list(tests_dir.glob("test_*.py")))

    return actuals


def classify_status(target, actual) -> str:
    """Classify metric as on_track, behind, or ahead."""
    if isinstance(target, bool):
        if actual == target:
            return "on_track"
        return "behind"
    if actual > target * 1.1:
        return "ahead"
    if actual >= target:
        return "on_track"
    return "behind"


def main():
    parser = argparse.ArgumentParser(description="Sprint progress tracker")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    args = parser.parse_args()

    today = date.today()
    sprint_day = (today - SPRINT_START).days + 1

    if sprint_day < 1 or sprint_day > 21:
        if args.json:
            print(json.dumps({"error": "Outside sprint window", "sprint_day": sprint_day}))
        else:
            print(f"Outside sprint window (day {sprint_day})")
        return

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

    report = {
        "sprint_day": sprint_day,
        "date": today.isoformat(),
        "targets": targets,
        "actuals": actuals,
        "status": status_entries,
    }

    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print(f"Sprint Day {sprint_day} ({today})")
        print("-" * 50)
        for entry in status_entries:
            icon = {"on_track": "OK", "behind": "!!", "ahead": "++"}[entry["status"]]
            print(f"  [{icon}] {entry['metric']}: {entry['actual']} / {entry['target']}")


if __name__ == "__main__":
    main()
