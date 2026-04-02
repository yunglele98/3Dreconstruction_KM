#!/usr/bin/env python3
"""Upscale baked textures using RealESRGAN 4x.

Usage:
    python scripts/texture/upscale_textures.py --input textures/baked/ --output textures/upscaled/
    python scripts/texture/upscale_textures.py --input textures/baked/22_Lippincott.png
"""

from __future__ import annotations

import argparse
import subprocess
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
INPUT_DIR = REPO_ROOT / "textures" / "baked"
OUTPUT_DIR = REPO_ROOT / "textures" / "upscaled"


def find_realesrgan():
    """Locate RealESRGAN executable or Python module."""
    # CLI binary
    binary = shutil.which("realesrgan-ncnn-vulkan")
    if binary:
        return "binary", binary

    # Python module
    try:
        from realesrgan import RealESRGANer
        return "python", None
    except ImportError:
        pass

    return None, None


def upscale_with_binary(input_path, output_path, binary, scale=4):
    """Upscale using realesrgan-ncnn-vulkan CLI."""
    cmd = [
        binary,
        "-i", str(input_path),
        "-o", str(output_path),
        "-s", str(scale),
        "-n", "realesrgan-x4plus",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    return result.returncode == 0


def upscale_with_python(input_path, output_path, scale=4):
    """Upscale using RealESRGAN Python package."""
    import cv2
    import torch
    from basicsr.archs.rrdbnet_arch import RRDBNet
    from realesrgan import RealESRGANer

    model = RRDBNet(num_in_ch=3, num_out_ch=3, num_feat=64, num_block=23, num_grow_ch=32, scale=4)

    upsampler = RealESRGANer(
        scale=scale,
        model_path="https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth",
        model=model,
        tile=400,
        tile_pad=10,
        pre_pad=0,
        half=torch.cuda.is_available(),
    )

    img = cv2.imread(str(input_path), cv2.IMREAD_UNCHANGED)
    output, _ = upsampler.enhance(img, outscale=scale)
    cv2.imwrite(str(output_path), output)
    return True


def upscale_with_pil(input_path, output_path, scale=4):
    """Fallback: upscale using PIL Lanczos (no AI, just interpolation)."""
    from PIL import Image
    img = Image.open(input_path)
    w, h = img.size
    upscaled = img.resize((w * scale, h * scale), Image.LANCZOS)
    upscaled.save(output_path, quality=95)
    return True


def main():
    parser = argparse.ArgumentParser(description="Upscale textures with RealESRGAN.")
    parser.add_argument("--input", type=Path, default=INPUT_DIR)
    parser.add_argument("--output", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--scale", type=int, default=4, choices=[2, 4])
    parser.add_argument("--skip-existing", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)

    if args.input.is_file():
        textures = [args.input]
    else:
        textures = sorted(args.input.glob("*.png")) + sorted(args.input.glob("*.jpg"))

    if args.limit:
        textures = textures[:args.limit]

    if not textures:
        print(f"No textures found in {args.input}")
        return

    method, binary = find_realesrgan()
    if method == "binary":
        print(f"Using RealESRGAN CLI: {binary}")
        upscale_fn = lambda i, o: upscale_with_binary(i, o, binary, args.scale)
    elif method == "python":
        print("Using RealESRGAN Python")
        upscale_fn = lambda i, o: upscale_with_python(i, o, args.scale)
    else:
        print("RealESRGAN not found, using PIL Lanczos fallback")
        upscale_fn = lambda i, o: upscale_with_pil(i, o, args.scale)

    print(f"Upscaling {len(textures)} textures ({args.scale}x)")

    processed = 0
    for i, tex in enumerate(textures, 1):
        out = args.output / tex.name
        if args.skip_existing and out.exists():
            continue
        try:
            upscale_fn(tex, out)
            processed += 1
            if i % 20 == 0:
                print(f"  [{i}/{len(textures)}] {tex.stem}")
        except Exception as e:
            print(f"  [{i}] {tex.stem}: ERROR - {e}")

    print(f"\nDone: {processed} upscaled -> {args.output}")


if __name__ == "__main__":
    main()
