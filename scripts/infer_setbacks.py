#!/usr/bin/env python3
"""Infer building setbacks by street and typology.

For each active param where site.setback_m is missing or 0,
write to inferred_setback_m (NOT site.* which is protected).

Rules by street + typology:
- Residential streets (Lippincott, Wales, Leonard, Hickory, Glen Baillie, Fitzroy,
  Casimir, Denison, St Andrew, Kensington Pl, Leonard Pl):
  - House-form detached/semi-detached: 3.0m
  - House-form row: 1.5m
  - Default: 2.5m

- Market streets (Kensington Ave, Augusta Ave, Baldwin St, Nassau St):
  - Commercial/storefront: 0.0m
  - House with storefront: 0.0m
  - House without storefront: 1.5m

- Major streets (Spadina Ave, College St, Dundas St W, Bathurst St):
  - Commercial: 0.0m
  - Default: 0.5m

- Other/unknown: 2.0m

Also compute step_count for all buildings:
- If foundation_height_m is set: max(1, round(foundation_height_m / 0.18))
- If setback > 0 and porch_present: max(2, round(foundation_height_m / 0.18))
- If commercial/storefront at grade: 1

Usage:
    python infer_setbacks.py              # dry-run
    python infer_setbacks.py --apply      # apply changes
    python infer_setbacks.py --params-dir /path/to/params --apply
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


def extract_street(building_name: str, site_dict: dict) -> str:
    """Extract street name from building_name or site.street."""
    # Try site.street first
    if isinstance(site_dict, dict) and site_dict.get("street"):
        return site_dict.get("street", "").lower().strip()

    # Parse from building_name (format: "22 Lippincott St")
    parts = building_name.lower().split()
    if len(parts) >= 2:
        # Skip the house number
        street_parts = parts[1:]
        # Rejoin and remove trailing abbreviations
        street = " ".join(street_parts).replace(" st", "").replace(" ave", "").replace(" pl", "")
        return street.strip()

    return ""


def get_typology_type(typology_str: str) -> str:
    """Extract building type from HCD typology string.

    Returns: "detached", "semi-detached", "row", "commercial", or "unknown"
    """
    if not typology_str:
        return "unknown"

    t_lower = typology_str.lower()

    if "detached" in t_lower:
        return "detached"
    if "semi-detached" in t_lower or "semi detached" in t_lower:
        return "semi-detached"
    if "row" in t_lower:
        return "row"
    if "commercial" in t_lower or "shopfront" in t_lower:
        return "commercial"

    return "unknown"


def is_residential_street(street: str) -> bool:
    """Check if street is residential."""
    residential = {
        "lippincott",
        "wales",
        "leonard",
        "hickory",
        "glen baillie",
        "fitzroy",
        "casimir",
        "denison",
        "st andrew",
        "kensington pl",
        "leonard pl",
    }
    street_norm = street.lower().strip()
    return any(res in street_norm for res in residential)


def is_market_street(street: str) -> bool:
    """Check if street is a market street."""
    market = {
        "kensington ave",
        "augusta ave",
        "baldwin",
        "nassau",
    }
    street_norm = street.lower().strip()
    return any(mkt in street_norm for mkt in market)


def is_major_street(street: str) -> bool:
    """Check if street is a major street."""
    major = {
        "spadina",
        "college",
        "dundas",
        "bathurst",
    }
    street_norm = street.lower().strip()
    return any(maj in street_norm for maj in major)


def infer_setback(
    building_name: str,
    site_dict: dict,
    hcd_data: dict | None,
    has_storefront: bool | None,
    context_dict: dict | None,
) -> float:
    """Infer setback based on street and typology."""
    street = extract_street(building_name, site_dict or {})
    hcd = hcd_data or {}
    context = context_dict or {}

    typology = hcd.get("typology", "")
    building_type = context.get("building_type", "")
    typology_type = get_typology_type(typology)

    is_commercial = (
        has_storefront
        or "commercial" in str(building_type).lower()
        or typology_type == "commercial"
    )

    # Residential streets
    if is_residential_street(street):
        if typology_type == "detached" or typology_type == "semi-detached":
            return 3.0
        if typology_type == "row":
            return 1.5
        return 2.5

    # Market streets
    if is_market_street(street):
        if is_commercial:
            return 0.0
        if has_storefront:
            return 0.0
        return 1.5

    # Major streets
    if is_major_street(street):
        if is_commercial:
            return 0.0
        return 0.5

    # Default
    return 2.0


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


def process_params(
    params_dir: Path, apply: bool = False, dry_run: bool = True
) -> dict:
    """Process all param files and infer setbacks."""
    if dry_run and not apply:
        apply = False
    elif apply:
        dry_run = False

    results = {
        "processed": 0,
        "skipped": 0,
        "inferred": 0,
        "step_count_added": 0,
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
            building_name = params.get("building_name", param_file.stem)
            site_dict = params.get("site", {})
            hcd_data = params.get("hcd_data", {})
            context_dict = params.get("context", {})
            has_storefront = params.get("has_storefront")

            # Check if setback is missing or 0
            current_setback = site_dict.get("setback_m")
            needs_inference = current_setback is None or current_setback == 0

            if needs_inference:
                inferred = infer_setback(
                    building_name, site_dict, hcd_data, has_storefront, context_dict
                )
                params["inferred_setback_m"] = inferred
                results["inferred"] += 1

                # For step count, use the final setback (prefer site.setback_m, fallback to inferred)
                final_setback = current_setback if current_setback else inferred
            else:
                final_setback = current_setback

            # Infer step_count
            deep_facade = params.get("deep_facade_analysis", {})
            if not isinstance(deep_facade, dict):
                deep_facade = {}
                params["deep_facade_analysis"] = deep_facade

            depth_notes = deep_facade.get("depth_notes", {})
            if not isinstance(depth_notes, dict):
                depth_notes = {}
                deep_facade["depth_notes"] = depth_notes

            # Only fill if not already set
            if "step_count" not in depth_notes:
                foundation_height = deep_facade.get("depth_notes", {}).get(
                    "foundation_height_m_est"
                ) or params.get("foundation_height_m")
                porch_present = params.get("porch_present", False)

                step_count = infer_step_count(
                    foundation_height,
                    final_setback,
                    porch_present,
                    has_storefront,
                    context_dict,
                )
                depth_notes["step_count"] = step_count
                results["step_count_added"] += 1

            # Stamp metadata
            meta = params.get("_meta", {})
            meta["setback_inferred"] = timestamp
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
        description="Infer building setbacks by street and typology."
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
    print(f"INFER SETBACKS {'DRY-RUN' if is_dry_run else 'APPLY'}")
    print(f"{'=' * 70}")
    print(f"Params dir: {params_dir}")
    print(f"Mode: {'DRY-RUN' if is_dry_run else 'APPLY'}")
    print()

    results = process_params(params_dir, apply=is_apply, dry_run=is_dry_run)

    print(f"Processed: {results['processed']}")
    print(f"Skipped: {results['skipped']}")
    print(f"Setbacks inferred: {results['inferred']}")
    print(f"Step counts added: {results['step_count_added']}")

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
