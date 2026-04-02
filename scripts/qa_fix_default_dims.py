#!/usr/bin/env python3
"""Fix buildings stuck at 5.0x10.0m defaults using street-based heuristics."""
import json
import re
from pathlib import Path

PARAMS = Path(__file__).resolve().parent.parent / "params"

# Perimeter streets are commercial: wider, deeper
PERIMETER_STREETS = {"College", "Spadina", "Bathurst", "Dundas"}

# Interior streets are residential
RESIDENTIAL_STREETS = {
    "Augusta", "Kensington", "Baldwin", "Nassau", "Oxford", "Wales",
    "Bellevue", "Denison", "Lippincott", "Leonard", "Hickory",
    "Casimir", "Fitzroy", "Glen_Baillie", "St_Andrew", "Carlyle",
}

STREET_RE = re.compile(
    r"(\d+[-A-Za-z]*_)?"
    r"((?:Glen_Baillie|St_Andrew|[A-Za-z]+))"
    r"_(?:St|Ave|Pl|Blvd|Rd|Terr|Dr|Cres)"
)


def main():
    fixed = 0
    for f in sorted(PARAMS.glob("*.json")):
        if f.name.startswith("_"):
            continue
        d = json.load(open(f, encoding="utf-8"))
        if d.get("skipped"):
            continue
        if d.get("_meta", {}).get("qa_photo_fixes"):
            continue

        w = d.get("facade_width_m", 0) or 0
        dep = d.get("facade_depth_m", 0) or 0

        if w != 5.0 or dep != 10.0:
            continue

        # Determine street type
        m = STREET_RE.search(f.stem)
        street = m.group(2) if m else ""

        fl = d.get("floors", 2) or 2
        has_sf = d.get("has_storefront", False)

        is_perimeter = any(s in street for s in PERIMETER_STREETS)
        is_commercial = has_sf or is_perimeter or fl >= 4

        if is_commercial:
            name_len = len(f.stem)
            if name_len > 80:
                new_w, new_d = 35.0, 18.0
            elif name_len > 50:
                new_w, new_d = 20.0, 15.0
            elif has_sf and fl >= 3:
                new_w, new_d = 12.0, 15.0
            else:
                new_w, new_d = 8.0, 12.0
            reason = f"commercial heuristic: {new_w}x{new_d}m"
        else:
            if "semi" in (d.get("hcd_data", {}).get("typology") or "").lower():
                new_w, new_d = 5.5, 12.0
            elif "row" in (d.get("hcd_data", {}).get("typology") or "").lower():
                new_w, new_d = 5.0, 12.0
            elif "detached" in (d.get("hcd_data", {}).get("typology") or "").lower():
                new_w, new_d = 7.0, 10.0
            else:
                new_w, new_d = 6.0, 11.0
            reason = f"residential heuristic: {new_w}x{new_d}m"

        d["facade_width_m"] = new_w
        d["facade_depth_m"] = new_d

        # Also fix window counts if too high for width
        wpf = d.get("windows_per_floor", [])
        if wpf:
            max_win = max(1, int(new_w / 1.5))
            new_wpf = [min(x, max_win) if isinstance(x, (int, float)) else x for x in wpf]
            if new_wpf != wpf:
                d["windows_per_floor"] = new_wpf
                reason += f", capped windows to {max_win}/floor"

        meta = d.setdefault("_meta", {})
        qa = meta.get("qa_photo_fixes", [])
        qa.append(reason)
        meta["qa_photo_fixes"] = qa

        json.dump(d, open(f, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
        fixed += 1

    print(f"Fixed {fixed} buildings with default 5x10m dimensions")


if __name__ == "__main__":
    main()
