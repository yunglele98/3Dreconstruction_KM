#!/usr/bin/env python3
"""
Move stale outputs (older than current params) to outputs/stale/.

Compares param file mtime vs manifest mtime.
Dry-run by default; pass --apply to move files.
"""
import argparse
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PARAMS_DIR = ROOT / "params"
OUTPUTS_DIR = ROOT / "outputs" / "full"
STALE_DIR = ROOT / "outputs" / "stale"


def main():
    parser = argparse.ArgumentParser(description="Archive stale output renders")
    parser.add_argument("--apply", action="store_true", help="Move files (default: dry-run)")
    args = parser.parse_args()

    if not OUTPUTS_DIR.exists():
        print(f"No outputs directory: {OUTPUTS_DIR}")
        return

    stale_count = 0
    current_count = 0
    no_param_count = 0

    for manifest in sorted(OUTPUTS_DIR.glob("*.manifest.json")):
        try:
            with open(manifest, encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue

        param_name = data.get("param_file", "")
        if not param_name:
            continue

        param_path = PARAMS_DIR / Path(param_name).name
        if not param_path.exists():
            no_param_count += 1
            continue

        param_mtime = param_path.stat().st_mtime
        manifest_mtime = manifest.stat().st_mtime

        if param_mtime > manifest_mtime:
            stale_count += 1
            stem = manifest.stem.replace(".manifest", "")
            action = "MOVE" if args.apply else "DRY-RUN"
            print(f"  {action}: {manifest.name} (stale)")

            if args.apply:
                STALE_DIR.mkdir(parents=True, exist_ok=True)
                shutil.move(str(manifest), str(STALE_DIR / manifest.name))
                # Also move the .blend and .png if they exist
                for ext in (".blend", ".png"):
                    render_file = OUTPUTS_DIR / (stem + ext)
                    if render_file.exists():
                        shutil.move(str(render_file), str(STALE_DIR / render_file.name))
        else:
            current_count += 1

    print(f"\nSummary: {stale_count} stale, {current_count} current, {no_param_count} no param file")


if __name__ == "__main__":
    main()
