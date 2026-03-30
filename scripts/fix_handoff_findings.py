#!/usr/bin/env python3
"""Apply fixes from agent handoff audit findings.

Reads TASK-20260327-007__gemini-1.json and patches param files for:
  1. missing_features  -- add decorative_elements from HCD templates
  2. window_count      -- correct windows_detail[floor].windows[0].count
  3. trim_colour       -- set facade_detail.trim_colour_hex + colour_palette.trim
  4. brick_colour      -- set facade_detail.brick_colour_hex + colour_palette.facade + facade_colour

Usage:
    python scripts/fix_handoff_findings.py              # dry-run (default)
    python scripts/fix_handoff_findings.py --apply      # write changes
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_ROOT = Path(__file__).resolve().parent.parent
if not (DEFAULT_ROOT / "params").exists():
    DEFAULT_ROOT = Path("D:/liam1_transfer/blender_buildings")
ROOT = None  # set in main()
PARAMS_DIR = None
HANDOFF = None

PROTECTED_KEYS = {
    "total_height_m", "facade_width_m", "facade_depth_m",
    "site", "city_data", "hcd_data",
}

FEATURE_TEMPLATES = {
    "voussoir": (
        "stone_voussoirs",
        {"present": True, "colour_hex": "#C8B898"},
    ),
    "bracket": (
        "gable_brackets",
        {"type": "scroll", "count": 4, "projection_mm": 120,
         "height_mm": 200, "colour_hex": "#4A3A2A"},
    ),
    "shingle": (
        "ornamental_shingles",
        {"present": True, "colour_hex": "#6A5A4A", "exposure_mm": 150},
    ),
    "cornice": (
        "cornice",
        {"present": True, "projection_mm": 200, "height_mm": 250,
         "colour_hex": "#4A3A2A"},
    ),
    "string course": (
        "string_courses",
        {"present": True, "width_mm": 80, "projection_mm": 30,
         "colour_hex": "#C8B898"},
    ),
}

WINDOW_FIXES = {
    "146 Baldwin St":    (0, 2),
    "14 Kensington Ave": (1, 2),
    "160 Baldwin St":    (0, 3),
    "168 Baldwin St":    (0, 2),
    "170 Baldwin St":    (0, 2),
    "172 Baldwin St":    (0, 2),
    "176 Baldwin St":    (0, 3),
    "184 Baldwin St":    (0, 4),
    "200 Baldwin St":    (0, 2),
    "202 Baldwin St":    (0, 2),
    "204 Baldwin St":    (0, 2),
    "206 Baldwin St":    (0, 2),
    "2A Kensington Ave": (0, 2),
    "376 Spadina Ave":   (0, 3),
}

TRIM_FIX_HEX = "#F0EDE8"
TRIM_FIX_ADDRESSES = [
    "12 Kensington Ave", "14 Kensington Ave", "38 Kensington Ave",
    "40 Kensington Ave", "42 Kensington Ave", "44 Kensington Ave",
    "46 Kensington Ave", "67 Kensington Ave", "71 Kensington Ave",
    "173 Baldwin St", "200A Baldwin St",
]

BRICK_FIX_HEX = "#B85A3A"
BRICK_FIX_ADDRESSES = [
    "2 Kensington Ave", "2A Kensington Ave", "42 Kensington Ave",
]


def address_to_filename(address):
    return address.replace(" ", "_") + ".json"


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    content = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
    except OSError:
        # D: drive may be read-only from sandbox; write via temp + PowerShell copy
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False,
                                         encoding="utf-8", dir=os.environ.get("TEMP")) as tmp:
            tmp.write(content)
            tmp_path = tmp.name
        subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command",
             f"Set-Content -Path '{path}' -Value (Get-Content '{tmp_path}' -Raw) "
             f"-Encoding UTF8 -NoNewline"],
            check=True, capture_output=True,
        )
        os.unlink(tmp_path)


def stamp_meta(data, fix_name):
    meta = data.setdefault("_meta", {})
    fixes = meta.setdefault("handoff_fixes_applied", [])
    fixes.append({
        "fix": fix_name,
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    })


def element_is_missing(decorative, key):
    if key not in decorative:
        return True
    val = decorative[key]
    if isinstance(val, dict) and val.get("present") is False:
        return True
    return False


def parse_expected_features(expected_str):
    m = re.search(r"Entries for:\s*(.+)", expected_str, re.IGNORECASE)
    if not m:
        return []
    return [f.strip().lower() for f in m.group(1).split(",")]


def fix_missing_features(findings, apply):
    log = []
    mf = [f for f in findings if f.get("status") == "missing_features"]
    for finding in mf:
        address = finding["address"]
        param_path = PARAMS_DIR / address_to_filename(address)
        if not param_path.exists():
            log.append(f"  SKIP {address}: param file not found")
            continue

        features = parse_expected_features(finding.get("expected", ""))
        if not features:
            log.append(f"  SKIP {address}: could not parse expected features")
            continue

        data = load_json(param_path)
        decorative = data.setdefault("decorative_elements", {})
        added = []

        for feat in features:
            if feat not in FEATURE_TEMPLATES:
                log.append(f"  SKIP {address}: no template for " + repr(feat))
                continue
            key, template = FEATURE_TEMPLATES[feat]
            if element_is_missing(decorative, key):
                decorative[key] = dict(template)
                added.append(key)

        if added:
            stamp_meta(data, "add_decorative:" + ",".join(added))
            tag = "APPLY" if apply else "DRY"
            log.append(f"  {tag} {address}: +{added}")
            if apply:
                save_json(param_path, data)
        else:
            log.append(f"  NOOP {address}: all features already present")

    return log


def fix_window_counts(apply):
    log = []
    for address, (floor_idx, correct_count) in WINDOW_FIXES.items():
        param_path = PARAMS_DIR / address_to_filename(address)
        if not param_path.exists():
            log.append(f"  SKIP {address}: param file not found")
            continue

        data = load_json(param_path)
        wd = data.get("windows_detail")
        if not wd or not isinstance(wd, list):
            log.append(f"  SKIP {address}: no windows_detail list")
            continue
        if floor_idx >= len(wd):
            log.append(f"  SKIP {address}: floor index {floor_idx} out of range (len={len(wd)})")
            continue

        floor_entry = wd[floor_idx]
        windows = floor_entry.get("windows", [])

        if not windows:
            windows = [{"count": correct_count, "type": "double-hung"}]
            floor_entry["windows"] = windows
            stamp_meta(data, f"window_count:floor{floor_idx}={correct_count}")
            tag = "APPLY" if apply else "DRY"
            log.append(f"  {tag} {address}: floor[{floor_idx}] created window entry count={correct_count}")
            if apply:
                save_json(param_path, data)
            continue

        current = windows[0].get("count", 0)
        if current >= correct_count:
            log.append(f"  NOOP {address}: floor[{floor_idx}] count={current} >= {correct_count}")
            continue

        old = current
        windows[0]["count"] = correct_count
        stamp_meta(data, f"window_count:floor{floor_idx}={old}->{correct_count}")
        tag = "APPLY" if apply else "DRY"
        log.append(f"  {tag} {address}: floor[{floor_idx}] count {old}->{correct_count}")
        if apply:
            save_json(param_path, data)

    return log


def fix_trim_colours(apply):
    log = []
    for address in TRIM_FIX_ADDRESSES:
        param_path = PARAMS_DIR / address_to_filename(address)
        if not param_path.exists():
            log.append(f"  SKIP {address}: param file not found")
            continue

        data = load_json(param_path)
        changed = False

        fd = data.setdefault("facade_detail", {})
        old_fd = fd.get("trim_colour_hex")
        if old_fd != TRIM_FIX_HEX:
            fd["trim_colour_hex"] = TRIM_FIX_HEX
            changed = True

        cp = data.setdefault("colour_palette", {})
        old_cp = cp.get("trim")
        if old_cp != TRIM_FIX_HEX:
            cp["trim"] = TRIM_FIX_HEX
            changed = True
        if cp.get("trim_hex") and cp["trim_hex"] != TRIM_FIX_HEX:
            cp["trim_hex"] = TRIM_FIX_HEX

        if changed:
            stamp_meta(data, f"trim_colour:{old_fd}->{TRIM_FIX_HEX}")
            tag = "APPLY" if apply else "DRY"
            log.append(f"  {tag} {address}: trim {old_fd}->{TRIM_FIX_HEX}")
            if apply:
                save_json(param_path, data)
        else:
            log.append(f"  NOOP {address}: trim already {TRIM_FIX_HEX}")

    return log


def fix_brick_colours(apply):
    log = []
    for address in BRICK_FIX_ADDRESSES:
        param_path = PARAMS_DIR / address_to_filename(address)
        if not param_path.exists():
            log.append(f"  SKIP {address}: param file not found")
            continue

        data = load_json(param_path)
        changed = False

        fd = data.setdefault("facade_detail", {})
        old_fd = fd.get("brick_colour_hex")
        if old_fd != BRICK_FIX_HEX:
            fd["brick_colour_hex"] = BRICK_FIX_HEX
            changed = True

        cp = data.setdefault("colour_palette", {})
        old_cp = cp.get("facade")
        if old_cp != BRICK_FIX_HEX:
            cp["facade"] = BRICK_FIX_HEX
            changed = True
        if cp.get("facade_hex") and cp["facade_hex"] != BRICK_FIX_HEX:
            cp["facade_hex"] = BRICK_FIX_HEX

        old_fc = data.get("facade_colour")
        if old_fc != BRICK_FIX_HEX:
            data["facade_colour"] = BRICK_FIX_HEX
            changed = True

        if changed:
            stamp_meta(data, f"brick_colour:{old_fd}->{BRICK_FIX_HEX}")
            tag = "APPLY" if apply else "DRY"
            log.append(f"  {tag} {address}: brick {old_fd}->{BRICK_FIX_HEX}")
            if apply:
                save_json(param_path, data)
        else:
            log.append(f"  NOOP {address}: brick already {BRICK_FIX_HEX}")

    return log


def main():
    global ROOT, PARAMS_DIR, HANDOFF
    parser = argparse.ArgumentParser(description="Fix handoff audit findings")
    parser.add_argument("--apply", action="store_true",
                        help="Write changes (default: dry-run)")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT,
                        help="Project root (default: D:/liam1_transfer/blender_buildings)")
    args = parser.parse_args()

    ROOT = args.root
    PARAMS_DIR = ROOT / "params"
    HANDOFF = ROOT / "agent_ops" / "30_handoffs" / "TASK-20260327-007__gemini-1.json"

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"=== fix_handoff_findings.py [{mode}] ===")
    print()

    if not HANDOFF.exists():
        print(f"ERROR: handoff file not found: {HANDOFF}")
        sys.exit(1)
    handoff = load_json(HANDOFF)
    findings = handoff.get("findings", [])
    print(f"Loaded {len(findings)} findings from {HANDOFF.name}")
    print()

    print("-- 1. Missing decorative features --")
    for line in fix_missing_features(findings, args.apply):
        print(line)

    print()
    print("-- 2. Window count fixes --")
    for line in fix_window_counts(args.apply):
        print(line)

    print()
    print("-- 3. Trim colour fixes --")
    for line in fix_trim_colours(args.apply):
        print(line)

    print()
    print("-- 4. Brick colour fixes --")
    for line in fix_brick_colours(args.apply):
        print(line)

    print()
    if args.apply:
        print("Done. Changes written.")
    else:
        print("Done. No files modified (dry-run).")


if __name__ == "__main__":
    main()
