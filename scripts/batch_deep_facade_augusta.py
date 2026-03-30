#!/usr/bin/env python3
"""
Backfill deep_facade_analysis for all Augusta Ave buildings.

Synthesizes deep_facade_analysis from existing param data + photo index.
Dry-run by default; pass --apply to write changes.
"""
import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PARAMS_DIR = ROOT / "params"
PHOTO_INDEX = ROOT / "PHOTOS KENSINGTON" / "csv" / "photo_address_index.csv"

STREET_KEY = "Augusta Ave"

DEFAULT_ROOF_PITCHES = {"gable": 35, "cross-gable": 35, "hip": 25, "flat": 0, "mansard": 45}


def load_photo_index() -> dict:
    """Load photo index CSV into {address: [filenames]} mapping."""
    index = {}
    if not PHOTO_INDEX.exists():
        return index
    with open(PHOTO_INDEX, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            addr = (row.get("address_or_location") or "").strip()
            fname = (row.get("filename") or "").strip()
            if addr and fname:
                index.setdefault(addr, []).append(fname)
    return index


def find_photo_for_address(address: str, photo_index: dict) -> str:
    """Find the best matching photo for an address."""
    # Direct match
    if address in photo_index:
        return photo_index[address][0]
    # Partial match
    addr_lower = address.lower()
    for key, photos in photo_index.items():
        if addr_lower in key.lower() or key.lower() in addr_lower:
            return photos[0]
    return ""


def synthesize_deep_facade(params: dict, source_photo: str) -> dict:
    """Synthesize deep_facade_analysis from existing param data."""
    floors = params.get("floors", 2)
    roof_type = (params.get("roof_type") or "flat").lower()
    facade_material = (params.get("facade_material") or "brick").lower()

    # Brick colour hex
    facade_detail = params.get("facade_detail", {})
    colour_palette = params.get("colour_palette", {})
    brick_hex = (
        facade_detail.get("brick_colour_hex")
        or colour_palette.get("facade")
        or ""
    )

    # Windows detail
    windows_detail = params.get("windows_detail", [])

    # Roof pitch
    roof_pitch = params.get("roof_pitch_deg")
    if roof_pitch is None:
        roof_pitch = DEFAULT_ROOF_PITCHES.get(roof_type, 0)

    # Decorative elements observed
    dec_elements = params.get("decorative_elements", {})
    dec_observed = [
        key for key, val in dec_elements.items()
        if isinstance(val, dict) and val.get("present")
    ]

    # Colour palette observed
    palette_observed = {}
    if colour_palette:
        for k in ("facade", "trim", "roof", "accent"):
            if colour_palette.get(k):
                palette_observed[k] = colour_palette[k]

    # Setback / depth notes
    site = params.get("site", {})
    setback = site.get("setback_m", 0)

    return {
        "source_photo": source_photo,
        "storeys_observed": floors,
        "facade_material_observed": facade_material,
        "brick_colour_hex": brick_hex,
        "windows_detail": windows_detail,
        "roof_type_observed": roof_type,
        "roof_pitch_deg": roof_pitch,
        "decorative_elements_observed": dec_observed,
        "colour_palette_observed": palette_observed,
        "condition_observed": params.get("condition", "fair"),
        "depth_notes": {
            "setback_m_est": setback,
            "foundation_height_m_est": 0.3,
        },
    }


def is_augusta_ave(params: dict, filename: str) -> bool:
    """Check if a building is on Augusta Ave."""
    site = params.get("site", {})
    street = (site.get("street") or "").lower()
    if "augusta" in street:
        return True
    name = (params.get("building_name") or filename).lower()
    return "augusta" in name


def process(apply: bool = False) -> None:
    photo_index = load_photo_index()
    print(f"Loaded photo index: {sum(len(v) for v in photo_index.values())} photos for {len(photo_index)} addresses")

    stats = {"filled": 0, "already_has": 0, "skipped": 0, "not_augusta": 0}

    for param_file in sorted(PARAMS_DIR.glob("*.json")):
        if param_file.name.startswith("_") or "backup" in param_file.name:
            continue

        with open(param_file, encoding="utf-8") as f:
            params = json.load(f)

        if params.get("skipped"):
            stats["skipped"] += 1
            continue

        if not is_augusta_ave(params, param_file.stem):
            stats["not_augusta"] += 1
            continue

        if params.get("deep_facade_analysis"):
            stats["already_has"] += 1
            continue

        address = params.get("building_name", param_file.stem.replace("_", " "))
        source_photo = find_photo_for_address(address, photo_index)

        dfa = synthesize_deep_facade(params, source_photo)

        action = "APPLY" if apply else "DRY-RUN"
        print(f"  {action}: {param_file.name}  (photo: {source_photo or 'none'})")

        if apply:
            params["deep_facade_analysis"] = dfa
            meta = params.setdefault("_meta", {})
            backfills = meta.setdefault("deep_facade_backfill", [])
            backfills.append({
                "source": "batch_deep_facade_augusta.py",
                "street": "Augusta Ave",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
            with open(param_file, "w", encoding="utf-8") as f:
                json.dump(params, f, indent=2, ensure_ascii=False)
                f.write("\n")

        stats["filled"] += 1

    print(f"\nSummary: {stats['filled']} {'filled' if apply else 'would fill'}, "
          f"{stats['already_has']} already have deep_facade_analysis, "
          f"{stats['skipped']} skipped, {stats['not_augusta']} not Augusta Ave")


def main():
    parser = argparse.ArgumentParser(description="Backfill deep_facade_analysis for Augusta Ave")
    parser.add_argument("--apply", action="store_true", help="Write changes (default: dry-run)")
    args = parser.parse_args()
    process(apply=args.apply)


if __name__ == "__main__":
    main()
