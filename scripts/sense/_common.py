"""Shared utilities for scripts/sense/ stage."""

import json
from pathlib import Path

PHOTO_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}


def discover_photos(input_dir: Path, *, limit: int = 0) -> list[Path]:
    """Find all photo files in *input_dir* (non-recursive)."""
    photos = sorted(
        p for p in input_dir.iterdir()
        if p.suffix.lower() in PHOTO_EXTENSIONS
    )
    return photos[:limit] if limit > 0 else photos
