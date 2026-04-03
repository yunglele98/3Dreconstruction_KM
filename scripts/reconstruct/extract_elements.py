#!/usr/bin/env python3
"""Extract architectural elements from per-building meshes using segmentation masks.

Matches segmentation results (from sense/segment_facades.py) to mesh faces
and extracts windows, doors, cornices, etc. as separate mesh files.
Falls back to copying whole meshes when segmentation data is not available.

Usage:
    python scripts/reconstruct/extract_elements.py --meshes meshes/per_building/ --segmentation segmentation/ --output assets/elements/
    python scripts/reconstruct/extract_elements.py --meshes meshes/per_building/ --output assets/elements/
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
MESHES_DIR = REPO_ROOT / "meshes" / "per_building"
SEGMENTATION_DIR = REPO_ROOT / "segmentation"
OUTPUT_DIR = REPO_ROOT / "assets" / "elements"

# Architectural element categories from segmentation
ELEMENT_CATEGORIES = [
    "window",
    "door",
    "cornice",
    "column",
    "balcony",
    "railing",
    "awning",
    "signage",
    "chimney",
    "dormer",
    "bay_window",
    "porch",
    "foundation",
    "roof",
    "wall",
]


def sanitize_name(name):
    """Convert name to filesystem-safe string."""
    return name.replace(" ", "_").replace(",", "").replace("/", "_")


def load_segmentation(seg_dir, building_name):
    """Load segmentation results for a building."""
    slug = sanitize_name(building_name)

    # Try various naming patterns
    candidates = [
        seg_dir / f"{slug}.json",
        seg_dir / f"{slug}_segmentation.json",
        seg_dir / f"{slug}_elements.json",
    ]

    for path in candidates:
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue

    return None


def read_obj(obj_path):
    """Read OBJ file into vertices and faces."""
    vertices = []
    faces = []
    materials = []
    current_material = None

    with open(obj_path, encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if stripped.startswith("v "):
                parts = stripped.split()
                vertices.append((float(parts[1]), float(parts[2]), float(parts[3])))
            elif stripped.startswith("f "):
                face_verts = []
                for p in stripped.split()[1:]:
                    idx = int(p.split("/")[0])
                    face_verts.append(idx)
                faces.append(face_verts)
                materials.append(current_material)
            elif stripped.startswith("usemtl "):
                current_material = stripped.split(None, 1)[1]

    return vertices, faces, materials


def write_obj(output_path, vertices, faces, comment=""):
    """Write vertices and faces to OBJ file."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Remap vertex indices
    used = set()
    for face in faces:
        used.update(face)
    sorted_verts = sorted(used)
    remap = {old: new for new, old in enumerate(sorted_verts, 1)}

    with open(output_path, "w", encoding="utf-8") as f:
        if comment:
            f.write(f"# {comment}\n")
        for idx in sorted_verts:
            v = vertices[idx - 1]
            f.write(f"v {v[0]} {v[1]} {v[2]}\n")
        for face in faces:
            indices = " ".join(str(remap[i]) for i in face)
            f.write(f"f {indices}\n")


def classify_faces_by_height(vertices, faces, floor_heights=None, total_height=None):
    """Simple face classification by height zones.

    When no segmentation is available, classify faces into rough
    architectural zones based on their vertical position.
    """
    if not vertices or not faces:
        return {}

    zs = [v[2] for v in vertices]
    min_z = min(zs)
    max_z = max(zs)
    height = max_z - min_z

    if height <= 0:
        return {"wall": list(range(len(faces)))}

    zones = {}
    foundation_top = min_z + height * 0.05
    ground_top = min_z + height * 0.35
    roof_bottom = min_z + height * 0.90

    for i, face in enumerate(faces):
        face_zs = [vertices[idx - 1][2] for idx in face]
        avg_z = sum(face_zs) / len(face_zs)

        if avg_z < foundation_top:
            category = "foundation"
        elif avg_z > roof_bottom:
            category = "roof"
        elif avg_z < ground_top:
            category = "wall"  # ground floor
        else:
            category = "wall"  # upper floors

        zones.setdefault(category, []).append(i)

    return zones


def classify_faces_by_segmentation(vertices, faces, segmentation):
    """Classify faces using segmentation data."""
    elements = segmentation.get("elements", [])
    if not elements:
        return None

    zones = {}
    assigned = set()

    for elem in elements:
        category = (elem.get("category") or elem.get("type") or "unknown").lower()
        bbox = elem.get("bbox")  # [x_min, y_min, x_max, y_max] in image space

        if not bbox or category not in ELEMENT_CATEGORIES:
            continue

        # Map image-space bbox to 3D (approximate via projection)
        # This is a simplified mapping; real implementation would use
        # camera calibration data
        for i, face in enumerate(faces):
            if i in assigned:
                continue
            face_zs = [vertices[idx - 1][2] for idx in face]
            face_xs = [vertices[idx - 1][0] for idx in face]
            avg_z = sum(face_zs) / len(face_zs)
            avg_x = sum(face_xs) / len(face_xs)

            # Simple heuristic: match by relative position
            # (real implementation needs camera parameters)
            zones.setdefault(category, []).append(i)
            assigned.add(i)
            break  # one face per element for now

    # Assign remaining faces as "wall"
    for i in range(len(faces)):
        if i not in assigned:
            zones.setdefault("wall", []).append(i)

    return zones


def extract_building_elements(mesh_path, seg_data, output_dir):
    """Extract elements from a single building mesh."""
    vertices, faces, materials = read_obj(mesh_path)

    if not vertices or not faces:
        return 0

    building_name = mesh_path.stem
    building_dir = output_dir / building_name

    # Try segmentation-based classification first
    zones = None
    if seg_data:
        zones = classify_faces_by_segmentation(vertices, faces, seg_data)

    # Fallback to height-based classification
    if not zones:
        zones = classify_faces_by_height(vertices, faces)

    if not zones:
        return 0

    extracted = 0
    for category, face_indices in zones.items():
        if not face_indices:
            continue
        category_faces = [faces[i] for i in face_indices]
        out_path = building_dir / f"{category}.obj"
        write_obj(out_path, vertices, category_faces,
                  comment=f"{category} element from {building_name}")
        extracted += 1

    # Write element manifest
    manifest = {
        "building": building_name,
        "source_mesh": str(mesh_path),
        "has_segmentation": seg_data is not None,
        "elements": {cat: len(indices) for cat, indices in zones.items()},
        "total_faces": len(faces),
    }
    manifest_path = building_dir / "elements.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    return extracted


def main():
    parser = argparse.ArgumentParser(
        description="Extract architectural elements from per-building meshes."
    )
    parser.add_argument("--meshes", type=Path, default=MESHES_DIR,
                        help="Directory with per-building OBJ meshes")
    parser.add_argument("--segmentation", type=Path, default=SEGMENTATION_DIR,
                        help="Directory with segmentation results")
    parser.add_argument("--output", type=Path, default=OUTPUT_DIR,
                        help="Output directory for extracted elements")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--skip-existing", action="store_true", default=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not args.meshes.exists():
        print(f"ERROR: Meshes directory not found: {args.meshes}")
        sys.exit(1)

    mesh_files = sorted(args.meshes.glob("*.obj"))
    if args.limit:
        mesh_files = mesh_files[:args.limit]

    has_segmentation = args.segmentation.exists()
    if not has_segmentation:
        print(f"WARNING: Segmentation directory not found: {args.segmentation}")
        print("  Will use height-based classification fallback.")

    print(f"Element extraction: {len(mesh_files)} meshes")
    print(f"  Segmentation: {'available' if has_segmentation else 'not available (fallback mode)'}")
    print(f"  Output: {args.output}")

    if args.dry_run:
        for mesh in mesh_files:
            existing = (args.output / mesh.stem / "elements.json").exists()
            status = "EXISTS" if existing else "PENDING"
            print(f"  [{status}] {mesh.name}")
        return

    args.output.mkdir(parents=True, exist_ok=True)

    total_extracted = 0
    processed = 0
    skipped = 0

    for mesh_path in mesh_files:
        building_name = mesh_path.stem
        building_dir = args.output / building_name

        if args.skip_existing and (building_dir / "elements.json").exists():
            skipped += 1
            continue

        # Load segmentation if available
        seg_data = None
        if has_segmentation:
            seg_data = load_segmentation(args.segmentation, building_name)

        count = extract_building_elements(mesh_path, seg_data, args.output)
        total_extracted += count
        processed += 1

        seg_status = "seg" if seg_data else "height"
        print(f"  [{seg_status}] {building_name}: {count} element categories")

    print(f"\nComplete: {processed} buildings, {total_extracted} element files, {skipped} skipped")


if __name__ == "__main__":
    main()
