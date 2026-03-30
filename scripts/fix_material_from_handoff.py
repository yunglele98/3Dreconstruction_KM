#!/usr/bin/env python3
"""
Fix facade material mismatches from agent handoff TASK-MATERIAL-AUDIT.

Reads reconciled findings where photo observations disagree with the param
facade_material. Updates facade_material to the photo-observed value when
confidence >= 0.7. For "mixed" materials, also adds a secondary_material note.

Dry-run by default; pass --apply to write changes.
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PARAMS_DIR = ROOT / "params"
HANDOFF_FILE = ROOT / "agent_ops" / "30_handoffs" / "TASK-20260327-MATERIAL-AUDIT__gemini-1.json"

CONFIDENCE_THRESHOLD = 0.7


def address_to_filename(address: str) -> str:
    """Convert an address string to the expected param filename."""
    return address.replace(" ", "_") + ".json"


def load_handoff(path: Path) -> list:
    """Load findings from the handoff JSON."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return data.get("findings", [])


def extract_secondary_material(expected: str) -> str:
    """Extract a secondary material note from 'mixed (...)' strings."""
    # e.g. "mixed (painted brick, stone veneer)" -> "painted brick, stone veneer"
    if "(" in expected and ")" in expected:
        start = expected.index("(") + 1
        end = expected.index(")")
        return expected[start:end].strip()
    return ""


def process(apply: bool = False) -> None:
    findings = load_handoff(HANDOFF_FILE)
    print(f"Loaded {len(findings)} findings from {HANDOFF_FILE.name}")

    stats = {"applied": 0, "low_confidence": 0, "skipped_missing": 0, "skipped_field": 0}

    for finding in findings:
        address = finding.get("address", "")
        field = finding.get("field", "")
        expected = finding.get("expected", "")
        actual = finding.get("actual", "")
        confidence = finding.get("confidence", 0)
        status = finding.get("status", "")

        # Only process facade_material reconciliations
        if field != "facade_material" or status != "reconciled":
            stats["skipped_field"] += 1
            continue

        # Skip low confidence
        if confidence < CONFIDENCE_THRESHOLD:
            print(f"  LOW_CONFIDENCE ({confidence:.2f}): {address}  {actual} -> {expected}")
            stats["low_confidence"] += 1
            continue

        filename = address_to_filename(address)
        param_path = PARAMS_DIR / filename

        if not param_path.exists():
            print(f"  SKIP (file not found): {filename}")
            stats["skipped_missing"] += 1
            continue

        with open(param_path, encoding="utf-8") as f:
            params = json.load(f)

        # Determine the clean material value (strip parenthetical detail)
        new_material = expected.split("(")[0].strip() if "(" in expected else expected

        # Extract secondary material note for mixed types
        secondary = extract_secondary_material(expected)

        action = "APPLY" if apply else "DRY-RUN"
        detail = f"  + secondary: {secondary}" if secondary else ""
        print(f"  {action}: {filename}  facade_material '{actual}' -> '{new_material}'"
              f"  (conf={confidence:.2f}){detail}")

        if apply:
            old_material = params.get("facade_material", "")
            params["facade_material"] = new_material

            # Add secondary material note for mixed types
            if secondary or new_material == "mixed":
                facade_detail = params.setdefault("facade_detail", {})
                facade_detail["secondary_material"] = secondary or f"mixed (previously {old_material})"

            # Stamp _meta
            meta = params.setdefault("_meta", {})
            fixes = meta.setdefault("handoff_fixes_applied", [])
            fixes.append({
                "fix": "fix_material_from_handoff",
                "task_id": "TASK-20260327-013",
                "field": "facade_material",
                "old_value": old_material,
                "new_value": new_material,
                "confidence": confidence,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

            with open(param_path, "w", encoding="utf-8") as f:
                json.dump(params, f, indent=2, ensure_ascii=False)
                f.write("\n")

        stats["applied"] += 1

    print(f"\nSummary: {stats['applied']} {'applied' if apply else 'would apply'}, "
          f"{stats['low_confidence']} low confidence, "
          f"{stats['skipped_missing']} missing files, "
          f"{stats['skipped_field']} non-material findings skipped")


def main():
    parser = argparse.ArgumentParser(description="Fix facade material from handoff findings")
    parser.add_argument("--apply", action="store_true", help="Write changes (default: dry-run)")
    args = parser.parse_args()
    process(apply=args.apply)


if __name__ == "__main__":
    main()
