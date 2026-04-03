#!/usr/bin/env python3
"""Build slim params JSON for the web planning platform.

Extracts key fields from all params into a lightweight JSON (~500KB)
for CesiumJS viewer, building inspector, and metrics dashboard.

Usage:
    python scripts/export/build_web_data.py
    python scripts/export/build_web_data.py --output web/public/data/params-slim.json
"""
import argparse, json, logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)
REPO = Path(__file__).parent.parent.parent


def build_slim_params(params_dir: Path, audit_path: Path | None = None) -> list[dict]:
    # Load audit scores if available
    scores = {}
    if audit_path and audit_path.exists():
        try:
            data = json.loads(audit_path.read_text(encoding="utf-8"))
            for b in data.get("buildings", []):
                scores[b.get("address", "")] = {
                    "gap_score": b.get("gap_score", 0),
                    "tier": b.get("tier", ""),
                    "primary_issue": b.get("primary_issue", {}).get("type", ""),
                }
        except Exception:
            pass

    buildings = []
    for f in sorted(params_dir.glob("*.json")):
        if f.name.startswith("_"):
            continue
        d = json.load(open(f, encoding="utf-8"))
        if d.get("skipped"):
            continue

        addr = f.stem.replace("_", " ")
        site = d.get("site", {})
        hcd = d.get("hcd_data", {})
        ctx = d.get("context", {})
        palette = d.get("colour_palette", {})
        meta = d.get("_meta", {})
        audit = scores.get(addr, {})

        # Photo reference
        photo = (d.get("deep_facade_analysis") or {}).get("source_photo") or \
                (d.get("photo_observations") or {}).get("photo")

        slim = {
            "address": addr,
            "lon": site.get("lon"),
            "lat": site.get("lat"),
            "street": site.get("street"),
            "street_number": site.get("street_number"),
            "height": d.get("total_height_m"),
            "width": d.get("facade_width_m"),
            "depth": d.get("facade_depth_m"),
            "floors": d.get("floors"),
            "material": d.get("facade_material"),
            "colour": palette.get("facade") or d.get("facade_colour"),
            "trim_colour": palette.get("trim"),
            "roof_type": d.get("roof_type"),
            "roof_colour": palette.get("roof"),
            "era": hcd.get("construction_date"),
            "typology": hcd.get("typology"),
            "contributing": hcd.get("contributing"),
            "condition": d.get("condition"),
            "has_storefront": d.get("has_storefront"),
            "building_type": ctx.get("building_type"),
            "business_name": ctx.get("business_name"),
            "photo": photo,
            "gap_score": audit.get("gap_score"),
            "tier": audit.get("tier"),
            "primary_issue": audit.get("primary_issue"),
            "has_depth": bool(d.get("depth_analysis")),
            "has_segmentation": "segmentation" in meta.get("fusion_applied", []),
            "has_export": (REPO / "outputs" / "exports" / f.stem).is_dir(),
        }
        buildings.append(slim)

    return buildings


def main():
    parser = argparse.ArgumentParser(description="Build slim params for web platform")
    parser.add_argument("--params", type=Path, default=REPO / "params")
    parser.add_argument("--audit", type=Path,
                        default=REPO / "outputs" / "visual_audit" / "priority_queue.json")
    parser.add_argument("--output", type=Path,
                        default=REPO / "web" / "public" / "data" / "params-slim.json")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    buildings = build_slim_params(args.params, args.audit)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(buildings, indent=2, ensure_ascii=False), encoding="utf-8")

    size_kb = args.output.stat().st_size / 1024
    with_coords = sum(1 for b in buildings if b.get("lon") and b.get("lat"))
    logger.info("Slim params: %d buildings (%.0f KB), %d with coordinates", len(buildings), size_kb, with_coords)


if __name__ == "__main__":
    main()
