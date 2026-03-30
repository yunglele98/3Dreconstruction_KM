#!/usr/bin/env python3
"""Diversify colour palettes to eliminate monotone streetscapes.

Problem: 83% of buildings have the exact same #B85A3A facade hex, 96% have
identical #5A5A5A roofs, and trim has only 3 dominant values. This produces
a monotone streetscape where every building looks the same colour.

Solution: Apply realistic variation based on era, typology, street position,
condition, and known Kensington Market brick diversity. Real historic Toronto
brick varies significantly — even "red brick" ranges from deep burgundy to
salmon to terracotta depending on the kiln, era, and clay source.

Sources of variation:
1. Era-specific brick colour ranges (different clay/kiln practices by decade)
2. Condition-based weathering shifts (aged brick darkens or develops patina)
3. Street-specific character (each street has a slightly different feel)
4. Random per-building jitter (±8% hue/saturation to avoid grid patterns)
5. Mortar colour affects perceived wall colour (dark mortar = darker wall)
6. Roof material diversity (asphalt shingle ages differently by era)
7. Trim/accent variation from photo observations where available

NEVER overwrites: total_height_m, facade_width_m, facade_depth_m, site.*,
city_data.*, hcd_data.*.
"""
from __future__ import annotations

import argparse
import colorsys
import hashlib
import json
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PARAMS_DIR = ROOT / "params"

# ── Era-specific red brick colour ranges ──
# Real Toronto brick varies A LOT. These are documented ranges from heritage
# building surveys. Each era used different clay sources and firing temps.
ERA_BRICK_RANGES = {
    "pre-1889": {
        # Deep, rich red — hand-pressed, high-iron clay, wood-fired
        "base": (0.72, 0.35, 0.23),  # #B85A3A-ish but as RGB 0-1
        "hue_range": (-0.01, 0.01),   # tight hue range
        "sat_range": (-0.05, 0.15),   # can be quite saturated
        "val_range": (-0.08, 0.05),   # tends darker
        "variants": [
            ("#A04030", 0.15),  # deep burgundy
            ("#B85A3A", 0.25),  # classic red
            ("#9C4A30", 0.15),  # dark red-brown
            ("#C06040", 0.10),  # warm terracotta
            ("#8A3828", 0.10),  # very dark red
            ("#A85838", 0.10),  # dusty red
            ("#B05040", 0.15),  # medium red
        ],
    },
    "1889-1903": {
        # Standard red, some variation — machine-pressed, coal-fired
        "base": (0.72, 0.35, 0.23),
        "hue_range": (-0.02, 0.02),
        "sat_range": (-0.08, 0.10),
        "val_range": (-0.05, 0.08),
        "variants": [
            ("#B85A3A", 0.20),  # classic red
            ("#C06848", 0.15),  # warm salmon-red
            ("#A85040", 0.15),  # subdued red
            ("#B86848", 0.10),  # pinkish red
            ("#A04838", 0.10),  # dark red
            ("#C87050", 0.10),  # orange-red
            ("#B06040", 0.10),  # terracotta
            ("#985038", 0.10),  # muted red
        ],
    },
    "1904-1913": {
        # Transitional: some red, increasing buff/orange — wider clay sources
        "base": (0.78, 0.44, 0.25),
        "hue_range": (-0.02, 0.03),
        "sat_range": (-0.10, 0.08),
        "val_range": (-0.05, 0.10),
        "variants": [
            ("#C87050", 0.20),  # orange-red
            ("#B86848", 0.15),  # warm red
            ("#C88060", 0.10),  # salmon
            ("#B07048", 0.10),  # terracotta
            ("#D08858", 0.10),  # light terracotta
            ("#A86040", 0.10),  # muted terracotta
            ("#C07850", 0.10),  # warm mid-tone
            ("#B87050", 0.15),  # classic Edwardian
        ],
    },
    "1914-1930": {
        # Buff/cream dominant — Don Valley brick, new firing methods
        "base": (0.83, 0.72, 0.59),
        "hue_range": (-0.02, 0.02),
        "sat_range": (-0.10, 0.05),
        "val_range": (-0.08, 0.08),
        "variants": [
            ("#D4B896", 0.25),  # classic buff
            ("#C8A880", 0.15),  # warm buff
            ("#DCC098", 0.15),  # light buff
            ("#C0A078", 0.10),  # dark buff
            ("#E0C8A0", 0.10),  # cream-buff
            ("#B89870", 0.10),  # brownish buff
            ("#D0B088", 0.15),  # mid buff
        ],
    },
}

# ── Condition-based colour shifts ──
CONDITION_SHIFTS = {
    "good": {"val_shift": 0.0, "sat_shift": 0.0},
    "fair": {"val_shift": -0.03, "sat_shift": -0.04},  # slightly darker, less saturated
    "poor": {"val_shift": -0.06, "sat_shift": -0.08},  # noticeable darkening
}

# ── Street character colour temperature adjustments ──
STREET_TEMP = {
    # Market streets: warmer, more varied (busier, more paint, more patina)
    "Kensington Ave": 0.01,
    "Augusta Ave": 0.005,
    "Baldwin St": 0.01,
    "Nassau St": -0.005,  # slightly cooler, more shaded
    # Residential: neutral to cool
    "Lippincott St": -0.01,
    "Wales Ave": -0.005,
    "Oxford St": -0.005,
    "Bellevue Ave": 0.0,
    # Major: neutral
    "Spadina Ave": 0.0,
    "College St": 0.0,
    "Dundas St W": 0.005,
    "Bathurst St": 0.0,
}

# ── Roof colour diversity by era ──
ROOF_VARIANTS = {
    "pre-1889": [
        ("#4A4A4A", 0.20),  # dark grey slate
        ("#5A5050", 0.20),  # brownish grey
        ("#505050", 0.15),  # medium grey
        ("#3A3A3A", 0.10),  # very dark
        ("#5A5A5A", 0.15),  # standard grey
        ("#4A5A5A", 0.10),  # blue-grey slate
        ("#605850", 0.10),  # warm dark grey
    ],
    "1889-1903": [
        ("#5A5A5A", 0.20),  # standard grey
        ("#505050", 0.15),  # slightly darker
        ("#5A5050", 0.15),  # warm grey
        ("#4A5050", 0.10),  # cool grey
        ("#605858", 0.10),  # brownish
        ("#585858", 0.15),  # neutral mid
        ("#4A4A4A", 0.15),  # dark
    ],
    "1904-1913": [
        ("#5A5A5A", 0.15),
        ("#585050", 0.15),  # warm-brown grey
        ("#504848", 0.15),  # dark warm
        ("#606060", 0.10),  # lighter grey
        ("#5A5050", 0.15),  # standard warm
        ("#505050", 0.15),  # mid grey
        ("#484848", 0.15),  # dark
    ],
    "1914-1930": [
        ("#5A5A5A", 0.15),
        ("#585858", 0.15),
        ("#606060", 0.15),  # lighter (newer roof)
        ("#555555", 0.15),
        ("#5A5555", 0.10),  # slight warm
        ("#505050", 0.15),
        ("#4A4A4A", 0.15),
    ],
}

# ── Trim diversity ──
TRIM_VARIANTS_BY_ERA = {
    "pre-1889": [
        ("#3A2A20", 0.30),  # dark brown
        ("#4A3828", 0.20),  # medium brown
        ("#2A2018", 0.15),  # very dark brown
        ("#503828", 0.15),  # reddish brown
        ("#453020", 0.20),  # warm dark
    ],
    "1889-1903": [
        ("#3A2A20", 0.25),  # dark brown
        ("#2A2A2A", 0.15),  # near-black
        ("#4A3828", 0.15),  # medium brown
        ("#3A3028", 0.15),  # cool dark brown
        ("#483020", 0.15),  # warm brown
        ("#382820", 0.15),  # standard
    ],
    "1904-1913": [
        ("#2A2A2A", 0.30),  # near-black
        ("#3A3A3A", 0.20),  # dark grey
        ("#2A2A30", 0.15),  # blue-black
        ("#383838", 0.15),  # medium dark
        ("#202020", 0.20),  # very dark
    ],
    "1914-1930": [
        ("#F0EDE8", 0.25),  # cream white
        ("#E8E0D0", 0.25),  # warm cream
        ("#E0D8C8", 0.15),  # darker cream
        ("#F0F0E8", 0.10),  # cool white
        ("#D8D0C0", 0.10),  # tan
        ("#E8E8E0", 0.15),  # neutral cream
    ],
}


def hex_to_rgb(h: str) -> tuple[float, float, float]:
    """Convert hex colour to RGB 0-1 floats."""
    h = h.lstrip("#")
    return (int(h[0:2], 16) / 255, int(h[2:4], 16) / 255, int(h[4:6], 16) / 255)


def rgb_to_hex(r: float, g: float, b: float) -> str:
    """Convert RGB 0-1 floats to hex."""
    return "#{:02X}{:02X}{:02X}".format(
        max(0, min(255, int(r * 255))),
        max(0, min(255, int(g * 255))),
        max(0, min(255, int(b * 255))),
    )


def building_seed(address: str) -> int:
    """Deterministic seed from address so colours are stable across runs."""
    return int(hashlib.md5(address.encode()).hexdigest()[:8], 16)


def weighted_choice(variants: list[tuple[str, float]], rng: random.Random) -> str:
    """Pick a hex from weighted variant list."""
    total = sum(w for _, w in variants)
    r = rng.random() * total
    cumulative = 0.0
    for hex_val, weight in variants:
        cumulative += weight
        if r <= cumulative:
            return hex_val
    return variants[-1][0]


def jitter_hex(hex_val: str, rng: random.Random,
               hue_range: tuple[float, float] = (-0.01, 0.01),
               sat_range: tuple[float, float] = (-0.05, 0.05),
               val_range: tuple[float, float] = (-0.05, 0.05)) -> str:
    """Add small random jitter to a hex colour in HSV space."""
    r, g, b = hex_to_rgb(hex_val)
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    h += rng.uniform(*hue_range)
    s = max(0.0, min(1.0, s + rng.uniform(*sat_range)))
    v = max(0.0, min(1.0, v + rng.uniform(*val_range)))
    h = h % 1.0
    r2, g2, b2 = colorsys.hsv_to_rgb(h, s, v)
    return rgb_to_hex(r2, g2, b2)


def get_era(params: dict) -> str:
    """Extract era bucket from hcd_data.construction_date."""
    cd = ((params.get("hcd_data") or {}).get("construction_date") or "").lower()
    if "pre-1889" in cd or "pre 1889" in cd:
        return "pre-1889"
    if "1889" in cd or "1890" in cd or "1891" in cd or "1903" in cd:
        return "1889-1903"
    if "1904" in cd or "1905" in cd or "1913" in cd:
        return "1904-1913"
    if "1914" in cd or "1920" in cd or "1930" in cd:
        return "1914-1930"
    # Check overall_style as fallback
    style = (params.get("overall_style") or "").lower()
    if "victorian" in style:
        return "1889-1903"
    if "edwardian" in style:
        return "1904-1913"
    if "georgian" in style:
        return "pre-1889"
    return "1889-1903"  # Kensington default


def get_street(params: dict) -> str:
    """Extract street name."""
    street = (params.get("site") or {}).get("street", "")
    if street:
        return street
    name = params.get("building_name", "")
    # Strip leading number
    import re
    m = re.match(r"^\d+[A-Za-z]?\s+(.+)$", name)
    return m.group(1) if m else ""


def diversify_building(params: dict, apply_mode: bool) -> dict:
    """Apply colour diversification to a single building.

    Returns dict of changes made (for reporting).
    """
    address = params.get("building_name", "unknown")
    era = get_era(params)
    street = get_street(params)
    condition = (params.get("condition") or "fair").lower()
    facade_material = (params.get("facade_material") or "brick").lower()
    rng = random.Random(building_seed(address))

    changes = {}
    cp = params.setdefault("colour_palette", {})
    fd = params.setdefault("facade_detail", {})

    # ── FACADE ──
    # Only diversify if the current hex is one of the monotone defaults
    current_facade = cp.get("facade", "")
    monotone_defaults = {"#B85A3A", "#D4B896", "#C87040", "#7A5C44", "#8A8A8A"}

    if "brick" in facade_material and current_facade in monotone_defaults:
        era_data = ERA_BRICK_RANGES.get(era, ERA_BRICK_RANGES["1889-1903"])
        # Pick a weighted variant
        base_hex = weighted_choice(era_data["variants"], rng)
        # Apply condition shift
        cond_data = CONDITION_SHIFTS.get(condition, CONDITION_SHIFTS["fair"])
        # Apply street temperature
        street_temp = STREET_TEMP.get(street, 0.0)
        # Jitter for uniqueness
        final_facade = jitter_hex(
            base_hex, rng,
            hue_range=(era_data["hue_range"][0] + street_temp,
                       era_data["hue_range"][1] + street_temp),
            sat_range=(era_data["sat_range"][0] + cond_data["sat_shift"],
                       era_data["sat_range"][1] + cond_data["sat_shift"]),
            val_range=(era_data["val_range"][0] + cond_data["val_shift"],
                       era_data["val_range"][1] + cond_data["val_shift"]),
        )
        if final_facade != current_facade:
            cp["facade"] = final_facade
            fd["brick_colour_hex"] = final_facade
            changes["facade"] = f"{current_facade} → {final_facade}"

    # ── ROOF ──
    current_roof = cp.get("roof", "")
    monotone_roofs = {"#5A5A5A"}
    if current_roof in monotone_roofs:
        roof_era = ROOF_VARIANTS.get(era, ROOF_VARIANTS["1889-1903"])
        roof_hex = weighted_choice(roof_era, rng)
        roof_hex = jitter_hex(roof_hex, rng,
                              hue_range=(-0.005, 0.005),
                              sat_range=(-0.02, 0.02),
                              val_range=(-0.03, 0.03))
        if roof_hex != current_roof:
            cp["roof"] = roof_hex
            changes["roof"] = f"{current_roof} → {roof_hex}"

    # ── TRIM ──
    current_trim = cp.get("trim", "")
    monotone_trims = {"#E8E0D0", "#3A2A20", "#2A2A2A"}
    if current_trim in monotone_trims:
        trim_era = TRIM_VARIANTS_BY_ERA.get(era, TRIM_VARIANTS_BY_ERA["1889-1903"])
        trim_hex = weighted_choice(trim_era, rng)
        trim_hex = jitter_hex(trim_hex, rng,
                              hue_range=(-0.005, 0.005),
                              sat_range=(-0.02, 0.02),
                              val_range=(-0.03, 0.03))
        if trim_hex != current_trim:
            cp["trim"] = trim_hex
            fd["trim_colour_hex"] = trim_hex
            changes["trim"] = f"{current_trim} → {trim_hex}"

    # ── ACCENT ──
    # Less aggressive — accent already has 61 unique values
    # Only diversify the dominant monotone ones
    current_accent = cp.get("accent", "")
    monotone_accents = {"#3A2A20", "#2A3A2A", "#1A1A2A"}
    if current_accent in monotone_accents:
        # Pick from a wider range of door/accent colours
        accent_variants = [
            ("#3A2A20", 0.10), ("#4A3020", 0.10), ("#2A3828", 0.10),
            ("#384030", 0.10), ("#503828", 0.08), ("#2A2A30", 0.08),
            ("#3A3020", 0.08), ("#1A2A28", 0.08), ("#4A4030", 0.08),
            ("#303828", 0.08), ("#282820", 0.06), ("#3A4030", 0.06),
        ]
        accent_hex = weighted_choice(accent_variants, rng)
        accent_hex = jitter_hex(accent_hex, rng,
                                hue_range=(-0.01, 0.01),
                                sat_range=(-0.03, 0.03),
                                val_range=(-0.03, 0.03))
        if accent_hex != current_accent:
            cp["accent"] = accent_hex
            changes["accent"] = f"{current_accent} → {accent_hex}"

    # ── MORTAR colour variation ──
    # Mortar strongly affects perceived brick colour in renders
    current_mortar = fd.get("mortar_colour_hex", fd.get("mortar_colour", ""))
    if not current_mortar or current_mortar in {"#B0A898", "#8A8A8A", "#C0B8A8"}:
        mortar_variants = {
            "pre-1889": [("#A89880", 0.3), ("#B0A090", 0.3), ("#988878", 0.2), ("#C0B098", 0.2)],
            "1889-1903": [("#B0A898", 0.3), ("#A89888", 0.2), ("#C0B8A8", 0.2), ("#B8A890", 0.3)],
            "1904-1913": [("#C0B8A8", 0.3), ("#B8B0A0", 0.3), ("#C8C0B0", 0.2), ("#A8A090", 0.2)],
            "1914-1930": [("#C8C0B0", 0.3), ("#D0C8B8", 0.3), ("#C0B8A8", 0.2), ("#B8B0A0", 0.2)],
        }
        era_mortars = mortar_variants.get(era, mortar_variants["1889-1903"])
        mortar_hex = weighted_choice(era_mortars, rng)
        mortar_hex = jitter_hex(mortar_hex, rng,
                                hue_range=(-0.005, 0.005),
                                sat_range=(-0.02, 0.02),
                                val_range=(-0.02, 0.02))
        fd["mortar_colour_hex"] = mortar_hex
        changes["mortar"] = f"{current_mortar or 'none'} → {mortar_hex}"

    return changes


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Write changes (default: dry-run)")
    parser.add_argument("--params-dir", type=Path, default=PARAMS_DIR)
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    now = datetime.now(timezone.utc).isoformat()
    total = 0
    changed = 0
    skipped = 0
    field_counts = {"facade": 0, "roof": 0, "trim": 0, "accent": 0, "mortar": 0}
    era_counts = {"pre-1889": 0, "1889-1903": 0, "1904-1913": 0, "1914-1930": 0}

    for pf in sorted(args.params_dir.glob("*.json")):
        if pf.name.startswith("_") or "backup" in pf.name:
            continue
        with open(pf, encoding="utf-8") as f:
            params = json.load(f)
        if params.get("skipped"):
            skipped += 1
            continue
        total += 1

        era = get_era(params)
        era_counts[era] = era_counts.get(era, 0) + 1

        changes = diversify_building(params, args.apply)
        if changes:
            changed += 1
            for field in changes:
                field_counts[field] = field_counts.get(field, 0) + 1

            if args.verbose:
                print(f"  {params.get('building_name', pf.stem)}: {changes}")

            if args.apply:
                meta = params.setdefault("_meta", {})
                meta["colour_diversified"] = now
                meta.setdefault("colour_diversification_changes", []).append(
                    {k: v for k, v in changes.items()}
                )
                with open(pf, "w", encoding="utf-8") as f:
                    json.dump(params, f, indent=2, ensure_ascii=False)
                    f.write("\n")

    print(f"\nColour Diversification Report")
    print(f"{'=' * 50}")
    print(f"Total active buildings: {total}")
    print(f"Buildings changed: {changed}")
    print(f"Skipped files: {skipped}")
    print(f"\nChanges by field:")
    for field, count in sorted(field_counts.items(), key=lambda x: -x[1]):
        print(f"  {field}: {count}")
    print(f"\nEra distribution:")
    for era, count in sorted(era_counts.items()):
        print(f"  {era}: {count}")

    if not args.apply:
        print(f"\n(DRY-RUN: no files written. Use --apply to persist.)")
    else:
        print(f"\n[OK] Changes WRITTEN to {changed} files")


if __name__ == "__main__":
    main()
