#!/usr/bin/env python3
"""Build address aliases for unmatched param files using DB address inventory.

Outputs:
- outputs/address_alias_candidates.json
- params/_address_aliases.auto.json  (high-confidence auto aliases only)
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

import psycopg2

from db_config import DB_CONFIG
from revise_params_from_db import (
    PARAMS_DIR,
    ROOT,
    derive_address_candidates,
    get_param_address,
    norm_addr_loose,
    norm_addr_raw,
)


OUT_DIR = ROOT / "outputs"
AUTO_ALIAS_PATH = PARAMS_DIR / "_address_aliases.auto.json"


def db_addresses() -> tuple[set[str], set[str]]:
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()
    cur.execute('select "ADDRESS_FULL" from public.building_assessment where "ADDRESS_FULL" is not null')
    rows = [r[0] for r in cur.fetchall()]
    cur.close()
    conn.close()
    raw = {norm_addr_raw(r) for r in rows}
    loose = {norm_addr_loose(r) for r in rows}
    return raw, loose


def extract_base_candidate(addr: str) -> str | None:
    s = norm_addr_raw(addr)
    s = re.sub(r"\(.*?\)", "", s)
    s = re.sub(r"/.*$", "", s)
    s = re.sub(r"\bAREA\b.*$", "", s)
    s = re.sub(r"\s+", " ", s).strip(" -")
    if not s:
        return None
    return norm_addr_loose(s)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    db_raw, db_loose = db_addresses()

    files = sorted(p for p in PARAMS_DIR.glob("*.json") if not p.name.startswith("_"))
    candidates_out = []
    auto_aliases: dict[str, str] = {}

    for p in files:
        data = json.loads(p.read_text(encoding="utf-8"))
        if data.get("skipped"):
            continue
        addr = get_param_address(data, p)
        key_raw = norm_addr_raw(addr)
        key_loose = norm_addr_loose(addr)
        if key_raw in db_raw or key_loose in db_loose:
            continue

        cands = derive_address_candidates(addr)
        in_db = [c for c in cands if c in db_loose]

        # Additional base cleanup candidate
        base = extract_base_candidate(addr)
        if base and base in db_loose and base not in in_db:
            in_db.append(base)

        entry = {
            "file": p.name,
            "address": addr,
            "candidates_in_db": in_db[:10],
        }
        candidates_out.append(entry)

        # Auto-promote only when exactly one candidate exists.
        if len(in_db) == 1:
            auto_aliases[p.name] = in_db[0]

    report = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "files_with_candidates": len(candidates_out),
        "auto_alias_count": len(auto_aliases),
        "candidates": candidates_out,
    }

    report_path = OUT_DIR / "address_alias_candidates.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    AUTO_ALIAS_PATH.write_text(json.dumps(auto_aliases, indent=2, ensure_ascii=False), encoding="utf-8")

    print("=== Address Alias Builder ===")
    print(f"Candidate report: {report_path}")
    print(f"Auto aliases: {AUTO_ALIAS_PATH}")
    print(f"Files with candidates: {len(candidates_out)}")
    print(f"Auto aliases generated: {len(auto_aliases)}")


if __name__ == "__main__":
    main()
