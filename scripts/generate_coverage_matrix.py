#!/usr/bin/env python3
"""Generate pipeline coverage matrix — which buildings have which outputs.

Scans params, depth_maps, segmentation, signage, exports, renders, blends
and produces a per-building coverage JSON + summary stats.

Usage:
    python scripts/generate_coverage_matrix.py
    python scripts/generate_coverage_matrix.py --output outputs/coverage_matrix.json
"""
import json, argparse, logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)
REPO = Path(__file__).parent.parent

def main():
    parser = argparse.ArgumentParser(description="Generate coverage matrix")
    parser.add_argument("--output", type=Path, default=REPO/"outputs"/"coverage_matrix.json")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    depth_dir = REPO/"depth_maps"; seg_dir = REPO/"segmentation"; sig_dir = REPO/"signage"
    exports_dir = REPO/"outputs"/"exports"; renders_dir = REPO/"outputs"/"buildings_renders_v1"
    full_dir = REPO/"outputs"/"full"

    depth_stems = {f.stem for f in depth_dir.glob("*.npy")} if depth_dir.exists() else set()
    seg_stems = {f.stem.replace("_elements","") for f in seg_dir.glob("*_elements.json")} if seg_dir.exists() else set()
    sig_stems = {f.stem.replace("_text","") for f in sig_dir.glob("*_text.json")} if sig_dir.exists() else set()

    buildings = []
    totals = {"active":0,"has_photo":0,"depth_map":0,"depth_fused":0,"seg_map":0,"seg_fused":0,
              "signage":0,"sig_fused":0,"exported":0,"rendered":0,"blended":0}

    for f in sorted((REPO/"params").glob("*.json")):
        if f.name.startswith("_"): continue
        d = json.load(open(f, encoding="utf-8"))
        if d.get("skipped"): continue
        totals["active"] += 1
        addr = f.stem
        meta = d.get("_meta",{})
        fa = meta.get("fusion_applied",[])
        photo = (d.get("deep_facade_analysis") or {}).get("source_photo") or (d.get("photo_observations") or {}).get("photo")
        photo_stem = Path(photo).stem if photo else None

        row = {"address": addr}
        row["has_photo"] = bool(photo); totals["has_photo"] += row["has_photo"]
        row["depth_map"] = photo_stem in depth_stems if photo_stem else False; totals["depth_map"] += row["depth_map"]
        row["depth_fused"] = bool(d.get("depth_analysis")); totals["depth_fused"] += row["depth_fused"]
        row["seg_map"] = photo_stem in seg_stems if photo_stem else False; totals["seg_map"] += row["seg_map"]
        row["seg_fused"] = "segmentation" in fa; totals["seg_fused"] += row["seg_fused"]
        row["signage"] = photo_stem in sig_stems if photo_stem else False; totals["signage"] += row["signage"]
        row["sig_fused"] = "signage" in fa; totals["sig_fused"] += row["sig_fused"]
        row["exported"] = (exports_dir/addr).is_dir(); totals["exported"] += row["exported"]
        row["rendered"] = (renders_dir/f"{addr}.png").exists(); totals["rendered"] += row["rendered"]
        row["blended"] = (full_dir/f"{addr}.blend").exists(); totals["blended"] += row["blended"]
        buildings.append(row)

    total = totals["active"]
    output = {"generated_at": datetime.now().isoformat(), "total_active": total,
              "summary": {k: {"count":v, "pct": round(v/total*100,1) if total else 0} for k,v in totals.items()},
              "buildings": buildings}

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2), encoding="utf-8")

    logger.info("Coverage Matrix (%d buildings):", total)
    for k,v in totals.items():
        if k == "active": continue
        pct = v/total*100 if total else 0
        bar = "#"*int(pct/5) + "."*(20-int(pct/5))
        logger.info("  %-15s %5d / %d  [%s] %.1f%%", k, v, total, bar, pct)
    logger.info("Saved: %s", args.output)

if __name__ == "__main__":
    main()
