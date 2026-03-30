#!/usr/bin/env python3
"""
Enrich windows_detail entries with era-aware defaults for arch_type, glazing,
frame_colour, sill_height_m, width_m, height_m. Also normalizes window_type.

Dry-run by default; pass --apply to write changes.
"""
import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PARAMS_DIR = ROOT / "params"

# Era detection helper
def get_era(params: dict) -> str:
    """Return era key from hcd_data.construction_date."""
    hcd = params.get("hcd_data", {})
    date_str = (hcd.get("construction_date") or "").strip()
    if not date_str:
        return "unknown"
    if "pre" in date_str.lower() or date_str.startswith("Pre"):
        return "pre-1889"
    # Try to extract a year
    for part in date_str.replace("-", " ").split():
        try:
            year = int(part)
            if year < 1889:
                return "pre-1889"
            elif year <= 1903:
                return "1889-1903"
            elif year <= 1913:
                return "1904-1913"
            elif year <= 1930:
                return "1914-1930"
            else:
                return "1930+"
        except ValueError:
            continue
    return "unknown"


# Arch type defaults by era
ARCH_TYPE_BY_ERA = {
    "pre-1889": {"ground": "segmental", "upper": "segmental"},
    "1889-1903": {"ground": "segmental", "upper": "flat"},
    "1904-1913": {"ground": "flat", "upper": "flat"},
    "1914-1930": {"ground": "flat", "upper": "flat"},
    "1930+": {"ground": "flat", "upper": "flat"},
    "unknown": {"ground": "flat", "upper": "flat"},
}

# Glazing defaults by era
GLAZING_BY_ERA = {
    "pre-1889": "2-over-2",
    "1889-1903": "2-over-2",
    "1904-1913": "1-over-1",
    "1914-1930": "1-over-1",
    "1930+": "1-over-1",
    "unknown": "1-over-1",
}

# Frame colour defaults by era
FRAME_COLOUR_BY_ERA = {
    "pre-1889": "dark",
    "1889-1903": "dark",
    "1904-1913": "dark",
    "1914-1930": "white",
    "1930+": "white",
    "unknown": "white",
}

# Window type normalization
WINDOW_TYPE_NORMALIZE = {
    "Double-hung sash": "double_hung",
    "double-hung sash": "double_hung",
    "double hung": "double_hung",
    "Double hung": "double_hung",
    "double-hung": "double_hung",
}

# Era-based default window type
WINDOW_TYPE_BY_ERA = {
    "pre-1889": "double_hung",
    "1889-1903": "double_hung",
    "1904-1913": "double_hung",
    "1914-1930": "casement",
    "1930+": "casement",
    "unknown": "double_hung",
}


def has_voussoirs(params: dict) -> bool:
    """Check if building has stone voussoirs present."""
    dec = params.get("decorative_elements", {})
    sv = dec.get("stone_voussoirs", {})
    return isinstance(sv, dict) and sv.get("present", False)


def enrich_windows(params: dict) -> list:
    """Enrich windows_detail entries. Returns list of changes made."""
    changes = []
    era = get_era(params)
    voussoirs = has_voussoirs(params)

    # Default dimensions from top-level or generation_defaults
    default_width = params.get("window_width_m") or 0.85
    default_height = params.get("window_height_m") or 1.3
    default_sill = 0.8

    # Normalize top-level window_type
    wt = params.get("window_type", "")
    if wt in WINDOW_TYPE_NORMALIZE:
        params["window_type"] = WINDOW_TYPE_NORMALIZE[wt]
        changes.append(f"window_type: {wt!r} -> {params['window_type']!r}")
    elif not wt or wt == "":
        params["window_type"] = WINDOW_TYPE_BY_ERA.get(era, "double_hung")
        changes.append(f"window_type: '' -> {params['window_type']!r}")

    windows_detail = params.get("windows_detail", [])
    for floor_idx, floor_entry in enumerate(windows_detail):
        if not isinstance(floor_entry, dict):
            continue
        floor_label = str(floor_entry.get("floor") or "").lower()
        is_ground = "ground" in floor_label or floor_idx == 0

        for win in floor_entry.get("windows", []):
            # Normalize window type in entry
            win_type = win.get("type", "")
            if win_type in WINDOW_TYPE_NORMALIZE:
                win["type"] = WINDOW_TYPE_NORMALIZE[win_type]
                changes.append(f"win.type: {win_type!r} -> {win['type']!r}")

            # arch_type
            if "arch_type" not in win or win["arch_type"] is None:
                if voussoirs:
                    win["arch_type"] = "segmental"
                else:
                    era_arches = ARCH_TYPE_BY_ERA.get(era, ARCH_TYPE_BY_ERA["unknown"])
                    win["arch_type"] = era_arches["ground"] if is_ground else era_arches["upper"]
                if "arch_type" not in [c.split(":")[0].strip() for c in changes]:
                    changes.append(f"arch_type filled ({era})")

            # glazing
            if "glazing" not in win or win["glazing"] is None:
                effective_type = (win.get("type") or params.get("window_type") or "").lower()
                if effective_type in ("casement", "fixed"):
                    win["glazing"] = "single-pane"
                else:
                    win["glazing"] = GLAZING_BY_ERA.get(era, "1-over-1")
                if "glazing" not in [c.split(":")[0].strip() for c in changes]:
                    changes.append(f"glazing filled ({era})")

            # frame_colour
            if "frame_colour" not in win or win["frame_colour"] is None:
                win["frame_colour"] = FRAME_COLOUR_BY_ERA.get(era, "white")
                if "frame_colour" not in [c.split(":")[0].strip() for c in changes]:
                    changes.append(f"frame_colour filled ({era})")

            # sill_height_m
            if "sill_height_m" not in win or win["sill_height_m"] is None:
                win["sill_height_m"] = default_sill

            # width_m
            if "width_m" not in win or win["width_m"] is None:
                win["width_m"] = default_width

            # height_m
            if "height_m" not in win or win["height_m"] is None:
                win["height_m"] = default_height

    return changes


def validate_windows(params: dict) -> list:
    """Check that all window entries have required fields."""
    missing = []
    required = ("count", "type", "arch_type", "glazing", "frame_colour", "width_m", "height_m")
    for floor_entry in params.get("windows_detail", []):
        for win in floor_entry.get("windows", []):
            for field in required:
                if field not in win or win[field] is None:
                    missing.append(f"{floor_entry.get('floor', '?')}: missing {field}")
    return missing


def process(apply: bool = False) -> None:
    stats = {"enriched": 0, "skipped": 0, "no_change": 0, "validation_fails": 0}
    type_changes = Counter()

    for param_file in sorted(PARAMS_DIR.glob("*.json")):
        if param_file.name.startswith("_") or "backup" in param_file.name:
            continue
        with open(param_file, encoding="utf-8") as f:
            params = json.load(f)
        if params.get("skipped"):
            stats["skipped"] += 1
            continue

        changes = enrich_windows(params)

        if not changes:
            stats["no_change"] += 1
            continue

        for c in changes:
            key = c.split(":")[0].strip() if ":" in c else c[:20]
            type_changes[key] += 1

        # Validate
        still_missing = validate_windows(params)
        if still_missing:
            stats["validation_fails"] += 1

        action = "APPLY" if apply else "DRY-RUN"
        if apply:
            meta = params.setdefault("_meta", {})
            fixes = meta.setdefault("handoff_fixes_applied", [])
            fixes.append({
                "fix": "enrich_window_details",
                "changes": changes[:10],  # cap to avoid huge meta
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
            with open(param_file, "w", encoding="utf-8") as f:
                json.dump(params, f, indent=2, ensure_ascii=False)
                f.write("\n")

        stats["enriched"] += 1

    print(f"Window Detail Enrichment")
    print(f"{'='*50}")
    print(f"Enriched: {stats['enriched']}, No change: {stats['no_change']}, "
          f"Skipped: {stats['skipped']}, Validation fails: {stats['validation_fails']}")
    print(f"\nChange types:")
    for ct, count in type_changes.most_common():
        print(f"  {ct}: {count}")


def main():
    parser = argparse.ArgumentParser(description="Enrich window details with era-aware defaults")
    parser.add_argument("--apply", action="store_true", help="Write changes (default: dry-run)")
    args = parser.parse_args()
    process(apply=args.apply)


if __name__ == "__main__":
    main()
