"""
Prepare photo analysis batches for AI agent processing.

Reads photo_address_index.csv and splits all photos into batch JSON files
that Claude Code, Codex, or Gemini CLI agents can pick up and process
using their native vision capabilities.

Photos are matched to existing param files (from PostGIS export) so agents
can merge visual observations into the database-backed skeletons.

Usage:
    python prepare_batches.py [--batch-size 50] [--output batches/]
"""

import argparse
import csv
import json
import math
import re
from pathlib import Path

INDEX_CSV = Path(__file__).parent.parent / "PHOTOS KENSINGTON" / "csv" / "photo_address_index.csv"
PHOTO_DIR = Path(__file__).parent.parent / "PHOTOS KENSINGTON"
PARAMS_DIR = Path(__file__).parent.parent / "params"


def address_to_filename(address):
    """Convert address to the param filename convention."""
    name = address.replace(" ", "_").replace(",", "").replace(".", "")
    name = re.sub(r"[^\w\-]", "_", name)
    name = re.sub(r"_+", "_", name).strip("_")
    return f"{name}.json"


def load_index(csv_path: Path) -> list[dict]:
    """Load all rows from photo_address_index.csv."""
    rows = []
    with open(csv_path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            rows.append({
                "filename": row["filename"],
                "address": row["address_or_location"],
                "source": row["source"],
            })
    return rows


def main():
    parser = argparse.ArgumentParser(description="Prepare photo analysis batches for AI agents")
    parser.add_argument("--batch-size", type=int, default=50, help="Photos per batch (default: 50)")
    parser.add_argument("--output", default="batches", help="Output directory for batch JSON files")
    parser.add_argument("--index", default=str(INDEX_CSV), help="Path to photo_address_index.csv")
    parser.add_argument("--photo-dir", default=str(PHOTO_DIR), help="Directory containing photos")
    parser.add_argument("--params-dir", default=str(PARAMS_DIR), help="Existing params directory")
    args = parser.parse_args()

    photos = load_index(Path(args.index))
    photo_dir = Path(args.photo_dir)
    params_dir = Path(args.params_dir)
    out_dir = Path(__file__).parent.parent / args.output
    out_dir.mkdir(exist_ok=True)

    # Verify photos exist
    missing = [p for p in photos if not (photo_dir / p["filename"]).exists()]
    if missing:
        print(f"[WARN] {len(missing)} photos not found in {photo_dir}")
        for m in missing[:5]:
            print(f"  - {m['filename']}")
        if len(missing) > 5:
            print(f"  ... and {len(missing) - 5} more")

    # Match photos to existing param files
    matched = 0
    for photo in photos:
        param_file = address_to_filename(photo["address"])
        param_path = params_dir / param_file
        photo["has_params"] = param_path.exists()
        photo["params_file"] = param_file
        if param_path.exists():
            matched += 1

    num_batches = math.ceil(len(photos) / args.batch_size)

    for i in range(num_batches):
        start = i * args.batch_size
        end = min(start + args.batch_size, len(photos))
        batch = photos[start:end]

        batch_file = out_dir / f"batch_{i + 1:03d}.json"
        batch_data = {
            "batch_id": i + 1,
            "total_batches": num_batches,
            "photo_dir": str(photo_dir.resolve()),
            "params_dir": str(params_dir.resolve()),
            "count": len(batch),
            "photos": batch,
        }
        with open(batch_file, "w", encoding="utf-8") as f:
            json.dump(batch_data, f, indent=2)

    print(f"Prepared {num_batches} batches ({args.batch_size} photos each)")
    print(f"Total photos: {len(photos)}")
    print(f"Matched to existing params: {matched}")
    print(f"New (no params yet): {len(photos) - matched}")
    print(f"Output: {out_dir}/")
    print(f"\nRun agents with:")
    print(f"  claude 'Follow AGENT_PROMPT.md to process batches/batch_001.json'")
    print(f"  codex 'Follow AGENT_PROMPT.md to process batches/batch_001.json'")
    print(f"  gemini 'Follow AGENT_PROMPT.md to process batches/batch_001.json'")


if __name__ == "__main__":
    main()
