"""Build complete data package for the web planning platform.
Combines: building params, footprints, renders, photos, audit results, street summaries.
"""

import json
import base64
from pathlib import Path

REPO = Path(__file__).parent.parent.parent
PARAMS_DIR = REPO / "params"
RENDERS_DIR = REPO / "outputs" / "buildings_renders_v1"
PHOTOS_DIR = REPO / "PHOTOS KENSINGTON sorted"
AUDIT_DIR = REPO / "outputs" / "visual_audit"
OUTPUT = REPO / "web" / "public" / "data"


def build():
    OUTPUT.mkdir(parents=True, exist_ok=True)

    # 1. Buildings with all data
    buildings = []
    for f in sorted(PARAMS_DIR.glob("*.json")):
        if f.name.startswith("_"):
            continue
        try:
            p = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        if p.get("skipped"):
            continue

        site = p.get("site", {}) if isinstance(p.get("site"), dict) else {}
        hcd = p.get("hcd_data", {}) if isinstance(p.get("hcd_data"), dict) else {}
        palette = p.get("colour_palette", {}) if isinstance(p.get("colour_palette"), dict) else {}
        fd = p.get("facade_detail", {}) if isinstance(p.get("facade_detail"), dict) else {}
        dec = p.get("decorative_elements", {}) if isinstance(p.get("decorative_elements"), dict) else {}

        stem = f.stem
        address = p.get("building_name", stem.replace("_", " "))

        # Check for render
        render_path = RENDERS_DIR / f"{stem}.png"
        has_render = render_path.exists()

        # Check for photo
        has_photo = False
        photo_rel = None
        for subdir in PHOTOS_DIR.iterdir():
            if not subdir.is_dir():
                continue
            for photo in subdir.glob("*.jpg"):
                if stem.lower() in photo.stem.lower():
                    has_photo = True
                    photo_rel = str(photo.relative_to(REPO))
                    break
            if has_photo:
                break

        buildings.append({
            "id": stem,
            "address": address,
            "lon": site.get("lon"),
            "lat": site.get("lat"),
            "street": site.get("street", ""),
            "street_number": site.get("street_number", ""),
            "floors": p.get("floors"),
            "total_height_m": p.get("total_height_m"),
            "facade_width_m": p.get("facade_width_m"),
            "facade_depth_m": p.get("facade_depth_m"),
            "roof_type": p.get("roof_type"),
            "facade_material": p.get("facade_material"),
            "facade_colour": p.get("facade_colour"),
            "facade_hex": fd.get("brick_colour_hex") or palette.get("facade"),
            "trim_hex": fd.get("trim_colour_hex") or palette.get("trim"),
            "roof_hex": palette.get("roof"),
            "condition": p.get("condition"),
            "has_storefront": p.get("has_storefront", False),
            "typology": hcd.get("typology", ""),
            "era": hcd.get("construction_date", ""),
            "contributing": hcd.get("contributing", ""),
            "architectural_style": hcd.get("architectural_style", ""),
            "party_wall_left": p.get("party_wall_left", False),
            "party_wall_right": p.get("party_wall_right", False),
            "decorative": [k for k, v in dec.items() if isinstance(v, dict) and v.get("present")],
            "has_render": has_render,
            "render_path": f"renders/{stem}.png" if has_render else None,
            "has_photo": has_photo,
            "photo_path": photo_rel,
        })

    # 2. Audit data
    audit = {}
    audit_path = AUDIT_DIR / "audit_report.json"
    if audit_path.exists():
        try:
            ar = json.loads(audit_path.read_text(encoding="utf-8"))
            for b in ar.get("buildings", []):
                addr = b.get("address", "")
                stem = addr.replace(" ", "_")
                audit[stem] = {
                    "gap_score": b.get("gap_score"),
                    "tier": b.get("tier"),
                    "primary_issue": b.get("primary_issue", {}).get("type") if isinstance(b.get("primary_issue"), dict) else None,
                }
        except Exception:
            pass

    # Merge audit into buildings
    for b in buildings:
        a = audit.get(b["id"], {})
        b["gap_score"] = a.get("gap_score")
        b["audit_tier"] = a.get("tier")
        b["primary_issue"] = a.get("primary_issue")

    # 3. Street summaries
    streets = {}
    ss_path = AUDIT_DIR / "street_summaries.json"
    if ss_path.exists():
        try:
            streets = json.loads(ss_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    # 4. Stats
    stats = {
        "total_buildings": len(buildings),
        "with_coords": sum(1 for b in buildings if b["lon"] and b["lat"]),
        "contributing": sum(1 for b in buildings if b["contributing"] == "Yes"),
        "with_renders": sum(1 for b in buildings if b["has_render"]),
        "with_photos": sum(1 for b in buildings if b["has_photo"]),
        "eras": {},
        "materials": {},
        "roof_types": {},
        "conditions": {},
        "streets": {},
    }
    for b in buildings:
        era = b["era"] or "Unknown"
        stats["eras"][era] = stats["eras"].get(era, 0) + 1
        mat = (b["facade_material"] or "unknown").lower()
        stats["materials"][mat] = stats["materials"].get(mat, 0) + 1
        roof = b["roof_type"] or "unknown"
        stats["roof_types"][roof] = stats["roof_types"].get(roof, 0) + 1
        cond = b["condition"] or "unknown"
        stats["conditions"][cond] = stats["conditions"].get(cond, 0) + 1
        street = b["street"] or "Unknown"
        stats["streets"][street] = stats["streets"].get(street, 0) + 1

    # Write
    (OUTPUT / "app_data.json").write_text(json.dumps({
        "buildings": buildings,
        "stats": stats,
        "streets": streets,
    }, ensure_ascii=False), encoding="utf-8")

    print(f"Web app data: {len(buildings)} buildings")
    print(f"  With coords: {stats['with_coords']}")
    print(f"  With renders: {stats['with_renders']}")
    print(f"  With photos: {stats['with_photos']}")
    print(f"  Contributing: {stats['contributing']}")


if __name__ == "__main__":
    build()
