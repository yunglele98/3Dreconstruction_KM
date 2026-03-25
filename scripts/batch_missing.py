#!/usr/bin/env python3
"""Generate missing buildings one at a time, spawning a fresh Blender per building."""
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PARAMS = ROOT / "params"
OUTPUT = ROOT / "outputs" / "full"
BLENDER = "blender"

# Force unbuffered output
import functools
print = functools.partial(print, flush=True)


def main():
    # Find missing
    active = []
    for f in sorted(PARAMS.glob("*.json")):
        if f.name.startswith("_"):
            continue
        try:
            d = json.load(open(f, encoding="utf-8"))
            if not d.get("skipped"):
                active.append(f)
        except Exception:
            continue

    rendered = {p.stem for p in OUTPUT.glob("*.blend")}
    missing = [f for f in active if f.stem not in rendered]

    print(f"Missing: {len(missing)} buildings")
    if not missing:
        print("Nothing to generate!")
        return

    failed = []
    for i, f in enumerate(missing, 1):
        print(f"\n[{i}/{len(missing)}] {f.stem}")
        t0 = time.time()
        try:
            result = subprocess.run(
                [BLENDER, "--background", "--python", str(ROOT / "generate_building.py"),
                 "--", "--params", str(f), "--batch-individual", "--output-dir", str(OUTPUT)],
                capture_output=True, text=True, timeout=120, encoding="utf-8", errors="replace"
            )
            elapsed = time.time() - t0
            blend = OUTPUT / f"{f.stem}.blend"
            if blend.exists():
                print(f"  OK ({elapsed:.1f}s)")
            else:
                print(f"  FAILED ({elapsed:.1f}s)")
                if result.stdout:
                    for line in result.stdout.strip().split("\n")[-5:]:
                        print(f"    {line}")
                if result.stderr:
                    for line in result.stderr.strip().split("\n")[-3:]:
                        print(f"    ERR: {line}")
                failed.append(f.stem)
        except subprocess.TimeoutExpired:
            print(f"  TIMEOUT (120s)")
            failed.append(f.stem)
        except Exception as e:
            print(f"  ERROR: {e}")
            failed.append(f.stem)

    print(f"\n=== DONE ===")
    print(f"Generated: {len(missing) - len(failed)}")
    print(f"Failed: {len(failed)}")
    if failed:
        print("Failed buildings:")
        for name in failed:
            print(f"  {name}")


if __name__ == "__main__":
    main()
