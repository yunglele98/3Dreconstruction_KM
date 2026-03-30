#!/usr/bin/env python3
"""Enrich storefronts with awnings, signage, and security grilles.

Reads each building in params/ with has_storefront=true and enriches:
- AWNING: inferred from deep_facade_analysis, photo_observations, or street type
- SIGNAGE: derived from context.business_name and category
- SECURITY GRILLE: added for market spine streets (Kensington/Augusta/Baldwin)

Stores enrichment in storefront.awning, storefront.signage, storefront.security_grille.
Stamps _meta.storefront_enriched with timestamp.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

PARAMS_DIR = Path(__file__).parent.parent / "params"

MARKET_STREETS = {"kensington", "kensington ave", "augusta", "augusta ave", "baldwin", "baldwin st"}
MAJOR_COMMERCIAL_STREETS = {"spadina", "spadina ave", "college", "college st", "dundas", "dundas st"}


def get_street_from_building_name(building_name: str) -> str:
    """Extract street name from building_name (e.g., '10 Kensington Ave' -> 'Kensington Ave')."""
    parts = building_name.split()
    if len(parts) >= 2:
        # Rejoin everything after the first number
        return " ".join(parts[1:]).strip()
    return ""


def infer_awning(params: dict) -> dict:
    """Infer awning config from observations or street type."""
    # Check deep_facade_analysis first
    deep_analysis = params.get("deep_facade_analysis", {})
    if isinstance(deep_analysis, dict):
        storefront_obs = deep_analysis.get("storefront_observed", {})
        if isinstance(storefront_obs, dict) and storefront_obs.get("awning"):
            return {
                "present": True,
                "type": "fixed",
                "width_m": params.get("facade_width_m", 5.0) * 0.9,
                "projection_m": 1.2,
                "colour_hex": params.get("colour_palette", {}).get("accent") or "#2A4A2A",
            }

    # Check photo_observations
    photo_obs = params.get("photo_observations", {})
    if isinstance(photo_obs, dict):
        porch_obs = photo_obs.get("porch_present") or photo_obs.get("awning")
        if porch_obs:
            return {
                "present": True,
                "type": "fixed",
                "width_m": params.get("facade_width_m", 5.0) * 0.9,
                "projection_m": 1.2,
                "colour_hex": params.get("colour_palette", {}).get("accent") or "#2A4A2A",
            }

    # Infer from street
    building_name = params.get("building_name", "")
    street = get_street_from_building_name(building_name).lower()
    site = params.get("site", {})
    if isinstance(site, dict):
        street = street or (site.get("street") or "").lower()

    # Market spine → retractable awning, market red
    if any(mkt in street for mkt in MARKET_STREETS):
        return {
            "present": True,
            "type": "retractable",
            "width_m": params.get("facade_width_m", 5.0) * 0.8,
            "projection_m": 1.0,
            "colour_hex": "#8A2A2A",
        }

    # Major commercial → fixed, dark green
    if any(cmm in street for cmm in MAJOR_COMMERCIAL_STREETS):
        return {
            "present": True,
            "type": "fixed",
            "width_m": params.get("facade_width_m", 5.0) * 0.9,
            "projection_m": 1.2,
            "colour_hex": "#2A4A2A",
        }

    # Default: no awning
    return {"present": False}


def infer_signage(params: dict) -> dict | None:
    """Infer signage from business_name and category."""
    context = params.get("context", {})
    if not isinstance(context, dict):
        return None

    business_name = context.get("business_name") or ""
    business_cat = context.get("business_category") or ""

    if not business_name:
        return None

    # Determine signage type from category
    sig_type = "fascia"
    if any(cat in business_cat.lower() for cat in ["restaurant", "cafe", "food"]):
        sig_type = "projecting"
    elif any(cat in business_cat.lower() for cat in ["market", "grocery", "produce"]):
        sig_type = "painted_window"

    facade_width = params.get("facade_width_m", 5.0)
    return {
        "text": business_name,
        "type": sig_type,
        "width_m": min(facade_width * 0.7, 4.0),
        "height_m": 0.6,
        "colour_hex": "#F0EDE8",
    }


def infer_security_grille(params: dict) -> dict | None:
    """Add security grille for market spine streets."""
    building_name = params.get("building_name", "")
    street = get_street_from_building_name(building_name).lower()
    site = params.get("site", {})
    if isinstance(site, dict):
        street = street or (site.get("street") or "").lower()

    if any(mkt in street for mkt in MARKET_STREETS):
        return {"present": True, "type": "rolling"}

    return None


def enrich_storefront(params: dict) -> tuple[bool, str]:
    """Enrich storefront dict with awning, signage, security_grille."""
    if not params.get("has_storefront"):
        return False, "no storefront"

    storefront = params.get("storefront", {})
    if not isinstance(storefront, dict):
        storefront = {}

    changed = False

    # Awning
    if "awning" not in storefront or not storefront.get("awning"):
        awning = infer_awning(params)
        if awning and awning.get("present"):
            storefront["awning"] = awning
            changed = True

    # Signage
    if "signage" not in storefront or not storefront.get("signage"):
        signage = infer_signage(params)
        if signage:
            storefront["signage"] = signage
            changed = True

    # Security grille
    if "security_grille" not in storefront or not storefront.get("security_grille"):
        grille = infer_security_grille(params)
        if grille:
            storefront["security_grille"] = grille
            changed = True

    if changed:
        params["storefront"] = storefront

    return changed, "awning/signage/grille enriched" if changed else "no changes"


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
    changed, msg = enrich_storefront(params)

    if not changed:
        return False, msg

    # Update metadata
    now = datetime.utcnow().isoformat() + "Z"
    meta["storefront_enriched"] = now
    params["_meta"] = meta

    # Write if --apply
    if apply:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(params, f, indent=2, ensure_ascii=False)
            f.write("\n")

    return True, msg


def main():
    parser = argparse.ArgumentParser(
        description="Enrich storefronts with awnings, signage, and security grilles"
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
    changed_count = 0

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
            changed_count += 1

    print(f"\n[{mode}] Results:")
    print(f"  Enriched:   {enriched_count}")
    print(f"  Unchanged:  {changed_count}")
    print(f"  Skipped:    {skipped_count}")
    print(f"  Total:      {len(files)}")

    if not args.apply:
        print("\nRun with --apply to write changes.")


if __name__ == "__main__":
    main()
