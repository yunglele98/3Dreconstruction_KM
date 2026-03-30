#!/usr/bin/env python3
"""Consolidate depth_notes for all buildings.

Ensures every active building has complete deep_facade_analysis.depth_notes:
  - setback_m_est: from site.setback_m or inferred_setback_m
  - foundation_height_m_est: from foundation_height_m or default 0.3
  - step_count: from existing or infer_setbacks logic
  - eave_overhang_mm_est: from roof_detail.eave_overhang_mm or default 300
  - wall_thickness_m: 0.3

Only fill MISSING fields, never overwrite existing.

Usage:
    python consolidate_depth_notes.py              # dry-run
    python consolidate_depth_notes.py --apply      # apply changes
    python consolidate_depth_notes.py --params-dir /path/to/params --apply
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path


def get_params_dir(override: str | None = None) -> Path:
    """Get params directory."""
    if override:
        return Path(override)
    return Path(__file__).parent.parent / "params"


def infer_step_count(
    foundation_height_m: float | None,
    setback_m: float | None,
    porch_present: bool = False,
    has_storefront: bool = False,
    context_dict: dict | None = None,
) -> int:
    """Infer step count based on foundation and setback."""
    context = context_dict or {}
    is_commercial = has_storefront or "commercial" in str(context.get("building_type", "")).lower()

    # Commercial/storefront at grade
    if is_commercial and not foundation_height_m:
        return 1

    # No foundation height, use defaults
    if not foundation_height_m:
        if porch_present:
            return 2
        return 1

    # Compute from foundation height
    base_count = max(1, round(foundation_height_m / 0.18))

    # Increase if setback and porch
    if setback_m and setback_m > 0 and porch_present:
        return max(2, base_count)

    return base_count


def consolidate_depth_notes(params: dict) -> dict:
    """Consolidate depth_notes for a building.

    Returns dict with new fields to add (only missing ones).
    """
    new_fields = {}

    # Get or create deep_facade_analysis
    deep_facade = params.get("deep_facade_analysis", {})
    if not isinstance(deep_facade, dict):
        deep_facade = {}

    # Get or create depth_notes
    depth_notes = deep_facade.get("depth_notes", {})
    if not isinstance(depth_notes, dict):
        depth_notes = {}

    # 1. setback_m_est
    if "setback_m_est" not in depth_notes:
        site = params.get("site", {})
        setback = site.get("setback_m")
        if setback is None or setback == 0:
            # Try inferred
            setback = params.get("inferred_setback_m", 2.0)
        new_fields["setback_m_est"] = setback

    # 2. foundation_height_m_est
    if "foundation_height_m_est" not in depth_notes:
        foundation = params.get("foundation_height_m")
        if foundation is None:
            foundation = 0.3
        new_fields["foundation_height_m_est"] = foundation

    # 3. step_count
    if "step_count" not in depth_notes:
        site = params.get("site", {})
        setback = site.get("setback_m")
        if setback is None or setback == 0:
            setback = params.get("inferred_setback_m", 2.0)

        foundation = params.get("foundation_height_m") or (
            depth_notes.get("foundation_height_m_est") or new_fields.get("foundation_height_m_est", 0.3)
        )
        porch_present = params.get("porch_present", False)
        has_storefront = params.get("has_storefront", False)
        context = params.get("context", {})

        step_count = infer_step_count(
            foundation,
            setback,
            porch_present,
            has_storefront,
            context,
        )
        new_fields["step_count"] = step_count

    # 4. eave_overhang_mm_est
    if "eave_overhang_mm_est" not in depth_notes:
        roof_detail = params.get("roof_detail", {})
        eave = roof_detail.get("eave_overhang_mm")
        if eave is None:
            eave = 300  # default
        new_fields["eave_overhang_mm_est"] = eave

    # 5. wall_thickness_m
    if "wall_thickness_m" not in depth_notes:
        new_fields["wall_thickness_m"] = 0.3

    return new_fields


def process_params(
    params_dir: Path, apply: bool = False, dry_run: bool = True
) -> dict:
    """Process all param files and consolidate depth_notes."""
    if dry_run and not apply:
        apply = False
    elif apply:
        dry_run = False

    results = {
        "processed": 0,
        "skipped": 0,
        "consolidated": 0,
        "setback_m_est_added": 0,
        "foundation_height_m_est_added": 0,
        "step_count_added": 0,
        "eave_overhang_mm_est_added": 0,
        "wall_thickness_m_added": 0,
        "errors": [],
    }

    timestamp = datetime.now().isoformat()

    for param_file in sorted(params_dir.glob("*.json")):
        # Skip metadata files
        if param_file.name.startswith("_"):
            results["skipped"] += 1
            continue

        try:
            with open(param_file, encoding="utf-8") as f:
                params = json.load(f)

            # Skip if marked as skipped
            if params.get("skipped"):
                results["skipped"] += 1
                continue

            results["processed"] += 1

            # Consolidate
            new_fields = consolidate_depth_notes(params)

            if new_fields:
                results["consolidated"] += 1

                # Update deep_facade_analysis.depth_notes
                if "deep_facade_analysis" not in params:
                    params["deep_facade_analysis"] = {}
                if "depth_notes" not in params["deep_facade_analysis"]:
                    params["deep_facade_analysis"]["depth_notes"] = {}

                # Count what was added
                for key in new_fields:
                    params["deep_facade_analysis"]["depth_notes"][key] = new_fields[key]

                    if key == "setback_m_est":
                        results["setback_m_est_added"] += 1
                    elif key == "foundation_height_m_est":
                        results["foundation_height_m_est_added"] += 1
                    elif key == "step_count":
                        results["step_count_added"] += 1
                    elif key == "eave_overhang_mm_est":
                        results["eave_overhang_mm_est_added"] += 1
                    elif key == "wall_thickness_m":
                        results["wall_thickness_m_added"] += 1

                # Stamp metadata
                meta = params.get("_meta", {})
                meta["depth_notes_consolidated"] = timestamp
                params["_meta"] = meta

                # Write if applying
                if apply:
                    with open(param_file, "w", encoding="utf-8") as f:
                        json.dump(params, f, indent=2, ensure_ascii=False)

        except Exception as e:
            results["errors"].append(f"{param_file.name}: {e}")

    return results


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Consolidate depth_notes for all buildings."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply changes (default: dry-run)",
    )
    parser.add_argument(
        "--params-dir",
        type=str,
        default=None,
        help="Override params directory path",
    )

    args = parser.parse_args()

    params_dir = get_params_dir(args.params_dir)

    if not params_dir.exists():
        print(f"Error: params directory not found: {params_dir}", file=sys.stderr)
        sys.exit(1)

    is_apply = args.apply
    is_dry_run = not is_apply

    print(f"\n{'=' * 70}")
    print(f"CONSOLIDATE DEPTH_NOTES {'DRY-RUN' if is_dry_run else 'APPLY'}")
    print(f"{'=' * 70}")
    print(f"Params dir: {params_dir}")
    print(f"Mode: {'DRY-RUN' if is_dry_run else 'APPLY'}")
    print()

    results = process_params(params_dir, apply=is_apply, dry_run=is_dry_run)

    print(f"Processed: {results['processed']}")
    print(f"Skipped: {results['skipped']}")
    print(f"Buildings consolidated: {results['consolidated']}")
    print(f"  setback_m_est added: {results['setback_m_est_added']}")
    print(f"  foundation_height_m_est added: {results['foundation_height_m_est_added']}")
    print(f"  step_count added: {results['step_count_added']}")
    print(f"  eave_overhang_mm_est added: {results['eave_overhang_mm_est_added']}")
    print(f"  wall_thickness_m added: {results['wall_thickness_m_added']}")

    if results["errors"]:
        print(f"\nErrors ({len(results['errors'])}):")
        for err in results["errors"][:10]:
            print(f"  {err}")
        if len(results["errors"]) > 10:
            print(f"  ... and {len(results['errors']) - 10} more")

    if is_dry_run:
        print("\n(DRY-RUN: no changes written)")
    else:
        print("\n(Changes applied)")

    print(f"{'=' * 70}\n")


if __name__ == "__main__":
    main()
