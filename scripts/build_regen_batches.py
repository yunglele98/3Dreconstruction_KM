#!/usr/bin/env python3
"""
Build ordered batches for Blender regeneration from regen_queue.json.

Priority:
  1. Buildings with handoff_fixes_applied
  2. Buildings with volumes[]
  3. Buildings where height changed
  4. Remaining stale/new

Each batch: max 50 buildings.
Output: outputs/regen_batches/batch_NNN.txt + run_all.ps1 + run_all.sh
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PARAMS_DIR = ROOT / "params"
QUEUE_FILE = ROOT / "outputs" / "regen_queue.json"
BATCH_DIR = ROOT / "outputs" / "regen_batches"
BATCH_SIZE = 50


def classify_priority(param_file: Path) -> int:
    """Assign priority (lower = higher priority)."""
    with open(param_file, encoding="utf-8") as f:
        params = json.load(f)
    meta = params.get("_meta", {})

    if meta.get("handoff_fixes_applied"):
        return 1
    if params.get("volumes"):
        return 2
    fixes = meta.get("handoff_fixes_applied", [])
    if isinstance(fixes, list):
        for fix in fixes:
            if isinstance(fix, dict) and "height" in fix.get("fix", ""):
                return 3
    return 4


def main():
    if not QUEUE_FILE.exists():
        print(f"Run fingerprint_params.py first")
        return

    with open(QUEUE_FILE, encoding="utf-8") as f:
        queue = json.load(f)

    to_regen = queue.get("stale", []) + queue.get("new", [])
    print(f"Total to regenerate: {len(to_regen)}")

    # Assign priorities
    prioritized = []
    for item in to_regen:
        param_path = PARAMS_DIR / item["file"]
        if param_path.exists():
            prio = classify_priority(param_path)
            prioritized.append((prio, item["file"]))

    prioritized.sort(key=lambda x: (x[0], x[1]))

    # Split into batches
    BATCH_DIR.mkdir(parents=True, exist_ok=True)
    batches = []
    for i in range(0, len(prioritized), BATCH_SIZE):
        batch = [p[1] for p in prioritized[i:i + BATCH_SIZE]]
        batches.append(batch)

    for i, batch in enumerate(batches, 1):
        batch_file = BATCH_DIR / f"batch_{i:03d}.txt"
        with open(batch_file, "w", encoding="utf-8") as f:
            for filename in batch:
                f.write(f"params/{filename}\n")

    # PowerShell script
    ps1 = BATCH_DIR / "run_all.ps1"
    with open(ps1, "w", encoding="utf-8") as f:
        f.write("# Blender batch regeneration\n")
        f.write(f"$total = {len(prioritized)}\n")
        f.write("$done = 0\n")
        f.write("$logFile = 'regen_log.txt'\n\n")
        for i, batch in enumerate(batches, 1):
            batch_file = f"outputs/regen_batches/batch_{i:03d}.txt"
            f.write(f"Write-Host \"Batch {i}/{len(batches)} starting ($done/$total done)\"\n")
            for filename in batch:
                f.write(f"try {{\n")
                f.write(f"  blender --background --python generate_building.py -- --params params/{filename} --batch-individual --render --output-dir outputs/full_v2/\n")
                f.write(f"  $done++\n")
                f.write(f"}} catch {{\n")
                f.write(f"  \"FAIL: {filename}\" | Out-File -Append $logFile\n")
                f.write(f"  $done++\n")
                f.write(f"}}\n")
            f.write(f"Write-Host \"Batch {i}/{len(batches)} complete, $done/$total buildings done\"\n\n")
        f.write("Write-Host \"All batches complete!\"\n")

    # Bash script
    sh = BATCH_DIR / "run_all.sh"
    with open(sh, "w", encoding="utf-8") as f:
        f.write("#!/bin/bash\n")
        f.write(f"TOTAL={len(prioritized)}\n")
        f.write("DONE=0\n")
        f.write("LOG=regen_log.txt\n\n")
        for i, batch in enumerate(batches, 1):
            f.write(f"echo \"Batch {i}/{len(batches)} starting ($DONE/$TOTAL done)\"\n")
            for filename in batch:
                f.write(f"blender --background --python generate_building.py -- --params params/{filename} --batch-individual --render --output-dir outputs/full_v2/ || echo \"FAIL: {filename}\" >> $LOG\n")
                f.write(f"DONE=$((DONE+1))\n")
            f.write(f"echo \"Batch {i}/{len(batches)} complete, $DONE/$TOTAL buildings done\"\n\n")

    print(f"Created {len(batches)} batches in {BATCH_DIR}")
    print(f"  Priority 1 (handoff fixes): {sum(1 for p in prioritized if p[0] == 1)}")
    print(f"  Priority 2 (multi-volume): {sum(1 for p in prioritized if p[0] == 2)}")
    print(f"  Priority 3 (height change): {sum(1 for p in prioritized if p[0] == 3)}")
    print(f"  Priority 4 (remaining): {sum(1 for p in prioritized if p[0] == 4)}")
    print(f"  PowerShell: {ps1}")
    print(f"  Bash: {sh}")


if __name__ == "__main__":
    main()
