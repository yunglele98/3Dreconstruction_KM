#!/usr/bin/env python3
"""Fuse signage OCR results into building params.

Reads per-photo signage JSONs from Stage 1 and updates business_name,
signage, and context fields in params.

Usage:
    python scripts/enrich/fuse_signage.py --signage signage/ --params params/
    python scripts/enrich/fuse_signage.py --signage signage/ --params params/ --apply
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def load_photo_index(index_path: Path) -> dict[str, list[str]]:
    """Load photo index CSV."""
    by_address: dict[str, list[str]] = defaultdict(list)
    if not index_path.exists():
        return dict(by_address)
    with open(index_path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            addr = (row.get("address_or_location") or "").strip()
            fname = (row.get("filename") or "").strip()
            if addr and fname:
                by_address[addr.lower()].append(fname)
    return dict(by_address)


def extract_business_info(detections: list[dict]) -> dict:
    """Extract business name and signage text from OCR detections.

    Filters for high-confidence text that looks like business names
    (excludes numbers-only, very short text, common non-signage).
    """
    # Filter high-confidence, non-trivial text
    texts = []
    for d in detections:
        text = d.get("text", "").strip()
        conf = d.get("confidence", 0)
        if conf < 0.6 or len(text) < 3:
            continue
        # Skip purely numeric
        if re.match(r"^\d+$", text):
            continue
        texts.append(text)

    if not texts:
        return {}

    # The longest high-confidence text is likely the business name
    texts.sort(key=len, reverse=True)
    business_name = texts[0] if texts else ""

    return {
        "business_name": business_name,
        "signage_texts": texts[:5],
        "text_count": len(texts),
    }


def fuse_signage_into_params(
    signage_dir: Path,
    params_dir: Path,
    photo_index_path: Path,
    apply: bool = False,
) -> dict:
    """Fuse signage OCR into building params."""
    photo_index = load_photo_index(photo_index_path)
    stats = {"updated": 0, "skipped": 0, "no_signage": 0}

    for param_file in sorted(params_dir.glob("*.json")):
        if param_file.name.startswith("_"):
            continue

        try:
            data = json.loads(param_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue

        if data.get("skipped"):
            stats["skipped"] += 1
            continue

        meta = data.get("_meta", {})
        if "signage" in (meta.get("fusion_applied") or []):
            stats["skipped"] += 1
            continue

        address = (
            meta.get("address")
            or data.get("building_name")
            or param_file.stem.replace("_", " ")
        )

        photos = photo_index.get(address.lower(), [])
        if not photos:
            stats["no_signage"] += 1
            continue

        # Collect OCR results
        all_detections = []
        for photo in photos:
            stem = Path(photo).stem
            sig_path = signage_dir / f"{stem}_signage.json"
            if sig_path.exists():
                try:
                    sig_data = json.loads(sig_path.read_text(encoding="utf-8"))
                    all_detections.extend(sig_data.get("detections", []))
                except (json.JSONDecodeError, OSError):
                    pass

        if not all_detections:
            stats["no_signage"] += 1
            continue

        info = extract_business_info(all_detections)
        if not info:
            stats["no_signage"] += 1
            continue

        changed = False

        # Update context.business_name if empty
        if "context" not in data:
            data["context"] = {}
        if not data["context"].get("business_name") and info.get("business_name"):
            data["context"]["business_name"] = info["business_name"]
            changed = True

        # Update assessment.signage
        if "assessment" not in data:
            data["assessment"] = {}
        if not data["assessment"].get("signage"):
            data["assessment"]["signage"] = ", ".join(info.get("signage_texts", [])[:3])
            changed = True

        if changed:
            if "_meta" not in data:
                data["_meta"] = {}
            if "fusion_applied" not in data["_meta"]:
                data["_meta"]["fusion_applied"] = []
            if "signage" not in data["_meta"]["fusion_applied"]:
                data["_meta"]["fusion_applied"].append("signage")

            if apply:
                param_file.write_text(
                    json.dumps(data, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
            stats["updated"] += 1

    return stats


def main():
    parser = argparse.ArgumentParser(description="Fuse signage OCR into params")
    parser.add_argument("--signage", type=Path, default=REPO_ROOT / "signage")
    parser.add_argument("--params", type=Path, default=REPO_ROOT / "params")
    parser.add_argument("--photo-index", type=Path,
                        default=REPO_ROOT / "PHOTOS KENSINGTON" / "csv" / "photo_address_index.csv")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    stats = fuse_signage_into_params(
        args.signage, args.params, args.photo_index, args.apply
    )
    mode = "APPLIED" if args.apply else "DRY RUN"
    print(f"Signage fusion ({mode}): {stats}")


if __name__ == "__main__":
    main()
