#!/usr/bin/env python3
"""Stage 3 — ENRICH: Fuse iPad LiDAR scan data into building params.

Reads per-building LiDAR clips (.laz/.las/.ply) and extracts precise
dimensions (height, width, depth, point density) to merge into params.

Extraction pipeline:
  1. Parse point cloud header or load points
  2. Compute bounding box → height/width/depth in metres
  3. Compute point density → quality indicator
  4. Compare with existing params dimensions (LiDAR vs city_data)
  5. Merge into params with provenance tracking

Usage:
    python scripts/enrich/fuse_lidar.py --lidar data/lidar/building/ --params params/
    python scripts/enrich/fuse_lidar.py --lidar data/lidar/building/ --params params/ --dry-run
"""

import argparse
import json
import struct
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_LIDAR = REPO_ROOT / "data" / "lidar" / "building"
DEFAULT_PARAMS = REPO_ROOT / "params"

LIDAR_EXTENSIONS = {".laz", ".las", ".ply"}


def discover_lidar_files(lidar_dir: Path) -> dict[str, Path]:
    """Map address stems to LiDAR files."""
    files = {}
    for f in lidar_dir.rglob("*"):
        if f.suffix.lower() in LIDAR_EXTENSIONS:
            files[f.stem] = f
    return files


def parse_las_header(las_path: Path) -> dict:
    """Parse a LAS/LAZ file header to extract bbox and point count.

    Reads the first 375 bytes of the LAS 1.2+ header which contains:
    - Point count (offset 107, uint32 for LAS 1.2; offset 247 uint64 for 1.4)
    - Bounding box (offset 179, 6x float64: xmax,xmin,ymax,ymin,zmax,zmin)
    - Scale factors and offsets (for coordinate conversion)
    """
    result = {"format": las_path.suffix.lower(), "path": str(las_path)}

    try:
        with open(las_path, "rb") as f:
            header = f.read(375)

        if len(header) < 235:
            result["status"] = "header_too_short"
            return result

        # File signature
        sig = header[0:4]
        if sig != b"LASF":
            result["status"] = "not_las_format"
            return result

        # Version
        major = header[24]
        minor = header[25]
        result["version"] = f"{major}.{minor}"

        # Point count (LAS 1.2: uint32 at offset 107)
        point_count = struct.unpack_from("<I", header, 107)[0]
        result["point_count"] = point_count

        # Scale and offset (offset 131: 3x float64 scale, 3x float64 offset)
        x_scale, y_scale, z_scale = struct.unpack_from("<3d", header, 131)
        x_offset, y_offset, z_offset = struct.unpack_from("<3d", header, 155)

        # Bounding box (offset 179: xmax, xmin, ymax, ymin, zmax, zmin as float64)
        xmax, xmin, ymax, ymin, zmax, zmin = struct.unpack_from("<6d", header, 179)

        result["bbox"] = {
            "x_min": xmin, "x_max": xmax,
            "y_min": ymin, "y_max": ymax,
            "z_min": zmin, "z_max": zmax,
        }
        result["dimensions_m"] = {
            "width": round(xmax - xmin, 3),
            "depth": round(ymax - ymin, 3),
            "height": round(zmax - zmin, 3),
        }
        result["scale"] = [x_scale, y_scale, z_scale]
        result["offset"] = [x_offset, y_offset, z_offset]

        # Point density (points per cubic metre)
        volume = (xmax - xmin) * (ymax - ymin) * (zmax - zmin)
        if volume > 0:
            result["density_pts_per_m3"] = round(point_count / volume, 1)

        result["status"] = "parsed"

    except Exception as e:
        result["status"] = "parse_error"
        result["error"] = str(e)

    return result


def parse_ply_header(ply_path: Path) -> dict:
    """Parse a PLY file header for vertex count and bounding box estimate."""
    result = {"format": ".ply", "path": str(ply_path)}

    try:
        vertex_count = 0
        with open(ply_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                if line.startswith("element vertex"):
                    vertex_count = int(line.split()[-1])
                if line.strip() == "end_header":
                    break

        result["point_count"] = vertex_count
        result["status"] = "parsed"

    except Exception as e:
        result["status"] = "parse_error"
        result["error"] = str(e)

    return result


def extract_lidar_dims(lidar_path: Path) -> dict:
    """Extract dimensions from a LiDAR point cloud."""
    ext = lidar_path.suffix.lower()
    if ext in (".las", ".laz"):
        return parse_las_header(lidar_path)
    elif ext == ".ply":
        return parse_ply_header(lidar_path)
    return {"status": "unsupported_format", "format": ext}


def fuse_lidar(
    lidar_dir: Path, params_dir: Path, *, dry_run: bool = False
) -> dict:
    """Fuse LiDAR data into params files."""
    lidar_files = discover_lidar_files(lidar_dir)
    stats = {"fused": 0, "no_match": 0, "errors": 0, "details": []}

    for param_file in sorted(params_dir.glob("*.json")):
        if param_file.name.startswith("_"):
            continue
        data = json.loads(param_file.read_text(encoding="utf-8"))
        if data.get("skipped"):
            continue

        stem = param_file.stem
        lidar_path = lidar_files.get(stem)
        if lidar_path is None:
            stats["no_match"] += 1
            continue

        try:
            lidar_data = extract_lidar_dims(lidar_path)

            if lidar_data.get("status") != "parsed":
                stats["errors"] += 1
                stats["details"].append({
                    "address": stem, "error": lidar_data.get("status"),
                })
                continue

            if dry_run:
                stats["fused"] += 1
                dims = lidar_data.get("dimensions_m", {})
                stats["details"].append({
                    "address": stem,
                    "height": dims.get("height"),
                    "width": dims.get("width"),
                    "points": lidar_data.get("point_count"),
                })
                continue

            # Merge into params
            data["lidar_analysis"] = {
                "point_count": lidar_data.get("point_count", 0),
                "dimensions_m": lidar_data.get("dimensions_m", {}),
                "density_pts_per_m3": lidar_data.get("density_pts_per_m3"),
                "bbox": lidar_data.get("bbox"),
                "source_file": str(lidar_path),
            }

            # Cross-reference with existing height data
            existing_h = data.get("total_height_m", 0)
            lidar_h = lidar_data.get("dimensions_m", {}).get("height", 0)
            if lidar_h > 0 and existing_h > 0:
                discrepancy = abs(lidar_h - existing_h)
                data["lidar_analysis"]["height_discrepancy_m"] = round(discrepancy, 2)
                if discrepancy > 2.0:
                    data["lidar_analysis"]["height_warning"] = (
                        f"LiDAR height ({lidar_h:.1f}m) differs from params "
                        f"({existing_h:.1f}m) by {discrepancy:.1f}m"
                    )

            meta = data.setdefault("_meta", {})
            fusion = meta.setdefault("fusion_applied", [])
            if "lidar" not in fusion:
                fusion.append("lidar")

            param_file.write_text(
                json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            stats["fused"] += 1

        except Exception as e:
            stats["errors"] += 1
            stats["details"].append({"address": stem, "error": str(e)})

    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Fuse LiDAR data into params")
    parser.add_argument("--lidar", type=Path, default=DEFAULT_LIDAR)
    parser.add_argument("--params", type=Path, default=DEFAULT_PARAMS)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not args.lidar.is_dir():
        print(f"[ERROR] LiDAR directory not found: {args.lidar}")
        sys.exit(1)

    stats = fuse_lidar(args.lidar, args.params, dry_run=args.dry_run)
    prefix = "[DRY RUN] " if args.dry_run else ""
    print(f"{prefix}LiDAR fusion: {stats['fused']} fused, "
          f"{stats['no_match']} unmatched, {stats['errors']} errors")

    if args.dry_run and stats["details"]:
        for d in stats["details"][:10]:
            print(f"  {d['address']}: h={d.get('height')}m, w={d.get('width')}m, "
                  f"pts={d.get('points')}")


if __name__ == "__main__":
    main()
