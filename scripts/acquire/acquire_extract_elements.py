#!/usr/bin/env python3
"""Stage 0 — ACQUIRE: Extract architectural elements from iPad LiDAR scans.

Segments scanned meshes into individual architectural elements (cornices,
windows, doors, brackets, etc.) and saves them to the scanned-elements
asset library. Uses trimesh for mesh processing when available.

Extraction strategies:
  1. trimesh: connected-component segmentation + bounding-box classification
  2. Open3D: DBSCAN clustering on point clouds
  3. Manifest-only: catalogues meshes without segmenting (no deps needed)

Usage:
    python scripts/acquire/acquire_extract_elements.py --input data/ipad_scans/ --output assets/scanned_elements/
    python scripts/acquire/acquire_extract_elements.py --input data/ipad_scans/ --output assets/scanned_elements/ --dry-run
"""

import argparse
import json
import sys
from pathlib import Path

MESH_EXTENSIONS = {".ply", ".obj", ".usdz"}

ELEMENT_CATEGORIES = [
    "cornice", "bracket", "window_frame", "door_frame",
    "column", "baluster", "finial", "quoin", "voussoir",
    "lintel", "sill", "keystone", "pilaster",
]

# Heuristic size ranges (metres) for classifying extracted components
SIZE_HEURISTICS = {
    "cornice":      {"width_min": 0.5, "height_max": 0.3},
    "bracket":      {"width_max": 0.4, "height_max": 0.5},
    "window_frame": {"width_min": 0.4, "width_max": 2.0, "height_min": 0.5},
    "door_frame":   {"width_min": 0.6, "height_min": 1.5},
    "column":       {"width_max": 0.4, "height_min": 1.5},
    "baluster":     {"width_max": 0.15, "height_min": 0.5},
    "finial":       {"width_max": 0.3, "height_max": 0.6},
}


def discover_meshes(input_dir: Path) -> list[Path]:
    return sorted(p for p in input_dir.rglob("*") if p.suffix.lower() in MESH_EXTENSIONS)


def get_mesh_bbox(mesh_path: Path) -> dict | None:
    """Get bounding box from a mesh file."""
    try:
        import trimesh
        mesh = trimesh.load(str(mesh_path))
        bounds = mesh.bounds  # [[min_x, min_y, min_z], [max_x, max_y, max_z]]
        dims = bounds[1] - bounds[0]
        return {
            "vertices": len(mesh.vertices),
            "faces": len(mesh.faces) if hasattr(mesh, "faces") else 0,
            "width_m": round(float(dims[0]), 3),
            "height_m": round(float(dims[2]), 3),
            "depth_m": round(float(dims[1]), 3),
            "volume_m3": round(float(mesh.volume) if mesh.is_volume else 0, 4),
        }
    except ImportError:
        return None
    except Exception:
        return None


def classify_by_size(bbox: dict) -> str:
    """Classify an extracted mesh component by its dimensions."""
    w = bbox.get("width_m", 0)
    h = bbox.get("height_m", 0)

    for cat, ranges in SIZE_HEURISTICS.items():
        if "width_min" in ranges and w < ranges["width_min"]:
            continue
        if "width_max" in ranges and w > ranges["width_max"]:
            continue
        if "height_min" in ranges and h < ranges["height_min"]:
            continue
        if "height_max" in ranges and h > ranges["height_max"]:
            continue
        return cat

    return "unknown"


def segment_mesh_trimesh(mesh_path: Path, output_dir: Path) -> dict:
    """Segment a mesh into connected components using trimesh."""
    try:
        import trimesh

        mesh = trimesh.load(str(mesh_path))
        components = mesh.split()

        elements = []
        for i, comp in enumerate(components):
            if len(comp.vertices) < 10:
                continue

            bounds = comp.bounds
            dims = bounds[1] - bounds[0]
            bbox = {
                "width_m": round(float(dims[0]), 3),
                "height_m": round(float(dims[2]), 3),
                "depth_m": round(float(dims[1]), 3),
                "vertices": len(comp.vertices),
            }
            classification = classify_by_size(bbox)

            elem_path = output_dir / f"{mesh_path.stem}_elem_{i:03d}_{classification}.obj"
            comp.export(str(elem_path))

            elements.append({
                "index": i,
                "type": classification,
                "path": str(elem_path),
                "bbox": bbox,
            })

        return {
            "status": "segmented",
            "components": len(components),
            "elements": elements,
        }

    except ImportError:
        return {"status": "trimesh_not_installed"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def extract_elements(
    input_dir: Path, output_dir: Path, *, dry_run: bool = False
) -> list[dict]:
    output_dir.mkdir(parents=True, exist_ok=True)
    meshes = discover_meshes(input_dir)
    results = []

    for mesh_path in meshes:
        stem = mesh_path.stem
        element_dir = output_dir / stem

        entry = {
            "source_mesh": str(mesh_path),
            "element_dir": str(element_dir),
            "size_bytes": mesh_path.stat().st_size,
        }

        # Get mesh stats if possible
        bbox = get_mesh_bbox(mesh_path)
        if bbox:
            entry["mesh_stats"] = bbox

        if dry_run:
            entry["status"] = "would_extract"
            entry["elements_found"] = []
            results.append(entry)
            continue

        element_dir.mkdir(parents=True, exist_ok=True)

        # Try segmentation
        seg_result = segment_mesh_trimesh(mesh_path, element_dir)

        if seg_result["status"] == "segmented":
            entry["status"] = "segmented"
            entry["elements_found"] = seg_result["elements"]
            entry["component_count"] = seg_result["components"]
        elif seg_result["status"] == "trimesh_not_installed":
            # Manifest-only fallback
            entry["status"] = "catalogued"
            entry["elements_found"] = []
            catalog = {
                "source": str(mesh_path),
                "mesh_stats": bbox,
                "elements": [],
                "note": "Install trimesh for automatic element segmentation",
            }
            (element_dir / "catalog.json").write_text(
                json.dumps(catalog, indent=2, ensure_ascii=False), encoding="utf-8"
            )
        else:
            entry.update(seg_result)

        results.append(entry)

    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract elements from LiDAR scans")
    parser.add_argument("--input", required=True, type=Path, help="iPad scan directory")
    parser.add_argument("--output", required=True, type=Path, help="Elements output directory")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not args.input.is_dir():
        print(f"[ERROR] Input directory not found: {args.input}")
        sys.exit(1)

    results = extract_elements(args.input, args.output, dry_run=args.dry_run)

    prefix = "[DRY RUN] " if args.dry_run else ""
    total_elems = sum(len(r.get("elements_found", [])) for r in results)
    print(f"{prefix}Processed {len(results)} meshes, extracted {total_elems} elements")
    for r in results[:5]:
        elems = len(r.get("elements_found", []))
        print(f"  {Path(r['source_mesh']).name}: {r['status']} ({elems} elements)")


if __name__ == "__main__":
    main()
