#!/usr/bin/env python3
"""Report status of batch pipeline jobs from session run logs.

Scans the log directory for session run logs, parses filenames for
timestamps and job types, and reports summary statistics.

Usage:
    python scripts/monitor/batch_job_status.py
    python scripts/monitor/batch_job_status.py --logs-dir outputs/session_runs/logs/
    python scripts/monitor/batch_job_status.py --output batch_status.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# Common log filename patterns:
#   2026-04-02_render_batch.log
#   20260402T220000_colmap_block_A.log
#   session_2026-04-02_enrichment.log
TIMESTAMP_PATTERNS = [
    (re.compile(r"(\d{4}-\d{2}-\d{2}T\d{2}[_:]\d{2}[_:]\d{2})"), "%Y-%m-%dT%H_%M_%S"),
    (re.compile(r"(\d{4}-\d{2}-\d{2})"), "%Y-%m-%d"),
    (re.compile(r"(\d{8}T\d{6})"), "%Y%m%dT%H%M%S"),
    (re.compile(r"(\d{8})"), "%Y%m%d"),
]


def parse_timestamp(filename: str) -> str | None:
    """Extract a timestamp string from a log filename."""
    for pattern, fmt in TIMESTAMP_PATTERNS:
        match = pattern.search(filename)
        if match:
            raw = match.group(1)
            try:
                dt = datetime.strptime(raw, fmt)
                return dt.isoformat()
            except ValueError:
                continue
    return None


def infer_job_type(filename: str) -> str:
    """Infer job type from the log filename."""
    name_lower = filename.lower()
    for keyword in [
        "render", "colmap", "photogrammetry", "enrich", "texture",
        "export", "sense", "reconstruct", "optimize", "verify",
        "acquire", "scenario", "audit", "qa",
    ]:
        if keyword in name_lower:
            return keyword
    return "unknown"


def classify_status(log_path: Path) -> str:
    """Classify a log file as completed, failed, or in-progress."""
    try:
        content = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "unknown"

    content_lower = content.lower()

    # Check for failure indicators
    if any(kw in content_lower for kw in ["error", "failed", "traceback", "exception"]):
        # But also check if it recovered/completed after the error
        lines = content_lower.strip().splitlines()
        tail = "\n".join(lines[-10:]) if len(lines) >= 10 else content_lower
        if any(kw in tail for kw in ["completed", "done", "success", "finished"]):
            return "completed"
        return "failed"

    if any(kw in content_lower for kw in ["completed", "done", "success", "finished"]):
        return "completed"

    # If file is very small or recently modified, likely in progress
    if log_path.stat().st_size < 100:
        return "in-progress"

    return "completed"


def scan_logs(logs_dir: Path) -> list[dict]:
    """Scan log directory and return job info dicts."""
    if not logs_dir.is_dir():
        return []

    jobs = []
    for log_file in sorted(logs_dir.iterdir()):
        if not log_file.is_file():
            continue
        if log_file.suffix not in (".log", ".txt", ""):
            continue

        timestamp = parse_timestamp(log_file.name)
        job_type = infer_job_type(log_file.name)
        status = classify_status(log_file)

        jobs.append({
            "filename": log_file.name,
            "timestamp": timestamp,
            "job_type": job_type,
            "status": status,
            "size_bytes": log_file.stat().st_size,
        })

    # Sort by timestamp (most recent first), unknowns at end
    jobs.sort(key=lambda j: j["timestamp"] or "0000", reverse=True)
    return jobs


def main():
    parser = argparse.ArgumentParser(
        description="Report status of batch pipeline jobs."
    )
    parser.add_argument(
        "--logs-dir",
        type=Path,
        default=REPO_ROOT / "outputs" / "session_runs" / "logs",
        help="Directory containing session run logs (default: outputs/session_runs/logs/)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Write JSON report to file (default: stdout)",
    )
    args = parser.parse_args()

    print("=" * 50)
    print("  Batch Job Status — Kensington Market 3D Pipeline")
    print("=" * 50)

    if not args.logs_dir.is_dir():
        print(f"\n  Log directory not found: {args.logs_dir}")
        report = {
            "logs_dir": str(args.logs_dir),
            "total": 0,
            "completed": 0,
            "failed": 0,
            "in_progress": 0,
            "recent_jobs": [],
        }
    else:
        jobs = scan_logs(args.logs_dir)

        completed = sum(1 for j in jobs if j["status"] == "completed")
        failed = sum(1 for j in jobs if j["status"] == "failed")
        in_progress = sum(1 for j in jobs if j["status"] == "in-progress")

        print(f"\n  Logs directory: {args.logs_dir}")
        print(f"  Total jobs:     {len(jobs)}")
        print(f"  Completed:      {completed}")
        print(f"  Failed:         {failed}")
        print(f"  In-progress:    {in_progress}")

        recent = jobs[:10]
        if recent:
            print(f"\n  Most recent {len(recent)} jobs:")
            for job in recent:
                ts = job["timestamp"] or "unknown-time"
                st = {"completed": "OK", "failed": "FAIL", "in-progress": "RUN", "unknown": "??"}.get(
                    job["status"], "??"
                )
                print(f"    [{st:>4}] {ts}  {job['job_type']:<16} {job['filename']}")

        report = {
            "logs_dir": str(args.logs_dir),
            "total": len(jobs),
            "completed": completed,
            "failed": failed,
            "in_progress": in_progress,
            "recent_jobs": recent,
        }

    output_json = json.dumps(report, indent=2, ensure_ascii=False)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output_json, encoding="utf-8")
        print(f"\n  Report written to {args.output}")
    else:
        print(f"\n{output_json}")

    if report.get("failed", 0) > 0:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
