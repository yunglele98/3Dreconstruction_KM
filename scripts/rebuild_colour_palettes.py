#!/usr/bin/env python3
"""
Rebuild colour_palette dicts for buildings with missing or incomplete values.

This script scans all active param files and ensures each has a complete
colour_palette dict with facade, trim, roof, and accent hex values. Missing
values are resolved using a priority-order lookup chain:

- facade hex: brick_colour_hex → deep analysis → text inference → era default
- trim hex: trim_colour_hex → deep analysis → era default
- roof hex: deep analysis → text inference → default grey
- accent hex: deep analysis → doors_detail → trim hex

Rebuilds ~1,166 of 1,241 buildings. Dry-run by default; use --apply to write.

Usage:
    python scripts/rebuild_colour_palettes.py                    # dry-run
    python scripts/rebuild_colour_palettes.py --apply            # apply changes
    python scripts/rebuild_colour_palettes.py --params-dir custom/path --apply
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


# Colour lookup tables (from enrich_skeletons.py and infer_missing_params.py)

BRICK_COLOURS = {
    "red": "#B85A3A",
    "buff": "#D4B896",
    "brown": "#7A5C44",
    "cream": "#E8D8B0",
    "orange": "#C87040",
    "grey": "#8A8A8A",
    "gray": "#8A8A8A",
    "white": "#F0EDE8",
    "yellow": "#D4B896",
    "pink": "#C87040",
}

TRIM_COLOURS_BY_ERA = {
    "pre-1889": "#3A2A20",
    "1889-1903": "#3A2A20",
    "1904-1913": "#2A2A2A",
    "1914-1930": "#F0EDE8",
    "1931+": "#F0EDE8",
}

ROOF_COLOURS = {
    "grey": "#5A5A5A",
    "gray": "#5A5A5A",
    "slate": "#4A5A5A",
    "brown": "#6A5040",
    "red": "#8A3A2A",
    "green": "#3A5A3A",
}

DEFAULT_ROOF_HEX = "#5A5A5A"


def is_valid_hex(value: str) -> bool:
    """Check if a value is a valid hex colour string."""
    if not isinstance(value, str):
        return False
    return bool(re.match(r"^#[0-9A-Fa-f]{6}$", value))


def parse_construction_date(construction_date: Optional[str]) -> str:
    """
    Parse construction_date field and map to era bucket.

    Args:
        construction_date: String like "1889-1903", "pre-1889", "1904-1913"

    Returns:
        Era key: "pre-1889", "1889-1903", "1904-1913", "1914-1930", "1931+"
    """
    if not construction_date:
        return "1889-1903"  # default

    date_str = (construction_date or "").lower().strip()

    # Exact match
    if date_str in TRIM_COLOURS_BY_ERA:
        return date_str

    # Extract year range from strings like "1889-1903" or "1904-1913"
    year_match = re.search(r"(\d{4})", date_str)
    if year_match:
        year = int(year_match.group(1))
        if year < 1889:
            return "pre-1889"
        elif year < 1904:
            return "1889-1903"
        elif year < 1914:
            return "1904-1913"
        elif year < 1931:
            return "1914-1930"
        else:
            return "1931+"

    return "1889-1903"  # default


def infer_facade_hex_from_text(facade_colour: Optional[str]) -> Optional[str]:
    """
    Infer hex colour from facade_colour text field.

    Args:
        facade_colour: Text like "red", "buff", "cream", etc.

    Returns:
        Hex colour string or None if not found.
    """
    if not facade_colour:
        return None

    colour_text = (facade_colour or "").lower().strip()

    # Direct lookup
    if colour_text in BRICK_COLOURS:
        return BRICK_COLOURS[colour_text]

    # Fuzzy match: check if any key is in the text
    for key, hex_val in BRICK_COLOURS.items():
        if key in colour_text:
            return hex_val

    return None


def infer_roof_hex_from_text(roof_colour: Optional[str]) -> Optional[str]:
    """
    Infer hex colour from roof_colour text field.

    Args:
        roof_colour: Text like "grey", "slate", "brown", etc.

    Returns:
        Hex colour string or None if not found.
    """
    if not roof_colour:
        return None

    colour_text = (roof_colour or "").lower().strip()

    # Direct lookup
    if colour_text in ROOF_COLOURS:
        return ROOF_COLOURS[colour_text]

    # Fuzzy match
    for key, hex_val in ROOF_COLOURS.items():
        if key in colour_text:
            return hex_val

    return None


def resolve_facade_hex(params: dict, stats: dict) -> Optional[str]:
    """
    Resolve facade hex with priority chain.

    Priority:
    1. facade_detail.brick_colour_hex (if facade_material is brick)
    2. deep_facade_analysis.brick_colour_hex
    3. deep_facade_analysis.colour_palette_observed.facade
    4. Text inference from facade_colour
    5. Era default

    Args:
        params: Building parameter dict.
        stats: Statistics accumulator dict.

    Returns:
        Hex colour string.
    """
    # 1. facade_detail.brick_colour_hex (if brick material)
    facade_material = (params.get("facade_material") or "").lower()
    facade_detail = params.get("facade_detail") or {}

    if "brick" in facade_material:
        brick_hex = facade_detail.get("brick_colour_hex")
        if is_valid_hex(brick_hex):
            stats["facade_from_detail_brick"] += 1
            return brick_hex

    # 2. deep_facade_analysis.brick_colour_hex
    deep = params.get("deep_facade_analysis") or {}
    deep_brick_hex = deep.get("brick_colour_hex")
    if is_valid_hex(deep_brick_hex):
        stats["facade_from_deep_brick"] += 1
        return deep_brick_hex

    # 3. deep_facade_analysis.colour_palette_observed.facade
    deep_palette = deep.get("colour_palette_observed") or {}
    deep_facade_hex = deep_palette.get("facade")
    if is_valid_hex(deep_facade_hex):
        stats["facade_from_deep_palette"] += 1
        return deep_facade_hex

    # 4. Text inference from facade_colour
    facade_colour = params.get("facade_colour")
    inferred_hex = infer_facade_hex_from_text(facade_colour)
    if inferred_hex:
        stats["facade_from_text_inference"] += 1
        return inferred_hex

    # 5. Era default
    hcd_data = params.get("hcd_data") or {}
    construction_date = hcd_data.get("construction_date")
    era = parse_construction_date(construction_date)

    # Pre-1889 and 1889-1903 both map to red brick
    if era in ("pre-1889", "1889-1903"):
        stats["facade_from_era_default_red"] += 1
        return "#B85A3A"
    elif era == "1904-1913":
        stats["facade_from_era_default_orange"] += 1
        return "#C87040"
    else:  # 1914-1930, 1931+
        stats["facade_from_era_default_buff"] += 1
        return "#D4B896"


def resolve_trim_hex(params: dict, stats: dict) -> str:
    """
    Resolve trim hex with priority chain.

    Priority:
    1. facade_detail.trim_colour_hex
    2. deep_facade_analysis.colour_palette_observed.trim
    3. Era default

    Args:
        params: Building parameter dict.
        stats: Statistics accumulator dict.

    Returns:
        Hex colour string.
    """
    facade_detail = params.get("facade_detail") or {}

    # 1. facade_detail.trim_colour_hex
    trim_hex = facade_detail.get("trim_colour_hex")
    if is_valid_hex(trim_hex):
        stats["trim_from_detail"] += 1
        return trim_hex

    # 2. deep_facade_analysis.colour_palette_observed.trim
    deep = params.get("deep_facade_analysis") or {}
    deep_palette = deep.get("colour_palette_observed") or {}
    deep_trim_hex = deep_palette.get("trim")
    if is_valid_hex(deep_trim_hex):
        stats["trim_from_deep"] += 1
        return deep_trim_hex

    # 3. Era default
    hcd_data = params.get("hcd_data") or {}
    construction_date = hcd_data.get("construction_date")
    era = parse_construction_date(construction_date)
    trim_hex = TRIM_COLOURS_BY_ERA.get(era, "#3A2A20")
    stats["trim_from_era_default"] += 1
    return trim_hex


def resolve_roof_hex(params: dict, stats: dict) -> str:
    """
    Resolve roof hex with priority chain.

    Priority:
    1. deep_facade_analysis.colour_palette_observed.roof
    2. Text inference from roof_colour
    3. Default grey

    Args:
        params: Building parameter dict.
        stats: Statistics accumulator dict.

    Returns:
        Hex colour string.
    """
    # 1. deep_facade_analysis.colour_palette_observed.roof
    deep = params.get("deep_facade_analysis") or {}
    deep_palette = deep.get("colour_palette_observed") or {}
    deep_roof_hex = deep_palette.get("roof")
    if is_valid_hex(deep_roof_hex):
        stats["roof_from_deep"] += 1
        return deep_roof_hex

    # 2. Text inference from roof_colour
    roof_colour = params.get("roof_colour")
    inferred_hex = infer_roof_hex_from_text(roof_colour)
    if inferred_hex:
        stats["roof_from_text_inference"] += 1
        return inferred_hex

    # 3. Default grey
    stats["roof_from_default"] += 1
    return DEFAULT_ROOF_HEX


def resolve_accent_hex(params: dict, stats: dict) -> str:
    """
    Resolve accent hex with priority chain.

    Priority:
    1. deep_facade_analysis.colour_palette_observed.accent
    2. doors_detail[0].colour_hex (if available)
    3. trim hex

    Args:
        params: Building parameter dict.
        stats: Statistics accumulator dict.

    Returns:
        Hex colour string.
    """
    # 1. deep_facade_analysis.colour_palette_observed.accent
    deep = params.get("deep_facade_analysis") or {}
    deep_palette = deep.get("colour_palette_observed") or {}
    deep_accent_hex = deep_palette.get("accent")
    if is_valid_hex(deep_accent_hex):
        stats["accent_from_deep"] += 1
        return deep_accent_hex

    # 2. doors_detail[0].colour_hex
    doors_detail = params.get("doors_detail") or []
    if doors_detail and len(doors_detail) > 0:
        first_door = doors_detail[0]
        door_hex = first_door.get("colour_hex")
        if is_valid_hex(door_hex):
            stats["accent_from_doors"] += 1
            return door_hex

    # 3. Trim hex (resolve it if needed)
    trim_hex = resolve_trim_hex(params, {})
    stats["accent_from_trim_default"] += 1
    return trim_hex


def is_complete_palette(colour_palette: Optional[dict]) -> bool:
    """
    Check if colour_palette has all 4 keys with valid hex values.

    Args:
        colour_palette: Dict with facade, trim, roof, accent keys.

    Returns:
        True if all 4 keys present and valid hex.
    """
    if not colour_palette or not isinstance(colour_palette, dict):
        return False

    required_keys = ("facade", "trim", "roof", "accent")
    for key in required_keys:
        if not is_valid_hex(colour_palette.get(key)):
            return False

    return True


def should_process_file(file_path: Path, params: dict) -> bool:
    """
    Check if a param file should be processed.

    Skips:
    - Files starting with _
    - Files with skipped=true
    - Non-building files

    Args:
        file_path: Path to param file.
        params: Parsed param dict.

    Returns:
        True if file should be processed.
    """
    # Skip metadata files
    if file_path.name.startswith("_"):
        return False

    # Skip skipped entries
    if params.get("skipped"):
        return False

    return True


def rebuild_colour_palettes(
    params_dir: Path,
    apply: bool = False,
    verbose: bool = False,
) -> None:
    """
    Rebuild colour_palette dicts for all active param files.

    Args:
        params_dir: Path to params directory.
        apply: If True, write changes to disk. Otherwise dry-run.
        verbose: If True, print per-building details.
    """
    params_dir = Path(params_dir).resolve()

    if not params_dir.is_dir():
        print(f"ERROR: params directory not found: {params_dir}")
        return

    # Accumulate statistics across all files
    global_stats = {
        "total_files": 0,
        "processed_files": 0,
        "skipped_files": 0,
        "incomplete_before": 0,
        "rebuilt_count": 0,
        "facade_from_detail_brick": 0,
        "facade_from_deep_brick": 0,
        "facade_from_deep_palette": 0,
        "facade_from_text_inference": 0,
        "facade_from_era_default_red": 0,
        "facade_from_era_default_orange": 0,
        "facade_from_era_default_buff": 0,
        "trim_from_detail": 0,
        "trim_from_deep": 0,
        "trim_from_era_default": 0,
        "roof_from_deep": 0,
        "roof_from_text_inference": 0,
        "roof_from_default": 0,
        "accent_from_deep": 0,
        "accent_from_doors": 0,
        "accent_from_trim_default": 0,
    }

    # Find all param JSON files
    json_files = sorted(params_dir.glob("*.json"))
    global_stats["total_files"] = len(json_files)

    print(f"Scanning {len(json_files)} files in {params_dir}")
    print(f"Mode: {'APPLY' if apply else 'DRY-RUN'}")
    print()

    for file_path in json_files:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                params = json.load(f)
        except Exception as e:
            print(f"WARN: Failed to read {file_path.name}: {e}")
            continue

        # Check if file should be processed
        if not should_process_file(file_path, params):
            global_stats["skipped_files"] += 1
            continue

        global_stats["processed_files"] += 1
        building_name = params.get("building_name", file_path.stem)

        # Check current palette completeness
        colour_palette = params.get("colour_palette") or {}
        is_complete = is_complete_palette(colour_palette)

        if is_complete:
            if verbose:
                print(f"[OK] {building_name}: palette already complete")
            continue

        global_stats["incomplete_before"] += 1

        # Resolve missing keys
        local_stats = {
            "facade_from_detail_brick": 0,
            "facade_from_deep_brick": 0,
            "facade_from_deep_palette": 0,
            "facade_from_text_inference": 0,
            "facade_from_era_default_red": 0,
            "facade_from_era_default_orange": 0,
            "facade_from_era_default_buff": 0,
            "trim_from_detail": 0,
            "trim_from_deep": 0,
            "trim_from_era_default": 0,
            "roof_from_deep": 0,
            "roof_from_text_inference": 0,
            "roof_from_default": 0,
            "accent_from_deep": 0,
            "accent_from_doors": 0,
            "accent_from_trim_default": 0,
        }

        facade_hex = resolve_facade_hex(params, local_stats)
        trim_hex = resolve_trim_hex(params, local_stats)
        roof_hex = resolve_roof_hex(params, local_stats)
        accent_hex = resolve_accent_hex(params, local_stats)

        # Ensure colour_palette dict exists
        if "colour_palette" not in params:
            params["colour_palette"] = {}

        # Update palette
        params["colour_palette"]["facade"] = facade_hex
        params["colour_palette"]["trim"] = trim_hex
        params["colour_palette"]["roof"] = roof_hex
        params["colour_palette"]["accent"] = accent_hex

        # Ensure facade_detail consistency: if facade_detail has hex, palette should match
        # (update palette FROM detail, not the reverse)
        facade_detail = params.get("facade_detail") or {}
        if is_valid_hex(facade_detail.get("brick_colour_hex")):
            params["colour_palette"]["facade"] = facade_detail["brick_colour_hex"]

        if is_valid_hex(facade_detail.get("trim_colour_hex")):
            params["colour_palette"]["trim"] = facade_detail["trim_colour_hex"]

        # Stamp _meta
        if "_meta" not in params:
            params["_meta"] = {}

        params["_meta"]["colour_palette_rebuilt"] = datetime.now(timezone.utc).isoformat()

        global_stats["rebuilt_count"] += 1

        # Accumulate source stats
        for key, val in local_stats.items():
            global_stats[key] += val

        if verbose:
            print(f"[OK] {building_name}:")
            print(f"    facade: {params['colour_palette']['facade']}")
            print(f"    trim:   {params['colour_palette']['trim']}")
            print(f"    roof:   {params['colour_palette']['roof']}")
            print(f"    accent: {params['colour_palette']['accent']}")

        # Write back if --apply
        if apply:
            try:
                with open(file_path, "w", encoding="utf-8") as f:
                    json.dump(params, f, indent=2, ensure_ascii=False)
            except Exception as e:
                print(f"ERROR: Failed to write {file_path.name}: {e}")

    # Print summary
    print()
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"Total files scanned:           {global_stats['total_files']}")
    print(f"  - Processed:                 {global_stats['processed_files']}")
    print(f"  - Skipped (metadata/etc):    {global_stats['skipped_files']}")
    print(f"Incomplete palettes found:     {global_stats['incomplete_before']}")
    print(f"Rebuilt:                       {global_stats['rebuilt_count']}")
    print()
    print("FACADE SOURCE DISTRIBUTION:")
    print(f"  - From brick_colour_hex:     {global_stats['facade_from_detail_brick']}")
    print(f"  - From deep analysis brick:  {global_stats['facade_from_deep_brick']}")
    print(f"  - From deep palette:         {global_stats['facade_from_deep_palette']}")
    print(f"  - From text inference:       {global_stats['facade_from_text_inference']}")
    print(f"  - Era default (red):         {global_stats['facade_from_era_default_red']}")
    print(f"  - Era default (orange):      {global_stats['facade_from_era_default_orange']}")
    print(f"  - Era default (buff):        {global_stats['facade_from_era_default_buff']}")
    print()
    print("TRIM SOURCE DISTRIBUTION:")
    print(f"  - From trim_colour_hex:      {global_stats['trim_from_detail']}")
    print(f"  - From deep analysis:        {global_stats['trim_from_deep']}")
    print(f"  - Era default:               {global_stats['trim_from_era_default']}")
    print()
    print("ROOF SOURCE DISTRIBUTION:")
    print(f"  - From deep analysis:        {global_stats['roof_from_deep']}")
    print(f"  - From text inference:       {global_stats['roof_from_text_inference']}")
    print(f"  - Default grey:              {global_stats['roof_from_default']}")
    print()
    print("ACCENT SOURCE DISTRIBUTION:")
    print(f"  - From deep analysis:        {global_stats['accent_from_deep']}")
    print(f"  - From doors_detail:         {global_stats['accent_from_doors']}")
    print(f"  - From trim default:         {global_stats['accent_from_trim_default']}")
    print()
    if apply:
        print(f"[OK] Changes WRITTEN to {global_stats['rebuilt_count']} files")
    else:
        print(f"(DRY-RUN: no files written. Use --apply to persist.)")


def main() -> None:
    """Parse CLI arguments and run rebuild."""
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--params-dir",
        type=str,
        default="params",
        help="Path to params directory (default: params)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply changes to disk (default: dry-run)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Print per-building details",
    )

    args = parser.parse_args()

    rebuild_colour_palettes(
        params_dir=args.params_dir,
        apply=args.apply,
        verbose=args.verbose,
    )


if __name__ == "__main__":
    main()
