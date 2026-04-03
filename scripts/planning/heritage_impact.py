#!/usr/bin/env python3
"""Assess heritage impact of scenario interventions.

Checks each intervention against HCD guidelines: contributing buildings
should not be demolished or have incompatible additions. Flags changes
to protected buildings and scores heritage preservation.

Usage:
    python scripts/planning/heritage_impact.py --scenario scenarios/10yr_gentle_density/
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PARAMS_DIR = REPO_ROOT / "params"

# Interventions that are compatible with contributing heritage buildings
HERITAGE_SAFE = {"heritage_restore", "facade_renovation", "signage_update", "green_roof"}
# Interventions that need review for contributing buildings
HERITAGE_REVIEW = {"add_floor", "convert_ground"}
# Interventions incompatible with contributing heritage buildings
HERITAGE_INCOMPATIBLE = {"demolish"}


def assess_heritage_impact(baseline_dir: Path, scenario_dir: Path) -> dict:
    """Assess heritage impact of all interventions."""
    intvs_path = scenario_dir / "interventions.json"
    if not intvs_path.exists():
        return {"error": "No interventions.json found"}

    data = json.loads(intvs_path.read_text(encoding="utf-8"))
    interventions = data.get("interventions", [])

    findings = []
    scores = {"safe": 0, "review": 0, "incompatible": 0, "non_contributing": 0, "new_build": 0}

    for intv in interventions:
        addr = intv.get("address", "")
        itype = intv.get("type", "")

        if itype == "new_build":
            scores["new_build"] += 1
            findings.append({
                "address": addr,
                "type": itype,
                "heritage_status": "n/a",
                "impact": "new_build",
                "severity": "info",
                "note": "New construction -- subject to HCD design review",
            })
            continue

        # Find baseline params for this address
        param_file = None
        for f in baseline_dir.glob("*.json"):
            if f.name.startswith("_"):
                continue
            try:
                p = json.loads(f.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            if p.get("_meta", {}).get("address") == addr:
                param_file = p
                break

        if not param_file:
            findings.append({
                "address": addr,
                "type": itype,
                "heritage_status": "unknown",
                "impact": "address_not_found",
                "severity": "warning",
                "note": f"Address not found in baseline params",
            })
            continue

        hcd = param_file.get("hcd_data", {})
        contributing = (hcd.get("contributing") or "").lower() == "yes"
        era = hcd.get("construction_date", "")
        typology = hcd.get("typology", "")

        if not contributing:
            scores["non_contributing"] += 1
            findings.append({
                "address": addr,
                "type": itype,
                "heritage_status": "non-contributing",
                "impact": "acceptable",
                "severity": "info",
                "note": "Non-contributing building -- intervention is acceptable",
            })
            continue

        # Contributing building -- check intervention type
        if itype in HERITAGE_SAFE:
            scores["safe"] += 1
            findings.append({
                "address": addr,
                "type": itype,
                "heritage_status": "contributing",
                "era": era,
                "typology": typology,
                "impact": "safe",
                "severity": "ok",
                "note": f"Heritage-compatible intervention on {era} {typology}",
            })
        elif itype in HERITAGE_REVIEW:
            scores["review"] += 1
            findings.append({
                "address": addr,
                "type": itype,
                "heritage_status": "contributing",
                "era": era,
                "typology": typology,
                "impact": "needs_review",
                "severity": "warning",
                "note": f"Contributing {era} building -- {itype} requires HCD review",
            })
        elif itype in HERITAGE_INCOMPATIBLE:
            scores["incompatible"] += 1
            findings.append({
                "address": addr,
                "type": itype,
                "heritage_status": "contributing",
                "era": era,
                "typology": typology,
                "impact": "incompatible",
                "severity": "critical",
                "note": f"INCOMPATIBLE: {itype} on contributing {era} heritage building",
            })
        else:
            scores["review"] += 1
            findings.append({
                "address": addr,
                "type": itype,
                "heritage_status": "contributing",
                "era": era,
                "typology": typology,
                "impact": "unknown",
                "severity": "warning",
                "note": f"Unknown intervention type on contributing building",
            })

    # Heritage preservation score (0-100)
    total = max(len(interventions), 1)
    preservation_score = round(
        100 * (scores["safe"] + scores["non_contributing"] + scores["new_build"] * 0.8)
        / total, 1
    )

    return {
        "scenario_id": data.get("scenario_id", ""),
        "total_interventions": len(interventions),
        "scores": scores,
        "heritage_preservation_score": preservation_score,
        "findings": findings,
    }


def main():
    parser = argparse.ArgumentParser(description="Assess heritage impact of scenario.")
    parser.add_argument("--baseline", type=Path, default=PARAMS_DIR)
    parser.add_argument("--scenario", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    result = assess_heritage_impact(args.baseline, args.scenario)

    output = args.output or (args.scenario / "heritage_impact.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    print(f"Heritage Impact: {result.get('scenario_id', '?')}")
    print(f"Preservation score: {result.get('heritage_preservation_score', 0)}/100")
    s = result.get("scores", {})
    print(f"  Safe: {s.get('safe', 0)}, Review needed: {s.get('review', 0)}, "
          f"Incompatible: {s.get('incompatible', 0)}, Non-contributing: {s.get('non_contributing', 0)}, "
          f"New builds: {s.get('new_build', 0)}")

    for f in result.get("findings", []):
        if f["severity"] in ("critical", "warning"):
            print(f"  [{f['severity'].upper()}] {f['address']}: {f['note']}")

    print(f"\nOutput: {output}")


if __name__ == "__main__":
    main()
