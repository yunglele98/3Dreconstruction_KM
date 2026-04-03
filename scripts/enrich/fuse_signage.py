#!/usr/bin/env python3
"""Stage 3b: Fuse OCR signage results into building params.

Reads OCR output JSONs from signage/ (produced by extract_signage.py) and
writes detected business names and storefront text into params. Cross-
references with existing context.business_name.

Usage:
    python scripts/enrich/fuse_signage.py --signage signage/ --params params/
    python scripts/enrich/fuse_signage.py --signage signage/ --params params/ --dry-run
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).parent.parent.parent
PARAMS_DIR = REPO_ROOT / "params"
SIGNAGE_DIR = REPO_ROOT / "signage"


def atomic_write_json(path: Path, data: dict) -> None:
    content = json.dumps(data, indent=2, ensure_ascii=False)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        os.write(fd, content.encode("utf-8"))
        os.close(fd)
        os.replace(tmp, path)
    except Exception:
        os.close(fd)
        os.unlink(tmp)
        raise


def get_matched_photo_stem(params: dict) -> str | None:
    dfa = params.get("deep_facade_analysis", {})
    photo = dfa.get("source_photo")
    if not photo:
        po = params.get("photo_observations", {})
        photo = po.get("photo")
    if not photo:
        return None
    return Path(photo).stem


def load_signage(signage_dir: Path, photo_stem: str) -> dict | None:
    sig_path = signage_dir / f"{photo_stem}_text.json"
    if not sig_path.exists():
        return None
    try:
        return json.loads(sig_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def extract_business_name(sig_data: dict, existing_name: str | None) -> dict:
    """Extract likely business name from OCR results.

    Storefront candidates are text detected in the lower half of the image
    with confidence >= 0.5. Prefers longest text as likely business name.
    """
    candidates = sig_data.get("storefront_candidates", [])
    if not candidates:
        return {}

    # Sort by text length descending (business names tend to be longer)
    candidates.sort(key=lambda c: len(c.get("text", "")), reverse=True)

    best = candidates[0]
    detected_name = best.get("text", "").strip()

    if not detected_name or len(detected_name) < 3:
        return {}

    result = {
        "detected_text": detected_name,
        "confidence": best.get("confidence", 0),
        "all_storefront_texts": [c.get("text", "") for c in candidates[:5]],
    }

    # Cross-reference with existing business name
    if existing_name:
        existing_lower = existing_name.lower()
        detected_lower = detected_name.lower()
        # Check if they match or overlap
        if existing_lower in detected_lower or detected_lower in existing_lower:
            result["matches_existing"] = True
        else:
            result["matches_existing"] = False
            result["existing_name"] = existing_name

    return result


def fuse_signage_into_params(params: dict, sig_data: dict) -> tuple[dict, bool]:
    """Merge signage OCR into params. Returns (params, modified)."""
    modified = False

    # Extract business name
    existing_name = params.get("context", {}).get("business_name")
    name_result = extract_business_name(sig_data, existing_name)

    if name_result:
        params["signage_analysis"] = {
            "detected_business_name": name_result.get("detected_text"),
            "confidence": name_result.get("confidence"),
            "all_texts": name_result.get("all_storefront_texts", []),
            "matches_existing": name_result.get("matches_existing"),
            "text_count": sig_data.get("text_count", 0),
        }
        modified = True

        # If no existing business name, suggest the detected one
        if not existing_name and name_result.get("confidence", 0) >= 0.8:
            ctx = params.setdefault("context", {})
            if not ctx.get("business_name"):
                ctx["business_name"] = name_result["detected_text"]
                modified = True

    return params, modified


def fuse_all(params_dir: Path, signage_dir: Path,
             limit: int = 0, dry_run: bool = False,
             force: bool = False) -> dict:
    param_files = sorted(params_dir.glob("*.json"))
    if limit > 0:
        param_files = param_files[:limit]

    stats = {"processed": 0, "fused": 0, "no_signage": 0,
             "no_photo": 0, "skipped": 0}

    for pf in param_files:
        if pf.name.startswith("_"):
            continue
        try:
            params = json.loads(pf.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if params.get("skipped"):
            stats["skipped"] += 1
            continue

        stats["processed"] += 1

        meta = params.get("_meta", {})
        if not force and "signage" in meta.get("fusion_applied", []):
            stats["skipped"] += 1
            continue

        photo_stem = get_matched_photo_stem(params)
        if not photo_stem:
            stats["no_photo"] += 1
            continue

        sig_data = load_signage(signage_dir, photo_stem)
        if not sig_data:
            stats["no_signage"] += 1
            continue

        if dry_run:
            texts = sig_data.get("storefront_count", 0)
            logger.info("  [DRY-RUN] %s: %d storefront texts", pf.name, texts)
            stats["fused"] += 1
            continue

        params, was_modified = fuse_signage_into_params(params, sig_data)

        if was_modified:
            meta = params.setdefault("_meta", {})
            fa = meta.get("fusion_applied", [])
            if "signage" not in fa:
                fa.append("signage")
            meta["fusion_applied"] = fa
            atomic_write_json(pf, params)
            stats["fused"] += 1

    return stats


def main():
    parser = argparse.ArgumentParser(description="Stage 3b: Fuse signage OCR into params")
    parser.add_argument("--signage", type=Path, default=SIGNAGE_DIR)
    parser.add_argument("--params", type=Path, default=PARAMS_DIR)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    logger.info("Fusing signage from %s into %s", args.signage, args.params)
    stats = fuse_all(args.params, args.signage,
                     limit=args.limit, dry_run=args.dry_run, force=args.force)

    logger.info("\nDone: %d processed, %d fused, %d no signage, %d no photo, %d skipped",
                stats["processed"], stats["fused"], stats["no_signage"],
                stats["no_photo"], stats["skipped"])


if __name__ == "__main__":
    main()
