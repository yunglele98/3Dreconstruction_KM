#!/usr/bin/env python3
"""Pipeline health check for all major components.

Checks database connectivity, key directories, photo index, GPU lock,
disk space, param counts, and render counts. Outputs a JSON report.

Usage:
    python scripts/monitor/healthcheck.py
    python scripts/monitor/healthcheck.py --output health_report.json
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def check_database() -> dict:
    """Try connecting to the PostGIS database."""
    try:
        import psycopg2

        conn = psycopg2.connect(
            host="localhost",
            port=5432,
            dbname="kensington",
            user="postgres",
            password="test123",
            connect_timeout=5,
        )
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM building_assessment")
        count = cur.fetchone()[0]
        cur.close()
        conn.close()
        return {
            "status": "ok",
            "message": f"Connected, {count} buildings in building_assessment",
        }
    except ImportError:
        return {
            "status": "warn",
            "message": "psycopg2 not installed",
        }
    except Exception as e:
        return {
            "status": "error",
            "message": str(e),
        }


def check_directories() -> dict:
    """Check that key directories exist."""
    required = ["params", "outputs", "scripts", "tests"]
    missing = [d for d in required if not (REPO_ROOT / d).is_dir()]
    if not missing:
        return {"status": "ok", "message": "All key directories present"}
    return {
        "status": "error",
        "message": f"Missing directories: {', '.join(missing)}",
    }


def check_photo_index() -> dict:
    """Check if the photo address index CSV exists."""
    index_path = REPO_ROOT / "PHOTOS KENSINGTON" / "csv" / "photo_address_index.csv"
    if index_path.is_file():
        line_count = sum(1 for _ in index_path.open(encoding="utf-8")) - 1
        return {
            "status": "ok",
            "message": f"Photo index exists ({line_count} entries)",
        }
    if (REPO_ROOT / "PHOTOS KENSINGTON").is_dir():
        return {
            "status": "warn",
            "message": "Photo directory exists but index CSV missing",
        }
    return {
        "status": "warn",
        "message": "PHOTOS KENSINGTON directory not found",
    }


def check_gpu_lock() -> dict:
    """Check GPU lock status."""
    lock_path = REPO_ROOT / ".gpu_lock"
    if lock_path.is_file():
        try:
            content = lock_path.read_text(encoding="utf-8").strip()
            return {
                "status": "ok",
                "message": f"GPU busy: {content[:100]}" if content else "GPU busy (lock file present)",
            }
        except Exception:
            return {"status": "ok", "message": "GPU busy (lock file present)"}
    return {"status": "ok", "message": "GPU free (no lock file)"}


def check_disk_space() -> dict:
    """Check available disk space on the repo partition."""
    usage = shutil.disk_usage(str(REPO_ROOT))
    free_gb = usage.free / (1024**3)
    total_gb = usage.total / (1024**3)
    pct_free = (usage.free / usage.total) * 100

    if free_gb < 1:
        status = "error"
    elif free_gb < 5:
        status = "warn"
    else:
        status = "ok"

    return {
        "status": status,
        "message": f"{free_gb:.1f} GB free of {total_gb:.1f} GB ({pct_free:.0f}% free)",
    }


def check_param_count() -> dict:
    """Count non-skipped param files."""
    params_dir = REPO_ROOT / "params"
    if not params_dir.is_dir():
        return {"status": "error", "message": "params/ directory not found"}

    total = 0
    skipped = 0
    active = 0

    for f in params_dir.glob("*.json"):
        if f.name.startswith("_"):
            continue
        total += 1
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            if data.get("skipped"):
                skipped += 1
            else:
                active += 1
        except (json.JSONDecodeError, OSError):
            skipped += 1

    return {
        "status": "ok",
        "message": f"{active} active, {skipped} skipped, {total} total param files",
    }


def check_render_count() -> dict:
    """Count rendered files in outputs/full/."""
    full_dir = REPO_ROOT / "outputs" / "full"
    if not full_dir.is_dir():
        return {"status": "warn", "message": "outputs/full/ not found"}

    blend_count = len(list(full_dir.glob("*.blend")))
    png_count = len(list(full_dir.glob("*.png")))
    return {
        "status": "ok",
        "message": f"{blend_count} .blend files, {png_count} .png renders in outputs/full/",
    }


def main():
    parser = argparse.ArgumentParser(
        description="Pipeline health check for all major components."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Write JSON report to file (default: stdout)",
    )
    args = parser.parse_args()

    checks = {
        "database": check_database,
        "directories": check_directories,
        "photo_index": check_photo_index,
        "gpu_lock": check_gpu_lock,
        "disk_space": check_disk_space,
        "param_count": check_param_count,
        "render_count": check_render_count,
    }

    report = {}
    has_errors = False

    print("=" * 50)
    print("  Health Check — Kensington Market 3D Pipeline")
    print("=" * 50)

    for name, check_fn in checks.items():
        result = check_fn()
        report[name] = result
        icon = {"ok": "OK", "warn": "WARN", "error": "FAIL"}.get(result["status"], "??")
        print(f"  [{icon:>4}] {name}: {result['message']}")
        if result["status"] == "error":
            has_errors = True

    report["overall"] = "error" if has_errors else "ok"
    print(f"\nOverall: {report['overall'].upper()}")

    output_json = json.dumps(report, indent=2, ensure_ascii=False)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output_json, encoding="utf-8")
        print(f"\nReport written to {args.output}")
    else:
        print(f"\n{output_json}")

    sys.exit(1 if has_errors else 0)


if __name__ == "__main__":
    main()
