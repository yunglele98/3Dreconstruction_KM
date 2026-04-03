"""Shared utilities for scripts/enrich/ fusion scripts."""

import json
from pathlib import Path


def load_photo_param_mapping(params_dir: Path) -> dict[str, Path]:
    """Map photo stems to their param files via matched_photos or photo_observations."""
    mapping: dict[str, Path] = {}
    for f in params_dir.glob("*.json"):
        if f.name.startswith("_"):
            continue
        data = json.loads(f.read_text(encoding="utf-8"))
        if data.get("skipped"):
            continue
        for photo in data.get("matched_photos", []):
            stem = Path(photo).stem
            mapping[stem] = f
        obs = data.get("photo_observations", {})
        if obs.get("photo"):
            stem = Path(obs["photo"]).stem
            mapping[stem] = f
    return mapping
