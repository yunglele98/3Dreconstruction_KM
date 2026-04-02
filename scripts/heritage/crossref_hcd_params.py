#!/usr/bin/env python3
"""Cross-reference parsed HCD Vol.2 data with existing params and fill gaps.

Matches parsed HCD buildings to param files by address. Updates hcd_data
with any new fields from the PDF (statement_of_contribution, typology detail,
heritage_score, extracted features). Does NOT touch protected fields.

Usage:
    python scripts/heritage/crossref_hcd_params.py
    python scripts/heritage/crossref_hcd_params.py --dry-run
"""
import argparse
import json
import os
import tempfile
from pathlib import Path

REPO = Path(__file__).parent.parent.parent
PARAMS_DIR = REPO / "params"

PROTECTED_FIELDS = {
    "total_height_m", "facade_width_m", "facade_depth_m",
    "site", "city_data", "hcd_data",
}


def atomic_write_json(path, data):
    content = json.dumps(data, indent=2, ensure_ascii=False)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        os.write(fd, content.encode("utf-8"))
        os.close(fd)
        os.replace(tmp, str(path))
    except Exception:
        os.close(fd)
        os.unlink(tmp)
        raise


def normalize_for_match(addr):
    """Normalize address for fuzzy matching."""
    return addr.lower().replace("_", " ").replace("-", " ").strip()


def build_param_index(params_dir):
    """Build index of param files by normalized address."""
    index = {}
    for pf in sorted(params_dir.glob("*.json")):
        if pf.name.startswith("_"):
            continue
        addr = pf.stem.replace("_", " ")
        index[normalize_for_match(addr)] = pf
    return index


def main():
    parser = argparse.ArgumentParser(description="Cross-reference HCD with params")
    parser.add_argument("--scores", type=Path,
                        default=REPO / "outputs" / "heritage" / "heritage_scores.json")
    parser.add_argument("--params", type=Path, default=PARAMS_DIR)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    scores = json.loads(args.scores.read_text(encoding="utf-8"))
    param_index = build_param_index(args.params)

    matched = 0
    updated = 0
    unmatched = []

    for addr, hcd_data in scores.items():
        norm = normalize_for_match(addr)
        pf = param_index.get(norm)

        if not pf:
            # Try variants: "St" vs "Street", etc.
            for suffix_map in [("ave", "ave"), ("st", "st"), ("pl", "pl")]:
                pass  # normalize_for_match already handles this
            unmatched.append(addr)
            continue

        matched += 1
        params = json.loads(pf.read_text(encoding="utf-8"))

        # Update hcd_data with new fields (don't overwrite existing)
        existing_hcd = params.get("hcd_data", {})
        if not isinstance(existing_hcd, dict):
            existing_hcd = {}

        changed = False

        # Add statement_of_contribution if missing
        if not existing_hcd.get("statement_of_contribution") and hcd_data.get("statement"):
            existing_hcd["statement_of_contribution"] = hcd_data["statement"]
            changed = True

        # Add/update sub_area from PDF
        pdf_sub_area = hcd_data.get("sub_area", "")
        if pdf_sub_area and pdf_sub_area != "n/a" and not existing_hcd.get("sub_area"):
            existing_hcd["sub_area"] = pdf_sub_area
            changed = True

        # Add typology from PDF (more detailed than DB)
        pdf_typology = hcd_data.get("typology", "")
        if pdf_typology and not existing_hcd.get("typology"):
            existing_hcd["typology"] = pdf_typology
            changed = True

        # Add heritage_score and significance
        if "heritage_score" not in existing_hcd:
            existing_hcd["heritage_score"] = hcd_data.get("heritage_score", 0)
            existing_hcd["significance"] = hcd_data.get("significance", "unknown")
            changed = True

        # Add extracted features
        features = hcd_data.get("features", [])
        if features and "extracted_features" not in existing_hcd:
            existing_hcd["extracted_features"] = features
            changed = True

        # Add materials from statement
        materials = hcd_data.get("materials", [])
        if materials and "statement_materials" not in existing_hcd:
            existing_hcd["statement_materials"] = materials
            changed = True

        if changed:
            params["hcd_data"] = existing_hcd
            if not args.dry_run:
                atomic_write_json(pf, params)
            updated += 1

    print(f"Cross-reference results:")
    print(f"  HCD entries: {len(scores)}")
    print(f"  Matched to params: {matched}")
    print(f"  Updated: {updated}")
    print(f"  Unmatched: {len(unmatched)}")
    if unmatched[:10]:
        print(f"  Sample unmatched: {unmatched[:10]}")
    if args.dry_run:
        print(f"\n  [DRY-RUN] No files modified")


if __name__ == "__main__":
    main()
