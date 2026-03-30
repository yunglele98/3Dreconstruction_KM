#!/usr/bin/env python3
"""
Post-regen verification: check that all expected buildings were rendered.

Compares regen_queue.json against outputs/full_v2/ manifests.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
QUEUE_FILE = ROOT / "outputs" / "regen_queue.json"
NEW_RENDERS_DIR = ROOT / "outputs" / "full_v2"
OLD_RENDERS_DIR = ROOT / "outputs" / "full"
OUTPUT_FILE = ROOT / "outputs" / "regen_verification.json"


def main():
    if not QUEUE_FILE.exists():
        print("No regen_queue.json — run fingerprint_params.py first")
        return

    with open(QUEUE_FILE, encoding="utf-8") as f:
        queue = json.load(f)

    expected = queue.get("stale", []) + queue.get("new", [])
    completed, missing, failed = [], [], []
    size_flags = []

    for item in expected:
        stem = Path(item["file"]).stem
        blend_path = NEW_RENDERS_DIR / f"{stem}.blend" if NEW_RENDERS_DIR.exists() else None
        manifest_path = NEW_RENDERS_DIR / f"{stem}.manifest.json" if NEW_RENDERS_DIR.exists() else None

        if manifest_path and manifest_path.exists():
            completed.append(item["address"])
            # Size ratio check
            old_blend = OLD_RENDERS_DIR / f"{stem}.blend"
            new_blend = NEW_RENDERS_DIR / f"{stem}.blend"
            if old_blend.exists() and new_blend.exists():
                ratio = new_blend.stat().st_size / max(old_blend.stat().st_size, 1)
                if ratio > 3.0 or ratio < 0.3:
                    size_flags.append({
                        "address": item["address"],
                        "ratio": round(ratio, 2),
                        "old_size": old_blend.stat().st_size,
                        "new_size": new_blend.stat().st_size,
                    })
        else:
            missing.append(item["address"])

    report = {
        "expected": len(expected),
        "completed": len(completed),
        "missing": len(missing),
        "size_anomalies": len(size_flags),
        "missing_list": missing[:50],
        "size_flags": size_flags[:20],
    }

    print(f"Regen Verification")
    print(f"{'='*50}")
    print(f"Expected: {len(expected)}, Completed: {len(completed)}, "
          f"Missing: {len(missing)}, Size anomalies: {len(size_flags)}")

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(f"Report: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
