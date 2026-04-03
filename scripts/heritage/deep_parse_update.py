#!/usr/bin/env python3
"""HCD Deep Parse: Extract features, compute scores, update all params.

Reads each params file's hcd_data.statement_of_contribution, extracts
architectural features, computes heritage significance scores, and
writes results back to params. Also fills any missing statements from
the freshly-parsed PDF data.

Usage:
    python scripts/heritage/deep_parse_update.py
    python scripts/heritage/deep_parse_update.py --dry-run
"""
import argparse
import json
import os
import tempfile
from pathlib import Path

REPO = Path(__file__).parent.parent.parent

# Import feature extraction and scoring from sibling modules
import sys
sys.path.insert(0, str(Path(__file__).parent))
from extract_hcd_features import extract_features, FEATURE_PATTERNS, MATERIAL_PATTERNS
from heritage_score import compute_score, classify


def atomic_write_json(path, data):
    content = json.dumps(data, indent=2, ensure_ascii=False)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        os.write(fd, content.encode("utf-8"))
        os.close(fd)
        os.replace(tmp, str(path))
    except Exception:
        os.close(fd)
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def load_parsed_pdf():
    """Load freshly-parsed PDF data as a lookup by normalized address."""
    parsed_path = REPO / "outputs" / "heritage" / "hcd_parsed.json"
    if not parsed_path.exists():
        return {}
    data = json.loads(parsed_path.read_text(encoding="utf-8"))
    # Build lookup by various address forms
    lookup = {}
    for addr, entry in data.items():
        lookup[addr.lower()] = entry
        norm = addr.replace("_", " ").lower()
        lookup[norm] = entry
    return lookup


def main():
    parser = argparse.ArgumentParser(description="HCD deep parse: features + scores -> params")
    parser.add_argument("--params-dir", type=Path, default=REPO / "params")
    parser.add_argument("--dry-run", action="store_true", help="Print changes without writing")
    args = parser.parse_args()

    pdf_lookup = load_parsed_pdf()

    param_files = sorted(args.params_dir.glob("*.json"))
    param_files = [f for f in param_files if not f.name.startswith("_") and not f.suffix == ".pdf"]
    # Filter out backup files
    param_files = [f for f in param_files if ".backup" not in f.name]

    stats = {
        "total": len(param_files),
        "had_statement": 0,
        "filled_from_pdf": 0,
        "features_added": 0,
        "scores_added": 0,
        "already_complete": 0,
        "no_statement": 0,
    }

    all_features = {}
    all_scores = {}
    feature_freq = {}

    for pf in param_files:
        data = json.loads(pf.read_text(encoding="utf-8"))
        hcd = data.get("hcd_data", {})
        if not isinstance(hcd, dict):
            hcd = {}

        changed = False
        addr = pf.stem.replace("_", " ")

        # Step 1: Ensure we have a statement
        statement = hcd.get("statement_of_contribution", "")
        if not statement or len(statement) < 20:
            # Try to fill from parsed PDF
            pdf_entry = pdf_lookup.get(addr.lower())
            if pdf_entry and pdf_entry.get("statement"):
                statement = pdf_entry["statement"]
                hcd["statement_of_contribution"] = statement
                # Also fill sub_area, typology, construction_date if missing
                for field in ("sub_area", "typology", "construction_date"):
                    if not hcd.get(field) and pdf_entry.get(field):
                        val = pdf_entry[field]
                        if field == "sub_area" and val == "n/a":
                            continue
                        hcd[field] = val
                changed = True
                stats["filled_from_pdf"] += 1
            else:
                stats["no_statement"] += 1
                continue
        else:
            stats["had_statement"] += 1

        # Step 2: Extract features from statement
        extraction = extract_features(statement)
        features = extraction["features"]
        materials = extraction["materials"]
        feature_count = extraction["feature_count"]

        if features and hcd.get("extracted_features") != features:
            hcd["extracted_features"] = features
            hcd["statement_materials"] = materials
            hcd["feature_count"] = feature_count
            changed = True
            stats["features_added"] += 1

        # Track frequency
        for f in features:
            feature_freq[f] = feature_freq.get(f, 0) + 1

        # Step 3: Compute heritage score
        score_input = {
            "contributing": hcd.get("contributing", "Yes"),
            "construction_date": hcd.get("construction_date", ""),
            "feature_count": feature_count,
            "typology": hcd.get("typology", ""),
            "sub_area": hcd.get("sub_area", "n/a"),
        }
        score = compute_score(score_input)
        significance = classify(score)

        if hcd.get("heritage_score") != score or hcd.get("significance") != significance:
            hcd["heritage_score"] = score
            hcd["significance"] = significance
            changed = True
            stats["scores_added"] += 1

        all_features[addr] = features
        all_scores[addr] = {"score": score, "significance": significance}

        if changed:
            data["hcd_data"] = hcd
            if not args.dry_run:
                atomic_write_json(pf, data)
        else:
            stats["already_complete"] += 1

    # Print report
    print(f"HCD Deep Parse Update")
    print(f"=" * 50)
    print(f"  Total param files:       {stats['total']}")
    print(f"  Had statement:           {stats['had_statement']}")
    print(f"  Filled from PDF:         {stats['filled_from_pdf']}")
    print(f"  No statement available:  {stats['no_statement']}")
    print(f"  Features added/updated:  {stats['features_added']}")
    print(f"  Scores added/updated:    {stats['scores_added']}")
    print(f"  Already complete:        {stats['already_complete']}")

    # Feature frequency
    buildings_with_features = sum(1 for f in all_features.values() if f)
    total_mentions = sum(len(f) for f in all_features.values())
    print(f"\nFeature extraction:")
    print(f"  Buildings with features: {buildings_with_features}")
    print(f"  Total feature mentions:  {total_mentions}")
    if buildings_with_features:
        print(f"  Avg features/building:   {total_mentions / buildings_with_features:.1f}")

    print(f"\nFeature frequency (top 20):")
    for fid, count in sorted(feature_freq.items(), key=lambda x: -x[1])[:20]:
        pct = count / max(buildings_with_features, 1) * 100
        print(f"    {fid:25s} {count:4d} ({pct:.0f}%)")

    # Score distribution
    scores = [s["score"] for s in all_scores.values()]
    if scores:
        sig_counts = {"high": 0, "medium": 0, "low": 0, "minimal": 0}
        for s in all_scores.values():
            sig_counts[s["significance"]] += 1
        print(f"\nHeritage scores ({len(scores)} buildings):")
        print(f"  Mean: {sum(scores) / len(scores):.1f}, Min: {min(scores)}, Max: {max(scores)}")
        for level, count in sig_counts.items():
            print(f"    {level:10s} {count:4d} ({count / len(scores) * 100:.0f}%)")

    if args.dry_run:
        print(f"\n  [DRY-RUN] No files modified")

    # Save summary to outputs
    summary_path = REPO / "outputs" / "heritage" / "heritage_report.json"
    summary = {
        "total_buildings": stats["total"],
        "buildings_with_statements": stats["had_statement"] + stats["filled_from_pdf"],
        "buildings_with_features": buildings_with_features,
        "total_feature_mentions": total_mentions,
        "feature_frequency": dict(sorted(feature_freq.items(), key=lambda x: -x[1])),
        "score_distribution": {
            "mean": round(sum(scores) / len(scores), 1) if scores else 0,
            "min": min(scores) if scores else 0,
            "max": max(scores) if scores else 0,
        },
        "significance_counts": sig_counts if scores else {},
    }
    if not args.dry_run:
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\nSaved report: {summary_path}")


if __name__ == "__main__":
    main()
