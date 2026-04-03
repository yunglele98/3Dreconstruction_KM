#!/usr/bin/env python3
"""Overnight pipeline: detect changed params, re-enrich, regenerate, export.

Called by n8n WF-02 at 10 PM. Chains:
1. Fingerprint → detect changed buildings
2. Re-enrich changed buildings
3. QA gate
4. Blender batch generate (--skip-existing)
5. Export + validate
6. Update manifests
7. Write session log

Usage:
    python scripts/run_overnight_queue.py
    python scripts/run_overnight_queue.py --dry-run
    python scripts/run_overnight_queue.py --skip-generate  # enrich only
"""
import argparse, json, logging, subprocess, sys, time
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)
REPO = Path(__file__).parent.parent

def run(cmd, timeout=3600):
    logger.info("  RUN: %s", cmd)
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True,
                            timeout=timeout, cwd=str(REPO))
    if result.returncode != 0:
        logger.warning("  WARN: exit %d: %s", result.returncode, result.stderr[-200:] if result.stderr else "")
    return result.returncode

def main():
    parser = argparse.ArgumentParser(description="Overnight pipeline")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-generate", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")

    t0 = time.time()
    session = {"started": datetime.now().isoformat(), "steps": [], "dry_run": args.dry_run}

    # 1. Fingerprint
    logger.info("Phase 1: Fingerprint params")
    rc = run("python scripts/fingerprint_params.py")
    session["steps"].append({"step": "fingerprint", "exit": rc})

    # 2. Re-enrich
    logger.info("Phase 2: Re-enrich")
    enrich_scripts = [
        "python scripts/translate_agent_params.py",
        "python scripts/enrich_skeletons.py",
        "python scripts/enrich_facade_descriptions.py",
        "python scripts/normalize_params_schema.py",
        "python scripts/patch_params_from_hcd.py",
        "python scripts/infer_missing_params.py",
        "python scripts/rebuild_colour_palettes.py",
        "python scripts/diversify_colour_palettes.py",
    ]
    for script in enrich_scripts:
        rc = run(script)
        session["steps"].append({"step": script.split("/")[-1], "exit": rc})

    # 3. QA gate
    logger.info("Phase 3: QA gate")
    rc = run("python scripts/qa_params_gate.py --ci")
    session["steps"].append({"step": "qa_gate", "exit": rc})
    if rc != 0 and not args.dry_run:
        logger.warning("QA gate failed — skipping generation")
        args.skip_generate = True

    # 4. Generate
    if not args.skip_generate and not args.dry_run:
        logger.info("Phase 4: Blender batch generate")
        blender = r'"C:\Program Files\Blender Foundation\Blender 5.1\blender.exe"'
        rc = run(f'{blender} --background --python generate_building.py -- --params params/ --batch-individual --skip-existing',
                 timeout=14400)
        session["steps"].append({"step": "generate", "exit": rc})
    else:
        logger.info("Phase 4: SKIPPED (dry-run or QA fail)")
        session["steps"].append({"step": "generate", "exit": "skipped"})

    # 5. Coverage matrix
    logger.info("Phase 5: Coverage matrix")
    rc = run("python scripts/generate_coverage_matrix.py")
    session["steps"].append({"step": "coverage", "exit": rc})

    elapsed = time.time() - t0
    session["completed"] = datetime.now().isoformat()
    session["elapsed_seconds"] = round(elapsed, 1)
    session["overall"] = "success" if all(s["exit"] in (0, "skipped") for s in session["steps"]) else "partial"

    log_dir = REPO / "outputs" / "session_runs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_overnight.json"
    log_path.write_text(json.dumps(session, indent=2), encoding="utf-8")
    logger.info("Done in %.0fs. Log: %s", elapsed, log_path)

if __name__ == "__main__":
    main()
