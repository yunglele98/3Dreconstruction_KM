#!/usr/bin/env python3
"""Phase 0: Generate COLMAP block priority list from audit results.

Groups buildings by street, ranks by critical/high count * photo availability.

Usage:
    python scripts/visual_audit/colmap_priority.py
"""
from __future__ import annotations
import argparse, json, logging, re
from pathlib import Path

logger = logging.getLogger(__name__)
REPO_ROOT = Path(__file__).parent.parent.parent
STREET_SUFFIXES = {"St","Ave","Pl","Rd","Ter","Ln","Cres","Blvd","Dr"}

def extract_street(address):
    parts = address.strip().split()
    if len(parts) < 2: return address
    for i, part in enumerate(parts):
        if part in STREET_SUFFIXES and i > 0:
            start = 0
            for j, p in enumerate(parts):
                if not re.match(r"^[\d\-]+[A-Za-z]?$", p):
                    start = j; break
            return " ".join(parts[start:i+1])
    for i, part in enumerate(parts):
        if not re.match(r"^[\d\-]+[A-Za-z]?$", part):
            return " ".join(parts[i:])
    return address

def main():
    parser = argparse.ArgumentParser(description="COLMAP block priority")
    parser.add_argument("--input", type=Path, default=REPO_ROOT/"outputs"/"visual_audit"/"priority_queue.json")
    parser.add_argument("--output", type=Path, default=REPO_ROOT/"outputs"/"visual_audit"/"colmap_priority.json")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    data = json.loads(args.input.read_text(encoding="utf-8"))
    streets = {}
    for b in data["buildings"]:
        if b["tier"] == "no_photo": continue
        street = extract_street(b.get("address",""))
        streets.setdefault(street, []).append(b)

    blocks = []
    for street, bldgs in streets.items():
        critical = sum(1 for b in bldgs if b["tier"] == "critical")
        high = sum(1 for b in bldgs if b["tier"] == "high")
        with_3_photos = sum(1 for b in bldgs if b.get("photo_count",0) >= 3)
        total_photos = sum(b.get("photo_count",0) for b in bldgs)
        avg_photos = total_photos / len(bldgs) if bldgs else 0
        priority_score = (critical * 3 + high) * max(avg_photos, 1)
        blocks.append({
            "block": street,
            "building_count": len(bldgs),
            "critical": critical,
            "high": high,
            "with_3plus_photos": with_3_photos,
            "total_photos": total_photos,
            "avg_photos": round(avg_photos, 1),
            "priority_score": round(priority_score, 1),
        })

    blocks.sort(key=lambda b: b["priority_score"], reverse=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(blocks, indent=2), encoding="utf-8")

    logger.info("COLMAP priority: %d blocks -> %s", len(blocks), args.output)
    logger.info("\nTop 10 blocks for COLMAP:")
    for b in blocks[:10]:
        logger.info("  %6.1f  %-20s (%d bldgs, %d critical, %d with 3+ photos)",
            b["priority_score"], b["block"], b["building_count"], b["critical"], b["with_3plus_photos"])

if __name__ == "__main__":
    main()
