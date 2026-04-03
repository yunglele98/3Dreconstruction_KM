#!/usr/bin/env python3
"""Stage 5 — TEXTURE: Generate micro-detail displacement maps.

Creates per-material displacement/height maps that add geometric micro-detail
to flat procedural surfaces: brick relief, mortar joint depth, stone erosion
profiles, wood grain, stucco texture.

These maps are applied in Blender (Displacement modifier or shader) and in
game engines (parallax occlusion mapping / tessellation).

Usage:
    python scripts/texture/generate_displacement.py --material brick --output textures/displacement/
    python scripts/texture/generate_displacement.py --params params/ --output textures/displacement/ --batch
    python scripts/texture/generate_displacement.py --material brick --bond flemish --scale 2048
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    import numpy as np
    from PIL import Image
except ImportError:
    np = None
    Image = None

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
OUTPUT_DIR = REPO_ROOT / "textures" / "displacement"


def generate_brick_displacement(
    width: int = 1024,
    height: int = 1024,
    *,
    bond: str = "running",
    brick_height_px: int = 40,
    mortar_depth: float = 0.8,
    brick_roughness: float = 0.15,
    erosion: float = 0.05,
    seed: int = 42,
) -> "np.ndarray":
    """Generate a brick wall displacement map.

    Brick faces are raised (bright), mortar joints are recessed (dark),
    individual bricks have subtle height variation and edge chips.
    """
    rng = np.random.RandomState(seed)
    disp = np.ones((height, width), dtype=np.float32)

    mortar_w = max(2, brick_height_px // 12)
    brick_w_px = brick_height_px * 2

    row = 0
    y = 0
    while y < height:
        # Horizontal mortar line
        y_end = min(y + mortar_w, height)
        disp[y:y_end, :] = 1.0 - mortar_depth
        y = y_end

        # Offset for bond pattern
        if bond == "running":
            offset = (brick_w_px // 2) * (row % 2)
        elif bond == "flemish":
            offset = (brick_w_px // 3) * (row % 2)
        elif bond == "stack":
            offset = 0
        else:
            offset = (brick_w_px // 2) * (row % 2)

        brick_y_end = min(y + brick_height_px, height)

        x = -offset
        while x < width:
            # Vertical mortar joint
            joint_x = x + brick_w_px
            if 0 <= joint_x < width:
                x_start = max(0, joint_x)
                x_end = min(width, joint_x + mortar_w)
                disp[y:brick_y_end, x_start:x_end] = 1.0 - mortar_depth

            # Per-brick height variation
            bx_start = max(0, x + mortar_w)
            bx_end = min(width, joint_x)
            if bx_start < bx_end and y < brick_y_end:
                brick_level = 1.0 - rng.random() * brick_roughness
                noise = rng.random((brick_y_end - y, bx_end - bx_start)).astype(np.float32)
                disp[y:brick_y_end, bx_start:bx_end] = brick_level + noise * 0.03

                # Edge chips (erosion)
                if erosion > 0 and rng.random() < erosion * 5:
                    chip_x = bx_start + rng.randint(0, max(1, bx_end - bx_start))
                    chip_y = y + rng.randint(0, max(1, brick_y_end - y))
                    chip_r = rng.randint(2, 6)
                    for dy in range(-chip_r, chip_r + 1):
                        for dx in range(-chip_r, chip_r + 1):
                            if dx * dx + dy * dy < chip_r * chip_r:
                                py, px = chip_y + dy, chip_x + dx
                                if 0 <= py < height and 0 <= px < width:
                                    disp[py, px] *= 0.7

            x += brick_w_px + mortar_w

        y = brick_y_end
        row += 1

    return np.clip(disp, 0, 1)


def generate_stone_displacement(
    width: int = 1024,
    height: int = 1024,
    *,
    block_size: int = 120,
    joint_depth: float = 0.6,
    erosion: float = 0.2,
    seed: int = 42,
) -> "np.ndarray":
    """Generate a cut stone wall displacement map with erosion."""
    rng = np.random.RandomState(seed)
    disp = np.ones((height, width), dtype=np.float32)
    joint_w = max(3, block_size // 20)

    for y in range(0, height, block_size + joint_w):
        # Horizontal joint
        disp[y:min(y + joint_w, height), :] = 1.0 - joint_depth
        offset = (block_size // 2) * ((y // (block_size + joint_w)) % 2)

        for x in range(-offset, width, block_size + joint_w):
            # Vertical joint
            jx = x + block_size
            if 0 <= jx < width:
                disp[:, max(0, jx):min(width, jx + joint_w)] = 1.0 - joint_depth

            # Stone face with gentle erosion
            sx = max(0, x + joint_w)
            ex = min(width, jx)
            sy = y + joint_w
            ey = min(height, y + block_size)
            if sx < ex and sy < ey:
                face = rng.random((ey - sy, ex - sx)).astype(np.float32)
                face = face * erosion + (1.0 - erosion * 0.5)
                disp[sy:ey, sx:ex] = face

    return np.clip(disp, 0, 1)


def generate_wood_displacement(
    width: int = 1024,
    height: int = 1024,
    *,
    board_width: int = 80,
    grain_depth: float = 0.15,
    seed: int = 42,
) -> "np.ndarray":
    """Generate wood clapboard/siding displacement map."""
    rng = np.random.RandomState(seed)
    disp = np.ones((height, width), dtype=np.float32)

    y = 0
    while y < height:
        # Board overlap shadow
        overlap = min(8, board_width // 10)
        disp[y:min(y + overlap, height), :] = 0.7

        # Wood grain (horizontal lines)
        board_end = min(y + board_width, height)
        for row in range(y + overlap, board_end):
            grain = 1.0 - rng.random() * grain_depth
            disp[row, :] = grain + rng.random(width).astype(np.float32) * 0.02

        y += board_width

    return np.clip(disp, 0, 1)


def generate_displacement_map(
    material: str,
    output_dir: Path,
    *,
    width: int = 1024,
    height: int = 1024,
    bond: str = "running",
    seed: int = 42,
) -> dict:
    """Generate displacement map for a material type."""
    if np is None or Image is None:
        return {"status": "requires_numpy_pillow"}

    output_dir.mkdir(parents=True, exist_ok=True)
    material_lower = material.lower()

    if "brick" in material_lower:
        disp = generate_brick_displacement(width, height, bond=bond, seed=seed)
    elif "stone" in material_lower:
        disp = generate_stone_displacement(width, height, seed=seed)
    elif "wood" in material_lower or "clapboard" in material_lower:
        disp = generate_wood_displacement(width, height, seed=seed)
    else:
        # Generic subtle noise
        disp = np.random.RandomState(seed).random((height, width)).astype(np.float32)
        disp = disp * 0.1 + 0.9

    filename = f"displacement_{material_lower}_{bond}_{width}x{height}.png"
    path = output_dir / filename
    img = Image.fromarray((disp * 255).astype(np.uint8), mode="L")
    img.save(path)

    return {
        "status": "generated",
        "material": material,
        "bond": bond,
        "resolution": [width, height],
        "path": str(path),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate displacement maps")
    parser.add_argument("--material", type=str, default="brick")
    parser.add_argument("--bond", type=str, default="running")
    parser.add_argument("--output", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--scale", type=int, default=1024, help="Resolution")
    parser.add_argument("--batch", action="store_true", help="Generate all material types")
    parser.add_argument("--params", type=Path, default=None)
    args = parser.parse_args()

    if args.batch:
        materials = ["brick", "stone", "wood"]
        bonds = {"brick": ["running", "flemish", "stack"], "stone": ["ashlar"], "wood": ["lap"]}
        for mat in materials:
            for bond in bonds.get(mat, ["default"]):
                result = generate_displacement_map(
                    mat, args.output, width=args.scale, height=args.scale, bond=bond,
                )
                print(f"  {mat}/{bond}: {result['status']} → {result.get('path', 'N/A')}")
    else:
        result = generate_displacement_map(
            args.material, args.output,
            width=args.scale, height=args.scale, bond=args.bond,
        )
        print(f"{result['material']}: {result['status']} → {result.get('path', 'N/A')}")


if __name__ == "__main__":
    main()
