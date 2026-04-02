#!/usr/bin/env python3
"""Phase 0: Generate per-street summary reports from audit results.

Usage:
    python scripts/visual_audit/street_summary.py
    python scripts/visual_audit/street_summary.py --input outputs/visual_audit/priority_queue.json
"""
from __future__ import annotations
import argparse, json, logging, re
from collections import Counter
from pathlib import Path
import numpy as np

logger = logging.getLogger(__name__)
REPO_ROOT = Path(__file__).parent.parent.parent
STREET_SUFFIXES = {"St","Ave","Pl","Rd","Ter","Ln","Cres","Blvd","Dr"}

def extract_street(address):
    parts = address.strip().split()
    if len(parts) < 2: return address
    for i, part in enumerate(parts):
        if part in STREET_SUFFIXES and i > 0:
            start = 0
            for j, p in enumerate(parts):
                if not re.match(r"^[\d\-]+[A-Za-z]?$", p):
                    start = j; break
            return " ".join(parts[start:i+1])
    for i, part in enumerate(parts):
        if not re.match(r"^[\d\-]+[A-Za-z]?$", part):
            return " ".join(parts[i:])
    return address

def generate_street_summaries(data):
    buildings = data.get("buildings", data) if isinstance(data, dict) else data
    streets = {}
    for b in buildings:
        street = extract_street(b.get("address", ""))
        streets.setdefault(street, []).append(b)
    summaries = {}
    for street, bldgs in sorted(streets.items()):
        matched = [b for b in bldgs if b["tier"] != "no_photo"]
        scores = [b["gap_score"] for b in matched]
        tiers = Counter(b["tier"] for b in bldgs)
        issues = Counter()
        for b in matched:
            for issue in b.get("all_issues", []):
                if issue["type"] != "acceptable": issues[issue["type"]] += 1
        colmap_candidates = sum(1 for b in matched if b.get("photo_count",0) >= 3 and b["gap_score"] >= 50)
        contributing = sum(1 for b in bldgs if (b.get("hcd_contributing") or "").lower() == "yes")
        eras = Counter(b.get("era") for b in bldgs if b.get("era"))
        needed_stages = {}
        for b in bldgs:
            for stage in b.get("needed_stages", []):
                needed_stages[stage] = needed_stages.get(stage, 0) + 1
        building_table = [{"address":b["address"],"gap_score":b["gap_score"],"tier":b["tier"],
            "primary_issue":b.get("primary_issue",{}).get("type",""),"photo_count":b.get("photo_count",0),
            "era":b.get("era",""),"contributing":b.get("hcd_contributing","")}
            for b in sorted(bldgs, key=lambda x: x["gap_score"], reverse=True)]
        summaries[street] = {"street":street,"building_count":len(bldgs),
            "avg_gap_score":round(float(np.mean(scores)),1) if scores else 0,
            "min_gap_score":round(min(scores),1) if scores else 0,
            "max_gap_score":round(max(scores),1) if scores else 0,
            "tier_distribution":dict(tiers),"top_issues":dict(issues.most_common(5)),
            "colmap_candidates":colmap_candidates,
            "heritage":{"contributing_count":contributing,
                "contributing_pct":round(contributing/len(bldgs)*100,1) if bldgs else 0,
                "era_distribution":dict(eras)},
            "needed_stages":needed_stages,"buildings":building_table}
    return summaries

def write_street_markdown(street, summary, output_dir):
    safe_name = re.sub(r"[^\w\s\-]","",street).replace(" ","_")
    md_path = output_dir / f"{safe_name}.md"
    lines = [f"# {street} -- Visual Audit Summary","",
        f"**Buildings:** {summary['building_count']}",
        f"**Average gap score:** {summary['avg_gap_score']}",
        f"**COLMAP candidates:** {summary['colmap_candidates']}",
        f"**Contributing:** {summary['heritage']['contributing_count']} ({summary['heritage']['contributing_pct']}%)","",
        "## Tier Distribution",""]
    for tier in ["critical","high","medium","low","acceptable","no_photo"]:
        c = summary["tier_distribution"].get(tier,0)
        if c > 0: lines.append(f"- **{tier}:** {c}")
    lines.extend(["","## Top Issues",""])
    for issue, count in summary.get("top_issues",{}).items():
        lines.append(f"- {issue.replace('_',' ')}: {count}")
    lines.extend(["","## Buildings","",
        "| Address | Score | Tier | Issue | Photos |",
        "|---------|-------|------|-------|--------|"])
    for b in summary["buildings"]:
        lines.append(f"| {b['address']} | {b['gap_score']} | {b['tier']} | {b['primary_issue']} | {b['photo_count']} |")
    md_path.write_text("\n".join(lines), encoding="utf-8")

def main():
    parser = argparse.ArgumentParser(description="Phase 0: Street summaries")
    parser.add_argument("--input", type=Path, default=REPO_ROOT/"outputs"/"visual_audit"/"priority_queue.json")
    parser.add_argument("--output", type=Path, default=REPO_ROOT/"outputs"/"visual_audit")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    data = json.loads(args.input.read_text(encoding="utf-8"))
    summaries = generate_street_summaries(data)
    json_path = args.output / "street_summaries.json"
    json_path.write_text(json.dumps(summaries, indent=2), encoding="utf-8")
    logger.info("Street summaries: %s (%d streets)", json_path, len(summaries))
    streets_dir = args.output / "streets"
    streets_dir.mkdir(parents=True, exist_ok=True)
    for street, summary in summaries.items():
        write_street_markdown(street, summary, streets_dir)
    logger.info("Street reports: %s/ (%d files)", streets_dir, len(summaries))
    ranked = sorted(summaries.values(), key=lambda s: s["avg_gap_score"], reverse=True)
    logger.info("\nWorst streets:")
    for s in ranked[:10]:
        logger.info("  %5.1f  %-20s (%d bldgs, %d COLMAP)", s["avg_gap_score"], s["street"], s["building_count"], s["colmap_candidates"])

if __name__ == "__main__":
    main()
