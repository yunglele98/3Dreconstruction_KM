#!/usr/bin/env python3
"""
Enrich doors_detail with colour_hex/material defaults and fill
foundation_height_m from typology heuristics.

Dry-run by default; pass --apply to write changes.
"""
import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PARAMS_DIR = ROOT / "params"


def get_era(params: dict) -> str:
    hcd = params.get("hcd_data", {})
    date_str = (hcd.get("construction_date") or "").strip()
    if not date_str:
        return "unknown"
    if "pre" in date_str.lower():
        return "pre-1889"
    for part in date_str.replace("-", " ").split():
        try:
            year = int(part)
            if year < 1889: return "pre-1889"
            elif year <= 1903: return "1889-1903"
            elif year <= 1913: return "1904-1913"
            else: return "1914+"
        except ValueError:
            continue
    return "unknown"


# Door colour defaults by material + era
DOOR_COLOURS_WOOD = {
    "pre-1889": ("#3A2A20", "dark brown"),
    "1889-1903": ("#2A3A2A", "dark green"),
    "1904-1913": ("#3A2A20", "dark brown"),
    "1914+": ("#4A3A2A", "medium brown"),
    "unknown": ("#3A2A20", "dark brown"),
}

DOOR_COLOURS_GLASS = ("#1A1A2A", "black frame")
DOOR_COLOURS_METAL = ("#3A3A3A", "charcoal")

# Foundation height by typology
FOUNDATION_HEIGHTS = {
    "house": 0.3,
    "commercial": 0.15,
    "institutional": 0.45,
    "row": 0.25,
    "attached": 0.25,
    "default": 0.3,
}


def is_commercial(params: dict) -> bool:
    ctx = params.get("context", {})
    btype = (ctx.get("building_type") or "").lower()
    if "commercial" in btype:
        return True
    return params.get("has_storefront", False)


def enrich_doors(params: dict) -> list:
    """Fill door colour_hex and material. Returns changes list."""
    changes = []
    era = get_era(params)
    commercial = is_commercial(params)

    for door in params.get("doors_detail", []):
        if not isinstance(door, dict):
            continue

        # Fill material if missing
        if not door.get("material"):
            door["material"] = "glass_and_aluminum" if commercial else "wood"
            changes.append(f"door.material: {door['material']}")

        # Fill colour_hex if missing
        if door.get("colour_hex"):
            continue

        material = (door.get("material") or "").lower()
        if material in ("glass", "glass_and_aluminum") or door.get("is_glass"):
            hex_val, name = DOOR_COLOURS_GLASS
        elif material in ("metal", "steel", "aluminum"):
            hex_val, name = DOOR_COLOURS_METAL
        else:
            hex_val, name = DOOR_COLOURS_WOOD.get(era, DOOR_COLOURS_WOOD["unknown"])

        door["colour_hex"] = hex_val
        door["colour"] = name
        changes.append(f"door.colour_hex: {hex_val} ({name})")

    return changes


def get_foundation_height(params: dict) -> float:
    """Get foundation height based on typology."""
    typology = (params.get("hcd_data", {}).get("typology") or "").lower()
    for key, height in FOUNDATION_HEIGHTS.items():
        if key in typology:
            return height
    return FOUNDATION_HEIGHTS["default"]


def enrich_foundations(params: dict) -> list:
    """Fill foundation_height_m. Returns changes list."""
    changes = []

    if params.get("foundation_height_m") is not None:
        return changes

    height = get_foundation_height(params)
    params["foundation_height_m"] = height
    changes.append(f"foundation_height_m: {height}")

    # Update deep_facade_analysis.depth_notes if present
    dfa = params.get("deep_facade_analysis", {})
    if isinstance(dfa, dict):
        dn = dfa.get("depth_notes", {})
        if isinstance(dn, dict):
            dn["foundation_height_m_est"] = height

    return changes


def process(apply: bool = False) -> None:
    stats = {"door_enriched": 0, "foundation_enriched": 0, "skipped": 0}
    change_counts = Counter()

    for param_file in sorted(PARAMS_DIR.glob("*.json")):
        if param_file.name.startswith("_") or "backup" in param_file.name:
            continue
        with open(param_file, encoding="utf-8") as f:
            params = json.load(f)
        if params.get("skipped"):
            stats["skipped"] += 1
            continue

        door_changes = enrich_doors(params)
        found_changes = enrich_foundations(params)
        all_changes = door_changes + found_changes

        if not all_changes:
            continue

        if door_changes:
            stats["door_enriched"] += 1
        if found_changes:
            stats["foundation_enriched"] += 1

        for c in all_changes:
            key = c.split(":")[0].strip()
            change_counts[key] += 1

        if apply:
            meta = params.setdefault("_meta", {})
            fixes = meta.setdefault("handoff_fixes_applied", [])
            fixes.append({
                "fix": "enrich_doors_and_foundations",
                "changes": all_changes[:10],
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
            with open(param_file, "w", encoding="utf-8") as f:
                json.dump(params, f, indent=2, ensure_ascii=False)
                f.write("\n")

    print(f"Doors & Foundations Enrichment")
    print(f"{'='*50}")
    print(f"Door enriched: {stats['door_enriched']}, "
          f"Foundation enriched: {stats['foundation_enriched']}, "
          f"Skipped: {stats['skipped']}")
    print(f"\nChange counts:")
    for ct, count in change_counts.most_common():
        print(f"  {ct}: {count}")


def main():
    parser = argparse.ArgumentParser(description="Enrich doors and foundations")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    process(apply=args.apply)


if __name__ == "__main__":
    main()
