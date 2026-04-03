#!/usr/bin/env python3
"""Stage 2 — RECONSTRUCT: Extract architectural elements from per-building meshes.

Uses segmentation masks to identify bounding regions of architectural
elements (windows, doors, cornices, brackets, etc.) in photogrammetric
meshes and extracts them as individual mesh files for the scanned element
library.

Element extraction pipeline:
1. Load per-building mesh + corresponding segmentation masks
2. Project 2D segmentation bboxes into 3D mesh space
3. Extract sub-meshes within each element's bounding volume
4. Classify by element type and save to assets/elements/

Usage:
    python scripts/reconstruct/extract_elements.py --meshes meshes/per_building/ --segmentation segmentation/
    python scripts/reconstruct/extract_elements.py --mesh meshes/per_building/22_Lippincott_St.obj --segmentation segmentation/
    python scripts/reconstruct/extract_elements.py --meshes meshes/per_building/ --segmentation segmentation/ --dry-run
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_MESHES = REPO_ROOT / "meshes" / "per_building"
DEFAULT_SEG = REPO_ROOT / "segmentation"
DEFAULT_OUTPUT = REPO_ROOT / "assets" / "elements"

ELEMENT_TYPES = {
    "window", "door", "cornice", "bracket", "voussoir",
    "lintel", "sill", "column", "baluster", "finial",
    "quoin", "keystone", "pilaster", "string_course",
    "bay_window", "dormer", "chimney",
}


def load_segmentation_for_building(address: str, seg_dir: Path) -> list[dict]:
    """Load detected elements from segmentation output for a building.

    Returns list of element dicts with bbox, class, confidence.
    """
    safe_name = address.replace(" ", "_").replace(",", "")
    elements = []

    # Check direct match
    building_seg = seg_dir / safe_name
    if not building_seg.is_dir():
        # Try fuzzy match on photo stems
        for d in seg_dir.iterdir():
            if d.is_dir() and safe_name.lower() in d.name.lower():
                building_seg = d
                break

    elements_file = building_seg / "elements.json" if building_seg.is_dir() else None
    if elements_file and elements_file.exists():
        data = json.loads(elements_file.read_text(encoding="utf-8"))
        for det in data.get("detections", []):
            elements.append({
                "class": det.get("class", "unknown"),
                "confidence": det.get("confidence", 0),
                "bbox_2d": det.get("bbox", []),
                "image_size": data.get("image_size", []),
            })

    return elements


def project_bbox_to_3d(
    bbox_2d: list,
    image_size: list,
    mesh_bbox: dict,
) -> dict | None:
    """Project a 2D segmentation bbox into 3D mesh space.

    Uses simple proportional mapping from image coordinates to mesh
    bounding box. More accurate projection requires camera intrinsics
    (available from COLMAP).
    """
    if not bbox_2d or len(bbox_2d) != 4 or not image_size or len(image_size) != 2:
        return None

    img_w, img_h = image_size
    if img_w == 0 or img_h == 0:
        return None

    x1, y1, x2, y2 = bbox_2d

    # Normalize to [0, 1]
    nx1, nx2 = x1 / img_w, x2 / img_w
    ny1, ny2 = y1 / img_h, y2 / img_h

    # Map to mesh bbox (X = width, Z = height for front facade)
    mesh_x_min = mesh_bbox.get("x_min", 0)
    mesh_x_max = mesh_bbox.get("x_max", 1)
    mesh_z_min = mesh_bbox.get("z_min", 0)
    mesh_z_max = mesh_bbox.get("z_max", 1)

    width = mesh_x_max - mesh_x_min
    height = mesh_z_max - mesh_z_min

    return {
        "x_min": mesh_x_min + nx1 * width,
        "x_max": mesh_x_min + nx2 * width,
        "z_min": mesh_z_max - ny2 * height,  # image Y is inverted vs Z
        "z_max": mesh_z_max - ny1 * height,
    }


def extract_submesh_by_bbox(
    mesh_path: Path,
    bbox_3d: dict,
    output_path: Path,
) -> dict:
    """Extract vertices within a 3D bounding box from a mesh.

    Supports OBJ and PLY formats.
    """
    try:
        import trimesh
        mesh = trimesh.load(str(mesh_path))
        vertices = mesh.vertices

        # Filter vertices inside bbox
        mask = (
            (vertices[:, 0] >= bbox_3d["x_min"]) &
            (vertices[:, 0] <= bbox_3d["x_max"]) &
            (vertices[:, 2] >= bbox_3d["z_min"]) &
            (vertices[:, 2] <= bbox_3d["z_max"])
        )

        if mask.sum() < 4:
            return {"status": "too_few_vertices", "count": int(mask.sum())}

        # Extract faces that have all vertices in bbox
        face_mask = mask[mesh.faces].all(axis=1)
        sub = mesh.submesh([face_mask.nonzero()[0]], append=True)
        sub.export(str(output_path))

        return {
            "status": "extracted",
            "vertices": int(mask.sum()),
            "faces": int(face_mask.sum()),
        }
    except ImportError:
        return {"status": "requires_trimesh"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def extract_from_building(
    mesh_path: Path,
    seg_dir: Path,
    output_dir: Path,
    *,
    dry_run: bool = False,
) -> dict:
    """Extract all detected elements from a single building mesh."""
    stem = mesh_path.stem
    address = stem.replace("_", " ")
    building_output = output_dir / "by_building" / stem

    elements = load_segmentation_for_building(address, seg_dir)

    result = {
        "address": address,
        "mesh": str(mesh_path),
        "elements_detected": len(elements),
        "elements_extracted": 0,
        "catalog": [],
    }

    if not elements:
        result["status"] = "no_segmentation"
        return result

    if dry_run:
        result["status"] = "would_extract"
        for e in elements:
            result["catalog"].append({
                "class": e["class"],
                "confidence": e["confidence"],
                "status": "would_extract",
            })
        return result

    building_output.mkdir(parents=True, exist_ok=True)

    # Get mesh bounding box
    try:
        lines = mesh_path.read_text(encoding="utf-8", errors="replace").splitlines()
        xs, zs = [], []
        for line in lines:
            if line.startswith("v "):
                parts = line.split()
                xs.append(float(parts[1]))
                zs.append(float(parts[3]))
        mesh_bbox = {
            "x_min": min(xs) if xs else 0,
            "x_max": max(xs) if xs else 1,
            "z_min": min(zs) if zs else 0,
            "z_max": max(zs) if zs else 1,
        }
    except Exception:
        mesh_bbox = {"x_min": 0, "x_max": 1, "z_min": 0, "z_max": 1}

    for i, elem in enumerate(elements):
        bbox_3d = project_bbox_to_3d(
            elem.get("bbox_2d", []),
            elem.get("image_size", []),
            mesh_bbox,
        )

        entry = {
            "class": elem["class"],
            "confidence": elem["confidence"],
            "index": i,
        }

        if bbox_3d is None:
            entry["status"] = "invalid_bbox"
        else:
            etype = elem["class"].replace(" ", "_")
            output_path = building_output / f"{etype}_{i:03d}.obj"
            extract_result = extract_submesh_by_bbox(mesh_path, bbox_3d, output_path)
            entry.update(extract_result)
            if extract_result.get("status") == "extracted":
                result["elements_extracted"] += 1
                entry["output"] = str(output_path)

                # Also copy to by_type directory for the element library
                type_dir = output_dir / "by_type" / etype
                type_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(output_path, type_dir / f"{stem}_{i:03d}.obj")

        result["catalog"].append(entry)

    result["status"] = "processed"

    # Write catalog
    (building_output / "catalog.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    return result


def main() -> None:
    import shutil

    parser = argparse.ArgumentParser(description="Extract architectural elements from meshes")
    parser.add_argument("--meshes", type=Path, default=DEFAULT_MESHES)
    parser.add_argument("--mesh", type=Path, default=None, help="Single mesh file")
    parser.add_argument("--segmentation", type=Path, default=DEFAULT_SEG)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.mesh:
        result = extract_from_building(
            args.mesh, args.segmentation, args.output, dry_run=args.dry_run,
        )
        print(f"{result['address']}: {result['status']} "
              f"({result['elements_extracted']}/{result['elements_detected']} elements)")
        return

    if not args.meshes.is_dir():
        print(f"[ERROR] Meshes directory not found: {args.meshes}")
        sys.exit(1)

    meshes = sorted(
        p for p in args.meshes.glob("*")
        if p.suffix.lower() in {".obj", ".ply", ".stl"}
    )

    prefix = "[DRY RUN] " if args.dry_run else ""
    total_extracted = 0
    for mesh in meshes:
        result = extract_from_building(
            mesh, args.segmentation, args.output, dry_run=args.dry_run,
        )
        total_extracted += result.get("elements_extracted", 0)

    print(f"{prefix}Processed {len(meshes)} meshes, extracted {total_extracted} elements")


if __name__ == "__main__":
    main()
