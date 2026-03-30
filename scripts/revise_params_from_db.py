#!/usr/bin/env python3
"""Revise param JSON files using building_assessment signals from PostgreSQL.

Applies conservative, auditable fixes:
- Recover DB joins via address normalization
- Correct severe height outliers
- Reconcile floor_heights_m totals with total_height_m
- Resolve storefront conflicts from DB storefront status

Usage:
    python scripts/revise_params_from_db.py --dry-run
    python scripts/revise_params_from_db.py --apply
"""

from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path
from typing import Any

import psycopg2
import psycopg2.extras

from db_config import DB_CONFIG, get_connection


ROOT = Path(__file__).resolve().parents[1]
PARAMS_DIR = ROOT / "params"
OUT_DIR = ROOT / "outputs"
AUTO_ALIAS_PATH = PARAMS_DIR / "_address_aliases.auto.json"
MANUAL_ALIAS_PATH = PARAMS_DIR / "_address_aliases.json"

MANUAL_FILE_ADDRESS_OVERRIDE = {
    # Multi-address storefront row segment: anchor to the middle storefront for deterministic DB linkage.
    "401_Spadina_Ave_Tankx_Ebike_399_Reiwatakiya_397_HANBINGO_한빙고.json": "400 SPADINA AVE",
}
MANUAL_NAME_ADDRESS_OVERRIDE = {
    # Same row-segment case keyed by normalized building_name for Unicode-safe matching.
    "397-401 SPADINA AVE": "400 SPADINA AVE",
}


def norm_addr_raw(value: str) -> str:
    s = (value or "").upper().replace("_", " ").strip()
    s = re.sub(r"\s+", " ", s)
    return s


def norm_addr_loose(value: str) -> str:
    s = norm_addr_raw(value)
    s = re.sub(r"\(.*?\)", "", s)   # strip bracketed notes
    s = re.sub(r"/.*$", "", s)      # use first address in slash chains
    s = re.sub(r"\bAREA\b.*$", "", s)
    s = re.sub(r"\s+", " ", s).strip(" -")
    return s


def derive_address_candidates(value: str) -> list[str]:
    """Generate plausible single-address candidates from noisy labels."""
    raw = norm_addr_raw(value)
    if not raw:
        return []

    # Remove parenthetical notes first.
    base = re.sub(r"\(.*?\)", "", raw)
    base = re.sub(r"\s+", " ", base).strip()

    candidates: list[str] = []

    # Split slash chains; keep first as-is, and expand numeric short-hands.
    parts = [p.strip() for p in base.split("/") if p.strip()]
    if parts:
        first = parts[0]
        candidates.append(first)
        # Infer street suffix from first address.
        m_first = re.match(r"^([0-9]+[A-Z]?)\s+(.+)$", first)
        suffix = m_first.group(2) if m_first else ""
        for p in parts[1:]:
            if re.fullmatch(r"[0-9]+[A-Z]?", p) and suffix:
                candidates.append(f"{p} {suffix}")
            else:
                candidates.append(p)
    else:
        candidates.append(base)

    expanded: list[str] = []
    for c in candidates:
        expanded.append(c)

        # Expand A/B slash numbers written inside the first token (e.g., 185A/186A Augusta Ave).
        m = re.match(r"^([0-9]+[A-Z]?)/([0-9]+[A-Z]?)\s+(.+)$", c)
        if m:
            expanded.append(f"{m.group(1)} {m.group(3)}")
            expanded.append(f"{m.group(2)} {m.group(3)}")

        # Expand numeric ranges (e.g., 142-144 Denison Ave).
        mr = re.match(r"^([0-9]+)-([0-9]+)\s+(.+)$", c)
        if mr:
            a = int(mr.group(1))
            b = int(mr.group(2))
            street = mr.group(3)
            lo, hi = min(a, b), max(a, b)
            if hi - lo <= 8:
                for n in range(lo, hi + 1):
                    expanded.append(f"{n} {street}")

    out: list[str] = []
    seen = set()
    for c in expanded:
        n = norm_addr_loose(c)
        if n and n not in seen:
            seen.add(n)
            out.append(n)
    return out


def derive_range_anchor(value: str) -> tuple[str, str] | None:
    """Return (start_addr, end_addr) for simple numeric ranges, else None."""
    s = norm_addr_loose(value)
    m = re.match(r"^([0-9]+)-([0-9]+)\s+(.+)$", s)
    if not m:
        return None
    a = int(m.group(1))
    b = int(m.group(2))
    street = m.group(3)
    return (norm_addr_loose(f"{a} {street}"), norm_addr_loose(f"{b} {street}"))


def get_param_address(data: dict[str, Any], path: Path) -> str:
    return data.get("building_name") or data.get("_meta", {}).get("address") or path.stem


def coerce_float(v: Any) -> float | None:
    try:
        if v is None or v == "":
            return None
        return float(v)
    except Exception:
        return None


def recompute_floor_heights(total_h: float, floors: float, old: list[Any]) -> list[float]:
    n = len(old)
    if n <= 0:
        n = max(1, int(round(floors)))
    if n == 1:
        return [round(total_h, 2)]
    base = round(total_h / n, 2)
    vals = [base] * n
    vals[-1] = round(total_h - sum(vals[:-1]), 2)
    return vals


def derive_storefront(status: str | None) -> bool | None:
    s = (status or "").strip().lower()
    if not s:
        return None
    if s in {"active", "converted_residential", "vacant"}:
        return True
    if s in {"n/a", "none", "residential_only", "residential only"}:
        return False
    return None


def fetch_db_rows() -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    conn = get_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(
        """
        select
            "ADDRESS_FULL" as address_full,
            ba_stories,
            "BLDG_HEIGHT_AVG_M" as bldg_height_avg_m,
            "LOT_WIDTH_FT" as lot_width_ft,
            "LOT_DEPTH_FT" as lot_depth_ft,
            ba_storefront_status
        from public.building_assessment
        where "ADDRESS_FULL" is not null
        """
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()

    by_raw: dict[str, dict[str, Any]] = {}
    by_loose: dict[str, dict[str, Any]] = {}
    for r in rows:
        raw = norm_addr_raw(r["address_full"])
        loose = norm_addr_loose(r["address_full"])
        if raw and raw not in by_raw:
            by_raw[raw] = r
        if loose and loose not in by_loose:
            by_loose[loose] = r
    return by_raw, by_loose


def score_candidate(db: dict[str, Any], data: dict[str, Any]) -> tuple[float, int]:
    """Lower is better. Returns (score, number_of_signals_used)."""
    score = 0.0
    used = 0

    pw = coerce_float(data.get("facade_width_m"))
    lw = coerce_float(db.get("lot_width_ft"))
    if pw and lw and lw > 0:
        lw_m = lw * 0.3048
        score += min(abs(pw - lw_m) / max(pw, 1.0), 2.0) * 3.0
        used += 1

    pd = coerce_float(data.get("facade_depth_m"))
    ld = coerce_float(db.get("lot_depth_ft"))
    if pd and ld and ld > 0:
        ld_m = ld * 0.3048
        score += min(abs(pd - ld_m) / max(pd, 1.0), 2.0) * 2.0
        used += 1

    pf = coerce_float(data.get("floors"))
    bf = coerce_float(db.get("ba_stories"))
    if pf is not None and bf is not None:
        score += min(abs(pf - bf) / 3.0, 1.5)
        used += 1

    ph = coerce_float(data.get("total_height_m"))
    bh = coerce_float(db.get("bldg_height_avg_m"))
    if ph and bh and bh > 0:
        # Height is noisier, so lower weight.
        score += min(abs(ph - bh) / max(bh, 1.0), 3.0) * 0.4
        used += 1

    return score, used


def process_file(
    path: Path,
    by_raw: dict[str, dict[str, Any]],
    by_loose: dict[str, dict[str, Any]],
    aliases_by_file: dict[str, str],
    apply: bool,
) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("skipped"):
        return {"file": path.name, "skipped_param": True, "changed": False}

    original = json.loads(json.dumps(data))
    address = get_param_address(data, path)
    key_raw = norm_addr_raw(address)
    key_loose = norm_addr_loose(address)
    candidates = derive_address_candidates(address)

    alias_addr = aliases_by_file.get(path.name)

    override_addr = MANUAL_FILE_ADDRESS_OVERRIDE.get(path.name)
    if not override_addr:
        override_addr = MANUAL_NAME_ADDRESS_OVERRIDE.get(key_loose)
    if not override_addr and alias_addr:
        override_addr = alias_addr
    if override_addr:
        db = by_raw.get(norm_addr_raw(override_addr)) or by_loose.get(norm_addr_loose(override_addr))
        match_mode = "manual_override" if db is not None else "none"
    else:
        db = by_raw.get(key_raw)
        match_mode = "raw"
    if db is None:
        db = by_loose.get(key_loose)
        match_mode = "loose" if db is not None else "none"
    if db is None and candidates:
        matched = [by_loose[c] for c in candidates if c in by_loose]
        if len(matched) == 1:
            db = matched[0]
            match_mode = "candidate"
        elif len(matched) > 1:
            scored = []
            for row in matched:
                s, used = score_candidate(row, data)
                scored.append((s, used, row))
            scored.sort(key=lambda t: t[0])
            best_s, best_used, best_row = scored[0]
            second_s = scored[1][0] if len(scored) > 1 else 999.0
            # Auto-resolve only when numeric signals are present and winner is clear.
            if best_used >= 2 and best_s <= 1.2 and (second_s - best_s) >= 0.35:
                db = best_row
                match_mode = "candidate_scored"
            else:
                match_mode = "candidate_ambiguous"
                # Deterministic fallback for range labels: anchor to start endpoint if available.
                anchor = derive_range_anchor(address)
                if anchor:
                    start_key, end_key = anchor
                    if start_key in by_loose:
                        db = by_loose[start_key]
                        match_mode = "candidate_range_anchor"
                    elif end_key in by_loose:
                        db = by_loose[end_key]
                        match_mode = "candidate_range_anchor"
    if db is None:
        return {"file": path.name, "match_mode": match_mode, "changed": False}

    changes: list[str] = []

    floors = coerce_float(data.get("floors"))
    total_h = coerce_float(data.get("total_height_m"))
    db_h = coerce_float(db.get("bldg_height_avg_m"))

    if floors and total_h and db_h and db_h > 0:
        ratio = total_h / db_h
        if ratio >= 2.5:
            # Conservative correction: anchor to DB avg height with small uplift, but respect floor count minimums.
            target = max(db_h * 1.15, floors * 3.0)
            target = round(target, 2)
            if abs(target - total_h) >= 0.5:
                data["total_height_m"] = target
                changes.append(f"total_height_m:{total_h:.2f}->{target:.2f}")
                fh = data.get("floor_heights_m")
                if isinstance(fh, list) and fh:
                    data["floor_heights_m"] = recompute_floor_heights(target, floors, fh)
                    changes.append("floor_heights_m:rescaled")

    # Ensure floor heights sum matches total height.
    total_h2 = coerce_float(data.get("total_height_m"))
    fh2 = data.get("floor_heights_m")
    if total_h2 and isinstance(fh2, list) and fh2:
        vals = [coerce_float(v) for v in fh2]
        if all(v is not None and v > 0 for v in vals):
            s = sum(v for v in vals if v is not None)
            if abs(s - total_h2) > 0.75:
                n_floors = floors if floors else float(len(fh2))
                data["floor_heights_m"] = recompute_floor_heights(total_h2, n_floors, fh2)
                changes.append(f"floor_heights_m:sum_fix:{s:.2f}->{total_h2:.2f}")

    # Storefront reconciliation from DB categorical signal.
    sf_db = derive_storefront(db.get("ba_storefront_status"))
    if sf_db is not None:
        sf_param = data.get("has_storefront")
        if isinstance(sf_param, bool) and sf_param != sf_db:
            data["has_storefront"] = sf_db
            changes.append(f"has_storefront:{sf_param}->{sf_db}")

    # Track DB match metadata.
    meta = data.get("_meta") if isinstance(data.get("_meta"), dict) else {}
    data["_meta"] = meta
    prev_mode = meta.get("db_match_mode")
    if prev_mode != match_mode:
        meta["db_match_mode"] = match_mode
        changes.append(f"db_match_mode:{prev_mode}->{match_mode}")
    if db.get("address_full") and meta.get("db_address_full") != db.get("address_full"):
        meta["db_address_full"] = db.get("address_full")
        changes.append("db_address_full:set")
    if candidates:
        if meta.get("db_address_candidates") != candidates:
            meta["db_address_candidates"] = candidates
            changes.append("db_address_candidates:set")
    meta["db_revision_ts"] = time.strftime("%Y-%m-%dT%H:%M:%S")

    changed = data != original
    if changed and apply:
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    return {
        "file": path.name,
        "match_mode": match_mode,
        "changed": changed,
        "changes": changes,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Revise params from building_assessment DB signals")
    parser.add_argument("--apply", action="store_true", help="Write changes to params/*.json")
    parser.add_argument("--dry-run", action="store_true", help="Analyze only (default if --apply omitted)")
    args = parser.parse_args()

    apply = bool(args.apply)
    by_raw, by_loose = fetch_db_rows()

    aliases_by_file: dict[str, str] = {}
    for alias_path in (AUTO_ALIAS_PATH, MANUAL_ALIAS_PATH):
        if alias_path.exists():
            try:
                obj = json.loads(alias_path.read_text(encoding="utf-8"))
                if isinstance(obj, dict):
                    for k, v in obj.items():
                        if isinstance(k, str) and isinstance(v, str):
                            aliases_by_file[k] = v
            except Exception:
                pass

    files = sorted(p for p in PARAMS_DIR.glob("*.json") if not p.name.startswith("_"))
    results: list[dict[str, Any]] = []
    for p in files:
        results.append(process_file(p, by_raw, by_loose, aliases_by_file=aliases_by_file, apply=apply))

    matched_raw = sum(1 for r in results if r.get("match_mode") == "raw")
    matched_loose = sum(1 for r in results if r.get("match_mode") == "loose")
    matched_candidate = sum(1 for r in results if r.get("match_mode") == "candidate")
    matched_candidate_scored = sum(1 for r in results if r.get("match_mode") == "candidate_scored")
    matched_candidate_range_anchor = sum(1 for r in results if r.get("match_mode") == "candidate_range_anchor")
    matched_manual_override = sum(1 for r in results if r.get("match_mode") == "manual_override")
    candidate_ambiguous = sum(1 for r in results if r.get("match_mode") == "candidate_ambiguous")
    unmatched = sum(1 for r in results if r.get("match_mode") == "none")
    changed = [r for r in results if r.get("changed")]

    summary = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "mode": "apply" if apply else "dry-run",
        "files_total": len(results),
        "matched_raw": matched_raw,
        "matched_loose": matched_loose,
        "matched_candidate": matched_candidate,
        "matched_candidate_scored": matched_candidate_scored,
        "matched_candidate_range_anchor": matched_candidate_range_anchor,
        "matched_manual_override": matched_manual_override,
        "candidate_ambiguous": candidate_ambiguous,
        "unmatched": unmatched,
        "changed_count": len(changed),
        "changed_files": changed,
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"db_param_revision_{time.strftime('%Y%m%d_%H%M%S')}.json"
    out.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print("=== DB Param Revision ===")
    print(f"Mode: {summary['mode']}")
    print(f"Files: {summary['files_total']}")
    print(f"Matched raw: {matched_raw}")
    print(f"Matched loose: {matched_loose}")
    print(f"Matched candidate: {matched_candidate}")
    print(f"Matched candidate scored: {matched_candidate_scored}")
    print(f"Matched candidate range-anchor: {matched_candidate_range_anchor}")
    print(f"Matched manual override: {matched_manual_override}")
    print(f"Candidate ambiguous: {candidate_ambiguous}")
    print(f"Unmatched: {unmatched}")
    print(f"Changed: {len(changed)}")
    print(f"Report: {out}")


if __name__ == "__main__":
    main()

