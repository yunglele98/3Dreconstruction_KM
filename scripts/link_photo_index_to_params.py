#!/usr/bin/env python3
"""Link photo index rows to params metadata.

Adds reference photo metadata from PHOTOS KENSINGTON/csv/photo_address_index.csv
to matching params files using the same address normalization as prepare_batches.py.
"""

from __future__ import annotations

import csv
import json
import re
import unicodedata
from pathlib import Path

from prepare_batches import address_to_filename


BASE_DIR = Path(__file__).parent.parent
INDEX_CSV = BASE_DIR / "PHOTOS KENSINGTON" / "csv" / "photo_address_index.csv"
PHOTO_DIR = BASE_DIR / "PHOTOS KENSINGTON"
PARAMS_DIR = BASE_DIR / "params"


def _ascii_text(value: str) -> str:
    return unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")


def candidate_param_names(address: str) -> list[str]:
    """Generate filename candidates for a potentially annotated address string."""
    raw = (address or "").strip()
    if not raw:
        return []

    variants = [raw]

    # Remove parenthetical business labels, then side-view suffixes.
    no_paren = re.sub(r"\s*\([^)]*\)", "", raw).strip()
    if no_paren:
        variants.append(no_paren)
    no_side = re.sub(r"\s*-\s*.*$", "", no_paren).strip()
    if no_side:
        variants.append(no_side)

    # Handle slash-separated alternates ("6 St Andrew / 8 ...").
    parts = [p.strip() for p in re.split(r"\s*/\s*", no_side) if p.strip()]
    variants.extend(parts)

    # Also try ASCII-safe variants for diacritics.
    variants.extend(_ascii_text(v) for v in list(variants))

    seen = set()
    out = []
    for v in variants:
        if not v:
            continue
        name = address_to_filename(v)
        if name not in seen:
            seen.add(name)
            out.append(name)
    return out


def main() -> None:
    if not INDEX_CSV.exists():
        raise SystemExit(f"[ERROR] Missing index CSV: {INDEX_CSV}")

    grouped: dict[str, list[dict[str, str]]] = {}
    with INDEX_CSV.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            address = (row.get("address_or_location") or "").strip()
            filename = (row.get("filename") or "").strip()
            source = (row.get("source") or "").strip() or "unknown"
            if not address or not filename:
                continue
            param_name = None
            for cand in candidate_param_names(address):
                if (PARAMS_DIR / cand).exists():
                    param_name = cand
                    break
            if not param_name:
                continue
            grouped.setdefault(param_name, []).append({
                "filename": filename,
                "source": source,
                "address": address,
            })

    touched = 0
    backfilled_photo = 0
    for param_name, rows in grouped.items():
        param_path = PARAMS_DIR / param_name
        with param_path.open(encoding="utf-8") as f:
            data = json.load(f)

        meta = data.get("_meta")
        if not isinstance(meta, dict):
            meta = {}
            data["_meta"] = meta

        # Prioritize confirmed rows and keep deterministic ordering.
        rows_sorted = sorted(
            rows,
            key=lambda r: (0 if r["source"].lower() == "confirmed" else 1, r["filename"]),
        )

        # Deduplicate while preserving order.
        filenames: list[str] = []
        seen = set()
        for row in rows_sorted:
            fn = row["filename"]
            if fn not in seen:
                seen.add(fn)
                filenames.append(fn)

        changed = False
        if not meta.get("photo") and filenames:
            meta["photo"] = filenames[0]
            backfilled_photo += 1
            changed = True

        # Keep metadata compact: sample list + explicit count.
        sample_size = 5
        sample = filenames[:sample_size]
        if meta.get("reference_photos") != sample:
            meta["reference_photos"] = sample
            changed = True

        if meta.get("reference_photo_count") != len(filenames):
            meta["reference_photo_count"] = len(filenames)
            changed = True

        if meta.get("photo_index_source") != str(INDEX_CSV):
            meta["photo_index_source"] = str(INDEX_CSV)
            changed = True

        if meta.get("photo_directory") != str(PHOTO_DIR):
            meta["photo_directory"] = str(PHOTO_DIR)
            changed = True

        if changed:
            with param_path.open("w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            touched += 1

    print(f"[OK] Param files matched to photo index: {len(grouped)}")
    print(f"[OK] Param files updated: {touched}")
    print(f"[OK] _meta.photo backfilled: {backfilled_photo}")


if __name__ == "__main__":
    main()
