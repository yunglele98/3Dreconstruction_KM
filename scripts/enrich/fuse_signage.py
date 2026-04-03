#!/usr/bin/env python3
"""Fuse signage/OCR observations into building parameter files.

Reads signage JSON files from Stage 1 (PaddleOCR) and extracts
business names and signage texts into `context.business_name` and
`assessment.signage`. "signage" is appended to `_meta.fusion_applied`.

Usage:
    python scripts/enrich/fuse_signage.py
    python scripts/enrich/fuse_signage.py --signage signage/ --params params/
"""

import argparse
import json
import os
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _atomic_write_json(filepath, data, ensure_ascii=False):
    """Write JSON atomically via temp file + rename to prevent corruption."""
    filepath = Path(filepath)
    with tempfile.NamedTemporaryFile(
        mode="w", dir=filepath.parent, delete=False,
        suffix=".tmp", encoding="utf-8",
    ) as tmp:
        json.dump(data, tmp, indent=2, ensure_ascii=ensure_ascii)
        tmp.write("\n")
        tmp_path = Path(tmp.name)
    os.replace(str(tmp_path), str(filepath))


def _sanitize_address(filename):
    """Convert param filename to address key: strip .json, replace _ with space."""
    return Path(filename).stem.replace("_", " ")


def _address_to_stem(address):
    """Convert address string to filename stem (spaces to underscores)."""
    return address.replace(" ", "_")


def _find_signage(signage_dir, address):
    """Find a matching signage JSON file for an address."""
    stem = _address_to_stem(address)
    # Direct match
    candidate = signage_dir / f"{stem}.json"
    if candidate.exists():
        return candidate
    # With _signage suffix
    candidate = signage_dir / f"{stem}_signage.json"
    if candidate.exists():
        return candidate
    # Case-insensitive search
    stem_lower = stem.lower()
    for f in signage_dir.glob("*.json"):
        f_stem_lower = f.stem.lower()
        if f_stem_lower == stem_lower or f_stem_lower == f"{stem_lower}_signage":
            return f
    return None


def _extract_signage_observations(sig_data):
    """Extract business name and signage texts from OCR results.

    Expects sig_data to be a dict with keys like 'texts', 'business_name',
    'detections', or a list of text detection results.
    """
    business_name = None
    signage_texts = []

    if isinstance(sig_data, dict):
        # Direct business_name field
        business_name = sig_data.get("business_name")

        # Collect all detected texts
        texts = sig_data.get("texts", [])
        if isinstance(texts, list):
            signage_texts.extend(
                t for t in texts if isinstance(t, str) and t.strip()
            )

        # Handle detections array (PaddleOCR format)
        detections = sig_data.get("detections", sig_data.get("results", []))
        if isinstance(detections, list):
            for det in detections:
                if isinstance(det, dict):
                    text = (det.get("text") or det.get("value") or "").strip()
                    if text:
                        signage_texts.append(text)
                elif isinstance(det, str) and det.strip():
                    signage_texts.append(det.strip())

        # If no business_name but there are texts, use the longest as
        # the likely business name (storefronts typically have one
        # prominent sign)
        if not business_name and signage_texts:
            business_name = max(signage_texts, key=len)

    elif isinstance(sig_data, list):
        for item in sig_data:
            if isinstance(item, str) and item.strip():
                signage_texts.append(item.strip())
            elif isinstance(item, dict):
                text = (item.get("text") or item.get("value") or "").strip()
                if text:
                    signage_texts.append(text)
        if signage_texts:
            business_name = max(signage_texts, key=len)

    # Deduplicate while preserving order
    seen = set()
    unique_texts = []
    for t in signage_texts:
        t_lower = t.lower()
        if t_lower not in seen:
            seen.add(t_lower)
            unique_texts.append(t)

    return business_name, unique_texts


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def fuse_signage(signage_dir, params_dir):
    """Fuse signage/OCR data into all matching param files."""
    signage_dir = Path(signage_dir)
    params_dir = Path(params_dir)

    fused = 0
    skipped_no_data = 0
    skipped_already = 0
    skipped_other = 0

    for param_file in sorted(params_dir.glob("*.json")):
        # Skip metadata files
        if param_file.name.startswith("_"):
            skipped_other += 1
            continue

        with open(param_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Skip non-building entries
        if data.get("skipped"):
            skipped_other += 1
            continue

        # Check idempotency
        meta = data.setdefault("_meta", {})
        fusion_applied = meta.setdefault("fusion_applied", [])
        if "signage" in fusion_applied:
            skipped_already += 1
            continue

        # Find matching signage file
        address = _sanitize_address(param_file.name)
        sig_file = _find_signage(signage_dir, address)
        if sig_file is None:
            skipped_no_data += 1
            continue

        try:
            with open(sig_file, "r", encoding="utf-8") as f:
                sig_data = json.load(f)
        except (json.JSONDecodeError, OSError):
            skipped_no_data += 1
            continue

        business_name, signage_texts = _extract_signage_observations(sig_data)
        if not business_name and not signage_texts:
            skipped_no_data += 1
            continue

        # Write business_name into context
        if business_name:
            context = data.setdefault("context", {})
            context["business_name"] = business_name

        # Write signage texts into assessment
        if signage_texts:
            assessment = data.setdefault("assessment", {})
            assessment["signage"] = signage_texts

        fusion_applied.append("signage")

        _atomic_write_json(param_file, data)
        fused += 1

    print(f"Fused {fused} buildings, skipped {skipped_no_data} (no data), "
          f"skipped {skipped_already} (already fused)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Fuse signage/OCR observations into building params"
    )
    parser.add_argument(
        "--signage", type=Path, default=REPO_ROOT / "signage",
        help="Directory containing signage JSON files (default: signage/)"
    )
    parser.add_argument(
        "--params", type=Path, default=REPO_ROOT / "params",
        help="Directory containing building param JSON files (default: params/)"
    )
    args = parser.parse_args()
    fuse_signage(args.signage, args.params)
