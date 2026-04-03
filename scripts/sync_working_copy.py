#!/usr/bin/env python3
"""
Sync working copy from C: to D: drive using robocopy.

Prints the commands to run. Requires elevation for /MIR.
"""
import os
import subprocess
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent
DST = Path(r"D:\liam1_transfer\blender_buildings")

SYNC_DIRS = [
    ("params", "/MIR"),
    ("scripts", "/MIR"),
    ("tests", "/MIR"),
    ("outputs", "/E"),
    ("docs", "/E"),
]


def is_elevated() -> bool:
    """Check if running with admin privileges (Windows)."""
    try:
        return os.getuid() == 0
    except AttributeError:
        # Windows
        try:
            import ctypes
            return ctypes.windll.shell32.IsUserAnAdmin() != 0
        except Exception:
            return False


def main():
    print("Sync Working Copy: C: → D:")
    print("=" * 50)

    if not SRC.exists():
        print(f"Source not found: {SRC}")
        print("This script is designed to run on the local Windows machine.")
        print("\nGenerated commands:")
        for dirname, flags in SYNC_DIRS:
            src_dir = SRC / dirname
            dst_dir = DST / dirname
            print(f"  robocopy \"{src_dir}\" \"{dst_dir}\" {flags}")
        return

    for dirname, flags in SYNC_DIRS:
        src_dir = SRC / dirname
        dst_dir = DST / dirname

        if not src_dir.exists():
            print(f"  SKIP: {src_dir} does not exist")
            continue

        cmd = f'robocopy "{src_dir}" "{dst_dir}" {flags}'
        print(f"\n  Running: {cmd}")

        try:
            result = subprocess.run(
                ["robocopy", str(src_dir), str(dst_dir)] + flags.split(),
                capture_output=True, text=True, timeout=300,
            )
            # robocopy returns 0-7 for success, 8+ for errors
            if result.returncode < 8:
                # Count changes from output
                for line in result.stdout.split("\n"):
                    if "Files" in line or "Dirs" in line:
                        print(f"    {line.strip()}")
            else:
                print(f"    ERROR (code {result.returncode}): {result.stderr[:200]}")
        except FileNotFoundError:
            print(f"    robocopy not found — not on Windows?")
            print(f"    Manual: {cmd}")
        except subprocess.TimeoutExpired:
            print(f"    TIMEOUT after 300s")

    print("\nDone.")


if __name__ == "__main__":
    main()
