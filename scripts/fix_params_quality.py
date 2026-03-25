#!/usr/bin/env python3
"""Bulk-fix common low-risk quality issues in params/*.json."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

try:
    import psycopg2
except Exception:  # noqa: BLE001
    psycopg2 = None

try:
    from db_config import DB_CONFIG
except Exception:  # noqa: BLE001
    DB_CONFIG = None

ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_PARAMS_DIR = ROOT_DIR / "params"

MATERIAL_LIKE_WORDS = {
    "brick",
    "stucco",
    "clapboard",
    "wood",
    "vinyl",
    "siding",
    "stone",
    "concrete",
    "masonry",
    "glass",
    "paint",
    "metal",
    "other",
    "mixed",
    "unknown",
}
ALLOWED_CONDITIONS = {"good", "fair", "poor"}


def normalize_text(value: Any) -> str:
    return "" if value is None else str(value).strip().lower()


def to_float(value: Any) -> float | None:
    try:
        if value is None or isinstance(value, bool):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def to_int(value: Any) -> int | None:
    try:
        if value is None or isinstance(value, bool):
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def canonical_material(raw: Any) -> str:
    text = normalize_text(raw).replace("_", " ")
    if not text:
        return ""
    if "brick" in text:
        return "brick"
    if "stucco" in text or "render" in text:
        return "stucco"
    if "clapboard" in text:
        return "clapboard"
    if "vinyl" in text:
        return "vinyl siding"
    if "wood" in text and "siding" in text:
        return "wood siding"
    if text == "wood":
        return "wood siding"
    if "stone" in text or "limestone" in text or "sandstone" in text:
        return "stone"
    if "concrete" in text or "cement" in text:
        return "concrete"
    if "mixed" in text:
        return "mixed masonry"
    if "glass" in text:
        return "glass"
    if "paint" in text:
        return "painted"
    if "metal" in text:
        return "metal"
    if "other" in text or "unknown" in text:
        return "brick"
    return text


def material_label(canonical: str) -> str:
    mapping = {
        "brick": "Brick",
        "stucco": "Stucco",
        "clapboard": "Clapboard",
        "wood siding": "Clapboard",
        "vinyl siding": "Vinyl siding",
        "stone": "Stone",
        "concrete": "Concrete",
        "mixed masonry": "Mixed masonry",
        "painted": "Painted",
        "glass": "Glass",
        "metal": "Metal",
    }
    return mapping.get(canonical, "Brick")


def default_facade_colour(material: str) -> str:
    m = normalize_text(material)
    if "brick" in m:
        return "red brick"
    if "stucco" in m:
        return "off-white stucco"
    if "clapboard" in m or "wood" in m:
        return "painted wood"
    if "vinyl" in m:
        return "light vinyl"
    if "stone" in m:
        return "buff stone"
    if "concrete" in m:
        return "grey concrete"
    if "glass" in m:
        return "glass and metal"
    if "mixed" in m:
        return "varied brick and stone"
    return "neutral"


def likely_material_label(text: str) -> bool:
    clean = normalize_text(text).replace("_", " ")
    if not clean:
        return False
    return len(clean) <= 24 and any(word in clean for word in MATERIAL_LIKE_WORDS)


def infer_windows_per_floor(floors: int, facade_width_m: float, has_storefront: bool) -> list[int]:
    bays = max(1, round(facade_width_m / 2.5)) if facade_width_m > 0 else 2
    out: list[int] = []
    for i in range(max(1, floors)):
        if i == 0 and has_storefront:
            out.append(0)
        elif i == max(1, floors) - 1 and floors >= 3:
            out.append(max(1, bays - 1))
        else:
            out.append(bays)
    return out


def infer_floor_heights(floors: int, total_height: float, has_storefront: bool) -> list[float]:
    floors = max(1, floors)
    if total_height <= 0:
        if has_storefront:
            if floors == 1:
                return [3.8]
            return [3.8] + [2.8] * (floors - 1)
        if floors == 1:
            return [3.2]
        return [3.1] + [2.8] * (floors - 1)

    avg = total_height / floors
    heights: list[float] = []
    for i in range(floors):
        if i == 0 and has_storefront:
            heights.append(round(min(avg * 1.3, 4.5), 1))
        elif i == 0:
            heights.append(round(min(avg * 1.1, 3.5), 1))
        elif i == floors - 1 and floors >= 3:
            heights.append(round(avg * 0.85, 1))
        else:
            heights.append(round(avg, 1))

    current_sum = sum(heights)
    if current_sum > 0 and abs(current_sum - total_height) > 0.5:
        factor = total_height / current_sum
        heights = [round(h * factor, 1) for h in heights]
    return heights


def floor_heights_suspicious(floor_heights: list[Any], floors: int, total_height: float) -> bool:
    values = [to_float(v) for v in floor_heights]
    if len(values) != floors:
        return True
    if any(v is None or v <= 0 for v in values):
        return True
    heights = [v for v in values if v is not None]
    if not heights:
        return True
    h_min = min(heights)
    h_max = max(heights)
    if h_max > 8.0 or (h_min > 0 and h_max / h_min > 2.5 and h_max > 5.5):
        return True
    if total_height > 0:
        h_sum = sum(heights)
        if abs(total_height - h_sum) > max(1.5, h_sum * 0.35):
            return True
        if total_height < h_max:
            return True
    return False


def infer_has_storefront(data: dict[str, Any], storefront_obj: dict[str, Any] | None) -> bool:
    if storefront_obj is not None:
        return True
    if isinstance(data.get("has_storefront"), bool) and bool(data["has_storefront"]):
        return True
    context = data.get("context") if isinstance(data.get("context"), dict) else {}
    general_use = normalize_text(context.get("general_use"))
    commercial_use = normalize_text(context.get("commercial_use"))
    if general_use in {"commercial", "mixed use"}:
        return True
    if commercial_use and commercial_use not in {"n/a", "na", "none", "null"}:
        return True
    return False


def resolve_site_from_db(
    building_name: str,
    file_stem: str,
    db_conn: Any,
    site_cache: dict[str, tuple[float | None, float | None, Any, Any] | None],
) -> tuple[float | None, float | None, Any, Any] | None:
    if not building_name and not file_stem:
        return None
    cache_key = f"{building_name}|{file_stem}"
    if cache_key in site_cache:
        return site_cache[cache_key]
    if db_conn is None:
        site_cache[cache_key] = None
        return None

    def _query_prefix(prefix: str):
        cur = db_conn.cursor()
        cur.execute(
            """
            SELECT
                ST_X(geom) AS lon,
                ST_Y(geom) AS lat,
                ba_street,
                ba_street_number
            FROM building_assessment
            WHERE "ADDRESS_FULL" ILIKE %s
              AND geom IS NOT NULL
            ORDER BY LENGTH("ADDRESS_FULL") ASC
            LIMIT 1
            """,
            (prefix + "%",),
        )
        row = cur.fetchone()
        cur.close()
        return row

    def _query_exact(addr: str):
        cur = db_conn.cursor()
        cur.execute(
            """
            SELECT
                ST_X(geom) AS lon,
                ST_Y(geom) AS lat,
                ba_street,
                ba_street_number
            FROM building_assessment
            WHERE "ADDRESS_FULL" = %s
              AND geom IS NOT NULL
            LIMIT 1
            """,
            (addr,),
        )
        row = cur.fetchone()
        cur.close()
        return row

    row = None
    candidates = []
    if building_name:
        candidates.append(building_name)
    if file_stem:
        candidates.append(file_stem.replace("_", " "))
    for cand in candidates:
        row = _query_exact(cand)
        if row:
            break

    if not row:
        prefix = ""
        range_num_a = ""
        range_num_b = ""
        street = ""
        for cand in candidates:
            m = re.match(
                r"^(\d+[A-Za-z]?(?:-\d+[A-Za-z]?)?)\s+([A-Za-z][A-Za-z\s]+?\s(?:St|Street|Ave|Avenue|Rd|Road|Blvd|Boulevard|Sq|Square|Pl|Place|Terr|Terrace|Lane|Ln|Way|Dr|Drive|Cres|Crescent|Ct|Court|Pkwy|Parkway))\b",
                cand.strip(),
                flags=re.IGNORECASE,
            )
            if m:
                prefix = f"{m.group(1)} {m.group(2)}"
                street = m.group(2)
                if "-" in m.group(1):
                    parts = m.group(1).split("-", 1)
                    range_num_a = parts[0]
                    range_num_b = parts[1]
                break
        if prefix:
            row = _query_prefix(prefix)
            if not row and range_num_a and street:
                row = _query_prefix(f"{range_num_a} {street}")
            if not row and range_num_b and street:
                row = _query_prefix(f"{range_num_b} {street}")

    site_cache[cache_key] = row if row else None
    return site_cache[cache_key]


def fix_file(
    path: Path,
    apply_changes: bool,
    db_conn: Any = None,
    site_cache: dict[str, tuple[float | None, float | None, Any, Any] | None] | None = None,
) -> Counter[str]:
    stats: Counter[str] = Counter()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        stats["parse_error"] += 1
        return stats

    if not isinstance(data, dict):
        stats["not_object"] += 1
        return stats

    if data.get("skipped") is True or data.get("skip") is True or normalize_text(data.get("reason")):
        stats["skipped"] += 1
        return stats

    changed = False
    if site_cache is None:
        site_cache = {}

    canonical = canonical_material(data.get("facade_material"))
    new_material = material_label(canonical)
    if normalize_text(data.get("facade_material")) != normalize_text(new_material):
        data["facade_material"] = new_material
        changed = True
        stats["facade_material_normalized"] += 1

    facade_colour = data.get("facade_colour")
    if not normalize_text(facade_colour) or likely_material_label(str(facade_colour)):
        data["facade_colour"] = default_facade_colour(data.get("facade_material", ""))
        changed = True
        stats["facade_colour_defaulted"] += 1

    roof_type = normalize_text(data.get("roof_type"))
    pitch = to_float(data.get("roof_pitch_deg"))
    roof_pitch_defaults = {
        "flat": 0,
        "hip": 30,
        "mansard": 70,
        "cross-gable": 45,
        "cross gable": 45,
        "gable": 40,
    }
    if pitch is None or pitch < 0 or pitch > 90:
        default_pitch = 35
        for key, val in roof_pitch_defaults.items():
            if key in roof_type:
                default_pitch = val
                break
        data["roof_pitch_deg"] = default_pitch
        changed = True
        stats["roof_pitch_fixed"] += 1

    floors_raw = to_int(data.get("floors"))
    floors = floors_raw if floors_raw and floors_raw > 0 else 1
    fw = to_float(data.get("facade_width_m")) or 5.5
    fd = to_float(data.get("facade_depth_m")) or 10.0
    storefront_obj = data.get("storefront") if isinstance(data.get("storefront"), dict) else None
    has_storefront = infer_has_storefront(data, storefront_obj)
    city = data.get("city_data") if isinstance(data.get("city_data"), dict) else {}
    site = data.get("site") if isinstance(data.get("site"), dict) else {}
    if not isinstance(data.get("site"), dict):
        data["site"] = site
        changed = True
        stats["site_object_created"] += 1

    lon = to_float(site.get("lon"))
    lat = to_float(site.get("lat"))
    if lon is None or lat is None:
        row = resolve_site_from_db(str(data.get("building_name") or ""), path.stem, db_conn, site_cache)
        if row:
            db_lon, db_lat, db_street, db_number = row
            if lon is None and db_lon is not None:
                site["lon"] = db_lon
                changed = True
                stats["site_lon_filled_from_db"] += 1
            if lat is None and db_lat is not None:
                site["lat"] = db_lat
                changed = True
                stats["site_lat_filled_from_db"] += 1
            if not normalize_text(site.get("street")) and db_street:
                site["street"] = db_street
                changed = True
                stats["site_street_filled_from_db"] += 1
            if site.get("street_number") is None and db_number is not None:
                site["street_number"] = db_number
                changed = True
                stats["site_street_number_filled_from_db"] += 1

    lot_width_ft = to_float(city.get("lot_width_ft"))
    if lot_width_ft and fw > 0:
        lot_width_m = lot_width_ft * 0.3048
        max_width = lot_width_m * 1.35
        if fw > max_width:
            data["facade_width_m"] = round(max_width, 1)
            fw = data["facade_width_m"]
            changed = True
            stats["facade_width_clamped_to_lot"] += 1

    lot_depth_ft = to_float(city.get("lot_depth_ft"))
    if lot_depth_ft and fd > 0:
        lot_depth_m = lot_depth_ft * 0.3048
        max_depth = lot_depth_m * 1.35
        if fd > max_depth:
            data["facade_depth_m"] = round(max_depth, 1)
            fd = data["facade_depth_m"]
            changed = True
            stats["facade_depth_clamped_to_lot"] += 1

    if data.get("has_storefront") is not has_storefront:
        data["has_storefront"] = has_storefront
        changed = True
        stats["has_storefront_normalized"] += 1

    windows_per_floor = data.get("windows_per_floor")
    if floors_raw is None and isinstance(windows_per_floor, list) and len(windows_per_floor) > 1:
        data["floors"] = len(windows_per_floor)
        floors = len(windows_per_floor)
        changed = True
        stats["floors_inferred_from_windows"] += 1

    if not isinstance(windows_per_floor, list) or not windows_per_floor:
        data["windows_per_floor"] = infer_windows_per_floor(floors, fw, has_storefront)
        changed = True
        stats["windows_per_floor_inferred"] += 1
    else:
        cleaned = []
        bad = False
        for value in windows_per_floor:
            iv = to_int(value)
            if iv is None:
                iv = 0
                bad = True
            iv = max(0, min(20, iv))
            cleaned.append(iv)
        if bad or cleaned != windows_per_floor:
            data["windows_per_floor"] = cleaned
            changed = True
            stats["windows_per_floor_cleaned"] += 1

    windows_per_floor = data.get("windows_per_floor")
    if isinstance(windows_per_floor, list) and floors > 0 and len(windows_per_floor) != floors:
        repaired = infer_windows_per_floor(floors, fw, has_storefront)
        data["windows_per_floor"] = repaired
        changed = True
        stats["windows_per_floor_length_aligned"] += 1

    if not normalize_text(data.get("window_type")):
        data["window_type"] = "Double-hung sash"
        changed = True
        stats["window_type_defaulted"] += 1
    if (to_float(data.get("window_width_m")) or 0) <= 0:
        data["window_width_m"] = 0.85
        changed = True
        stats["window_width_defaulted"] += 1
    if (to_float(data.get("window_height_m")) or 0) <= 0:
        data["window_height_m"] = 1.3
        changed = True
        stats["window_height_defaulted"] += 1
    if (to_int(data.get("door_count")) or -1) < 0:
        data["door_count"] = 1
        changed = True
        stats["door_count_defaulted"] += 1

    cond = normalize_text(data.get("condition"))
    if not cond or cond not in ALLOWED_CONDITIONS:
        data["condition"] = "poor" if cond in {"demolished", "ruin", "unsafe"} else "fair"
        changed = True
        stats["condition_normalized"] += 1

    total_height = to_float(data.get("total_height_m")) or 0.0
    city_avg = to_float(city.get("height_avg_m")) or 0.0
    if city_avg > 0 and total_height > city_avg * 1.8:
        total_height = round(city_avg, 2)
        data["total_height_m"] = total_height
        changed = True
        stats["total_height_clamped_to_city_avg"] += 1

    floor_heights = data.get("floor_heights_m")
    if isinstance(floor_heights, list) and floor_heights:
        if floor_heights_suspicious(floor_heights, floors, total_height):
            if total_height <= 0:
                total_height = sum(v for v in (to_float(x) for x in floor_heights) if v is not None and v > 0)
                if total_height <= 0:
                    total_height = max(1, floors) * (3.8 if has_storefront else 3.1)
                data["total_height_m"] = round(total_height, 2)
                changed = True
                stats["total_height_repaired_from_floor_heights"] += 1
            data["floor_heights_m"] = infer_floor_heights(floors, total_height, has_storefront)
            changed = True
            stats["floor_heights_reinferred"] += 1
    # Ensure total height is not below the maximum floor height due to rounding drift.
    floor_heights = data.get("floor_heights_m")
    if isinstance(floor_heights, list) and floor_heights:
        max_floor = max((to_float(v) or 0.0) for v in floor_heights)
        total_height_now = to_float(data.get("total_height_m")) or 0.0
        if max_floor > 0 and total_height_now > 0 and total_height_now < max_floor:
            data["total_height_m"] = round(max_floor, 2)
            changed = True
            stats["total_height_raised_to_floor_max"] += 1
    else:
        if total_height <= 0:
            total_height = max(1, floors) * (3.8 if has_storefront else 3.1)
            data["total_height_m"] = round(total_height, 2)
            changed = True
            stats["total_height_defaulted"] += 1
        data["floor_heights_m"] = infer_floor_heights(floors, total_height, has_storefront)
        changed = True
        stats["floor_heights_defaulted"] += 1

    if has_storefront:
        if storefront_obj is None:
            storefront_obj = {}
            data["storefront"] = storefront_obj
            changed = True
            stats["storefront_created"] += 1
        if not normalize_text(storefront_obj.get("type")):
            storefront_obj["type"] = "Commercial ground floor"
            changed = True
            stats["storefront_type_defaulted"] += 1
        if not normalize_text(storefront_obj.get("status")):
            storefront_obj["status"] = "inferred_from_fix"
            changed = True
            stats["storefront_status_defaulted"] += 1
        if not normalize_text(storefront_obj.get("status_source")):
            storefront_obj["status_source"] = "normalized_fix"
            changed = True
            stats["storefront_status_source_defaulted"] += 1
    else:
        if storefront_obj is not None:
            data.pop("storefront", None)
            changed = True
            stats["storefront_removed_when_false"] += 1

    if changed and apply_changes:
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        stats["files_updated"] += 1
    else:
        stats["files_scanned"] += 1
    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description="Bulk-fix common low-risk params anomalies")
    parser.add_argument("--params-dir", default=str(DEFAULT_PARAMS_DIR), help="Directory containing param JSON files")
    parser.add_argument("--limit", type=int, default=None, help="Limit files processed")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without writing")
    parser.add_argument("--no-db-fill", action="store_true", help="Disable DB backfill for missing site fields")
    args = parser.parse_args()

    params_dir = Path(args.params_dir).expanduser().resolve()
    if not params_dir.exists():
        raise SystemExit(f"params dir not found: {params_dir}")

    files = sorted(
        p for p in params_dir.glob("*.json")
        if p.is_file() and not p.name.startswith(("_", "."))
    )
    if isinstance(args.limit, int) and args.limit > 0:
        files = files[:args.limit]

    db_conn = None
    site_cache: dict[str, tuple[float | None, float | None, Any, Any] | None] = {}
    if not args.no_db_fill and psycopg2 is not None and DB_CONFIG is not None:
        try:
            db_conn = psycopg2.connect(**DB_CONFIG)
        except Exception:
            db_conn = None

    total: Counter[str] = Counter()
    try:
        for path in files:
            total.update(
                fix_file(
                    path,
                    apply_changes=not args.dry_run,
                    db_conn=db_conn,
                    site_cache=site_cache,
                )
            )
    finally:
        if db_conn is not None:
            db_conn.close()

    print(f"Processed files: {len(files)}")
    for key in sorted(total):
        print(f"{key}: {total[key]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
