#!/usr/bin/env python3
"""Validate that all scripts referenced by the pipeline orchestrator exist,
have valid Python syntax, include an ``if __name__`` guard, and use argparse.

Usage:
    python scripts/verify/validate_pipeline_interfaces.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# ---------------------------------------------------------------------------
# Import the script list directly from the orchestrator definition
# ---------------------------------------------------------------------------

# Inline copy of STAGES scripts so this validator has zero import dependency
# on the orchestrator itself.  Kept in sync manually.

STAGES = {
    0: [
        "scripts/export_db_params.py",
        "scripts/acquire_ipad_scans.py",
        "scripts/acquire_streetview.py",
        "scripts/acquire_open_data.py",
    ],
    1: [
        "scripts/sense/extract_depth.py",
        "scripts/sense/segment_facades.py",
        "scripts/sense/extract_normals.py",
        "scripts/sense/extract_signage.py",
        "scripts/sense/extract_features.py",
    ],
    2: [
        "scripts/reconstruct/select_candidates.py",
        "scripts/reconstruct/run_photogrammetry.py",
        "scripts/reconstruct/run_photogrammetry_block.py",
        "scripts/reconstruct/run_dust3r.py",
        "scripts/reconstruct/clip_block_mesh.py",
        "scripts/reconstruct/retopologize.py",
        "scripts/reconstruct/extract_elements.py",
        "scripts/reconstruct/calibrate_defaults.py",
        "scripts/reconstruct/train_splats.py",
    ],
    3: [
        "scripts/translate_agent_params.py",
        "scripts/enrich_skeletons.py",
        "scripts/enrich_facade_descriptions.py",
        "scripts/normalize_params_schema.py",
        "scripts/patch_params_from_hcd.py",
        "scripts/infer_missing_params.py",
        "scripts/enrich/fuse_depth.py",
        "scripts/enrich/fuse_segmentation.py",
        "scripts/enrich/fuse_lidar.py",
        "scripts/enrich/fuse_photogrammetry.py",
        "scripts/enrich/fuse_signage.py",
        "scripts/rebuild_colour_palettes.py",
        "scripts/diversify_colour_palettes.py",
        "scripts/match_photos_to_params.py",
        "scripts/enrich_storefronts_advanced.py",
        "scripts/enrich_porch_dimensions.py",
        "scripts/infer_setbacks.py",
        "scripts/consolidate_depth_notes.py",
        "scripts/build_adjacency_graph.py",
        "scripts/analyze_streetscape_rhythm.py",
    ],
    4: [
        "generate_building.py",
    ],
    5: [
        "scripts/texture/extract_pbr.py",
        "scripts/texture/project_textures.py",
        "scripts/texture/upscale_textures.py",
    ],
    6: [
        "scripts/generate_lods.py",
        "scripts/generate_collision_mesh.py",
        "scripts/optimize_meshes.py",
        "scripts/validate_export_pipeline.py",
    ],
    7: [
        "scripts/export_gis_scene.py",
        "scripts/build_unreal_datasmith.py",
        "scripts/build_unity_prefab_manifest.py",
    ],
    8: [
        "scripts/export/export_citygml.py",
        "scripts/export/export_3dtiles.py",
        "scripts/export/export_potree.py",
        "scripts/export/build_web_data.py",
        "scripts/export/build_web_geojson.py",
        "scripts/export/package_splats.py",
        "scripts/planning/generate_scenarios.py",
    ],
    9: [
        "scripts/qa_params_gate.py",
        "scripts/audit_params_quality.py",
        "scripts/audit_structural_consistency.py",
        "scripts/audit_generator_contracts.py",
        "scripts/verify/visual_regression.py",
        "scripts/verify/run_full_qa.py",
    ],
}


def check_script(rel_path: str) -> list[str]:
    """Return a list of issues for the given script (empty = OK)."""
    issues: list[str] = []
    full = REPO_ROOT / rel_path

    # 1. Existence
    if not full.exists():
        issues.append("file not found")
        return issues

    # 2. Valid Python syntax
    source = full.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source, filename=str(full))
    except SyntaxError as exc:
        issues.append(f"syntax error: {exc}")
        return issues

    # 3. __name__ == "__main__" guard
    has_main_guard = False
    for node in ast.walk(tree):
        if isinstance(node, ast.If):
            test = node.test
            if isinstance(test, ast.Compare):
                left = test.left
                # Match:  __name__ == "__main__"  (either side)
                if (isinstance(left, ast.Name) and left.id == "__name__"
                        and any(isinstance(c, ast.Constant) and c.value == "__main__"
                                for c in test.comparators)):
                    has_main_guard = True
                    break
                if (any(isinstance(c, ast.Name) and c.id == "__name__"
                        for c in test.comparators)
                        and isinstance(left, ast.Constant)
                        and left.value == "__main__"):
                    has_main_guard = True
                    break
    if not has_main_guard:
        issues.append("missing if __name__ == '__main__' guard")

    # 4. argparse usage
    if "argparse" not in source:
        issues.append("no argparse usage detected")

    return issues


def main() -> None:
    total = 0
    valid = 0
    issue_count = 0
    all_issues: list[tuple[str, list[str]]] = []

    for stage_num in sorted(STAGES):
        for script in STAGES[stage_num]:
            total += 1
            issues = check_script(script)
            if issues:
                issue_count += 1
                all_issues.append((script, issues))
            else:
                valid += 1

    # Report
    print(f"Pipeline Interface Validation")
    print(f"{'=' * 50}")
    print(f"  Scripts checked: {total}")
    print(f"  Valid:           {valid}")
    print(f"  With issues:     {issue_count}")
    print()

    if all_issues:
        print("Issues found:")
        for script, issues in all_issues:
            for issue in issues:
                print(f"  [{script}] {issue}")
        print()
        sys.exit(1)
    else:
        print("All scripts passed validation.")


if __name__ == "__main__":
    main()
