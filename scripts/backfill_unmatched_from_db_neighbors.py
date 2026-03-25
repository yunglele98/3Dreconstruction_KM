#!/usr/bin/env python3
"""Backfill unmatched params from nearest same-street DB neighbors.

Conservative policy:
- Only touches params that still do not match building_assessment directly.
- Only fills missing fields (no overwrite).
- Adds provenance in _meta.db_neighbor_backfill with low confidence tags.
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

from revise_params_from_db import (
    PARAMS_DIR,
    ROOT,
    derive_address_candidates,
    get_param_address,
    norm_addr_loose,
    norm_addr_raw,
)

from db_config import DB_CONFIG


OUT_DIR = ROOT / "outputs"


def coerce_float(v: Any) -> float | None:
    try:
        if v is None or v == "":
            return None
        return float(v)
    except Exception:
        return None


def parse_addr_num_street(addr: str) -> tuple[int | None, str]:
    s = norm_addr_loose(addr)
    m = re.match(r"^([0-9]+)[A-Z]?\s+(.+)$", s)
    if not m:
        return None, s
    return int(m.group(1)), m.group(2).strip()


def is_missing(value: Any) -> bool:
    return value in (None, "", [], {})


def derive_storefront(status: str | None) -> bool | None:
    s = (status or "").strip().lower()
    if not s:
        return None
    if s in {"active", "converted_residential", "vacant"}:
        return True
    if s in {"n/a", "none", "residential_only", "residential only"}:
        return False
    return None


def load_db_rows() -> tuple[dict[str, dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(
        """
        select
            "ADDRESS_FULL" as address_full,
            ba_stories,
            "LOT_WIDTH_FT" as lot_width_ft,
            "LOT_DEPTH_FT" as lot_depth_ft,
            "BLDG_HEIGHT_AVG_M" as bldg_height_avg_m,
            ba_storefront_status
        from public.building_assessment
        where "ADDRESS_FULL" is not null
        """
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()

    by_loose: dict[str, dict[str, Any]] = {}
    by_street: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        k = norm_addr_loose(r["address_full"])
        if k not in by_loose:
            by_loose[k] = r
        num, street = parse_addr_num_street(r["address_full"])
        rr = dict(r)
        rr["_num"] = num
        rr["_street"] = street
        by_street.setdefault(street, []).append(rr)
    return by_loose, by_street


def has_direct_db_match(addr: str, by_loose: dict[str, dict[str, Any]]) -> bool:
    if norm_addr_loose(addr) in by_loose:
        return True
    for c in derive_address_candidates(addr):
        if c in by_loose:
            return True
    return False


def confidence_from_gap(gap: int) -> str:
    if gap <= 2:
        return "medium"
    if gap <= 6:
        return "low"
    return "very_low"


def backfill_file(path: Path, by_loose: dict[str, dict[str, Any]], by_street: dict[str, list[dict[str, Any]]], apply: bool) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("skipped"):
        return {"file": path.name, "eligible": False, "changed": False, "reason": "skipped"}

    addr = get_param_address(data, path)
    if has_direct_db_match(addr, by_loose):
        return {"file": path.name, "eligible": False, "changed": False, "reason": "matched"}

    num, street = parse_addr_num_street(addr)
    if num is None or not street:
        return {"file": path.name, "eligible": False, "changed": False, "reason": "unparseable_address"}

    pool = [r for r in by_street.get(street, []) if r.get("_num") is not None]
    if not pool:
        return {"file": path.name, "eligible": False, "changed": False, "reason": "no_street_neighbors"}

    best = min(pool, key=lambda r: abs(r["_num"] - num))
    gap = abs(best["_num"] - num)
    if gap > 12:
        return {"file": path.name, "eligible": False, "changed": False, "reason": "neighbor_too_far", "gap": gap}

    changes: list[str] = []

    if is_missing(data.get("facade_width_m")):
        lw = coerce_float(best.get("lot_width_ft"))
        if lw and lw > 0:
            data["facade_width_m"] = round(lw * 0.3048, 2)
            changes.append("facade_width_m:set_from_lot_width_ft")

    if is_missing(data.get("facade_depth_m")):
        ld = coerce_float(best.get("lot_depth_ft"))
        if ld and ld > 0:
            data["facade_depth_m"] = round(ld * 0.3048, 2)
            changes.append("facade_depth_m:set_from_lot_depth_ft")

    if is_missing(data.get("floors")):
        bs = coerce_float(best.get("ba_stories"))
        if bs is not None and bs > 0:
            data["floors"] = int(round(bs))
            changes.append("floors:set_from_ba_stories")

    if is_missing(data.get("total_height_m")):
        bh = coerce_float(best.get("bldg_height_avg_m"))
        floors = coerce_float(data.get("floors"))
        if bh and bh > 0:
            target = bh * 1.1
            if floors and floors > 0:
                target = max(target, floors * 3.0)
            data["total_height_m"] = round(target, 2)
            changes.append("total_height_m:set_from_bldg_height_avg_m")

    if is_missing(data.get("has_storefront")):
        sf = derive_storefront(best.get("ba_storefront_status"))
        if sf is not None:
            data["has_storefront"] = sf
            changes.append("has_storefront:set_from_ba_storefront_status")

    proxy_defaults: dict[str, Any] = {}
    lw = coerce_float(best.get("lot_width_ft"))
    if lw and lw > 0:
        proxy_defaults["facade_width_m"] = round(lw * 0.3048, 2)
    ld = coerce_float(best.get("lot_depth_ft"))
    if ld and ld > 0:
        proxy_defaults["facade_depth_m"] = round(ld * 0.3048, 2)
    bs = coerce_float(best.get("ba_stories"))
    if bs is not None and bs > 0:
        proxy_defaults["floors"] = int(round(bs))
    bh = coerce_float(best.get("bldg_height_avg_m"))
    if bh and bh > 0:
        proxy_defaults["total_height_m"] = round(bh * 1.1, 2)
    sf = derive_storefront(best.get("ba_storefront_status"))
    if sf is not None:
        proxy_defaults["has_storefront"] = sf

    meta = data.get("_meta") if isinstance(data.get("_meta"), dict) else {}
    data["_meta"] = meta
    meta["db_neighbor_backfill"] = {
        "source_address": best.get("address_full"),
        "source_street": street,
        "house_number_gap": gap,
        "confidence": confidence_from_gap(gap),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "proxy_defaults": proxy_defaults,
    }
    changes.append("_meta:db_neighbor_backfill")

    changed = bool(changes)
    if changed and apply:
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    return {
        "file": path.name,
        "eligible": True,
        "changed": changed,
        "gap": gap,
        "changes": changes,
        "source_address": best.get("address_full"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill unmatched params from DB street neighbors")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    apply = bool(args.apply)

    by_loose, by_street = load_db_rows()
    files = sorted(p for p in PARAMS_DIR.glob("*.json") if not p.name.startswith("_"))
    results = [backfill_file(p, by_loose, by_street, apply=apply) for p in files]

    eligible = [r for r in results if r.get("eligible")]
    changed = [r for r in eligible if r.get("changed")]
    reason_counts: dict[str, int] = {}
    for r in results:
        reason = r.get("reason")
        if reason:
            reason_counts[reason] = reason_counts.get(reason, 0) + 1

    summary = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "mode": "apply" if apply else "dry-run",
        "files_total": len(results),
        "eligible_unmatched_files": len(eligible),
        "changed_count": len(changed),
        "reasons": reason_counts,
        "changed_files": changed,
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"db_neighbor_backfill_{time.strftime('%Y%m%d_%H%M%S')}.json"
    out.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    print("=== DB Neighbor Backfill ===")
    print(f"Mode: {summary['mode']}")
    print(f"Files: {summary['files_total']}")
    print(f"Eligible unmatched: {summary['eligible_unmatched_files']}")
    print(f"Changed: {summary['changed_count']}")
    print(f"Report: {out}")


if __name__ == "__main__":
    main()
