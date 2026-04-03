#!/usr/bin/env python3
"""WF-08: Morning report — collects overnight results for Slack."""
import json, logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)
REPO = Path(__file__).parent.parent.parent

def generate_report():
    # Coverage
    cm = REPO / "outputs" / "coverage_matrix.json"
    coverage = json.loads(cm.read_text(encoding="utf-8")) if cm.exists() else {}
    s = coverage.get("summary", {})

    # Latest session run
    runs_dir = REPO / "outputs" / "session_runs"
    latest = None
    if runs_dir.exists():
        runs = sorted(runs_dir.glob("*.json"))
        if runs:
            latest = json.loads(runs[-1].read_text(encoding="utf-8"))

    # Disk
    import shutil
    usage = shutil.disk_usage(str(REPO))
    disk_free = usage.free / (1024**3)
    disk_pct = usage.used / usage.total * 100

    # Sprint
    from datetime import date
    sprint_day = (date.today() - date(2026, 4, 2)).days + 1

    report = {
        "generated": datetime.now().isoformat(),
        "sprint_day": sprint_day,
        "coverage": {k: v.get("pct", 0) for k, v in s.items()} if isinstance(s, dict) else {},
        "overnight": latest,
        "disk_free_gb": round(disk_free, 1),
        "disk_pct": round(disk_pct, 1),
    }

    # Format for Slack
    lines = [
        f"KENSINGTON FACTORY - Day {sprint_day}/21",
        "=" * 40,
    ]
    for k, v in report.get("coverage", {}).items():
        if k == "active": continue
        lines.append(f"  {k:15s} {v:.1f}%")
    lines.append(f"  Disk: {disk_free:.0f}GB free ({disk_pct:.0f}%)")
    if latest:
        lines.append(f"  Overnight: {latest.get('overall', '?')}")

    return report, "\n".join(lines)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    report, text = generate_report()
    print(text)
    (REPO / "outputs" / "morning_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
