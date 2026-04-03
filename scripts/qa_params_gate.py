#!/usr/bin/env python3
"""Run QA gate checks on param files and export a fail list."""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

try:
    import psycopg2
    import psycopg2.extras
except ImportError:
    psycopg2 = None

try:
    from db_config import DB_CONFIG, get_connection
    from revise_params_from_db import get_param_address, norm_addr_loose
except ImportError:
    DB_CONFIG = None
    get_connection = None
    def get_param_address(d, p): return d.get("_meta", {}).get("address") or d.get("building_name") or p.stem
    def norm_addr_loose(a): return a.strip().lower()


ROOT = Path(__file__).resolve().parents[1]
PARAMS_DIR = ROOT / "params"
OUT_DIR = ROOT / "outputs"


def coerce_float(v: Any) -> float | None:
    try:
        if v is None or v == "":
            return None
        return float(v)
    except Exception:
        return None


def derive_storefront(status: str | None) -> bool | None:
    s = (status or "").strip().lower()
    if not s:
        return None
    if s in {"active", "converted_residential", "vacant"}:
        return True
    if s in {"n/a", "none", "residential_only", "residential only"}:
        return False
    return None


def db_storefront_map() -> dict[str, bool]:
    if psycopg2 is None or get_connection is None:
        return {}
    conn = get_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute('select "ADDRESS_FULL" as address_full, ba_storefront_status from public.building_assessment where "ADDRESS_FULL" is not null')
    rows = cur.fetchall()
    cur.close()
    conn.close()
    out: dict[str, bool] = {}
    for r in rows:
        sf = derive_storefront(r.get("ba_storefront_status"))
        if sf is not None:
            out[norm_addr_loose(r["address_full"])] = sf
    return out


def severity_for(reasons: list[str]) -> str:
    if any(r.startswith("height_per_floor") for r in reasons):
        return "high"
    if any(r.startswith("floor_height_sum_mismatch") for r in reasons):
        return "medium"
    if any(r.startswith("deep_facade_analysis_not_dict") for r in reasons):
        return "medium"
    if any(r.startswith(("storefront_conflict", "invalid_bond", "invalid_dfa_bond",
                         "malformed_hex", "invalid_accent_hex",
                         "polychromatic_brick_not_dict")) for r in reasons):
        return "low"
    return "low"


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    sf_db = db_storefront_map()

    files = sorted(p for p in PARAMS_DIR.glob("*.json") if not p.name.startswith("_"))
    checked = 0
    failed = []

    for p in files:
        d = json.loads(p.read_text(encoding="utf-8"))
        if d.get("skipped"):
            continue
        checked += 1

        reasons: list[str] = []
        addr = get_param_address(d, p)

        floors = coerce_float(d.get("floors"))
        total_h = coerce_float(d.get("total_height_m"))
        if floors and floors > 0 and total_h and total_h > 0:
            hpf = total_h / floors
            if hpf < 2.4 or hpf > 4.8:
                reasons.append(f"height_per_floor_out_of_range:{hpf:.2f}")

        fh = d.get("floor_heights_m")
        if isinstance(fh, list) and fh:
            vals = [coerce_float(v) for v in fh]
            if all(v is not None for v in vals) and total_h:
                s = sum(v for v in vals if v is not None)
                diff = abs(s - total_h)
                if diff > 0.75:
                    reasons.append(f"floor_height_sum_mismatch:{diff:.2f}")

        sf_param = d.get("has_storefront")
        sf_expected = sf_db.get(norm_addr_loose(addr))
        if isinstance(sf_param, bool) and sf_expected is not None and sf_param != sf_expected:
            reasons.append(f"storefront_conflict:param={sf_param},db={sf_expected}")

        # Validate bond_pattern if present (must be running/flemish/stack)
        fd = d.get("facade_detail", {})
        if isinstance(fd, dict):
            bp = fd.get("bond_pattern", "")
            if bp and bp.lower().strip() not in ("running", "flemish", "stack", "running bond", ""):
                reasons.append(f"invalid_bond_pattern:{bp}")

        # Validate deep_facade_analysis structure
        dfa = d.get("deep_facade_analysis")
        if dfa is not None and not isinstance(dfa, dict):
            reasons.append("deep_facade_analysis_not_dict")
        elif isinstance(dfa, dict):
            poly = dfa.get("polychromatic_brick")
            if poly is not None and not isinstance(poly, dict):
                reasons.append("polychromatic_brick_not_dict")
            elif isinstance(poly, dict):
                accent = poly.get("accent_hex", "")
                if accent and isinstance(accent, str) and not accent.startswith("#"):
                    reasons.append(f"invalid_accent_hex:{accent}")
            dfa_bond = dfa.get("brick_bond_observed", "")
            if dfa_bond and dfa_bond.lower().strip() not in (
                "running", "flemish", "stack", "running bond", "stretcher", ""
            ):
                reasons.append(f"invalid_dfa_bond:{dfa_bond}")

        # Validate colour hex fields are valid 7-char hex strings
        for hex_path, hex_val in [
            ("facade_detail.brick_colour_hex", fd.get("brick_colour_hex", "") if isinstance(fd, dict) else ""),
            ("facade_detail.trim_colour_hex", fd.get("trim_colour_hex", "") if isinstance(fd, dict) else ""),
        ]:
            if hex_val and isinstance(hex_val, str) and not (
                hex_val.startswith("#") and len(hex_val) == 7
            ):
                reasons.append(f"malformed_hex:{hex_path}={hex_val}")

        # Array length consistency
        wpf = d.get("windows_per_floor", [])
        if isinstance(wpf, list) and floors and len(wpf) != int(floors):
            reasons.append(f"windows_per_floor_length:{len(wpf)}!=floors:{int(floors)}")

        if isinstance(fh, list) and floors and len(fh) != int(floors):
            reasons.append(f"floor_heights_length:{len(fh)}!=floors:{int(floors)}")

        # Facade width sanity
        width = coerce_float(d.get("facade_width_m"))
        if width and (width < 2.0 or width > 30.0):
            reasons.append(f"facade_width_out_of_range:{width:.1f}")

        depth = coerce_float(d.get("facade_depth_m"))
        if depth and (depth < 2.0 or depth > 40.0):
            reasons.append(f"facade_depth_out_of_range:{depth:.1f}")

        # Missing critical enrichment
        meta = d.get("_meta", {})
        if not meta.get("enriched") and not meta.get("geometry_revised"):
            reasons.append("not_enriched_or_promoted")

        # Colour palette completeness
        cp = d.get("colour_palette", {})
        if isinstance(cp, dict) and not cp.get("facade"):
            reasons.append("missing_colour_palette_facade")

        if reasons:
            failed.append(
                {
                    "file": p.name,
                    "address": addr,
                    "severity": severity_for(reasons),
                    "reasons": reasons,
                }
            )

    # Priority sort: high > medium > low
    rank = {"high": 0, "medium": 1, "low": 2}
    failed.sort(key=lambda x: (rank.get(x["severity"], 3), x["file"]))

    summary = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "checked_active_files": checked,
        "failed_count": len(failed),
        "high": sum(1 for x in failed if x["severity"] == "high"),
        "medium": sum(1 for x in failed if x["severity"] == "medium"),
        "low": sum(1 for x in failed if x["severity"] == "low"),
        "failed_files": failed,
    }

    out = OUT_DIR / f"qa_fail_list_{time.strftime('%Y%m%d_%H%M%S')}.json"
    out.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print("=== QA Gate ===")
    print(f"Checked active files: {checked}")
    print(f"Failed: {len(failed)} (high={summary['high']}, medium={summary['medium']}, low={summary['low']})")
    print(f"Report: {out}")


if __name__ == "__main__":
    main()

