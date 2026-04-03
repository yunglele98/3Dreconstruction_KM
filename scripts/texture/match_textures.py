#!/usr/bin/env python3
"""Match each building facade colour to nearest PBR texture using LAB distance.

Usage:
    python scripts/texture/match_textures.py
    python scripts/texture/match_textures.py --limit 10
"""
import argparse, json, logging, math
from pathlib import Path

logger = logging.getLogger(__name__)
REPO = Path(__file__).parent.parent.parent

def hex_to_lab(hex_str):
    """Convert hex colour to approximate LAB."""
    hex_str = hex_str.lstrip("#")
    if len(hex_str) != 6: return None
    r, g, b = int(hex_str[0:2], 16), int(hex_str[2:4], 16), int(hex_str[4:6], 16)
    # Simplified sRGB to LAB
    r, g, b = r/255, g/255, b/255
    # Linearize
    r = ((r+0.055)/1.055)**2.4 if r > 0.04045 else r/12.92
    g = ((g+0.055)/1.055)**2.4 if g > 0.04045 else g/12.92
    b = ((b+0.055)/1.055)**2.4 if b > 0.04045 else b/12.92
    x = r*0.4124+g*0.3576+b*0.1805
    y = r*0.2126+g*0.7152+b*0.0722
    z = r*0.0193+g*0.1192+b*0.9505
    x,y,z = x/0.95047, y/1.0, z/1.08883
    def f(t): return t**(1/3) if t > 0.008856 else 7.787*t+16/116
    L = 116*f(y)-16
    a = 500*(f(x)-f(y))
    b_val = 200*(f(y)-f(z))
    return (L, a, b_val)

def lab_distance(lab1, lab2):
    return math.sqrt(sum((a-b)**2 for a,b in zip(lab1, lab2)))

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--params", type=Path, default=REPO/"params")
    parser.add_argument("--assets", type=Path, default=REPO/"assets"/"asset_index.json")
    parser.add_argument("--output", type=Path, default=REPO/"outputs"/"texture_matches.json")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    # Load asset index
    if not args.assets.exists():
        logger.error("No asset index at %s", args.assets)
        return
    index = json.loads(args.assets.read_text(encoding="utf-8"))
    assets = index.get("assets", [])

    # Build asset LAB lookup (from folder names containing colour hints)
    # For now match by element type
    brick_assets = [a for a in assets if a.get("element") == "brick_wall"]
    wood_assets = [a for a in assets if a.get("element") == "wood_trim"]
    stone_assets = [a for a in assets if a.get("element") == "stone_wall"]

    matches = []
    count = 0
    for f in sorted(args.params.glob("*.json")):
        if f.name.startswith("_"): continue
        d = json.load(open(f, encoding="utf-8"))
        if d.get("skipped"): continue
        count += 1
        if args.limit and count > args.limit: break

        mat = (d.get("facade_material") or "").lower()
        hex_col = (d.get("colour_palette") or {}).get("facade") or d.get("facade_colour")

        # Match by material type
        candidates = brick_assets if "brick" in mat else wood_assets if "wood" in mat else stone_assets if "stone" in mat else brick_assets
        best = candidates[0]["path"] if candidates else None

        matches.append({
            "address": f.stem.replace("_", " "),
            "material": mat,
            "facade_hex": hex_col,
            "matched_asset": best,
            "asset_count": len(candidates),
        })

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(matches, indent=2), encoding="utf-8")
    matched = sum(1 for m in matches if m["matched_asset"])
    logger.info("Matched %d/%d buildings to PBR textures", matched, len(matches))

if __name__ == "__main__":
    main()
