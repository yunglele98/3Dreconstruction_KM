#!/usr/bin/env python3
"""
Export street-level profile summaries as JSON.

For each street: building_count, avg_height, avg_width, dominant_material,
dominant_era, heritage_density, common_decorative_features.
"""
import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PARAMS_DIR = ROOT / "params"
OUTPUT_FILE = ROOT / "outputs" / "deliverables" / "street_profiles.json"


def get_street(params: dict, filename: str) -> str:
    site = params.get("site", {})
    street = (site.get("street") or "").strip()
    if street:
        return street
    name = params.get("building_name", filename.replace("_", " "))
    for suffix in ("Ave", "St", "Pl", "Sq", "Terrace"):
        parts = name.split()
        for i, part in enumerate(parts):
            if part == suffix and i > 0:
                street_parts = []
                for j in range(i, -1, -1):
                    if parts[j].replace("-", "").replace("A", "").replace("a", "").isdigit():
                        break
                    street_parts.insert(0, parts[j])
                if street_parts:
                    return " ".join(street_parts)
    return "Unknown"


def main():
    streets = defaultdict(lambda: {
        "heights": [], "widths": [], "materials": [],
        "eras": [], "contributing": 0, "total": 0,
        "decorative_features": [],
    })

    for param_file in sorted(PARAMS_DIR.glob("*.json")):
        if param_file.name.startswith("_") or "backup" in param_file.name:
            continue
        with open(param_file, encoding="utf-8") as f:
            params = json.load(f)
        if params.get("skipped"):
            continue

        street = get_street(params, param_file.stem)
        s = streets[street]
        s["total"] += 1

        h = params.get("total_height_m")
        if isinstance(h, (int, float)) and h > 0:
            s["heights"].append(h)

        w = params.get("facade_width_m")
        if isinstance(w, (int, float)) and w > 0:
            s["widths"].append(w)

        mat = params.get("facade_material", "")
        if mat:
            s["materials"].append(mat)

        hcd = params.get("hcd_data", {})
        era = hcd.get("construction_date", "")
        if era:
            s["eras"].append(era)

        if (hcd.get("contributing") or "").lower() == "yes":
            s["contributing"] += 1

        dec = params.get("decorative_elements", {})
        for key, val in dec.items():
            if isinstance(val, dict) and val.get("present"):
                s["decorative_features"].append(key)

    # Build output
    profiles = []
    for street, data in sorted(streets.items(), key=lambda x: -x[1]["total"]):
        avg_h = round(sum(data["heights"]) / len(data["heights"]), 1) if data["heights"] else 0
        avg_w = round(sum(data["widths"]) / len(data["widths"]), 1) if data["widths"] else 0

        mat_counter = Counter(data["materials"])
        era_counter = Counter(data["eras"])
        dec_counter = Counter(data["decorative_features"])

        profiles.append({
            "street_name": street,
            "building_count": data["total"],
            "avg_height": avg_h,
            "avg_width": avg_w,
            "dominant_material": mat_counter.most_common(1)[0][0] if mat_counter else "",
            "dominant_era": era_counter.most_common(1)[0][0] if era_counter else "",
            "heritage_density": round(data["contributing"] / data["total"] * 100, 1) if data["total"] > 0 else 0,
            "common_decorative_features": [f[0] for f in dec_counter.most_common(5)],
        })

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(profiles, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print(f"Exported {len(profiles)} street profiles to {OUTPUT_FILE}")
    for p in profiles[:10]:
        print(f"  {p['street_name']}: {p['building_count']} buildings, "
              f"avg_h={p['avg_height']}m, {p['dominant_material']}, {p['dominant_era']}")


if __name__ == "__main__":
    main()
