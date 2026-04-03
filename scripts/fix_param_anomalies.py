#!/usr/bin/env python3
"""Fix common parameter anomalies detected by audit scripts.

Addresses three classes of issues:
1. Floor heights unreasonably tall (>6m per floor for residential)
2. Floor heights unreasonably short (<2.2m per floor)
3. Single-floor buildings with total_height > 10m (wrong floor count)
4. Non-standard condition values

Does NOT touch: total_height_m (from LiDAR), site, city_data, hcd_data.
Recalculates floor_heights_m from total_height_m and floors.

Usage:
    python scripts/fix_param_anomalies.py --dry-run
    python scripts/fix_param_anomalies.py
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PARAMS_DIR = REPO_ROOT / "params"

# Reasonable floor height bounds (metres)
# Kensington Market: Victorian/Edwardian residential typically 2.7-3.5m per floor
MIN_FLOOR_HEIGHT = 2.2
MAX_FLOOR_HEIGHT = 6.0   # above this per-floor is clearly wrong
TYPICAL_GROUND_FLOOR = 3.2
TYPICAL_UPPER_FLOOR = 2.9

# Valid condition values
VALID_CONDITIONS = {"good", "fair", "poor"}
CONDITION_MAP = {
    "weathered": "poor",
    "deteriorated": "poor",
    "excellent": "good",
    "average": "fair",
    "moderate": "fair",
}

# Height thresholds for floor count inference
MIN_TOTAL_FOR_2_FLOORS = 5.0   # below this is definitely 1 floor
MAX_TOTAL_FOR_1_FLOOR = 4.5    # above this is probably multi-floor


def estimate_floors_from_height(total_height_m: float, has_storefront: bool = False) -> int:
    """Estimate floor count from total height."""
    if total_height_m <= 0:
        return 1
    if total_height_m < MIN_TOTAL_FOR_2_FLOORS:
        return 1
    # Ground floor is taller for commercial
    ground = TYPICAL_GROUND_FLOOR if not has_storefront else 3.8
    if total_height_m < ground + MIN_FLOOR_HEIGHT:
        return 1
    remaining = total_height_m - ground
    upper = max(1, round(remaining / TYPICAL_UPPER_FLOOR))
    return 1 + upper


def compute_floor_heights(
    total_height_m: float, floors: int, has_storefront: bool = False
) -> list[float]:
    """Compute reasonable floor heights that sum to total_height_m."""
    if floors <= 0 or total_height_m <= 0:
        return [3.0]
    if floors == 1:
        return [round(total_height_m, 2)]

    # Ground floor gets more height
    ground_ratio = 1.2 if has_storefront else 1.1
    total_parts = ground_ratio + (floors - 1)
    upper_h = total_height_m / total_parts
    ground_h = upper_h * ground_ratio

    heights = [round(ground_h, 2)]
    for _ in range(floors - 1):
        heights.append(round(upper_h, 2))

    # Adjust last floor to match total exactly
    diff = total_height_m - sum(heights)
    heights[-1] = round(heights[-1] + diff, 2)

    return heights


def fix_building(params: dict, filename: str) -> tuple[dict, list[str]]:
    """Fix anomalies in a single building's params. Returns (params, fixes_applied)."""
    fixes = []
    floors = params.get("floors", 0)
    total_h = params.get("total_height_m", 0)
    fh = params.get("floor_heights_m", [])
    has_sf = params.get("has_storefront", False)

    # Fix 1: Non-standard condition value
    condition = params.get("condition", "")
    if condition and condition.lower() not in VALID_CONDITIONS:
        mapped = CONDITION_MAP.get(condition.lower())
        if mapped:
            params["condition"] = mapped
            fixes.append(f"condition '{condition}' → '{mapped}'")

    # Fix 2: Single floor with tall height → infer floor count
    if floors == 1 and total_h > 10.0:
        new_floors = estimate_floors_from_height(total_h, has_sf)
        if new_floors > 1:
            params["floors"] = new_floors
            floors = new_floors
            fixes.append(f"floors 1 → {new_floors} (total_height={total_h}m)")

    # Fix 3: Unreasonable per-floor heights → recalculate
    if fh and floors > 0 and total_h > 0:
        max_fh = max(fh)
        avg_fh = total_h / floors

        needs_recalc = False

        # Case A: per-floor way too tall (>6m each for multi-storey)
        if max_fh > MAX_FLOOR_HEIGHT and floors > 1:
            needs_recalc = True

        # Case B: too many floors for this height (avg < 2.2m/floor)
        if avg_fh < MIN_FLOOR_HEIGHT:
            new_floors = estimate_floors_from_height(total_h, has_sf)
            if new_floors < floors:
                params["floors"] = new_floors
                fixes.append(f"floors {floors} → {new_floors} (avg floor was {avg_fh:.1f}m)")
                floors = new_floors
                needs_recalc = True

        if needs_recalc:
            new_fh = compute_floor_heights(total_h, floors, has_sf)
            old_fh = [round(h, 1) for h in fh]
            params["floor_heights_m"] = new_fh
            fixes.append(f"floor_heights {old_fh} → {new_fh}")

            # Also fix windows_per_floor length if needed
            wpf = params.get("windows_per_floor", [])
            if wpf and len(wpf) != floors:
                if len(wpf) > floors:
                    params["windows_per_floor"] = wpf[:floors]
                else:
                    while len(wpf) < floors:
                        wpf.append(wpf[-1] if wpf else 3)
                    params["windows_per_floor"] = wpf
                fixes.append(f"windows_per_floor adjusted to {floors} entries")

    return params, fixes


def run(params_dir: Path, *, dry_run: bool = False) -> dict:
    """Fix anomalies across all param files."""
    stats = {"fixed": 0, "total": 0, "fixes": []}

    for f in sorted(params_dir.glob("*.json")):
        if f.name.startswith("_"):
            continue
        data = json.loads(f.read_text(encoding="utf-8"))
        if data.get("skipped"):
            continue

        stats["total"] += 1
        data, fixes = fix_building(data, f.name)

        if fixes:
            addr = data.get("_meta", {}).get("address", f.stem)
            stats["fixed"] += 1
            stats["fixes"].append({"address": addr, "fixes": fixes})

            if not dry_run:
                meta = data.setdefault("_meta", {})
                applied = meta.setdefault("anomaly_fixes", [])
                applied.extend(fixes)
                f.write_text(
                    json.dumps(data, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )

    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Fix parameter anomalies")
    parser.add_argument("--params", type=Path, default=PARAMS_DIR)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    stats = run(args.params, dry_run=args.dry_run)

    prefix = "[DRY RUN] " if args.dry_run else ""
    print(f"{prefix}Fixed {stats['fixed']}/{stats['total']} buildings")
    for entry in stats["fixes"]:
        print(f"  {entry['address']}:")
        for fix in entry["fixes"]:
            print(f"    - {fix}")


if __name__ == "__main__":
    main()
