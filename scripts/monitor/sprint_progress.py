#!/usr/bin/env python3
"""Sprint progress tracker — compare actual vs planned targets.

Reads sprint targets from docs/sprint_targets.json (if exists) or uses
hardcoded Day 1-2 targets. Compares against actual coverage matrix.

Usage:
    python scripts/monitor/sprint_progress.py
    python scripts/monitor/sprint_progress.py --json
"""
import json, logging
from datetime import date, datetime
from pathlib import Path

logger = logging.getLogger(__name__)
REPO = Path(__file__).parent.parent.parent
SPRINT_START = date(2026, 4, 2)

DAY_TARGETS = {
    1: {"depth_maps": 1900, "segmentation": 1900, "renders": 1200, "tests": 90},
    2: {"fbx_exported": 1241, "ci_pipeline": True, "depth_fused": 1200},
    3: {"signage": 1900, "normals": 1900},
    7: {"fusion_scripts": 5, "colmap_blocks": 1, "asset_library": 20},
    14: {"colmap_blocks": 5, "citygml": True, "web_platform": True},
    21: {"fbx_exported": 1241, "photogrammetric_meshes": 200, "tests": 2500},
}

def get_actuals():
    cm_path = REPO / "outputs" / "coverage_matrix.json"
    if cm_path.exists():
        cm = json.loads(cm_path.read_text(encoding="utf-8"))
        s = cm.get("summary", {})
        return {
            "renders": s.get("rendered", {}).get("count", 0),
            "blends": s.get("blended", {}).get("count", 0),
            "depth_fused": s.get("depth_fused", {}).get("count", 0),
            "segmentation": s.get("seg_fused", {}).get("count", 0),
            "signage": s.get("sig_fused", {}).get("count", 0),
            "fbx_exported": s.get("exported", {}).get("count", 0),
        }
    return {}

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Sprint progress")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    today = date.today()
    sprint_day = (today - SPRINT_START).days + 1
    if sprint_day < 1 or sprint_day > 21:
        logger.info("Outside sprint window (Day %d)", sprint_day)
        return

    actuals = get_actuals()
    targets = DAY_TARGETS.get(sprint_day, DAY_TARGETS.get(max(d for d in DAY_TARGETS if d <= sprint_day), {}))

    # Extra counts
    depth_maps = len(list((REPO/"depth_maps").glob("*.npy"))) if (REPO/"depth_maps").exists() else 0
    seg_files = len(list((REPO/"segmentation").glob("*_elements.json"))) if (REPO/"segmentation").exists() else 0
    sig_files = len(list((REPO/"signage").glob("*_text.json"))) if (REPO/"signage").exists() else 0
    test_count = len(list((REPO/"tests").glob("test_*.py")))
    assets = len(list((REPO/"assets"/"external").rglob("*"))) if (REPO/"assets"/"external").exists() else 0
    ci = (REPO/".github"/"workflows"/"qa.yml").exists()

    actuals.update({"depth_maps": depth_maps, "seg_files": seg_files, "sig_files": sig_files,
                     "tests": test_count, "asset_library": assets, "ci_pipeline": ci})

    report = {"sprint_day": sprint_day, "date": str(today), "targets": targets,
              "actuals": actuals, "status": []}

    on_track = behind = ahead = 0
    for key, target in targets.items():
        actual = actuals.get(key, 0)
        if isinstance(target, bool):
            ok = actual == target
            status = "on_track" if ok else "behind"
        else:
            if actual >= target: status = "ahead" if actual > target * 1.1 else "on_track"
            else: status = "behind"
        report["status"].append({"metric": key, "target": target, "actual": actual, "status": status})
        if status == "ahead": ahead += 1
        elif status == "behind": behind += 1
        else: on_track += 1

    if not args.json:
        logger.info("Sprint Day %d/21 — %s", sprint_day, today)
        logger.info("=" * 50)
        for s in report["status"]:
            icon = {"on_track": "OK", "behind": "!!", "ahead": "++"}[s["status"]]
            logger.info("  [%s] %-20s target=%-6s actual=%-6s", icon, s["metric"], s["target"], s["actual"])
        logger.info("-" * 50)
        logger.info("  On track: %d | Behind: %d | Ahead: %d", on_track, behind, ahead)
        logger.info("\nExtras: %d depth maps, %d seg files, %d signage, %d tests, CI=%s",
                     depth_maps, seg_files, sig_files, test_count, ci)
    else:
        print(json.dumps(report, indent=2))

if __name__ == "__main__":
    main()
