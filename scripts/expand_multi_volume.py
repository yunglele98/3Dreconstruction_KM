#!/usr/bin/env python3
"""
Expand multi-volume param arrays for wide buildings.

Identifies buildings >10m wide with >=2 floors that could benefit from
multi-volume representation, and creates a volumes[] array splitting
the facade proportionally based on heuristics.

Dry-run by default; pass --apply to write changes.
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PARAMS_DIR = ROOT / "params"

MIN_WIDTH_M = 10.0
MIN_FLOORS = 2


def should_expand(params: dict) -> bool:
    """Check if building is a candidate for multi-volume expansion."""
    if params.get("skipped"):
        return False
    if params.get("volumes"):
        return False  # already multi-volume
    width = params.get("facade_width_m", 0)
    floors = params.get("floors", 1)
    return width > MIN_WIDTH_M and floors >= MIN_FLOORS


def create_volumes(params: dict) -> list:
    """Create a volumes[] array from existing params."""
    width = params.get("facade_width_m", 10)
    depth = params.get("facade_depth_m", 10)
    floors = params.get("floors", 2)
    total_height = params.get("total_height_m", floors * 3.0)
    floor_heights = params.get("floor_heights_m", [total_height / floors] * floors)
    material = params.get("facade_material", "brick")
    colour = params.get("facade_colour", "")
    roof_type = (params.get("roof_type") or "flat").lower()
    has_storefront = params.get("has_storefront", False)

    volumes = []

    if has_storefront and floors >= 2:
        # Split into commercial ground + residential upper
        # Commercial volume: full width, ground floor only
        ground_height = floor_heights[0] if floor_heights else 3.5
        upper_heights = floor_heights[1:] if len(floor_heights) > 1 else [3.0] * (floors - 1)
        upper_height = sum(upper_heights)

        volumes = [
            {
                "id": "commercial_ground",
                "width_m": round(width, 2),
                "depth_m": round(depth, 2),
                "floor_heights_m": [round(ground_height, 2)],
                "total_height_m": round(ground_height, 2),
                "facade_colour": colour,
                "facade_material": material,
                "roof_type": "flat",
            },
            {
                "id": "residential_upper",
                "width_m": round(width, 2),
                "depth_m": round(depth, 2),
                "floor_heights_m": [round(h, 2) for h in upper_heights],
                "total_height_m": round(upper_height, 2),
                "facade_colour": colour,
                "facade_material": material,
                "roof_type": roof_type,
            },
        ]
    elif width > 12:
        # Side-by-side split for very wide buildings
        left_width = round(width * 0.5, 2)
        right_width = round(width - left_width, 2)

        volumes = [
            {
                "id": "main_left",
                "width_m": left_width,
                "depth_m": round(depth, 2),
                "floor_heights_m": [round(h, 2) for h in floor_heights],
                "total_height_m": round(total_height, 2),
                "facade_colour": colour,
                "facade_material": material,
                "roof_type": roof_type,
            },
            {
                "id": "main_right",
                "width_m": right_width,
                "depth_m": round(depth, 2),
                "floor_heights_m": [round(h, 2) for h in floor_heights],
                "total_height_m": round(total_height, 2),
                "facade_colour": colour,
                "facade_material": material,
                "roof_type": roof_type,
            },
        ]
    else:
        # Single volume with storefront+residential vertical split
        volumes = [
            {
                "id": "main",
                "width_m": round(width, 2),
                "depth_m": round(depth, 2),
                "floor_heights_m": [round(h, 2) for h in floor_heights],
                "total_height_m": round(total_height, 2),
                "facade_colour": colour,
                "facade_material": material,
                "roof_type": roof_type,
            },
        ]

    return volumes


def process(apply: bool = False, limit: int = 20) -> None:
    stats = {"expanded": 0, "already_multi": 0, "not_candidate": 0, "skipped": 0}
    candidates = []

    for param_file in sorted(PARAMS_DIR.glob("*.json")):
        if param_file.name.startswith("_") or "backup" in param_file.name:
            continue

        with open(param_file, encoding="utf-8") as f:
            params = json.load(f)

        if params.get("skipped"):
            stats["skipped"] += 1
            continue

        if params.get("volumes"):
            stats["already_multi"] += 1
            continue

        if should_expand(params):
            candidates.append((param_file, params))
        else:
            stats["not_candidate"] += 1

    # Sort by width descending, take top N
    candidates.sort(key=lambda x: x[1].get("facade_width_m", 0), reverse=True)
    candidates = candidates[:limit]

    for param_file, params in candidates:
        volumes = create_volumes(params)
        if len(volumes) < 2:
            stats["not_candidate"] += 1
            continue

        width = params.get("facade_width_m", 0)
        action = "APPLY" if apply else "DRY-RUN"
        vol_ids = [v["id"] for v in volumes]
        print(f"  {action}: {param_file.name}  width={width}m  volumes={vol_ids}")

        if apply:
            params["volumes"] = volumes
            meta = params.setdefault("_meta", {})
            fixes = meta.setdefault("handoff_fixes_applied", [])
            fixes.append({
                "fix": "expand_multi_volume",
                "volumes_created": len(volumes),
                "volume_ids": vol_ids,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
            with open(param_file, "w", encoding="utf-8") as f:
                json.dump(params, f, indent=2, ensure_ascii=False)
                f.write("\n")

        stats["expanded"] += 1

    print(f"\nSummary: {stats['expanded']} {'expanded' if apply else 'would expand'} (top {limit}), "
          f"{stats['already_multi']} already multi-volume, "
          f"{stats['not_candidate']} not candidates, "
          f"{stats['skipped']} skipped")


def main():
    parser = argparse.ArgumentParser(description="Expand multi-volume params for wide buildings")
    parser.add_argument("--apply", action="store_true", help="Write changes (default: dry-run)")
    parser.add_argument("--limit", type=int, default=20, help="Top N candidates to process (default: 20)")
    args = parser.parse_args()
    process(apply=args.apply, limit=args.limit)


if __name__ == "__main__":
    main()
