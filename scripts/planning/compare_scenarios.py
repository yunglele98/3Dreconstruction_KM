#!/usr/bin/env python3
"""Stage 11 — SCENARIOS: Compare baseline vs scenario outputs.

Side-by-side comparison of baseline and scenario builds: height deltas,
density changes, heritage impact summary, and visual diff candidates.

Usage:
    python scripts/planning/compare_scenarios.py --baseline outputs/full/ --scenario outputs/scenarios/gentle_density/
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def load_manifests(directory: Path) -> dict[str, dict]:
    """Load all .manifest.json files from a directory, indexed by address."""
    manifests = {}
    for f in directory.glob("*.manifest.json"):
        data = json.loads(f.read_text(encoding="utf-8"))
        addr = data.get("address", f.stem.replace(".manifest", "").replace("_", " "))
        manifests[addr] = data
    return manifests


def compare(baseline_dir: Path, scenario_dir: Path) -> dict:
    """Compare baseline and scenario outputs.

    Returns a comparison report with per-building diffs and summary.
    """
    base_manifests = load_manifests(baseline_dir)
    scen_manifests = load_manifests(scenario_dir)

    all_addrs = sorted(set(base_manifests) | set(scen_manifests))
    diffs = []
    new_builds = []
    removed = []

    for addr in all_addrs:
        base = base_manifests.get(addr)
        scen = scen_manifests.get(addr)

        if base and not scen:
            removed.append(addr)
        elif scen and not base:
            new_builds.append(addr)
        elif base and scen:
            changes = {}
            for key in ("floors", "total_height_m", "roof_type", "has_storefront"):
                bv = base.get(key)
                sv = scen.get(key)
                if bv != sv:
                    changes[key] = {"baseline": bv, "scenario": sv}
            if changes:
                diffs.append({"address": addr, "changes": changes})

    return {
        "baseline_count": len(base_manifests),
        "scenario_count": len(scen_manifests),
        "modified": len(diffs),
        "new_builds": len(new_builds),
        "removed": len(removed),
        "diffs": diffs,
        "new_build_addresses": new_builds,
        "removed_addresses": removed,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare baseline vs scenario")
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--scenario", required=True, type=Path)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    result = compare(args.baseline, args.scenario)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(result, indent=2), encoding="utf-8"
        )

    print(f"Comparison: {result['modified']} modified, "
          f"{result['new_builds']} new, {result['removed']} removed")


if __name__ == "__main__":
    main()
