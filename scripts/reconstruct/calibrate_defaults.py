#!/usr/bin/env python3
"""Stage 2 — RECONSTRUCT: Calibrate default element dimensions from scanned elements.

Analyzes the scanned element catalog to compute statistical defaults
(median dimensions, proportions) for each element type and era.
Updates the element catalog with calibrated measurements.

Usage:
    python scripts/reconstruct/calibrate_defaults.py --elements assets/elements/metadata/element_catalog.json
    python scripts/reconstruct/calibrate_defaults.py --elements assets/elements/metadata/element_catalog.json --dry-run
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def load_catalog(catalog_path: Path) -> dict:
    """Load the element catalog JSON."""
    if not catalog_path.exists():
        return {"elements": [], "calibrated": False}
    return json.loads(catalog_path.read_text(encoding="utf-8"))


def calibrate(catalog: dict) -> dict:
    """Compute calibrated defaults from scanned element measurements.

    Groups elements by type and era, computes median dimensions,
    and adds calibrated_defaults section.
    """
    elements = catalog.get("elements", [])

    # Group by element type
    by_type: dict[str, list[dict]] = {}
    for elem in elements:
        etype = elem.get("type", "unknown")
        by_type.setdefault(etype, []).append(elem)

    calibrated = {}
    for etype, elems in by_type.items():
        widths = [e["width_mm"] for e in elems if "width_mm" in e]
        heights = [e["height_mm"] for e in elems if "height_mm" in e]

        if widths:
            widths.sort()
            calibrated[etype] = {
                "count": len(elems),
                "median_width_mm": widths[len(widths) // 2],
            }
            if heights:
                heights.sort()
                calibrated[etype]["median_height_mm"] = heights[len(heights) // 2]

    catalog["calibrated_defaults"] = calibrated
    catalog["calibrated"] = True
    return catalog


def main() -> None:
    parser = argparse.ArgumentParser(description="Calibrate element defaults")
    parser.add_argument("--elements", required=True, type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    catalog = load_catalog(args.elements)
    calibrated = calibrate(catalog)

    if args.dry_run:
        defaults = calibrated.get("calibrated_defaults", {})
        print(f"[DRY RUN] Would calibrate {len(defaults)} element types")
        for etype, vals in defaults.items():
            print(f"  {etype}: {vals}")
    else:
        args.elements.parent.mkdir(parents=True, exist_ok=True)
        args.elements.write_text(
            json.dumps(calibrated, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"Calibrated {len(calibrated.get('calibrated_defaults', {}))} element types")


if __name__ == "__main__":
    main()
