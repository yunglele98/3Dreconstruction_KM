#!/usr/bin/env python3
"""Run full QA suite for final verification.

Orchestrates all verification scripts and produces a consolidated
pass/fail report. Designed for Session 20 final QA gate.

Usage:
    python scripts/verify/run_full_qa.py
    python scripts/verify/run_full_qa.py --quick   # skip slow checks
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def run_check(name, cmd, timeout=120):
    """Run a check command and return pass/fail."""
    print(f"\n  [{name}]")
    start = time.time()
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, cwd=str(REPO_ROOT)
        )
        elapsed = time.time() - start
        passed = result.returncode == 0
        output = result.stdout[-500:] if result.stdout else ""
        error = result.stderr[-300:] if result.stderr else ""
        status = "PASS" if passed else "FAIL"
        print(f"    {status} ({elapsed:.1f}s)")
        if not passed and error:
            print(f"    {error[:200]}")
        return {"name": name, "passed": passed, "elapsed": round(elapsed, 1), "output": output}
    except subprocess.TimeoutExpired:
        print(f"    TIMEOUT ({timeout}s)")
        return {"name": name, "passed": False, "elapsed": timeout, "output": "TIMEOUT"}
    except Exception as e:
        print(f"    ERROR: {e}")
        return {"name": name, "passed": False, "elapsed": 0, "output": str(e)}


def count_files(pattern, directory):
    """Count files matching a glob pattern."""
    d = REPO_ROOT / directory
    if not d.exists():
        return 0
    return len(list(d.rglob(pattern)))


def main():
    parser = argparse.ArgumentParser(description="Run full QA suite.")
    parser.add_argument("--quick", action="store_true", help="Skip slow checks")
    parser.add_argument("--output", type=Path,
                        default=REPO_ROOT / "outputs" / "final_qa_report.json")
    args = parser.parse_args()

    print("=" * 60)
    print("  FINAL QA SUITE — Kensington Market 3D Pipeline")
    print("=" * 60)

    results = []

    # 1. Test suite
    results.append(run_check(
        "pytest",
        [sys.executable, "-m", "pytest", "tests/", "-q", "--tb=no"],
        timeout=120,
    ))

    # 2. Parameter QA gate
    results.append(run_check(
        "params_qa_gate",
        [sys.executable, "scripts/qa_params_gate.py", "--ci"],
        timeout=60,
    ))

    # 3. Structural consistency
    if not args.quick:
        results.append(run_check(
            "structural_audit",
            [sys.executable, "scripts/audit_structural_consistency.py"],
            timeout=60,
        ))

    # 4. Generator contracts
    if not args.quick:
        results.append(run_check(
            "generator_contracts",
            [sys.executable, "scripts/audit_generator_contracts.py"],
            timeout=60,
        ))

    # 5. Coverage matrix
    results.append(run_check(
        "coverage_matrix",
        [sys.executable, "scripts/generate_coverage_matrix.py"],
        timeout=60,
    ))

    # 6. Asset counts
    print("\n  [Asset Counts]")
    counts = {
        "params_active": count_files("*.json", "params") - count_files("_*.json", "params"),
        "blend_files": count_files("*.blend", "outputs/full"),
        "renders": count_files("*.png", "outputs/buildings_renders_v1"),
        "fbx_exports": count_files("*.fbx", "outputs/exports"),
        "depth_maps": count_files("*.npy", "depth_maps"),
        "photos": count_files("*.jpg", "PHOTOS KENSINGTON sorted"),
        "test_files": count_files("test_*.py", "tests"),
    }
    for k, v in counts.items():
        print(f"    {k}: {v}")

    # 7. Web platform build
    results.append(run_check(
        "web_build",
        [sys.executable, "-c",
         "import subprocess; subprocess.run(['npm', 'run', 'build'], cwd='web', shell=True, check=True)"],
        timeout=30,
    ))

    # 8. Scenario validation
    results.append(run_check(
        "scenario_heritage_first",
        [sys.executable, "scripts/planning/heritage_impact.py",
         "--scenario", "scenarios/10yr_heritage_first/"],
        timeout=30,
    ))

    # Summary
    passed = sum(1 for r in results if r["passed"])
    failed = sum(1 for r in results if not r["passed"])
    total = len(results)

    print("\n" + "=" * 60)
    print(f"  RESULTS: {passed}/{total} passed, {failed} failed")
    print("=" * 60)

    for r in results:
        status = "PASS" if r["passed"] else "FAIL"
        print(f"  [{status}] {r['name']} ({r['elapsed']}s)")

    report = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "summary": {"passed": passed, "failed": failed, "total": total},
        "asset_counts": counts,
        "checks": results,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"\n  Report: {args.output}")

    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
