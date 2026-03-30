#!/usr/bin/env python3
"""Enrich porch dimensions based on facade width, era, and foundation height.

For each building with porch_present=true but missing porch dimension fields:
- porch_width_m: facade-dependent (≤5m → 0.6×width, 5-8m → 0.5×width, >8m → 4.0m)
- porch_depth_m: always 1.8m
- porch_height_m: floor_heights_m[0] or 3.0m default
- porch_columns: era-based (turned/tapered/square)
- porch_railing: baluster type, 0.9m height
- step_count: from deep_facade_analysis or inferred from foundation_height_m

Stores at top level (porch_width_m, porch_depth_m, porch_height_m) and in
structured porch_detail dict. Stamps _meta.porch_enriched with timestamp.

Era detection: hcd_data.construction_date parsed → "pre-1889", "1889-1903", etc.
Default era: "1889-1903" (Kensington Market default).
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path

PARAMS_DIR = Path(__file__).parent.parent / "params"


def parse_era(construction_date: str) -> str:
    """Parse construction_date string to era keyword.

    Examples:
        "Pre-1889" → "pre-1889"
        "1889-1903" → "1889-1903"
        "1904-1913" → "1904-1913"
        None or "" → "1889-1903" (default)
    """
    if not construction_date:
        return "1889-1903"

    cd = str(construction_date).lower().strip()

    # Pre-1889 variants
    if cd.startswith("pre-"):
        return "pre-1889"

    # Extract first 4-digit year
    match = re.search(r"(\d{4})", cd)
    if match:
        year = int(match.group(1))
        if year < 1889:
            return "pre-1889"
        elif year <= 1903:
            return "1889-1903"
        elif year <= 1913:
            return "1904-1913"
        else:
            return "1914+"

    return "1889-1903"


def get_porch_width_m(facade_width_m: float) -> float:
    """Infer porch width from facade width."""
    if facade_width_m <= 5.0:
        return facade_width_m * 0.6
    elif facade_width_m <= 8.0:
        return facade_width_m * 0.5
    else:
        return 4.0


def get_porch_columns(era: str) -> dict:
    """Get column config by era."""
    if era == "pre-1889" or era == "1889-1903":
        return {
            "count": 2,
            "type": "turned",
            "material": "wood",
        }
    elif era == "1904-1913":
        return {
            "count": 2,
            "type": "tapered_square",
            "material": "wood",
        }
    else:  # 1914+
        return {
            "count": 2,
            "type": "square",
            "material": "wood",
        }


def infer_step_count(params: dict) -> int:
    """Infer step count from deep_facade_analysis, foundation_height_m, or default."""
    # Check deep_facade_analysis first
    deep_analysis = params.get("deep_facade_analysis", {})
    if isinstance(deep_analysis, dict):
        depth_notes = deep_analysis.get("depth_notes", {})
        if isinstance(depth_notes, dict):
            step_count = depth_notes.get("step_count")
            if step_count is not None and isinstance(step_count, int):
                return step_count

    # Infer from foundation_height_m
    foundation_height = params.get("foundation_height_m")
    if foundation_height is not None:
        # Assume 0.18m per step (typical)
        return max(2, round(foundation_height / 0.18))

    # Default
    return 2


def enrich_porch(params: dict) -> tuple[bool, str]:
    """Enrich porch dimensions if porch_present=true but dimensions missing."""
    if not params.get("porch_present"):
        return False, "no porch"

    # Check if already has width/depth/height at top level
    has_dimensions = (
        "porch_width_m" in params
        and "porch_depth_m" in params
        and "porch_height_m" in params
    )
    if has_dimensions:
        return False, "already has dimensions"

    changed = False

    # Facade width
    facade_width = params.get("facade_width_m", 5.0)

    # Floor heights
    floor_heights = params.get("floor_heights_m", [3.0])
    ground_floor_h = floor_heights[0] if floor_heights and len(floor_heights) > 0 else 3.0

    # Era for column type
    hcd_data = params.get("hcd_data", {})
    if not isinstance(hcd_data, dict):
        hcd_data = {}
    construction_date = hcd_data.get("construction_date", "")
    era = parse_era(construction_date)

    # Add top-level dimensions
    if "porch_width_m" not in params:
        params["porch_width_m"] = round(get_porch_width_m(facade_width), 2)
        changed = True

    if "porch_depth_m" not in params:
        params["porch_depth_m"] = 1.8
        changed = True

    if "porch_height_m" not in params:
        params["porch_height_m"] = round(ground_floor_h, 2)
        changed = True

    # Build porch_detail dict
    porch_detail = params.get("porch_detail", {})
    if not isinstance(porch_detail, dict):
        porch_detail = {}

    # Columns
    if "columns" not in porch_detail:
        porch_detail["columns"] = get_porch_columns(era)
        changed = True

    # Railing
    if "railing" not in porch_detail:
        porch_detail["railing"] = {
            "present": True,
            "height_m": 0.9,
            "type": "baluster",
        }
        changed = True

    # Step count
    if "step_count" not in porch_detail:
        porch_detail["step_count"] = infer_step_count(params)
        changed = True

    if changed:
        params["porch_detail"] = porch_detail

    return changed, "dimensions and columns enriched" if changed else "no changes"


def process_file(filepath: Path, apply: bool = False) -> tuple[bool, str]:
    """Process a single params file."""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            params = json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        return False, f"read error: {e}"

    # Skip non-building or already-processed
    if params.get("skipped"):
        return False, "non-building (skipped)"

    meta = params.get("_meta", {})
    if not isinstance(meta, dict):
        meta = {}

    # Enrich
    changed, msg = enrich_porch(params)

    if not changed:
        return False, msg

    # Update metadata
    now = datetime.utcnow().isoformat() + "Z"
    meta["porch_enriched"] = now
    params["_meta"] = meta

    # Write if --apply
    if apply:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(params, f, indent=2, ensure_ascii=False)
            f.write("\n")

    return True, msg


def main():
    parser = argparse.ArgumentParser(
        description="Enrich porch dimensions based on facade width and era"
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write changes to files (default: dry-run)",
    )
    parser.add_argument(
        "--params-dir",
        type=Path,
        default=PARAMS_DIR,
        help="Override params directory",
    )

    args = parser.parse_args()
    params_dir = args.params_dir

    files = sorted(params_dir.glob("*.json"))
    files = [f for f in files if not f.name.startswith("_")]

    enriched_count = 0
    skipped_count = 0
    unchanged_count = 0

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"[{mode}] Processing {len(files)} files...\n")

    for f in files:
        changed, msg = process_file(f, apply=args.apply)
        if changed:
            enriched_count += 1
            print(f"  [ENRICHED] {f.name}: {msg}")
        elif msg.startswith("non-building"):
            skipped_count += 1
        else:
            unchanged_count += 1

    print(f"\n[{mode}] Results:")
    print(f"  Enriched:   {enriched_count}")
    print(f"  Unchanged:  {unchanged_count}")
    print(f"  Skipped:    {skipped_count}")
    print(f"  Total:      {len(files)}")

    if not args.apply:
        print("\nRun with --apply to write changes.")


if __name__ == "__main__":
    main()
