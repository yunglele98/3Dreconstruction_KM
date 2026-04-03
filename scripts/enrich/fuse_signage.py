#!/usr/bin/env python3
"""Stage 3 — ENRICH: Fuse OCR signage results into building params.

Reads per-photo signage JSON from signage/ and merges detected text
(business names, addresses, heritage plaques) into params.

Usage:
    python scripts/enrich/fuse_signage.py --signage signage/ --params params/
    python scripts/enrich/fuse_signage.py --signage signage/ --params params/ --dry-run
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_SIGNAGE = REPO_ROOT / "signage"
DEFAULT_PARAMS = REPO_ROOT / "params"


def load_photo_param_mapping(params_dir: Path) -> dict[str, Path]:
    """Map photo stems to param files."""
    mapping: dict[str, Path] = {}
    for f in params_dir.glob("*.json"):
        if f.name.startswith("_"):
            continue
        data = json.loads(f.read_text(encoding="utf-8"))
        if data.get("skipped"):
            continue
        for photo in data.get("matched_photos", []):
            mapping[Path(photo).stem] = f
        obs = data.get("photo_observations", {})
        if obs.get("photo"):
            mapping[Path(obs["photo"]).stem] = f
    return mapping


def load_signage_results(signage_path: Path) -> dict:
    """Load signage JSON for a photo."""
    if not signage_path.exists():
        return {}
    return json.loads(signage_path.read_text(encoding="utf-8"))


def fuse_signage(
    signage_dir: Path, params_dir: Path, *, dry_run: bool = False
) -> dict:
    """Fuse signage OCR results into params files."""
    mapping = load_photo_param_mapping(params_dir)
    signage_files = sorted(signage_dir.glob("*_signage.json"))
    stats = {"fused": 0, "no_match": 0, "errors": 0}

    for sig_file in signage_files:
        photo_stem = sig_file.stem.replace("_signage", "")
        param_file = mapping.get(photo_stem)
        if param_file is None:
            stats["no_match"] += 1
            continue

        try:
            sig_data = load_signage_results(sig_file)
            text_regions = sig_data.get("text_regions", [])

            if dry_run:
                stats["fused"] += 1
                continue

            data = json.loads(param_file.read_text(encoding="utf-8"))

            # Extract business names and signage text
            texts = [r.get("text", "") for r in text_regions if r.get("text")]

            if texts:
                data.setdefault("signage_analysis", {}).update({
                    "detected_texts": texts,
                    "source_photo": photo_stem,
                    "model": sig_data.get("model", ""),
                })

                # Try to identify business name (longest text usually)
                if texts:
                    longest = max(texts, key=len)
                    ctx = data.setdefault("context", {})
                    if not ctx.get("business_name"):
                        ctx["business_name"] = longest

            meta = data.setdefault("_meta", {})
            fusion = meta.setdefault("fusion_applied", [])
            if "signage" not in fusion:
                fusion.append("signage")

            param_file.write_text(
                json.dumps(data, indent=2), encoding="utf-8"
            )
            stats["fused"] += 1

        except Exception:
            stats["errors"] += 1

    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Fuse signage OCR into params")
    parser.add_argument("--signage", type=Path, default=DEFAULT_SIGNAGE)
    parser.add_argument("--params", type=Path, default=DEFAULT_PARAMS)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not args.signage.is_dir():
        print(f"[ERROR] Signage directory not found: {args.signage}")
        sys.exit(1)

    stats = fuse_signage(args.signage, args.params, dry_run=args.dry_run)
    prefix = "[DRY RUN] " if args.dry_run else ""
    print(f"{prefix}Signage fusion: {stats['fused']} fused, "
          f"{stats['no_match']} unmatched, {stats['errors']} errors")


if __name__ == "__main__":
    main()
