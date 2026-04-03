#!/usr/bin/env python3
"""Stage 5 — TEXTURE: Generate condition-driven weathering overlay maps.

Creates per-building weathering texture maps (dirt, water stains, moss,
paint peeling, efflorescence) based on building condition, age, material,
and orientation. These maps are applied as overlay textures in the
generator or game engine.

Weathering types by condition:
  good:  subtle dust, minor mortar discoloration
  fair:  water stains, gutter streaks, foundation dirt, slight moss
  poor:  heavy staining, paint peeling, efflorescence, moss/lichen, cracks

Usage:
    python scripts/texture/generate_weathering.py --params params/ --output textures/weathering/
    python scripts/texture/generate_weathering.py --address "22 Lippincott St" --output textures/weathering/
    python scripts/texture/generate_weathering.py --params params/ --output textures/weathering/ --dry-run
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    import numpy as np
    from PIL import Image, ImageDraw, ImageFilter
except ImportError:
    np = None
    Image = None

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PARAMS_DIR = REPO_ROOT / "params"
OUTPUT_DIR = REPO_ROOT / "textures" / "weathering"

# Weathering intensity by condition
CONDITION_INTENSITY = {
    "good": {"stains": 0.05, "dirt": 0.08, "moss": 0.0, "peeling": 0.0},
    "fair": {"stains": 0.15, "dirt": 0.20, "moss": 0.03, "peeling": 0.05},
    "poor": {"stains": 0.35, "dirt": 0.40, "moss": 0.15, "peeling": 0.20},
}

# Texture resolution
DEFAULT_RES = 1024


def generate_water_stains(width: int, height: int, intensity: float, seed: int = 0) -> "np.ndarray":
    """Generate vertical water stain streaks."""
    rng = np.random.RandomState(seed)
    stains = np.ones((height, width), dtype=np.float32)

    num_streaks = max(1, int(intensity * 15))
    for _ in range(num_streaks):
        x = rng.randint(0, width)
        streak_width = rng.randint(3, 15)
        streak_length = rng.randint(height // 3, height)
        start_y = rng.randint(0, height // 3)
        darkness = 0.4 + rng.random() * 0.3

        for dy in range(streak_length):
            y = start_y + dy
            if y >= height:
                break
            # Wander horizontally
            x += rng.randint(-1, 2)
            x = max(0, min(width - streak_width, x))
            # Fade with distance
            fade = 1.0 - (dy / streak_length) * 0.5
            for dx in range(streak_width):
                if 0 <= x + dx < width:
                    stains[y, x + dx] = min(stains[y, x + dx], 1.0 - darkness * fade * intensity)

    return stains


def generate_dirt_gradient(width: int, height: int, intensity: float) -> "np.ndarray":
    """Generate gravity-driven dirt accumulation (darker at bottom)."""
    gradient = np.linspace(1.0 - intensity * 0.5, 1.0, height)
    dirt = np.tile(gradient[:, np.newaxis], (1, width))

    # Add noise
    noise = np.random.RandomState(42).random((height, width)).astype(np.float32)
    noise = (noise - 0.5) * intensity * 0.15
    dirt = np.clip(dirt + noise, 0.0, 1.0)

    return dirt.astype(np.float32)


def generate_moss_patches(width: int, height: int, coverage: float, seed: int = 7) -> "np.ndarray":
    """Generate moss/lichen patches (concentrated at base and crevices)."""
    rng = np.random.RandomState(seed)
    moss = np.zeros((height, width), dtype=np.float32)

    if coverage <= 0:
        return moss

    num_patches = max(1, int(coverage * 30))
    for _ in range(num_patches):
        # Bias towards bottom third
        cx = rng.randint(0, width)
        cy = rng.randint(height * 2 // 3, height)
        radius = rng.randint(10, 50)

        for y in range(max(0, cy - radius), min(height, cy + radius)):
            for x in range(max(0, cx - radius), min(width, cx + radius)):
                dist = ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5
                if dist < radius:
                    moss[y, x] = max(moss[y, x], 1.0 - dist / radius)

    return np.clip(moss * coverage * 3, 0, 1).astype(np.float32)


def generate_peeling_mask(width: int, height: int, intensity: float, seed: int = 13) -> "np.ndarray":
    """Generate paint peeling / efflorescence patches."""
    rng = np.random.RandomState(seed)
    peeling = np.zeros((height, width), dtype=np.float32)

    if intensity <= 0:
        return peeling

    num = max(1, int(intensity * 20))
    for _ in range(num):
        cx = rng.randint(0, width)
        cy = rng.randint(0, height)
        rx = rng.randint(15, 80)
        ry = rng.randint(10, 60)

        for y in range(max(0, cy - ry), min(height, cy + ry)):
            for x in range(max(0, cx - rx), min(width, cx + rx)):
                dx = (x - cx) / rx
                dy = (y - cy) / ry
                if dx * dx + dy * dy < 1.0:
                    peeling[y, x] = max(peeling[y, x], 0.8)

    return np.clip(peeling * intensity, 0, 1).astype(np.float32)


def generate_weathering_maps(
    params: dict,
    output_dir: Path,
    *,
    resolution: int = DEFAULT_RES,
) -> dict:
    """Generate all weathering maps for a single building."""
    if np is None or Image is None:
        return {"status": "requires_numpy_pillow"}

    address = params.get("_meta", {}).get("address", "unknown")
    condition = (params.get("condition") or "fair").lower()
    material = (params.get("facade_material") or "brick").lower()
    era = params.get("hcd_data", {}).get("construction_date", "")

    # Estimate age
    age = 80
    if "pre-1889" in era.lower():
        age = 140
    elif "1889" in era or "1903" in era:
        age = 125
    elif "1904" in era or "1913" in era:
        age = 115

    intensities = CONDITION_INTENSITY.get(condition, CONDITION_INTENSITY["fair"])

    # Facade aspect ratio
    width_m = params.get("facade_width_m", 6.0)
    height_m = params.get("total_height_m", 8.0)
    aspect = width_m / max(height_m, 1.0)
    tex_w = resolution
    tex_h = max(256, int(resolution / aspect))

    safe_name = address.replace(" ", "_").replace(",", "")
    building_dir = output_dir / safe_name
    building_dir.mkdir(parents=True, exist_ok=True)

    seed = hash(address) % 10000

    # Generate maps
    stains = generate_water_stains(tex_w, tex_h, intensities["stains"], seed)
    dirt = generate_dirt_gradient(tex_w, tex_h, intensities["dirt"])
    moss = generate_moss_patches(tex_w, tex_h, intensities["moss"], seed + 1)
    peeling = generate_peeling_mask(tex_w, tex_h, intensities["peeling"], seed + 2)

    # Composite weathering overlay (multiply map: 1.0 = no change, <1 = darker)
    composite = stains * dirt
    # Moss adds green tint (handled in material shader, store as separate channel)

    # Save maps
    def save_map(arr, name):
        img = Image.fromarray((arr * 255).astype(np.uint8), mode="L")
        path = building_dir / f"{safe_name}_{name}.png"
        img.save(path)
        return path

    paths = {
        "stains": str(save_map(stains, "stains")),
        "dirt": str(save_map(dirt, "dirt")),
        "composite": str(save_map(composite, "weathering_composite")),
    }
    if intensities["moss"] > 0:
        paths["moss"] = str(save_map(moss, "moss"))
    if intensities["peeling"] > 0:
        paths["peeling"] = str(save_map(peeling, "peeling"))

    # Write metadata
    meta = {
        "address": address,
        "condition": condition,
        "material": material,
        "age_estimate": age,
        "intensities": intensities,
        "resolution": [tex_w, tex_h],
        "maps": paths,
    }
    (building_dir / "weathering_meta.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    return {"status": "generated", "maps": len(paths), **meta}


def run_batch(
    params_dir: Path, output_dir: Path, *, dry_run: bool = False, limit: int = 0
) -> dict:
    """Generate weathering maps for all buildings."""
    output_dir.mkdir(parents=True, exist_ok=True)
    results = []

    files = sorted(params_dir.glob("*.json"))
    if limit > 0:
        files = files[:limit]

    for f in files:
        if f.name.startswith("_"):
            continue
        data = json.loads(f.read_text(encoding="utf-8"))
        if data.get("skipped"):
            continue

        if dry_run:
            addr = data.get("_meta", {}).get("address", f.stem)
            cond = (data.get("condition") or "fair").lower()
            results.append({"address": addr, "condition": cond, "status": "would_generate"})
        else:
            result = generate_weathering_maps(data, output_dir)
            results.append(result)

    stats = {
        "total": len(results),
        "generated": sum(1 for r in results if r.get("status") == "generated"),
        "by_condition": {},
    }
    for r in results:
        c = r.get("condition", "unknown")
        stats["by_condition"][c] = stats["by_condition"].get(c, 0) + 1

    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate weathering overlay maps")
    parser.add_argument("--params", type=Path, default=PARAMS_DIR)
    parser.add_argument("--address", type=str, default=None)
    parser.add_argument("--output", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--resolution", type=int, default=DEFAULT_RES)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.address:
        stem = args.address.replace(" ", "_")
        param_file = args.params / f"{stem}.json"
        if not param_file.exists():
            print(f"[ERROR] Not found: {param_file}")
            sys.exit(1)
        data = json.loads(param_file.read_text(encoding="utf-8"))
        result = generate_weathering_maps(data, args.output, resolution=args.resolution)
        print(f"Generated {result.get('maps', 0)} maps for {args.address}")
        return

    stats = run_batch(args.params, args.output, dry_run=args.dry_run, limit=args.limit)
    prefix = "[DRY RUN] " if args.dry_run else ""
    print(f"{prefix}Weathering maps: {stats['generated']}/{stats['total']} generated")
    for cond, count in sorted(stats["by_condition"].items()):
        print(f"  {cond}: {count}")


if __name__ == "__main__":
    main()
