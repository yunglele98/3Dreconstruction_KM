#!/usr/bin/env python3
"""Extract architectural features from HCD statement text via keyword matching.

Usage:
    python scripts/heritage/extract_hcd_features.py
"""
import argparse
import json
import re
from pathlib import Path

REPO = Path(__file__).parent.parent.parent

FEATURE_PATTERNS = {
    "bay_window": [r"\bbay window", r"\bbay-and-gable", r"\bcanted bay", r"\bbox bay", r"\boriel"],
    "cornice": [r"\bcornice", r"\bcorbelled cornice", r"\bbrick cornice"],
    "porch": [r"\bporch", r"\bveranda", r"\bverandah", r"\bcovered entry", r"\benclosed porch"],
    "dormer": [r"\bdormer"],
    "gable": [r"\bgable", r"\bfront gable", r"\bcross gable", r"\bbay-and-gable"],
    "bargeboard": [r"\bbargeboard", r"\bverge board", r"\bdecorative gable"],
    "string_course": [r"\bstring course", r"\bbelt course", r"\bbrick band", r"\bhorizontal band"],
    "quoins": [r"\bquoin", r"\bcorner detail"],
    "voussoirs": [r"\bvoussoir", r"\bsegmental arch", r"\bflat arch", r"\bbrick arch", r"\barched window"],
    "transom": [r"\btransom", r"\bfanlight", r"\bsidelights?"],
    "storefront": [r"\bstorefront", r"\bshopfront", r"\bcommercial conversion", r"\bcommercial addition",
                   r"\bdisplay window", r"\bretail", r"\bground.floor commercial"],
    "awning": [r"\bawning", r"\bcanopy", r"\bsignage"],
    "chimney": [r"\bchimney"],
    "parapet": [r"\bparapet", r"\bflat roof"],
    "brackets": [r"\bbracket", r"\bmodillion", r"\bcorbel"],
    "pilasters": [r"\bpilaster", r"\bengaged column"],
    "stained_glass": [r"\bstained glass", r"\bleaded glass", r"\bart glass"],
    "shutters": [r"\bshutter"],
    "balcony": [r"\bbalcon"],
    "tower": [r"\btower", r"\bturret"],
    "foundation_stone": [r"\bstone foundation", r"\brubble.*foundation"],
    # HCD-specific general terms
    "victorian_style": [r"\bvictorian", r"\bvernacular.*victorian"],
    "commercial_conversion": [r"\bcommercial conversion", r"\bcommercial addition",
                              r"\bmodified to accommodate"],
    "heritage_fabric": [r"\boriginal.*fabric", r"\bheritage attribute", r"\bcontribut"],
    "row_housing": [r"\brow\b.*hous", r"\bworkers.*housing", r"\brow building"],
    "semi_detached": [r"\bsemi-detached", r"\bsemi detached"],
}

MATERIAL_PATTERNS = {
    "brick": [r"\bbrick"],
    "stone": [r"\bstone", r"\blimestone", r"\bsandstone"],
    "wood_clad": [r"\bclapboard", r"\bwood.*clad", r"\bframe construction"],
    "stucco": [r"\bstucco", r"\bplaster"],
}


def extract_features(statement):
    if not statement:
        return {"features": [], "materials": [], "feature_count": 0}
    text = statement.lower()
    features = []
    materials = []
    for fid, patterns in FEATURE_PATTERNS.items():
        for p in patterns:
            if re.search(p, text):
                features.append(fid)
                break
    for mid, patterns in MATERIAL_PATTERNS.items():
        for p in patterns:
            if re.search(p, text):
                materials.append(mid)
                break
    return {"features": features, "materials": materials, "feature_count": len(features)}


def main():
    parser = argparse.ArgumentParser(description="Extract HCD features")
    parser.add_argument("--input", type=Path,
                        default=REPO / "outputs" / "heritage" / "hcd_parsed.json")
    parser.add_argument("--output", type=Path,
                        default=REPO / "outputs" / "heritage" / "hcd_features.json")
    args = parser.parse_args()

    parsed = json.loads(args.input.read_text(encoding="utf-8"))
    results = {}
    feature_counts = {}

    for addr, data in parsed.items():
        extraction = extract_features(data.get("statement", ""))
        results[addr] = {**data, **extraction}
        for f in extraction["features"]:
            feature_counts[f] = feature_counts.get(f, 0) + 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")

    total = sum(r["feature_count"] for r in results.values())
    print(f"Extracted features for {len(results)} buildings")
    print(f"Total feature mentions: {total}, avg {total / max(len(results), 1):.1f}/building")
    print(f"\nFeature frequency:")
    for fid, count in sorted(feature_counts.items(), key=lambda x: -x[1]):
        print(f"  {fid:25s} {count:4d} ({count / len(results) * 100:.0f}%)")


if __name__ == "__main__":
    main()
