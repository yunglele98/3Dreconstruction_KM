#!/usr/bin/env python3
"""
Match unmatched buildings to field photos using fuzzy address matching.

Processes ~919 unmatched param files against a photo index CSV (1,867 photos,
~1,169 unique addresses). Uses progressive matching strategies:

1. Exact match on building_name
2. Normalized match (strip suffixes, remove punctuation, lowercase)
3. Composite match (street_number + space + street)
4. Number variants (case-insensitive suffix handling like "10A" ↔ "10a")
5. Substring match (both number and street appear in photo address)
6. Fuzzy ratio (difflib SequenceMatcher > 0.85)

Output: outputs/photo_param_matches.json with matched/unmatched lists and
per-method statistics. When --apply flag is set, updates matching param files
with photo_observations.photo and deep_facade_analysis.source_photo.

Usage:
    python scripts/match_photos_to_params.py
    python scripts/match_photos_to_params.py --apply
    python scripts/match_photos_to_params.py --params-dir custom_params/ --apply
    python scripts/match_photos_to_params.py --photo-index custom.csv --dry-run
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def normalize_address(addr: str) -> str:
    """
    Normalize address for comparison.

    Strips street suffixes (St, Ave, Pl, Rd, etc.), removes punctuation,
    collapses whitespace, and lowercases.

    Args:
        addr: Raw address string

    Returns:
        Normalized address string
    """
    if not addr:
        return ""

    # Lowercase and strip
    addr = addr.strip().lower()

    # Remove common punctuation
    for char in "(),-./\\'\"":
        addr = addr.replace(char, " ")

    # Strip common street suffixes
    suffixes = [
        " street", " st", " avenue", " ave", " place", " pl",
        " road", " rd", " drive", " dr", " lane", " ln", " court", " ct"
    ]
    for suffix in suffixes:
        if addr.endswith(suffix):
            addr = addr[: -len(suffix)]
            break

    # Collapse whitespace
    addr = " ".join(addr.split())

    return addr


def load_photo_index(index_path: Path) -> dict[str, list[str]]:
    """
    Load photo index CSV and build address→filenames mapping.

    Args:
        index_path: Path to photo_address_index.csv

    Returns:
        Dict mapping normalized address to list of photo filenames
    """
    photos_by_addr = {}

    with open(index_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            filename = row.get("filename", "").strip()
            addr = row.get("address_or_location", "").strip()

            if not filename or not addr:
                continue

            norm_addr = normalize_address(addr)
            if norm_addr not in photos_by_addr:
                photos_by_addr[norm_addr] = []

            photos_by_addr[norm_addr].append(filename)

    return photos_by_addr


def find_photo(
    building_name: str,
    site_street_number: Optional[int | str],
    site_street: Optional[str],
    photos_by_addr: dict[str, list[str]],
) -> tuple[Optional[str], str]:
    """
    Find a matching photo for a building using progressive strategies.

    Tries matching strategies in order, returning (photo_filename, method_name)
    on first success. Returns (None, "") if no match found.

    Args:
        building_name: Building name (e.g., "100 Oxford St")
        site_street_number: Street number or None
        site_street: Street name or None
        photos_by_addr: Photo index dict (normalized_addr → [filenames])

    Returns:
        Tuple of (photo_filename, method_name), or (None, "") if no match
    """

    # Strategy 0: Extract leading address from composite building names
    # e.g., "374_College_St_Pho_Ha_Noi_..." → try "374 College St"
    # Matches photo index entries that START WITH the same leading address
    if building_name and len(building_name.split()) >= 4:
        parts = building_name.replace("_", " ").split()
        if len(parts) >= 3 and parts[0][0].isdigit():
            # Build prefix candidates using raw lowercase (NOT normalized,
            # because normalize strips suffixes like "st" that appear mid-key)
            for prefix_len in (3, 2):
                prefix = " ".join(parts[:prefix_len]).lower()
                for norm_addr, filenames in photos_by_addr.items():
                    if norm_addr.startswith(prefix):
                        return (filenames[0], "composite_prefix")
            # Also try extracting a trailing address (e.g., "School 242 Augusta Ave")
            # Look for a number followed by street name near the end
            for i in range(len(parts) - 2, 0, -1):
                if parts[i][0].isdigit():
                    trailing = " ".join(parts[i:i + 3]).lower()
                    for norm_addr, filenames in photos_by_addr.items():
                        if norm_addr.startswith(trailing):
                            return (filenames[0], "composite_trailing")

    # Strategy 0b: Terrace/Place/Lane alias expansion
    # "Fitzroy Ter" → also try "Fitzroy Terrace"
    ALIAS_MAP = {
        "ter": "terrace", "pl": "place", "ln": "lane",
        "ct": "court", "crt": "court", "cir": "circle",
    }
    if building_name:
        name_parts = building_name.replace("_", " ").split()
        if len(name_parts) >= 2:
            last_word = name_parts[-1].lower()
            if last_word in ALIAS_MAP:
                expanded = " ".join(name_parts[:-1]) + " " + ALIAS_MAP[last_word]
                norm_expanded = normalize_address(expanded)
                if norm_expanded in photos_by_addr:
                    return (photos_by_addr[norm_expanded][0], "alias_expansion")
                # Also try without number for generic terrace/place shots
                for norm_addr, filenames in photos_by_addr.items():
                    expanded_street = ALIAS_MAP[last_word]
                    base_street = " ".join(name_parts[1:-1]).lower()
                    if base_street and expanded_street in norm_addr and base_street in norm_addr:
                        return (filenames[0], "alias_expansion")

    # Strategy 1: Exact match on building_name
    norm_building = normalize_address(building_name)
    if norm_building in photos_by_addr:
        return (photos_by_addr[norm_building][0], "exact")

    # Strategy 2: Normalized match on building_name
    if building_name and normalize_address(building_name) in photos_by_addr:
        norm_addr = normalize_address(building_name)
        return (photos_by_addr[norm_addr][0], "normalized")

    # Strategy 3: Composite match (street_number + space + street)
    if site_street_number is not None and site_street:
        composite = f"{site_street_number} {site_street}"
        norm_composite = normalize_address(composite)
        if norm_composite in photos_by_addr:
            return (photos_by_addr[norm_composite][0], "composite")

    # Strategy 4: Number variants (e.g., "10A" ↔ "10a")
    if site_street_number is not None and site_street:
        num_str = str(site_street_number).lower()
        for norm_addr in photos_by_addr.keys():
            # Extract number and street from normalized address
            parts = norm_addr.split()
            if len(parts) > 0:
                # Check if number (with possible suffix) matches
                addr_num = parts[0].lower()
                if addr_num.replace("a", "").replace("b", "").replace("c", "") == num_str.replace(
                    "a", ""
                ).replace("b", "").replace("c", ""):
                    # Check if street name matches (case-insensitive)
                    addr_street_norm = normalize_address(site_street).lower()
                    addr_street = " ".join(parts[1:]).lower()
                    if addr_street_norm == addr_street or addr_street_norm in addr_street:
                        return (photos_by_addr[norm_addr][0], "number_variant")

    # Strategy 5: Substring (photo address contains both number and street)
    if site_street_number is not None and site_street:
        num_str = str(site_street_number)
        street_lower = site_street.lower()
        for norm_addr, filenames in photos_by_addr.items():
            if num_str in norm_addr and street_lower in norm_addr:
                return (filenames[0], "substring")

    # Strategy 6: Substring containment (fuzzy words)
    # Check if major words from building appear in photo address
    if building_name:
        norm_building = normalize_address(building_name)
        building_words = set(norm_building.split())

        # Remove number-only words for this check
        building_words = {w for w in building_words if not w.isdigit()}

        best_match = None
        best_score = 0.0

        for norm_addr, filenames in photos_by_addr.items():
            addr_words = set(norm_addr.split())
            if building_words and addr_words:
                # Score: what percentage of building words appear in address
                overlap = len(building_words & addr_words) / len(building_words)
                if overlap > best_score and overlap >= 0.5:
                    best_score = overlap
                    best_match = filenames[0]

        if best_match:
            return (best_match, "fuzzy")

    # Strategy 7: Fuzzy ratio (SequenceMatcher > 0.80)
    if building_name:
        norm_building = normalize_address(building_name)
        best_match = None
        best_ratio = 0.0

        for norm_addr, filenames in photos_by_addr.items():
            ratio = SequenceMatcher(None, norm_building, norm_addr).ratio()
            if ratio > best_ratio and ratio > 0.80:
                best_ratio = ratio
                best_match = filenames[0]

        if best_match:
            return (best_match, "fuzzy")

    return (None, "")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Match unmatched buildings to field photos using fuzzy address matching."
    )
    parser.add_argument(
        "--params-dir",
        type=Path,
        default=Path("params"),
        help="Directory containing param JSON files (default: params/)",
    )
    parser.add_argument(
        "--photo-index",
        type=Path,
        default=Path("PHOTOS KENSINGTON/csv/photo_address_index.csv"),
        help="Path to photo_address_index.csv (default: PHOTOS KENSINGTON/csv/photo_address_index.csv)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("outputs"),
        help="Output directory for results JSON (default: outputs/)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply matches to param files (default: dry-run)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show planned operations without applying (default behavior)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )

    args = parser.parse_args()

    if args.verbose:
        logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    else:
        logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")

    # Verify paths
    if not args.params_dir.is_dir():
        logger.error(f"Params directory not found: {args.params_dir}")
        return 1

    if not args.photo_index.is_file():
        logger.error(f"Photo index CSV not found: {args.photo_index}")
        return 1

    # Create output directory
    args.output_dir.mkdir(parents=True, exist_ok=True)

    # Load photo index
    logger.info(f"Loading photo index from {args.photo_index}...")
    photos_by_addr = load_photo_index(args.photo_index)
    logger.info(f"Loaded {len(photos_by_addr)} unique addresses from photo index")

    # Scan param files
    matched = []
    unmatched = []
    stats = {
        "exact": 0,
        "normalized": 0,
        "composite": 0,
        "number_variant": 0,
        "substring": 0,
        "fuzzy": 0,
        "total_matched": 0,
        "newly_matched": 0,
        "still_unmatched": 0,
        "total_active_params": 0,
    }

    logger.info(f"Scanning param files in {args.params_dir}...")

    param_files = sorted(args.params_dir.glob("*.json"))
    for param_file in param_files:
        # Skip metadata and backup files
        if param_file.name.startswith("_") or ".backup" in param_file.name:
            continue

        try:
            with open(param_file, encoding="utf-8") as f:
                params = json.load(f)
        except json.JSONDecodeError:
            logger.warning(f"Skipping invalid JSON: {param_file.name}")
            continue

        # Skip non-building photos
        if params.get("skipped"):
            continue

        stats["total_active_params"] += 1

        building_name = params.get("building_name", "")
        site = params.get("site", {})
        street_number = site.get("street_number")
        street = site.get("street")

        # Fallback: parse street_number and street from building_name
        # Handles "374-362 College St mixed-use row" → 374, "College St"
        if street_number is None and building_name:
            import re
            bn_match = re.match(r"(\d+)(?:-\d+)?\s+(.+?)(?:\s+(?:mixed|row|block|apartment|house))", building_name)
            if bn_match:
                street_number = int(bn_match.group(1))
                street = bn_match.group(2).strip()

        # Check if already has photo
        has_photo = bool(params.get("photo_observations", {}).get("photo"))

        # Try to find a photo
        photo_filename, match_method = find_photo(
            building_name, street_number, street, photos_by_addr
        )

        if photo_filename:
            stats["total_matched"] += 1
            if not has_photo:
                stats["newly_matched"] += 1
                stats[match_method] = stats.get(match_method, 0) + 1

            matched.append(
                {
                    "param_file": param_file.name,
                    "photo_file": photo_filename,
                    "match_method": match_method,
                    "confidence": 1.0 if match_method in ["exact", "composite"] else 0.85,
                    "already_had_photo": has_photo,
                }
            )

            # Apply if requested and doesn't already have photo
            if args.apply and not args.dry_run and not has_photo:
                params.setdefault("photo_observations", {})["photo"] = photo_filename
                params.setdefault("deep_facade_analysis", {})["source_photo"] = photo_filename

                # Stamp metadata
                params.setdefault("_meta", {})["photo_matched"] = {
                    "method": match_method,
                    "timestamp": datetime.utcnow().isoformat() + "Z",
                    "script": "match_photos_to_params.py",
                }

                # Write back
                with open(param_file, "w", encoding="utf-8") as f:
                    json.dump(params, f, indent=2, ensure_ascii=False)

                logger.info(f"Updated {param_file.name} with {photo_filename} ({match_method})")
        else:
            if not has_photo:
                unmatched.append(param_file.name)
                stats["still_unmatched"] += 1

    # Summary
    logger.info("")
    logger.info("=" * 70)
    logger.info("PHOTO MATCHING SUMMARY")
    logger.info("=" * 70)
    logger.info(f"Total active param files:     {stats['total_active_params']}")
    logger.info(f"Total matched:                {stats['total_matched']}")
    logger.info(f"Newly matched:                {stats['newly_matched']}")
    logger.info(f"Still unmatched:              {stats['still_unmatched']}")
    logger.info("")
    logger.info("Matches by method:")
    for method in ["exact", "normalized", "composite", "number_variant", "substring", "fuzzy"]:
        count = stats.get(method, 0)
        if count > 0:
            logger.info(f"  {method:20s}: {count:4d}")
    logger.info("=" * 70)

    if args.apply and not args.dry_run:
        logger.info(f"Applied matches to {stats['newly_matched']} param files")
    else:
        logger.info(f"DRY RUN: No changes applied (use --apply to update)")

    # Write output JSON
    output_file = args.output_dir / "photo_param_matches.json"
    output_data = {
        "matched": matched,
        "unmatched": unmatched,
        "stats": stats,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "dry_run": not (args.apply and not args.dry_run),
    }

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)

    logger.info(f"Results written to {output_file}")

    return 0


if __name__ == "__main__":
    exit(main())
