#!/usr/bin/env python3
"""Combined realism dashboard — runs all realism analyzers and produces
a unified report with per-street and per-building scores.

Aggregates results from:
- Facade colour realism
- Streetscape continuity
- Weathering consistency
- Window pattern realism
- Decorative completeness
- Roofline silhouette

Usage:
    python scripts/analyze/realism_dashboard.py
    python scripts/analyze/realism_dashboard.py --street "Augusta Ave"
    python scripts/analyze/realism_dashboard.py --json
"""

import argparse
import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
PARAMS_DIR = ROOT / "params"
OUTPUTS = ROOT / "outputs"


def load_report(name):
    """Load a previously generated analysis report."""
    path = OUTPUTS / f"{name}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def run_all_analyzers():
    """Run all realism analysis scripts if reports don't exist."""
    import subprocess
    scripts = [
        "facade_colour_realism",
        "streetscape_continuity",
        "weathering_consistency",
        "window_pattern_realism",
        "decorative_completeness",
        "roofline_silhouette",
    ]
    for name in scripts:
        report = OUTPUTS / f"{name}.json"
        if not report.exists():
            script = ROOT / "scripts" / "analyze" / f"{name}.py"
            if script.exists():
                print(f"Running {name}...")
                subprocess.run(
                    ["python3", str(script)],
                    capture_output=True, text=True
                )


def build_dashboard(street_filter=None):
    """Build unified dashboard from individual reports."""
    # Load all reports
    colour = load_report("facade_colour_realism") or []
    continuity = load_report("streetscape_continuity") or []
    weathering_report = load_report("weathering_consistency") or {}
    weathering = weathering_report.get("street_summaries", [])
    windows = load_report("window_pattern_realism") or []
    decorative = load_report("decorative_completeness") or []
    silhouette = load_report("roofline_silhouette") or []

    # Index by street
    colour_by_street = {r["street"]: r for r in colour}
    continuity_by_street = {r["street"]: r for r in continuity}
    weathering_by_street = {r["street"]: r for r in weathering}
    silhouette_by_street = {r["street"]: r for r in silhouette}

    # Window and decorative are per-building — aggregate by street
    win_by_street = defaultdict(list)
    for r in windows:
        win_by_street[r.get("street", "Unknown")].append(r)
    dec_by_street = defaultdict(list)
    for r in decorative:
        street = "Unknown"
        # Try to get street from address
        for f in PARAMS_DIR.glob("*.json"):
            if f.name.startswith("_"):
                continue
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
                if d.get("building_name") == r.get("address"):
                    street = d.get("site", {}).get("street", "Unknown")
                    break
            except Exception:
                continue
        dec_by_street[street].append(r)

    # Collect all streets
    all_streets = sorted(set(
        list(colour_by_street) + list(continuity_by_street) +
        list(weathering_by_street) + list(silhouette_by_street)
    ))

    if street_filter:
        all_streets = [s for s in all_streets if s == street_filter]

    dashboard = []
    for street in all_streets:
        c = colour_by_street.get(street, {})
        cont = continuity_by_street.get(street, {})
        w = weathering_by_street.get(street, {})
        sil = silhouette_by_street.get(street, {})
        win_scores = [r["score"] for r in win_by_street.get(street, [])]
        dec_scores = [r["completeness"] for r in dec_by_street.get(street, [])]

        scores = {
            "colour_diversity": round(c.get("diversity_ratio", 0.5) * 100, 1),
            "continuity": cont.get("continuity_score", 50),
            "weathering_issues": w.get("total_issues", 0),
            "silhouette": sil.get("silhouette_score", 50),
            "window_avg": round(sum(win_scores) / max(1, len(win_scores)), 1) if win_scores else 50,
            "decorative_avg": round(sum(dec_scores) / max(1, len(dec_scores)) * 100, 1) if dec_scores else 50,
        }

        # Combined realism score (weighted)
        combined = (
            scores["colour_diversity"] * 0.15 +
            scores["continuity"] * 0.25 +
            max(0, 100 - scores["weathering_issues"] * 5) * 0.10 +
            scores["silhouette"] * 0.20 +
            scores["window_avg"] * 0.15 +
            scores["decorative_avg"] * 0.15
        )

        dashboard.append({
            "street": street,
            "building_count": cont.get("building_count", c.get("building_count", 0)),
            "realism_score": round(combined, 1),
            "scores": scores,
            "era_mismatches": len(c.get("era_mismatches", [])),
            "continuity_issues": cont.get("issues", {}).get("total", 0),
            "missing_chimneys": sil.get("missing_chimneys", 0),
        })

    dashboard.sort(key=lambda r: r["realism_score"])
    return dashboard


def main():
    parser = argparse.ArgumentParser(description="Combined realism dashboard")
    parser.add_argument("--street", help="Filter to single street")
    parser.add_argument("--json", action="store_true", help="Output JSON only")
    parser.add_argument("--run", action="store_true",
                        help="Run all analyzers first if reports missing")
    args = parser.parse_args()

    if args.run:
        run_all_analyzers()

    dashboard = build_dashboard(street_filter=args.street)

    if args.json:
        print(json.dumps(dashboard, indent=2))
        return

    avg_score = sum(d["realism_score"] for d in dashboard) / max(1, len(dashboard))

    print("=" * 80)
    print("  KENSINGTON MARKET — REALISM DASHBOARD")
    print("=" * 80)
    print(f"  Streets: {len(dashboard)}   Average realism score: {avg_score:.1f}/100")
    print()
    print(f"  {'Street':25s}  {'Score':>6s}  {'Color':>6s}  {'Contin':>6s}  "
          f"{'Silhou':>6s}  {'Window':>6s}  {'Decor':>6s}  {'Issues':>6s}")
    print("  " + "-" * 78)

    for d in dashboard:
        s = d["scores"]
        icon = "✓" if d["realism_score"] >= 65 else "△" if d["realism_score"] >= 45 else "✗"
        print(f"  {icon} {d['street']:24s} {d['realism_score']:5.1f}  "
              f"{s['colour_diversity']:5.1f}  {s['continuity']:5.1f}  "
              f"{s['silhouette']:5.1f}  {s['window_avg']:5.1f}  "
              f"{s['decorative_avg']:5.1f}  "
              f"{d['continuity_issues']:5d}")

    print()
    print("  Legend: Color=colour diversity, Contin=streetscape continuity,")
    print("         Silhou=roofline silhouette, Window=window patterns,")
    print("         Decor=decorative completeness, Issues=continuity issues")

    # Save
    out = OUTPUTS / "realism_dashboard.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w") as f:
        json.dump(dashboard, f, indent=2)
    print(f"\n  Report: {out}")


if __name__ == "__main__":
    main()
