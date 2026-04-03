#!/usr/bin/env python3
"""Phase 0, Stage 1: Match each render to its best field photo.

Reads renders from buildings_renders_v1/, finds the matched photo from
each building's param file (photo_observations.photo or
deep_facade_analysis.source_photo), and resolves the photo path.

Usage:
    python scripts/visual_audit/pair_renders_to_photos.py
    python scripts/visual_audit/pair_renders_to_photos.py --renders outputs/buildings_renders_v1/ --limit 10
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).parent.parent.parent
RENDERS_DIR = REPO_ROOT / "outputs" / "buildings_renders_v1"
PARAMS_DIR = REPO_ROOT / "params"
PHOTOS_DIR = REPO_ROOT / "PHOTOS KENSINGTON"
PHOTOS_SORTED_DIR = REPO_ROOT / "PHOTOS KENSINGTON sorted"
PHOTO_INDEX_CSV = PHOTOS_DIR / "csv" / "photo_address_index.csv"


def load_photo_index(csv_path: Path) -> dict[str, list[str]]:
    """Load photo index CSV → {address_lower: [filename, ...]}."""
    index: dict[str, list[str]] = {}
    if not csv_path.exists():
        return index
    with open(csv_path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            addr = (row.get("address_or_location") or "").strip().lower()
            filename = (row.get("filename") or "").strip()
            if addr and filename:
                index.setdefault(addr, []).append(filename)
    return index


def resolve_photo_path(filename: str) -> Path | None:
    """Find the actual photo file on disk."""
    if not filename:
        return None

    # Try flat PHOTOS KENSINGTON/ first
    flat = PHOTOS_DIR / filename
    if flat.exists():
        return flat

    # Try sorted subdirectories
    for subdir in PHOTOS_SORTED_DIR.iterdir():
        if subdir.is_dir():
            candidate = subdir / filename
            if candidate.exists():
                return candidate

    return None


def load_param_photo(param_path: Path) -> str | None:
    """Extract the matched photo filename from a param file."""
    try:
        data = json.loads(param_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None

    # Priority: deep_facade_analysis.source_photo > photo_observations.photo
    dfa = data.get("deep_facade_analysis", {})
    photo = dfa.get("source_photo")
    if photo:
        return photo

    po = data.get("photo_observations", {})
    photo = po.get("photo")
    if photo:
        return photo

    return None


def address_from_render(render_path: Path) -> str:
    """Convert render filename to address string."""
    return render_path.stem.replace("_", " ")


def address_to_param_filename(address: str) -> str:
    """Convert address to param filename."""
    return address.replace(" ", "_") + ".json"


def pair_all(renders_dir: Path, params_dir: Path,
             limit: int = 0) -> list[dict]:
    """Match each render to its best field photo."""
    render_files = sorted(renders_dir.glob("*.png"))
    if limit > 0:
        render_files = render_files[:limit]

    photo_index = load_photo_index(PHOTO_INDEX_CSV)

    pairs = []
    for render_path in render_files:
        address = address_from_render(render_path)
        param_name = address_to_param_filename(address)
        param_path = params_dir / param_name

        result = {
            "address": address,
            "render": str(render_path),
            "photo": None,
            "photo_path": None,
            "match_status": "no_photo",
            "match_source": None,
            "all_photos": [],
            "photo_count": 0,
        }

        # Strategy 1: photo referenced in param file
        if param_path.exists():
            photo_filename = load_param_photo(param_path)
            if photo_filename:
                photo_path = resolve_photo_path(photo_filename)
                if photo_path and photo_path.exists():
                    result["photo"] = photo_filename
                    result["photo_path"] = str(photo_path)
                    result["match_status"] = "matched"
                    result["match_source"] = "param_file"

        # Strategy 2: photo index CSV lookup
        if result["match_status"] == "no_photo":
            addr_lower = address.lower()
            candidates = photo_index.get(addr_lower, [])
            if not candidates:
                # Try partial match
                for idx_addr, filenames in photo_index.items():
                    if addr_lower in idx_addr or idx_addr in addr_lower:
                        candidates.extend(filenames)

            if candidates:
                # Pick largest file (proxy for best quality)
                best = None
                best_size = 0
                for fn in candidates:
                    p = resolve_photo_path(fn)
                    if p and p.exists():
                        sz = p.stat().st_size
                        if sz > best_size:
                            best = p
                            best_size = sz

                if best:
                    result["photo"] = best.name
                    result["photo_path"] = str(best)
                    result["match_status"] = "matched"
                    result["match_source"] = "photo_index"

            result["all_photos"] = candidates
            result["photo_count"] = len(candidates)

        # If matched via param, also gather all photos from index
        if result["match_source"] == "param_file":
            addr_lower = address.lower()
            all_photos = photo_index.get(addr_lower, [])
            result["all_photos"] = all_photos
            result["photo_count"] = max(len(all_photos), 1)

        pairs.append(result)

    return pairs


def main():
    parser = argparse.ArgumentParser(description="Phase 0: Pair renders to photos")
    parser.add_argument("--renders", type=Path, default=RENDERS_DIR)
    parser.add_argument("--params", type=Path, default=PARAMS_DIR)
    parser.add_argument("--output", type=Path,
                        default=REPO_ROOT / "outputs" / "visual_audit" / "pairs.json")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    logger.info("Pairing renders from %s", args.renders)
    pairs = pair_all(args.renders, args.params, limit=args.limit)

    matched = sum(1 for p in pairs if p["match_status"] == "matched")
    no_photo = sum(1 for p in pairs if p["match_status"] == "no_photo")
    logger.info("Paired: %d matched, %d no_photo (total: %d)", matched, no_photo, len(pairs))

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(pairs, indent=2), encoding="utf-8")
    logger.info("Saved → %s", args.output)

    return pairs


if __name__ == "__main__":
    main()
