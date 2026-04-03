#!/usr/bin/env python3
"""V7 pipeline orchestrator — chains stages 0-9.

Usage:
    python scripts/run_full_pipeline.py
    python scripts/run_full_pipeline.py --stages 0,3,4 --address "22 Lippincott St"
    python scripts/run_full_pipeline.py --dry-run
    python scripts/run_full_pipeline.py --street "Augusta Ave" --skip-missing
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# Scripts that accept --address / --street flags
# ---------------------------------------------------------------------------

ADDR_SCRIPTS = {
    "scripts/export_db_params.py",
    "scripts/enrich/fuse_depth.py",
    "scripts/enrich/fuse_segmentation.py",
    "scripts/enrich/fuse_lidar.py",
    "scripts/enrich/fuse_photogrammetry.py",
    "scripts/enrich/fuse_signage.py",
    "scripts/reconstruct/select_candidates.py",
}

STREET_SCRIPTS = {
    "scripts/export_db_params.py",
    "scripts/reconstruct/run_photogrammetry_block.py",
}

# ---------------------------------------------------------------------------
# Stage definitions
# ---------------------------------------------------------------------------

STAGES = {
    0: {
        "name": "ACQUIRE",
        "scripts": [
            ("python", "scripts/export_db_params.py"),
            ("python", "scripts/acquire_ipad_scans.py"),
            ("python", "scripts/acquire_streetview.py"),
            ("python", "scripts/acquire_open_data.py"),
        ],
        "prereqs": [],
    },
    1: {
        "name": "SENSE",
        "scripts": [
            ("python", "scripts/sense/extract_depth.py"),
            ("python", "scripts/sense/segment_facades.py"),
            ("python", "scripts/sense/extract_normals.py"),
            ("python", "scripts/sense/extract_signage.py"),
            ("python", "scripts/sense/extract_features.py"),
        ],
        "prereqs": ["PHOTOS KENSINGTON/"],
    },
    2: {
        "name": "RECONSTRUCT",
        "scripts": [
            ("python", "scripts/reconstruct/select_candidates.py"),
            ("python", "scripts/reconstruct/run_photogrammetry.py"),
            ("python", "scripts/reconstruct/run_photogrammetry_block.py"),
            ("python", "scripts/reconstruct/run_dust3r.py"),
            ("python", "scripts/reconstruct/clip_block_mesh.py"),
            ("python", "scripts/reconstruct/retopologize.py"),
            ("python", "scripts/reconstruct/extract_elements.py"),
            ("python", "scripts/reconstruct/calibrate_defaults.py"),
            ("python", "scripts/reconstruct/train_splats.py"),
            # COLMAP analysis (read-only, no --address flag)
            # NOTE: analyze_sparse_model.py is intentionally NOT here —
            # it's for manual deep-dives on specific models.
            ("python", "scripts/reconstruct/analyze_photo_coverage.py"),
            ("python", "scripts/reconstruct/analyze_colmap_quality.py"),
            ("python", "scripts/reconstruct/colmap_report.py"),
        ],
        "prereqs": ["params/", "PHOTOS KENSINGTON/"],
    },
    3: {
        "name": "ENRICH",
        "scripts": [
            # Core enrichment pipeline (run in order)
            ("python", "scripts/translate_agent_params.py"),
            ("python", "scripts/enrich_skeletons.py"),
            ("python", "scripts/enrich_facade_descriptions.py"),
            ("python", "scripts/normalize_params_schema.py"),
            ("python", "scripts/patch_params_from_hcd.py"),
            ("python", "scripts/infer_missing_params.py"),
            # Fusion scripts
            ("python", "scripts/enrich/fuse_depth.py"),
            ("python", "scripts/enrich/fuse_segmentation.py"),
            ("python", "scripts/enrich/fuse_lidar.py"),
            ("python", "scripts/enrich/fuse_photogrammetry.py"),
            ("python", "scripts/enrich/fuse_signage.py"),
            # Post-enrichment
            ("python", "scripts/rebuild_colour_palettes.py"),
            ("python", "scripts/diversify_colour_palettes.py"),
            ("python", "scripts/match_photos_to_params.py"),
            ("python", "scripts/enrich_storefronts_advanced.py"),
            ("python", "scripts/enrich_porch_dimensions.py"),
            ("python", "scripts/infer_setbacks.py"),
            ("python", "scripts/consolidate_depth_notes.py"),
            ("python", "scripts/build_adjacency_graph.py"),
            ("python", "scripts/analyze_streetscape_rhythm.py"),
        ],
        "prereqs": ["params/"],
    },
    4: {
        "name": "GENERATE",
        "scripts": [
            ("blender", "generate_building.py"),
        ],
        "prereqs": ["params/"],
        "note": "Requires Blender CLI",
    },
    5: {
        "name": "TEXTURE",
        "scripts": [
            ("python", "scripts/texture/extract_pbr.py"),
            ("python", "scripts/texture/project_textures.py"),
            ("python", "scripts/texture/upscale_textures.py"),
        ],
        "prereqs": ["PHOTOS KENSINGTON/"],
    },
    6: {
        "name": "OPTIMIZE",
        "scripts": [
            ("blender", "scripts/generate_lods.py"),
            ("blender", "scripts/generate_collision_mesh.py"),
            ("python", "scripts/optimize_meshes.py"),
            ("python", "scripts/validate_export_pipeline.py"),
        ],
        "prereqs": ["outputs/"],
        "note": "LOD/collision require Blender CLI",
    },
    7: {
        "name": "ASSEMBLE",
        "scripts": [
            ("python", "scripts/export_gis_scene.py"),
            ("python", "scripts/build_unreal_datasmith.py"),
            ("python", "scripts/build_unity_prefab_manifest.py"),
        ],
        "prereqs": ["params/", "outputs/"],
    },
    8: {
        "name": "EXPORT",
        "scripts": [
            ("python", "scripts/export/export_citygml.py"),
            ("python", "scripts/export/export_3dtiles.py"),
            ("python", "scripts/export/export_potree.py"),
            ("python", "scripts/export/build_web_data.py"),
            ("python", "scripts/export/build_web_geojson.py"),
            ("python", "scripts/export/package_splats.py"),
            ("python", "scripts/planning/generate_scenarios.py"),
        ],
        "prereqs": ["params/"],
    },
    9: {
        "name": "VERIFY",
        "scripts": [
            ("python", "scripts/qa_params_gate.py"),
            ("python", "scripts/audit_params_quality.py"),
            ("python", "scripts/audit_structural_consistency.py"),
            ("python", "scripts/audit_generator_contracts.py"),
            ("python", "scripts/verify/visual_regression.py"),
            ("python", "scripts/verify/run_full_qa.py"),
        ],
        "prereqs": ["params/"],
    },
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def check_prereqs(prereqs: list[str]) -> list[str]:
    """Return list of missing prerequisite paths."""
    missing = []
    for p in prereqs:
        full = REPO_ROOT / p
        if not full.exists():
            missing.append(p)
    return missing


def build_command(runner: str, script: str, args: argparse.Namespace) -> list[str]:
    """Build the subprocess command for a script."""
    script_path = str(REPO_ROOT / script)

    if runner == "blender":
        cmd = [
            "blender", "--background", "--python", script_path,
            "--",
            "--params", str(REPO_ROOT / "params/"),
            "--batch-individual",
        ]
        if args.address:
            cmd = [
                "blender", "--background", "--python", script_path,
                "--",
                "--params", str(REPO_ROOT / f"params/{args.address.replace(' ', '_')}.json"),
            ]
        return cmd

    cmd = [sys.executable, script_path]
    if args.address and script in ADDR_SCRIPTS:
        cmd.extend(["--address", args.address])
    if args.street and script in STREET_SCRIPTS:
        cmd.extend(["--street", args.street])
    return cmd


def run_script(cmd: list[str], dry_run: bool) -> tuple[str, bool]:
    """Run a single script. Returns (label, success)."""
    label = " ".join(cmd)
    if dry_run:
        print(f"  [DRY-RUN] would run: {label}")
        return label, True

    print(f"  Running: {label}")
    try:
        result = subprocess.run(cmd, cwd=str(REPO_ROOT), timeout=3600)
        success = result.returncode == 0
        status = "PASS" if success else f"FAIL (exit {result.returncode})"
        print(f"  -> {status}")
        return label, success
    except FileNotFoundError:
        print(f"  -> FAIL (command not found)")
        return label, False
    except subprocess.TimeoutExpired:
        print(f"  -> FAIL (timeout after 3600s)")
        return label, False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="V7 pipeline orchestrator — chains stages 0-9."
    )
    parser.add_argument(
        "--stages",
        default="0,1,2,3,4,5,6,7,8,9",
        help="Comma-separated stage numbers to run (default: 0,1,2,3,4,5,6,7,8,9)",
    )
    parser.add_argument(
        "--address",
        help='Single building mode, e.g. "22 Lippincott St"',
    )
    parser.add_argument(
        "--street",
        help='Street mode, e.g. "Augusta Ave"',
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show plan without executing",
    )
    parser.add_argument(
        "--skip-missing",
        action="store_true",
        help="Skip stages with missing prerequisites instead of failing",
    )
    args = parser.parse_args()

    requested = [int(s.strip()) for s in args.stages.split(",")]

    # Counters
    attempted = 0
    passed = 0
    failed = 0
    skipped = 0
    results: list[tuple[int, str, str]] = []  # (stage_num, name, status)

    start_time = time.time()

    for stage_num in requested:
        if stage_num not in STAGES:
            print(f"\nWARNING: Unknown stage {stage_num}, skipping.")
            skipped += 1
            results.append((stage_num, f"UNKNOWN_{stage_num}", "SKIPPED"))
            continue

        stage = STAGES[stage_num]
        name = stage["name"]
        note = stage.get("note", "")
        note_str = f" ({note})" if note else ""

        print(f"\n{'='*60}")
        print(f"  Stage {stage_num}: {name}{note_str}")
        print(f"{'='*60}")

        # Check prerequisites
        missing = check_prereqs(stage["prereqs"])
        if missing:
            if args.skip_missing:
                print(f"  SKIPPED — missing prerequisites: {', '.join(missing)}")
                skipped += 1
                results.append((stage_num, name, "SKIPPED"))
                continue
            elif args.dry_run:
                print(f"  WARNING — missing prerequisites: {', '.join(missing)}")
            else:
                print(f"  FAILED — missing prerequisites: {', '.join(missing)}")
                failed += 1
                results.append((stage_num, name, "FAILED"))
                continue

        attempted += 1
        stage_ok = True

        for runner, script in stage["scripts"]:
            cmd = build_command(runner, script, args)
            _, success = run_script(cmd, args.dry_run)
            if not success and not args.dry_run:
                stage_ok = False

        if args.dry_run:
            passed += 1
            results.append((stage_num, name, "DRY-RUN"))
        elif stage_ok:
            passed += 1
            results.append((stage_num, name, "PASSED"))
        else:
            failed += 1
            results.append((stage_num, name, "FAILED"))

    elapsed = time.time() - start_time

    # Summary dashboard
    print(f"\n{'='*60}")
    print(f"  PIPELINE SUMMARY")
    print(f"{'='*60}")
    print(f"  Elapsed:   {elapsed:.1f}s")
    print(f"  Attempted: {attempted}")
    print(f"  Passed:    {passed}")
    print(f"  Failed:    {failed}")
    print(f"  Skipped:   {skipped}")
    print()
    for stage_num, name, status in results:
        marker = {"PASSED": "+", "DRY-RUN": "~", "FAILED": "X", "SKIPPED": "-"}.get(
            status, "?"
        )
        print(f"  [{marker}] Stage {stage_num}: {name} — {status}")
    print()

    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
