#!/usr/bin/env python3
"""
Automates COLMAP → OpenMVS photogrammetry pipeline for building-by-building reconstruction.

Processes geotagged field photos from PHOTOS_KENSINGTON/ into dense 3D models.
Creates per-building directories in outputs/photogrammetry/<safe_address>/,
runs COLMAP sparse reconstruction, then densifies + meshes + textures via OpenMVS.

Logs results to outputs/photogrammetry/manifest.json with per-building metadata:
address, photo_count, steps_completed, output_files, status, duration_s, timestamp.

CLI flags:
  --address "Toronto Fire Station 315"  — single building (spaces → underscores in path)
  --all                                 — all buildings with 10+ photos
  --colmap-path PATH                    — override COLMAP.bat location
  --openmvs-path PATH                   — override OpenMVS tool dir
  --quality low|medium|high             — COLMAP quality (default: medium)
  --dry-run                             — print commands without executing
  --skip-existing                       — skip addresses with status "success" in manifest

Example:
  python scripts/run_photogrammetry_batch.py --address "22 Lippincott St"
  python scripts/run_photogrammetry_batch.py --all --quality high --skip-existing
"""

import argparse
import csv
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# Default tool paths (Windows)
DEFAULT_COLMAP_PATH = Path("C:/Tools/COLMAP/COLMAP.bat")
DEFAULT_OPENMVS_PATH = Path("C:/Tools/OpenMVS")

# Project root directories
PROJECT_ROOT = Path(__file__).parent.parent
PHOTOS_DIR = PROJECT_ROOT / "PHOTOS KENSINGTON"
PHOTO_CSV = PHOTOS_DIR / "csv" / "photo_address_index.csv"
OUTPUT_DIR = PROJECT_ROOT / "outputs" / "photogrammetry"
MANIFEST_PATH = OUTPUT_DIR / "manifest.json"


def load_photo_index() -> Dict[str, List[Path]]:
    """
    Read photo_address_index.csv and return dict mapping addresses to photo paths.
    CSV columns: filename, address_or_location, source
    """
    photo_map: Dict[str, List[Path]] = {}

    if not PHOTO_CSV.exists():
        raise FileNotFoundError(f"Photo index not found: {PHOTO_CSV}")

    with open(PHOTO_CSV, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            filename = row.get("filename", "").strip()
            address = row.get("address_or_location", "").strip()

            if not filename or not address:
                continue

            photo_path = PHOTOS_DIR / filename
            if not photo_path.exists():
                continue

            if address not in photo_map:
                photo_map[address] = []
            photo_map[address].append(photo_path)

    return photo_map


def load_manifest() -> Dict[str, Any]:
    """Load existing manifest.json or return empty dict."""
    if MANIFEST_PATH.exists():
        with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"buildings": {}}


def save_manifest(manifest: Dict[str, Any]) -> None:
    """Save manifest.json."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)


def safe_address(address: str) -> str:
    """Convert address to safe filename (spaces → underscores)."""
    return address.replace(" ", "_").replace("/", "_").replace(":", "_")


def copy_images(
    image_paths: List[Path],
    dest_dir: Path,
    dry_run: bool = False,
) -> int:
    """
    Copy (or symlink on Windows, copy on other OS) photos to a temp directory.
    Returns count of copied images.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    count = 0

    for src in image_paths:
        if not src.exists():
            print(f"  Warning: source photo not found: {src}")
            continue

        dst = dest_dir / src.name
        if dst.exists():
            print(f"  Skipping existing: {dst.name}")
            continue

        if dry_run:
            print(f"  [DRY] Copy {src.name} → {dest_dir}")
        else:
            try:
                # Copy file
                dst.write_bytes(src.read_bytes())
                count += 1
            except Exception as e:
                print(f"  Error copying {src.name}: {e}")

    return count


def run_colmap(
    image_dir: Path,
    workspace_dir: Path,
    colmap_path: Path,
    quality: str = "medium",
    dry_run: bool = False,
) -> Tuple[bool, str]:
    """
    Run COLMAP automatic_reconstructor.
    Returns (success, error_message).
    """
    quality_map = {
        "low": 1,
        "medium": 2,
        "high": 3,
    }
    quality_level = quality_map.get(quality, 2)

    database_path = workspace_dir / "database.db"
    sparse_dir = workspace_dir / "sparse"
    sparse_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        str(colmap_path),
        "automatic_reconstructor",
        f"--image_path={image_dir}",
        f"--workspace_path={workspace_dir}",
        f"--quality={quality_level}",
        "--use_gpu=1",
    ]

    print(f"\n  Step 1: COLMAP automatic_reconstructor (quality={quality})")
    if dry_run:
        print(f"  [DRY] {' '.join(cmd)}")
        return True, ""

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
        if result.returncode != 0:
            return False, f"COLMAP failed: {result.stderr}"
        return True, ""
    except subprocess.TimeoutExpired:
        return False, "COLMAP timeout (1h exceeded)"
    except Exception as e:
        return False, f"COLMAP exception: {e}"


def run_openmvs_interface(
    workspace_dir: Path,
    openmvs_path: Path,
    dry_run: bool = False,
) -> Tuple[bool, str]:
    """
    Run InterfaceCOLMAP to convert COLMAP sparse to MVS format.
    Returns (success, error_message).
    """
    sparse_dir = workspace_dir / "sparse"
    mvs_scene = workspace_dir / "scene.mvs"

    interface_exe = openmvs_path / "InterfaceCOLMAP.exe"
    if not interface_exe.exists() and not dry_run:
        return False, f"InterfaceCOLMAP.exe not found: {interface_exe}"

    cmd = [
        str(interface_exe),
        str(sparse_dir),
        f"--output-file={mvs_scene}",
    ]

    print(f"  Step 2: InterfaceCOLMAP (COLMAP → MVS)")
    if dry_run:
        print(f"  [DRY] {' '.join(cmd)}")
        return True, ""

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if result.returncode != 0:
            return False, f"InterfaceCOLMAP failed: {result.stderr}"
        if not mvs_scene.exists():
            return False, f"Output scene not created: {mvs_scene}"
        return True, ""
    except subprocess.TimeoutExpired:
        return False, "InterfaceCOLMAP timeout (10m exceeded)"
    except Exception as e:
        return False, f"InterfaceCOLMAP exception: {e}"


def run_openmvs_densify(
    workspace_dir: Path,
    openmvs_path: Path,
    dry_run: bool = False,
) -> Tuple[bool, str]:
    """
    Run DensifyPointCloud on MVS scene.
    Returns (success, error_message).
    """
    mvs_scene = workspace_dir / "scene.mvs"
    densified_scene = workspace_dir / "scene_dense.mvs"

    densify_exe = openmvs_path / "DensifyPointCloud.exe"
    if not densify_exe.exists() and not dry_run:
        return False, f"DensifyPointCloud.exe not found: {densify_exe}"

    cmd = [
        str(densify_exe),
        str(mvs_scene),
        f"--output-file={densified_scene}",
        "--number-views=3",
    ]

    print(f"  Step 3: DensifyPointCloud")
    if dry_run:
        print(f"  [DRY] {' '.join(cmd)}")
        return True, ""

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
        if result.returncode != 0:
            return False, f"DensifyPointCloud failed: {result.stderr}"
        if not densified_scene.exists():
            return False, f"Densified scene not created: {densified_scene}"
        return True, ""
    except subprocess.TimeoutExpired:
        return False, "DensifyPointCloud timeout (30m exceeded)"
    except Exception as e:
        return False, f"DensifyPointCloud exception: {e}"


def run_openmvs_reconstruct(
    workspace_dir: Path,
    openmvs_path: Path,
    dry_run: bool = False,
) -> Tuple[bool, str]:
    """
    Run ReconstructMesh on densified point cloud.
    Returns (success, error_message).
    """
    densified_scene = workspace_dir / "scene_dense.mvs"
    mesh_scene = workspace_dir / "scene_mesh.mvs"

    reconstruct_exe = openmvs_path / "ReconstructMesh.exe"
    if not reconstruct_exe.exists() and not dry_run:
        return False, f"ReconstructMesh.exe not found: {reconstruct_exe}"

    cmd = [
        str(reconstruct_exe),
        str(densified_scene),
        f"--output-file={mesh_scene}",
        "--smooth=1",
    ]

    print(f"  Step 4: ReconstructMesh")
    if dry_run:
        print(f"  [DRY] {' '.join(cmd)}")
        return True, ""

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
        if result.returncode != 0:
            return False, f"ReconstructMesh failed: {result.stderr}"
        if not mesh_scene.exists():
            return False, f"Mesh scene not created: {mesh_scene}"
        return True, ""
    except subprocess.TimeoutExpired:
        return False, "ReconstructMesh timeout (30m exceeded)"
    except Exception as e:
        return False, f"ReconstructMesh exception: {e}"


def run_openmvs_texture(
    workspace_dir: Path,
    openmvs_path: Path,
    dry_run: bool = False,
) -> Tuple[bool, str]:
    """
    Run TextureMesh on reconstructed mesh.
    Returns (success, error_message).
    """
    mesh_scene = workspace_dir / "scene_mesh.mvs"
    textured_scene = workspace_dir / "scene_textured.mvs"

    texture_exe = openmvs_path / "TextureMesh.exe"
    if not texture_exe.exists() and not dry_run:
        return False, f"TextureMesh.exe not found: {texture_exe}"

    cmd = [
        str(texture_exe),
        str(mesh_scene),
        f"--output-file={textured_scene}",
        "--export-type=ply",
    ]

    print(f"  Step 5: TextureMesh")
    if dry_run:
        print(f"  [DRY] {' '.join(cmd)}")
        return True, ""

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=1200)
        if result.returncode != 0:
            return False, f"TextureMesh failed: {result.stderr}"
        return True, ""
    except subprocess.TimeoutExpired:
        return False, "TextureMesh timeout (20m exceeded)"
    except Exception as e:
        return False, f"TextureMesh exception: {e}"


def collect_output_files(workspace_dir: Path) -> Dict[str, str]:
    """
    Collect final output files from workspace.
    Returns dict mapping output type to absolute path.
    """
    outputs = {}

    # Key output files
    candidate_files = {
        "sparse_ply": workspace_dir / "sparse" / "points3D.ply",
        "dense_ply": workspace_dir / "scene_dense.ply",
        "mesh_ply": workspace_dir / "scene_mesh.ply",
        "textured_mesh": workspace_dir / "scene_textured.ply",
        "mvs_scene": workspace_dir / "scene.mvs",
        "dense_scene": workspace_dir / "scene_dense.mvs",
        "mesh_scene": workspace_dir / "scene_mesh.mvs",
        "textured_scene": workspace_dir / "scene_textured.mvs",
    }

    for key, path in candidate_files.items():
        if path.exists():
            outputs[key] = str(path.resolve())

    return outputs


def process_address(
    address: str,
    image_paths: List[Path],
    colmap_path: Path,
    openmvs_path: Path,
    quality: str = "medium",
    dry_run: bool = False,
) -> Dict[str, Any]:
    """
    Process a single address through the photogrammetry pipeline.
    Returns result dict with status, steps_completed, output_files, etc.
    """
    start_time = time.time()
    safe_addr = safe_address(address)
    workspace_dir = OUTPUT_DIR / safe_addr
    images_dir = workspace_dir / "images"

    result = {
        "address": address,
        "photo_count": len(image_paths),
        "steps_completed": [],
        "output_files": {},
        "status": "pending",
        "errors": [],
        "duration_s": 0,
        "timestamp": datetime.now().isoformat(),
    }

    print(f"\n{'='*70}")
    print(f"Processing: {address}")
    print(f"Photos: {len(image_paths)}")
    print(f"Workspace: {workspace_dir}")
    print(f"{'='*70}")

    if not image_paths:
        result["status"] = "failed"
        result["errors"].append("No photos found for address")
        return result

    # Step 0: Copy images
    if not dry_run:
        print(f"\n  Step 0: Copying {len(image_paths)} photos...")
        copied = copy_images(image_paths, images_dir, dry_run=False)
        if copied == 0:
            result["status"] = "failed"
            result["errors"].append("Failed to copy any images")
            return result
    else:
        print(f"\n  Step 0: [DRY] Would copy {len(image_paths)} photos")

    # Step 1: COLMAP
    success, error = run_colmap(images_dir, workspace_dir, colmap_path, quality, dry_run)
    if success:
        result["steps_completed"].append("colmap")
    else:
        result["errors"].append(error)
        result["status"] = "partial" if result["steps_completed"] else "failed"
        result["duration_s"] = time.time() - start_time
        return result

    # Step 2: InterfaceCOLMAP
    success, error = run_openmvs_interface(workspace_dir, openmvs_path, dry_run)
    if success:
        result["steps_completed"].append("interface_colmap")
    else:
        result["errors"].append(error)
        result["status"] = "partial"
        result["duration_s"] = time.time() - start_time
        result["output_files"] = collect_output_files(workspace_dir)
        return result

    # Step 3: DensifyPointCloud
    success, error = run_openmvs_densify(workspace_dir, openmvs_path, dry_run)
    if success:
        result["steps_completed"].append("densify_point_cloud")
    else:
        result["errors"].append(error)
        result["status"] = "partial"
        result["duration_s"] = time.time() - start_time
        result["output_files"] = collect_output_files(workspace_dir)
        return result

    # Step 4: ReconstructMesh
    success, error = run_openmvs_reconstruct(workspace_dir, openmvs_path, dry_run)
    if success:
        result["steps_completed"].append("reconstruct_mesh")
    else:
        result["errors"].append(error)
        result["status"] = "partial"
        result["duration_s"] = time.time() - start_time
        result["output_files"] = collect_output_files(workspace_dir)
        return result

    # Step 5: TextureMesh
    success, error = run_openmvs_texture(workspace_dir, openmvs_path, dry_run)
    if success:
        result["steps_completed"].append("texture_mesh")
        result["status"] = "success"
    else:
        result["errors"].append(error)
        result["status"] = "partial"

    result["output_files"] = collect_output_files(workspace_dir)
    result["duration_s"] = time.time() - start_time

    if result["status"] == "success":
        print(f"\n  SUCCESS: All steps completed ({result['duration_s']:.1f}s)")
    elif result["status"] == "partial":
        print(
            f"\n  PARTIAL: {len(result['steps_completed'])} steps completed "
            f"({result['duration_s']:.1f}s)"
        )
        for error in result["errors"]:
            print(f"    Error: {error}")
    else:
        print(f"\n  FAILED: {result['errors'][0] if result['errors'] else 'Unknown error'}")

    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Automate COLMAP → OpenMVS photogrammetry reconstruction.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--address",
        type=str,
        help="Single building address (e.g., '22 Lippincott St')",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Process all buildings with 10+ photos",
    )
    parser.add_argument(
        "--colmap-path",
        type=Path,
        default=DEFAULT_COLMAP_PATH,
        help=f"Path to COLMAP.bat (default: {DEFAULT_COLMAP_PATH})",
    )
    parser.add_argument(
        "--openmvs-path",
        type=Path,
        default=DEFAULT_OPENMVS_PATH,
        help=f"Path to OpenMVS tool directory (default: {DEFAULT_OPENMVS_PATH})",
    )
    parser.add_argument(
        "--quality",
        choices=["low", "medium", "high"],
        default="medium",
        help="COLMAP quality level (default: medium)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print commands without executing",
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="Skip addresses with status 'success' in manifest",
    )

    args = parser.parse_args()

    # Validate input
    if not args.address and not args.all:
        parser.error("Specify --address or --all")
    if args.address and args.all:
        parser.error("Use either --address or --all, not both")

    # Load photo index
    print("Loading photo index...")
    try:
        photo_map = load_photo_index()
    except FileNotFoundError as e:
        print(f"Error: {e}")
        return 1

    print(f"Found {len(photo_map)} addresses with photos")

    # Determine addresses to process
    addresses_to_process: List[Tuple[str, List[Path]]] = []

    if args.address:
        if args.address not in photo_map:
            print(f"Error: No photos found for '{args.address}'")
            return 1
        addresses_to_process = [(args.address, photo_map[args.address])]

    elif args.all:
        # Filter to 10+ photos
        addresses_to_process = [
            (addr, paths)
            for addr, paths in photo_map.items()
            if len(paths) >= 10
        ]
        print(f"Found {len(addresses_to_process)} addresses with 10+ photos")

    # Load manifest for skip-existing check
    manifest = load_manifest()
    if args.skip_existing:
        filtered = []
        for addr, paths in addresses_to_process:
            safe_addr = safe_address(addr)
            if safe_addr in manifest.get("buildings", {}):
                entry = manifest["buildings"][safe_addr]
                if entry.get("status") == "success":
                    print(f"Skipping {addr} (already successful)")
                    continue
            filtered.append((addr, paths))
        addresses_to_process = filtered
        print(f"After skip-existing filter: {len(addresses_to_process)} addresses")

    if not addresses_to_process:
        print("No addresses to process")
        return 0

    # Process each address
    processed_count = 0
    for addr, image_paths in addresses_to_process:
        result = process_address(
            addr,
            image_paths,
            args.colmap_path,
            args.openmvs_path,
            quality=args.quality,
            dry_run=args.dry_run,
        )

        safe_addr = safe_address(addr)
        manifest.setdefault("buildings", {})[safe_addr] = result
        processed_count += 1

        if not args.dry_run:
            save_manifest(manifest)

    # Summary
    print(f"\n{'='*70}")
    print(f"Summary: Processed {processed_count} buildings")
    print(f"Manifest: {MANIFEST_PATH}")

    if not args.dry_run:
        # Count statuses
        statuses = {}
        for entry in manifest.get("buildings", {}).values():
            status = entry.get("status", "unknown")
            statuses[status] = statuses.get(status, 0) + 1
        print(f"Statuses: {statuses}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
