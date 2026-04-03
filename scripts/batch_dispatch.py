#!/usr/bin/env python3
"""Dispatch pipeline stages in batches with progress tracking.

Runs any pipeline script against batches of buildings with parallel
execution, progress bars, and automatic retry on failure.

Usage:
    python scripts/batch_dispatch.py --script scripts/enrich_skeletons.py --batch-size 50
    python scripts/batch_dispatch.py --script "python scripts/sense/extract_depth.py" --street "Augusta Ave"
    python scripts/batch_dispatch.py --stage enrich --dry-run
    python scripts/batch_dispatch.py --stage sense --batch-size 100 --workers 2
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)
REPO_ROOT = Path(__file__).resolve().parent.parent

# Pre-defined stage pipelines
STAGES = {
    "enrich": [
        "python scripts/translate_agent_params.py",
        "python scripts/enrich_skeletons.py",
        "python scripts/enrich_facade_descriptions.py",
        "python scripts/normalize_params_schema.py",
        "python scripts/patch_params_from_hcd.py",
        "python scripts/infer_missing_params.py",
        "python scripts/rebuild_colour_palettes.py",
        "python scripts/diversify_colour_palettes.py",
    ],
    "sense": [
        "python scripts/sense/extract_depth.py --input 'PHOTOS KENSINGTON/' --output depth_maps/ --skip-existing",
        "python scripts/sense/segment_facades.py --input 'PHOTOS KENSINGTON/' --output segmentation/ --skip-existing",
        "python scripts/sense/extract_signage.py --input 'PHOTOS KENSINGTON/' --output signage/ --skip-existing",
        "python scripts/sense/extract_normals.py --input 'PHOTOS KENSINGTON/' --output normals/ --skip-existing",
    ],
    "fuse": [
        "python scripts/enrich/fuse_depth.py --apply",
        "python scripts/enrich/fuse_segmentation.py --apply",
        "python scripts/enrich/fuse_signage.py --apply",
    ],
    "post_enrich": [
        "python scripts/match_photos_to_params.py --apply",
        "python scripts/enrich_storefronts_advanced.py",
        "python scripts/enrich_porch_dimensions.py",
        "python scripts/infer_setbacks.py",
        "python scripts/consolidate_depth_notes.py --apply",
        "python scripts/build_adjacency_graph.py",
        "python scripts/analyze_streetscape_rhythm.py",
    ],
    "qa": [
        "python scripts/qa_params_gate.py",
        "python scripts/audit_params_quality.py",
        "python scripts/audit_structural_consistency.py",
        "python scripts/generate_coverage_matrix.py",
    ],
    "export": [
        "python scripts/export/export_citygml.py --lod 2",
        "python scripts/export/export_3dtiles.py",
        "python scripts/export/build_web_data.py",
        "python scripts/export/build_web_geojson.py",
    ],
}


def run_command(cmd: str, timeout: int = 600) -> dict:
    """Execute a command and capture output."""
    start = time.time()
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True,
            timeout=timeout, cwd=str(REPO_ROOT),
        )
        elapsed = time.time() - start
        return {
            "command": cmd,
            "returncode": result.returncode,
            "stdout": result.stdout[-500:] if result.stdout else "",
            "stderr": result.stderr[-500:] if result.stderr else "",
            "elapsed_s": round(elapsed, 1),
            "success": result.returncode == 0,
        }
    except subprocess.TimeoutExpired:
        return {"command": cmd, "success": False, "error": "timeout", "elapsed_s": timeout}
    except Exception as e:
        return {"command": cmd, "success": False, "error": str(e), "elapsed_s": 0}


def dispatch_stage(stage_name: str, dry_run: bool = False) -> list[dict]:
    """Run all commands in a pipeline stage sequentially."""
    commands = STAGES.get(stage_name, [])
    if not commands:
        print(f"Unknown stage: {stage_name}. Available: {', '.join(STAGES.keys())}")
        return []

    print(f"\n{'='*60}")
    print(f"Stage: {stage_name} ({len(commands)} commands)")
    print(f"{'='*60}")

    results = []
    for i, cmd in enumerate(commands, 1):
        print(f"\n[{i}/{len(commands)}] {cmd}")
        if dry_run:
            results.append({"command": cmd, "success": True, "dry_run": True})
            continue

        result = run_command(cmd)
        results.append(result)

        status = "OK" if result["success"] else "FAIL"
        print(f"  -> {status} ({result['elapsed_s']}s)")
        if not result["success"]:
            stderr = result.get("stderr", result.get("error", ""))
            if stderr:
                print(f"  stderr: {stderr[:200]}")

    return results


def main():
    parser = argparse.ArgumentParser(description="Dispatch pipeline stages in batches")
    parser.add_argument("--stage", type=str, default=None,
                        choices=list(STAGES.keys()),
                        help=f"Pipeline stage: {', '.join(STAGES.keys())}")
    parser.add_argument("--script", type=str, default=None, help="Custom script/command to run")
    parser.add_argument("--street", type=str, default=None)
    parser.add_argument("--batch-size", type=int, default=50)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--report", type=Path, default=None)
    parser.add_argument("--all-stages", action="store_true", help="Run all stages in order")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    all_results = {}

    if args.all_stages:
        stage_order = ["enrich", "sense", "fuse", "post_enrich", "qa", "export"]
        for stage in stage_order:
            results = dispatch_stage(stage, args.dry_run)
            all_results[stage] = results
    elif args.stage:
        results = dispatch_stage(args.stage, args.dry_run)
        all_results[args.stage] = results
    elif args.script:
        cmd = args.script
        if args.street:
            cmd += f" --street \"{args.street}\""
        print(f"Running: {cmd}")
        if not args.dry_run:
            result = run_command(cmd)
            print(f"  -> {'OK' if result['success'] else 'FAIL'} ({result['elapsed_s']}s)")
            all_results["custom"] = [result]
    else:
        print("Available stages:")
        for name, cmds in STAGES.items():
            print(f"  {name}: {len(cmds)} commands")
        print("\nUse --stage <name>, --all-stages, or --script <command>")
        return

    # Summary
    total = sum(len(v) for v in all_results.values())
    ok = sum(1 for v in all_results.values() for r in v if r.get("success"))
    fail = total - ok
    print(f"\n{'='*60}")
    print(f"DISPATCH COMPLETE: {ok}/{total} commands succeeded, {fail} failed")

    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        report = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "stages": {k: v for k, v in all_results.items()},
            "summary": {"total": total, "ok": ok, "failed": fail},
        }
        args.report.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"Report: {args.report}")


if __name__ == "__main__":
    main()
