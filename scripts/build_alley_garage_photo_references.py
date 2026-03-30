#!/usr/bin/env python3
"""Build alley/garage photo reference catalog from PHOTOS KENSINGTON index."""

from __future__ import annotations

import csv
import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "PHOTOS KENSINGTON" / "csv" / "photo_address_index.csv"
PHOTO_DIR = ROOT / "PHOTOS KENSINGTON"
OUT_DIR = ROOT / "outputs" / "alley_garages"

KEYWORDS = ["alley", "lane", "laneway", "ruelle", "garage", "rear", "back"]
COORD_RE = re.compile(r"(-?\d+\.\d+)\s*,\s*(-?\d+\.\d+)")


def classify_text(text: str) -> str:
    t = (text or "").lower()
    if "parking garage interior" in t:
        return "garage_structured_interior_marker"
    if "parking garage" in t:
        return "garage_structured_entrance"
    if "garages with graffiti" in t or ("garage" in t and "graffiti" in t):
        return "garage_row_rollup_tagged"
    if "brick houses with garages" in t:
        return "garage_residential_pair"
    if "graffiti wall" in t:
        return "alley_graffiti_wall"
    if "caution tape" in t:
        return "alley_hazard_segment"
    if any(k in t for k in ["lane", "alley", "ruelle", "laneway"]):
        return "alley_service_corridor"
    if "garage" in t:
        return "garage_single_modern"
    return "alley_service_corridor"


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_csv = OUT_DIR / "photo_reference_catalog.csv"
    out_json = OUT_DIR / "photo_reference_summary.json"

    rows = []
    counts = Counter()
    with_coords = 0

    with INDEX.open("r", encoding="utf-8", newline="") as f:
        rd = csv.DictReader(f)
        for r in rd:
            loc = r.get("address_or_location") or ""
            loc_l = loc.lower()
            if not any(k in loc_l for k in KEYWORDS):
                continue
            category = classify_text(loc)
            m = COORD_RE.search(loc)
            lat = m.group(1) if m else ""
            lon = m.group(2) if m else ""
            if m:
                with_coords += 1
            fn = r.get("filename") or ""
            photo_path = (PHOTO_DIR / fn).resolve()
            rows.append(
                {
                    "filename": fn,
                    "photo_path": str(photo_path),
                    "address_or_location": loc,
                    "source": r.get("source") or "",
                    "category": category,
                    "lat": lat,
                    "lon": lon,
                    "has_coords": "yes" if m else "no",
                }
            )
            counts[category] += 1

    with out_csv.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else [])
        w.writeheader()
        w.writerows(rows)

    out_json.write_text(
        json.dumps(
            {
                "total_references": len(rows),
                "references_with_coords": with_coords,
                "categories": [{"category": k, "count": v} for k, v in counts.most_common()],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    print(f"[OK] Wrote {out_csv}")
    print(f"[OK] Wrote {out_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
