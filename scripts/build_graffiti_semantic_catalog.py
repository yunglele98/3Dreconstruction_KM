#!/usr/bin/env python3
"""Build semantic graffiti catalog from Kensington photo reference text."""

from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IN_CSV = ROOT / "outputs" / "alley_garages" / "graffiti_reference_shortlist.csv"
OUT_JSON = ROOT / "outputs" / "alley_garages" / "graffiti_semantic_catalog.json"
OUT_CSV = ROOT / "outputs" / "alley_garages" / "graffiti_semantic_catalog.csv"


def classify_style(text: str) -> str:
    t = (text or "").lower()
    if "mural" in t or "keith haring" in t:
        return "mural_figurative"
    if "graffiti" in t and "wall" in t:
        return "wall_tag_cluster"
    if "garages with graffiti" in t:
        return "rollup_throwup_cluster"
    if "tag" in t:
        return "tag_linework"
    if "alley" in t or "lane" in t or "ruelle" in t:
        return "alley_mixed_surface"
    return "generic_urban_marking"


def classify_surface(text: str) -> str:
    t = (text or "").lower()
    if "garage" in t:
        return "painted_metal_door"
    if "mural" in t or "wall" in t:
        return "masonry_wall"
    if "interior" in t and "parking" in t:
        return "sealed_concrete"
    if "lane" in t or "alley" in t or "ruelle" in t:
        return "asphalt_or_concrete_ground"
    return "mixed_surface"


def weather_bias(text: str) -> str:
    t = (text or "").lower()
    if "hdr" in t:
        return "neutral"
    if "night" in t:
        return "wet_specular"
    return "neutral"


def main() -> int:
    rows = list(csv.DictReader(IN_CSV.open("r", encoding="utf-8", newline="")))

    style_c = Counter()
    surface_c = Counter()
    out_rows = []
    for r in rows:
        text = r.get("address_or_location") or ""
        style = classify_style(text)
        surface = classify_surface(text)
        wb = weather_bias(text)
        style_c[style] += 1
        surface_c[surface] += 1
        out_rows.append(
            {
                "filename": r.get("filename") or "",
                "style": style,
                "surface": surface,
                "weather_bias": wb,
                "score": r.get("score") or "",
                "address_or_location": text,
            }
        )

    OUT_JSON.write_text(
        json.dumps(
            {
                "total_entries": len(out_rows),
                "style_counts": dict(style_c),
                "surface_counts": dict(surface_c),
                "entries": out_rows,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    with OUT_CSV.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out_rows[0].keys()) if out_rows else ["filename", "style", "surface", "weather_bias", "score", "address_or_location"])
        w.writeheader()
        w.writerows(out_rows)

    print(f"[OK] Wrote {OUT_JSON}")
    print(f"[OK] Wrote {OUT_CSV}")
    print(f"[INFO] styles={len(style_c)} surfaces={len(surface_c)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
