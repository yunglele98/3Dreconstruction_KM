#!/usr/bin/env python3
"""Write photo analysis results back to the PostGIS kensington database.

Reads params/*.json files that have been updated by agent photo analysis,
extracts the visual observations, and writes them to new columns on the
building_assessment table.

First run creates the columns (--migrate). Subsequent runs update rows.

Usage:
    python writeback_to_db.py --migrate          # Add columns (run once)
    python writeback_to_db.py                    # Write all analyzed params back
    python writeback_to_db.py --address "22 Lippincott St"  # Single building
    python writeback_to_db.py --dry-run          # Preview without writing
"""

import argparse
import json
import re
import sys
from pathlib import Path

try:
    import psycopg2
    import psycopg2.extras
except ImportError:
    print("[ERROR] psycopg2 not installed. Run: pip install psycopg2-binary")
    sys.exit(1)

from db_config import DB_CONFIG

PARAMS_DIR = Path(__file__).parent.parent / "params"

# ---------------------------------------------------------------------------
# Schema migration — new columns for photo analysis data
# ---------------------------------------------------------------------------

MIGRATION_SQL = """
-- Photo analysis visual observations (March 2026 fieldwork)
-- These columns are populated by AI agent vision analysis of field photos.
-- DB measurements (height, footprint, lot dims) are never overwritten.

ALTER TABLE building_assessment ADD COLUMN IF NOT EXISTS photo_analyzed boolean DEFAULT false;
ALTER TABLE building_assessment ADD COLUMN IF NOT EXISTS photo_date text;
ALTER TABLE building_assessment ADD COLUMN IF NOT EXISTS photo_agent text;
ALTER TABLE building_assessment ADD COLUMN IF NOT EXISTS photo_filename text;
ALTER TABLE building_assessment ADD COLUMN IF NOT EXISTS photo_confidence double precision;

-- Facade visual details
ALTER TABLE building_assessment ADD COLUMN IF NOT EXISTS photo_facade_colour text;
ALTER TABLE building_assessment ADD COLUMN IF NOT EXISTS photo_facade_condition text;
ALTER TABLE building_assessment ADD COLUMN IF NOT EXISTS photo_alterations text;

-- Window observations
ALTER TABLE building_assessment ADD COLUMN IF NOT EXISTS photo_windows_per_floor integer[];
ALTER TABLE building_assessment ADD COLUMN IF NOT EXISTS photo_window_type text;
ALTER TABLE building_assessment ADD COLUMN IF NOT EXISTS photo_window_width_m double precision;
ALTER TABLE building_assessment ADD COLUMN IF NOT EXISTS photo_window_height_m double precision;
ALTER TABLE building_assessment ADD COLUMN IF NOT EXISTS photo_window_arrangement text;
ALTER TABLE building_assessment ADD COLUMN IF NOT EXISTS photo_window_details text;

-- Door observations
ALTER TABLE building_assessment ADD COLUMN IF NOT EXISTS photo_door_count integer;
ALTER TABLE building_assessment ADD COLUMN IF NOT EXISTS photo_door_type text;
ALTER TABLE building_assessment ADD COLUMN IF NOT EXISTS photo_door_details text;

-- Decorative elements
ALTER TABLE building_assessment ADD COLUMN IF NOT EXISTS photo_cornice text;
ALTER TABLE building_assessment ADD COLUMN IF NOT EXISTS photo_cornice_details text;
ALTER TABLE building_assessment ADD COLUMN IF NOT EXISTS photo_bay_windows integer;
ALTER TABLE building_assessment ADD COLUMN IF NOT EXISTS photo_bay_window_details text;
ALTER TABLE building_assessment ADD COLUMN IF NOT EXISTS photo_balconies integer;
ALTER TABLE building_assessment ADD COLUMN IF NOT EXISTS photo_balcony_type text;
ALTER TABLE building_assessment ADD COLUMN IF NOT EXISTS photo_quoins boolean;
ALTER TABLE building_assessment ADD COLUMN IF NOT EXISTS photo_pilasters boolean;
ALTER TABLE building_assessment ADD COLUMN IF NOT EXISTS photo_string_course boolean;
ALTER TABLE building_assessment ADD COLUMN IF NOT EXISTS photo_decorative_lintels boolean;
ALTER TABLE building_assessment ADD COLUMN IF NOT EXISTS photo_decorative_details text;

-- Roof observations
ALTER TABLE building_assessment ADD COLUMN IF NOT EXISTS photo_roof_type text;
ALTER TABLE building_assessment ADD COLUMN IF NOT EXISTS photo_roof_features text[];

-- Storefront
ALTER TABLE building_assessment ADD COLUMN IF NOT EXISTS photo_has_storefront boolean;
ALTER TABLE building_assessment ADD COLUMN IF NOT EXISTS photo_storefront_desc text;
ALTER TABLE building_assessment ADD COLUMN IF NOT EXISTS photo_signage text;

-- Style and condition
ALTER TABLE building_assessment ADD COLUMN IF NOT EXISTS photo_overall_style text;
ALTER TABLE building_assessment ADD COLUMN IF NOT EXISTS photo_condition text;
ALTER TABLE building_assessment ADD COLUMN IF NOT EXISTS photo_matches_hcd boolean;
ALTER TABLE building_assessment ADD COLUMN IF NOT EXISTS photo_notes text;

-- Full observations as JSONB for anything not in dedicated columns
ALTER TABLE building_assessment ADD COLUMN IF NOT EXISTS photo_observations jsonb;

-- Index for quick lookups
CREATE INDEX IF NOT EXISTS idx_ba_photo_analyzed ON building_assessment (photo_analyzed);
"""


def run_migration(conn):
    """Add photo analysis columns to building_assessment."""
    cur = conn.cursor()
    cur.execute(MIGRATION_SQL)
    conn.commit()
    cur.close()
    print("[OK] Migration complete — photo analysis columns added.")


# ---------------------------------------------------------------------------
# Extract write-back data from a params file
# ---------------------------------------------------------------------------

def extract_writeback(data: dict) -> dict | None:
    """Extract photo analysis fields from a params dict for DB write-back."""
    # Must have photo observations or agent metadata
    obs = data.get("photo_observations", {})
    meta = data.get("_meta", {})

    # Check if this file has been photo-analyzed
    has_observations = bool(obs)
    has_agent = bool(meta.get("agent"))
    has_translated = bool(meta.get("translated"))

    if not has_observations and not has_agent and not has_translated:
        return None

    address = data.get("building_name") or meta.get("address", "")
    if not address:
        return None

    # Build the update dict
    row = {
        "address": address,
        "photo_analyzed": True,
        "photo_agent": meta.get("agent") or obs.get("agent", ""),
        "photo_confidence": obs.get("confidence") or data.get("confidence"),
    }

    # Photo date — from meta timestamp or infer from photo filename
    timestamp = meta.get("timestamp", "")
    if timestamp:
        row["photo_date"] = timestamp[:10] if len(timestamp) >= 10 else timestamp

    # Photo filename
    photo = meta.get("photo", "")
    if photo:
        row["photo_filename"] = photo

    # Facade
    row["photo_facade_colour"] = (
        obs.get("facade_colour_observed")
        or data.get("facade_colour")
    )
    row["photo_facade_condition"] = obs.get("facade_condition_notes")
    row["photo_alterations"] = obs.get("alterations_visible")

    # Windows
    wpf = obs.get("windows_per_floor") or data.get("windows_per_floor")
    if isinstance(wpf, list):
        row["photo_windows_per_floor"] = wpf
    row["photo_window_type"] = obs.get("window_type") or data.get("window_type")
    row["photo_window_width_m"] = obs.get("window_width_m") or data.get("window_width_m")
    row["photo_window_height_m"] = obs.get("window_height_m") or data.get("window_height_m")
    row["photo_window_arrangement"] = obs.get("window_arrangement")
    row["photo_window_details"] = obs.get("window_details")

    # Doors
    row["photo_door_count"] = obs.get("door_count") or data.get("door_count")
    row["photo_door_type"] = obs.get("door_type")
    row["photo_door_details"] = obs.get("door_details")

    # Decorative
    row["photo_cornice"] = obs.get("cornice")
    row["photo_cornice_details"] = obs.get("cornice_details")
    row["photo_bay_windows"] = obs.get("bay_windows")
    row["photo_bay_window_details"] = obs.get("bay_window_details")
    row["photo_balconies"] = obs.get("balconies")
    row["photo_balcony_type"] = obs.get("balcony_type")
    row["photo_quoins"] = obs.get("quoins")
    row["photo_pilasters"] = obs.get("pilasters")
    row["photo_string_course"] = obs.get("string_course")
    row["photo_decorative_lintels"] = obs.get("decorative_lintels")
    row["photo_decorative_details"] = obs.get("decorative_details")

    # Roof
    row["photo_roof_type"] = obs.get("roof_type_observed")
    rf = obs.get("roof_features") or data.get("roof_features")
    if isinstance(rf, list):
        # Flatten any dicts to strings
        row["photo_roof_features"] = [
            str(f) if not isinstance(f, str) else f for f in rf
        ]

    # Storefront
    sf_obs = obs.get("has_storefront_observed")
    if sf_obs is not None:
        row["photo_has_storefront"] = sf_obs
    else:
        sf = data.get("has_storefront")
        if sf is not None:
            row["photo_has_storefront"] = sf
    row["photo_storefront_desc"] = obs.get("storefront_description")
    row["photo_signage"] = obs.get("signage_observed")

    # Style and condition
    row["photo_overall_style"] = obs.get("overall_style") or data.get("overall_style")
    row["photo_condition"] = obs.get("condition") or obs.get("facade_condition_notes") or data.get("condition")
    row["photo_matches_hcd"] = obs.get("matches_hcd_typology")
    row["photo_notes"] = obs.get("notes") or data.get("notes")

    # Store full observations as JSONB
    if obs:
        row["photo_observations"] = json.dumps(obs)

    # Strip None values
    return {k: v for k, v in row.items() if v is not None}


# ---------------------------------------------------------------------------
# Build UPDATE statement dynamically
# ---------------------------------------------------------------------------

def build_update(row: dict) -> tuple[str, list]:
    """Build a parameterized UPDATE statement from a row dict."""
    address = row.get("address")
    fields = {k: v for k, v in row.items() if k != "address"}
    if not fields:
        return "", []

    set_clauses = []
    values = []
    for i, (col, val) in enumerate(fields.items(), 1):
        if col == "photo_observations":
            set_clauses.append(f"{col} = %s::jsonb")
        elif col == "photo_windows_per_floor":
            set_clauses.append(f"{col} = %s::integer[]")
        elif col == "photo_roof_features":
            set_clauses.append(f"{col} = %s::text[]")
        else:
            set_clauses.append(f"{col} = %s")
        values.append(val)

    values.append(address)
    sql = f"""
        UPDATE building_assessment
        SET {', '.join(set_clauses)}
        WHERE UPPER("ADDRESS_FULL") = UPPER(%s)
    """
    return sql, values


def build_update_by_id(row: dict, building_id: int) -> tuple[str, list]:
    """Build UPDATE statement targeted by building id."""
    fields = {k: v for k, v in row.items() if k != "address"}
    if not fields:
        return "", []

    set_clauses = []
    values = []
    for col, val in fields.items():
        if col == "photo_observations":
            set_clauses.append(f"{col} = %s::jsonb")
        elif col == "photo_windows_per_floor":
            set_clauses.append(f"{col} = %s::integer[]")
        elif col == "photo_roof_features":
            set_clauses.append(f"{col} = %s::text[]")
        else:
            set_clauses.append(f"{col} = %s")
        values.append(val)

    values.append(building_id)
    sql = f"""
        UPDATE building_assessment
        SET {', '.join(set_clauses)}
        WHERE id = %s
    """
    return sql, values


def _collapse_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _street_variants(street: str) -> list[str]:
    """Generate conservative street-name variants for matching."""
    if not street:
        return []
    variants = {_collapse_ws(street)}
    replacements = [
        (r"\bSt\b", "Street"),
        (r"\bStreet\b", "St"),
        (r"\bAve\b", "Avenue"),
        (r"\bAvenue\b", "Ave"),
        (r"\bRd\b", "Road"),
        (r"\bRoad\b", "Rd"),
    ]
    for src, dst in replacements:
        current = list(variants)
        for value in current:
            swapped = re.sub(src, dst, value, flags=re.IGNORECASE)
            variants.add(_collapse_ws(swapped))
    return [v for v in variants if v]


def _is_coordinate_like(text: str) -> bool:
    return bool(re.match(r"^\s*-?\d+\.\d+\s*,\s*-?\d+\.\d+\s*$", text or ""))


def _address_candidates(raw: str) -> list[str]:
    """Generate cleaned address candidates from noisy labels."""
    if not raw:
        return []
    if _is_coordinate_like(raw):
        return []
    if not re.search(r"\d", raw):
        return []

    seeds = {_collapse_ws(raw).lstrip("~").strip()}
    out = set()
    iterations = 0

    while seeds:
        iterations += 1
        if iterations > 64:
            break
        candidate = seeds.pop()
        if not candidate:
            continue

        # Strip parenthetical notes and trailing descriptors.
        candidate = _collapse_ws(re.sub(r"\([^)]*\)", "", candidate))
        candidate = _collapse_ws(re.sub(r"\s+-\s+.*$", "", candidate))
        candidate = _collapse_ws(re.sub(r"\s+area.*$", "", candidate, flags=re.IGNORECASE))
        candidate = _collapse_ws(re.sub(r"^side of\s+", "", candidate, flags=re.IGNORECASE))
        if not candidate or _is_coordinate_like(candidate):
            continue
        out.add(candidate)

        # Split slash-separated alternatives.
        if " / " in candidate:
            for part in candidate.split(" / "):
                part = _collapse_ws(part)
                if part:
                    seeds.add(part)

        # Split comma-heavy labels to first address-like piece.
        if "," in candidate:
            first = _collapse_ws(candidate.split(",", 1)[0])
            if first:
                seeds.add(first)

        # Trim descriptor tails after a complete street suffix.
        m_full = re.match(
            r"^(\d+[A-Za-z]?(?:\s*[-/]\s*\d+[A-Za-z]?)?)\s+(.+?\b(?:St|Street|Ave|Avenue|Rd|Road|Blvd|Boulevard|Dr|Drive|Ln|Lane|Ter|Terrace|Ct|Court|Pl|Place|Way)\b)",
            candidate,
            flags=re.IGNORECASE,
        )
        if m_full:
            seeds.add(_collapse_ws(f"{m_full.group(1)} {m_full.group(2)}"))

        # Expand civic-number ranges: "12-14 Hickory St" -> 12 and 14 variants.
        m = re.match(r"^(\d+[A-Za-z]?)\s*-\s*(\d+[A-Za-z]?)\s+(.+)$", candidate)
        if m:
            left, right, street = m.group(1), m.group(2), _collapse_ws(m.group(3))
            seeds.add(f"{left} {street}")
            seeds.add(f"{right} {street}")

        # Expand slash civic alternatives: "185A/186A Augusta Ave".
        m2 = re.match(r"^(\d+[A-Za-z]?)\s*/\s*(\d+[A-Za-z]?)\s+(.+)$", candidate)
        if m2:
            left, right, street = m2.group(1), m2.group(2), _collapse_ws(m2.group(3))
            seeds.add(f"{left} {street}")
            seeds.add(f"{right} {street}")

    return sorted(out, key=len)


def _parse_number_street(candidate: str) -> tuple[int, str] | None:
    """Parse leading civic number + street text from candidate."""
    if not candidate:
        return None
    m = re.match(r"^(\d+)[A-Za-z]?\s+(.+)$", candidate.strip())
    if not m:
        return None
    return int(m.group(1)), _collapse_ws(m.group(2))


def find_building_id(cur, raw_address: str) -> tuple[int | None, str]:
    """Find unique building id for a noisy address string."""
    candidates = _address_candidates(raw_address)
    if not candidates:
        return None, ""
    candidates = candidates[:12]

    # 1) Exact case-insensitive ADDRESS_FULL candidate match.
    for candidate in candidates:
        cur.execute(
            """
            SELECT id
            FROM building_assessment
            WHERE UPPER("ADDRESS_FULL") = UPPER(%s)
            LIMIT 2
            """,
            (candidate,),
        )
        rows = cur.fetchall()
        if len(rows) == 1:
            return rows[0][0], "address_candidate"

    # 2) Street number + street-name match (with conservative suffix variants).
    for candidate in candidates:
        parsed = _parse_number_street(candidate)
        if not parsed:
            continue
        number, street = parsed
        for street_variant in _street_variants(street):
            cur.execute(
                """
                SELECT id
                FROM building_assessment
                WHERE ba_street_number = %s
                  AND UPPER(ba_street) = UPPER(%s)
                LIMIT 2
                """,
                (number, street_variant),
            )
            rows = cur.fetchall()
            if len(rows) == 1:
                return rows[0][0], "street_number"

    return None, ""


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

    parser = argparse.ArgumentParser(description="Write photo analysis results back to PostGIS")
    parser.add_argument("--migrate", action="store_true", help="Add photo columns to DB (run once)")
    parser.add_argument("--address", default=None, help="Write back single address")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    parser.add_argument("--params-dir", default=str(PARAMS_DIR), help="Params directory")
    args = parser.parse_args()

    conn = psycopg2.connect(**DB_CONFIG)

    if args.migrate:
        run_migration(conn)
        conn.close()
        return

    params_dir = Path(args.params_dir)
    files = sorted(params_dir.glob("*.json"))
    files = [f for f in files if not f.name.startswith("_")]

    print(f"=== Write-back to PostGIS ===")
    print(f"Params dir: {params_dir}")
    print(f"Total param files: {len(files)}")
    print()

    updated = 0
    skipped_no_analysis = 0
    skipped_no_match = 0
    errors = 0
    matched_fallback = 0
    match_cache: dict[str, tuple[int | None, str]] = {}

    cur = conn.cursor()

    for filepath in files:
        try:
            with open(filepath, encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            print(f"  [ERROR] {filepath.name}: {e}")
            errors += 1
            continue

        # Skip non-buildings
        if data.get("skipped"):
            skipped_no_analysis += 1
            continue

        # Filter to single address if specified
        address = data.get("building_name") or data.get("_meta", {}).get("address", "")
        if args.address and address != args.address:
            continue

        row = extract_writeback(data)
        if not row:
            skipped_no_analysis += 1
            continue

        sql, values = build_update(row)
        if not sql:
            skipped_no_analysis += 1
            continue

        if args.dry_run:
            print(f"  [DRY RUN] {address}: {len(row)} fields")
            updated += 1
            continue

        try:
            cur.execute(sql, values)
            if cur.rowcount == 0:
                if address not in match_cache:
                    match_cache[address] = find_building_id(cur, address)

                building_id, method = match_cache[address]
                if building_id is None:
                    print(f"  [NO MATCH] {address}")
                    skipped_no_match += 1
                else:
                    alt_sql, alt_values = build_update_by_id(row, building_id)
                    cur.execute(alt_sql, alt_values)
                    if cur.rowcount == 0:
                        print(f"  [NO MATCH] {address}")
                        skipped_no_match += 1
                    else:
                        updated += 1
                        matched_fallback += 1
            else:
                updated += 1
            # Commit per row to avoid losing work on later errors
            conn.commit()
        except Exception as e:
            print(f"  [ERROR] {address}: {e}")
            conn.rollback()
            errors += 1

    cur.close()
    conn.close()

    print(f"Updated: {updated}")
    print(f"Skipped (no analysis): {skipped_no_analysis}")
    if skipped_no_match:
        print(f"Skipped (no DB match): {skipped_no_match}")
    if matched_fallback:
        print(f"Matched via fallback: {matched_fallback}")
    if errors:
        print(f"Errors: {errors}")


if __name__ == "__main__":
    main()
