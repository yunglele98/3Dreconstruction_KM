#!/usr/bin/env python3
"""Generate comprehensive audit of all 1,241 active building params.

Outputs:
  outputs/deliverables/comprehensive_audit.json
  outputs/deliverables/comprehensive_audit_summary.md
"""

import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PARAMS_DIR = ROOT / "params"
OUTPUT_DIR = ROOT / "outputs" / "deliverables"

MAJOR_SECTIONS = [
    "windows_detail", "decorative_elements", "facade_detail",
    "colour_palette", "deep_facade_analysis", "doors_detail",
    "bay_window", "storefront", "roof_detail", "volumes",
    "photo_observations", "hcd_data", "context", "assessment",
    "city_data", "site",
]

REQUIRED_FIELDS = [
    "building_name", "floors", "total_height_m", "facade_width_m",
    "facade_material", "roof_type", "floor_heights_m", "windows_per_floor",
]

HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


def load_active_params():
    results = []
    for f in sorted(PARAMS_DIR.glob("*.json")):
        if f.name.startswith("_"):
            continue
        data = json.load(open(f, encoding="utf-8"))
        if data.get("skipped"):
            continue
        results.append((f.name, data))
    return results


def audit_field_coverage(params_list):
    coverage = {}
    total = len(params_list)
    for section in MAJOR_SECTIONS:
        count = sum(1 for _, d in params_list if d.get(section))
        coverage[section] = {"populated": count, "total": total,
                             "pct": round(count / total * 100, 1) if total else 0}
    return coverage


def audit_required_fields(params_list):
    missing = defaultdict(int)
    ready = marginal = fail = 0
    for _, d in params_list:
        m = [f for f in REQUIRED_FIELDS if not d.get(f)]
        if not m:
            ready += 1
        elif len(m) <= 2:
            marginal += 1
        else:
            fail += 1
        for f in m:
            missing[f] += 1
    return {"ready": ready, "marginal": marginal, "fail": fail,
            "missing_counts": dict(missing)}


def audit_consistency(params_list):
    height_mismatch = array_mismatch = hex_errors = 0
    for _, d in params_list:
        fh = d.get("floor_heights_m", [])
        th = d.get("total_height_m", 0) or 0
        floors = d.get("floors", 0) or 0
        if fh and abs(sum(fh) - th) > 0.5:
            height_mismatch += 1
        if fh and len(fh) != floors:
            array_mismatch += 1
        wpf = d.get("windows_per_floor", [])
        if wpf and len(wpf) != floors:
            array_mismatch += 1
        # Check hex colours
        for key in ["facade_detail.brick_colour_hex", "facade_detail.trim_colour_hex"]:
            parts = key.split(".")
            val = d
            for p in parts:
                val = val.get(p, {}) if isinstance(val, dict) else None
                if val is None:
                    break
            if isinstance(val, str) and val and not HEX_RE.match(val):
                hex_errors += 1
    return {"height_floor_mismatch": height_mismatch,
            "array_length_mismatch": array_mismatch,
            "hex_format_errors": hex_errors}


def audit_colour_quality(params_list):
    facade_hexes = Counter()
    for _, d in params_list:
        cp = d.get("colour_palette", {})
        fh = cp.get("facade", "")
        if fh:
            facade_hexes[fh] += 1
    return {"unique_facade_colours": len(facade_hexes),
            "top_10": dict(facade_hexes.most_common(10)),
            "singletons": sum(1 for c in facade_hexes.values() if c == 1)}


def audit_provenance(params_list):
    sources = Counter()
    stages = Counter()
    for _, d in params_list:
        meta = d.get("_meta", {})
        if meta.get("source"):
            sources[meta["source"]] += 1
        for key in ["translated", "enriched", "gaps_filled"]:
            if meta.get(key):
                stages[key] += 1
        fixes = meta.get("handoff_fixes_applied", [])
        for fix in fixes:
            fn = fix.get("fix", "").split(":")[0]
            stages[f"handoff:{fn}"] += 1
        if meta.get("deep_facade_backfill"):
            stages["deep_facade_backfill"] += 1
        if meta.get("photo_matched"):
            stages["photo_matched"] += 1
    return {"sources": dict(sources), "pipeline_stages": dict(stages)}


def audit_photo_coverage(params_list):
    matched = unmatched = 0
    for _, d in params_list:
        dfa = d.get("deep_facade_analysis", {})
        photo = (dfa.get("source_photo") if isinstance(dfa, dict) else None)
        po = d.get("photo_observations", {})
        photo2 = po.get("photo") if isinstance(po, dict) else None
        if photo or photo2:
            matched += 1
        else:
            unmatched += 1
    return {"matched": matched, "unmatched": unmatched,
            "coverage_pct": round(matched / len(params_list) * 100, 1) if params_list else 0}


def generate_summary_md(audit):
    lines = []
    lines.append("# Comprehensive Audit Summary")
    lines.append(f"**Generated:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    lines.append(f"**Buildings audited:** {audit['total_buildings']}")
    lines.append("")

    lines.append("## Generation Readiness")
    gr = audit["generation_readiness"]
    lines.append(f"- Ready: {gr['ready']} ({gr['ready']/audit['total_buildings']*100:.1f}%)")
    lines.append(f"- Marginal: {gr['marginal']}")
    lines.append(f"- Fail: {gr['fail']}")
    lines.append("")

    lines.append("## Section Coverage")
    for section, info in audit["field_coverage"].items():
        lines.append(f"- {section}: {info['populated']}/{info['total']} ({info['pct']}%)")
    lines.append("")

    lines.append("## Consistency")
    c = audit["consistency"]
    lines.append(f"- Height/floor mismatches: {c['height_floor_mismatch']}")
    lines.append(f"- Array length mismatches: {c['array_length_mismatch']}")
    lines.append(f"- Hex format errors: {c['hex_format_errors']}")
    lines.append("")

    lines.append("## Colour Quality")
    cq = audit["colour_quality"]
    lines.append(f"- Unique facade colours: {cq['unique_facade_colours']}")
    lines.append(f"- Singleton colours: {cq['singletons']}")
    lines.append("")

    lines.append("## Photo Coverage")
    pc = audit["photo_coverage"]
    lines.append(f"- Matched: {pc['matched']} ({pc['coverage_pct']}%)")
    lines.append(f"- Unmatched: {pc['unmatched']}")
    lines.append("")

    lines.append("## Data Provenance")
    prov = audit["provenance"]
    for src, count in sorted(prov["sources"].items(), key=lambda x: -x[1]):
        lines.append(f"- {src}: {count}")
    lines.append("")
    lines.append("### Pipeline stages")
    for stage, count in sorted(prov["pipeline_stages"].items(), key=lambda x: -x[1]):
        lines.append(f"- {stage}: {count}")

    return "\n".join(lines) + "\n"


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    params_list = load_active_params()
    print(f"Auditing {len(params_list)} active buildings...")

    audit = {
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "total_buildings": len(params_list),
        "field_coverage": audit_field_coverage(params_list),
        "generation_readiness": audit_required_fields(params_list),
        "consistency": audit_consistency(params_list),
        "colour_quality": audit_colour_quality(params_list),
        "provenance": audit_provenance(params_list),
        "photo_coverage": audit_photo_coverage(params_list),
    }

    json_path = OUTPUT_DIR / "comprehensive_audit.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(audit, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(f"Wrote {json_path}")

    md_path = OUTPUT_DIR / "comprehensive_audit_summary.md"
    md_path.write_text(generate_summary_md(audit), encoding="utf-8")
    print(f"Wrote {md_path}")

    # Print summary
    gr = audit["generation_readiness"]
    pc = audit["photo_coverage"]
    cq = audit["colour_quality"]
    print(f"\nReadiness: {gr['ready']} ready, {gr['marginal']} marginal, {gr['fail']} fail")
    print(f"Photo coverage: {pc['coverage_pct']}%")
    print(f"Unique facade colours: {cq['unique_facade_colours']}")


if __name__ == "__main__":
    main()
