#!/usr/bin/env python3
"""Build photo shortlist for printable urban features beyond graffiti."""

from __future__ import annotations

import csv
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IN_IDX = ROOT / "PHOTOS KENSINGTON" / "csv" / "photo_address_index.csv"
OUT = ROOT / "outputs" / "printable_features" / "printable_reference_shortlist.csv"


def classify(loc: str) -> str:
    t = (loc or "").lower()
    if "one way" in t or "limite" in t or "speed" in t or "stop" in t or "street sign" in t:
        return "street_sign"
    if "shop" in t or "store" in t or "market" in t or "dispensary" in t or "restaurant" in t or "cafe" in t or "bar" in t:
        return "shop_sign"
    if "awning" in t or "canopy" in t:
        return "awning_sign"
    if "poster" in t or "flyer" in t or "bill" in t or "advert" in t:
        return "poster_panel"
    if "mural" in t or "graffiti" in t:
        return "mural_or_graffiti"
    if "sign" in t:
        return "street_sign"
    return "other_printable"


def score(loc: str) -> int:
    t = (loc or "").lower()
    s = 0
    for k in ["sign", "shop", "store", "poster", "mural", "graffiti", "awning", "one way", "speed", "restaurant", "market"]:
        if k in t:
            s += 1
    if re.search(r"-?\d+\.\d+\s*,\s*-?\d+\.\d+", loc or ""):
        s += 2
    return s


def main() -> int:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    with IN_IDX.open("r", encoding="utf-8", newline="") as f:
        rd = csv.DictReader(f)
        for r in rd:
            loc = r.get("address_or_location") or ""
            cat = classify(loc)
            if cat == "other_printable":
                continue
            sc = score(loc)
            if sc < 1:
                continue
            rows.append(
                {
                    "filename": r.get("filename") or "",
                    "address_or_location": loc,
                    "source": r.get("source") or "",
                    "category": cat,
                    "score": sc,
                }
            )

    rows.sort(key=lambda x: x["score"], reverse=True)
    rows = rows[:260]

    with OUT.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else ["filename", "address_or_location", "source", "category", "score"])
        w.writeheader()
        if rows:
            w.writerows(rows)

    print(f"[OK] Wrote {OUT}")
    print(f"[INFO] shortlist_count={len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
