#!/usr/bin/env python3
"""Batch mesh repair and watertight triage for exported buildings.

Combines the work of TASK-20260329-901 (mesh triage) and
TASK-20260329-902 (103 Bellevue repair):
1. Scan all exported GLBs for validation issues
2. Rank by severity into auto-fix vs manual-review buckets
3. Apply automated repairs (degenerate faces, duplicates, holes)
4. Generate triage report

Usage:
    python scripts/batch_mesh_repair.py --exports-dir outputs/exports/
    python scripts/batch_mesh_repair.py --exports-dir outputs/exports/ --apply --fill-holes
    python scripts/batch_mesh_repair.py --exports-dir outputs/exports/ --top 20
    python scripts/batch_mesh_repair.py --exports-dir outputs/exports/ --address "103 Bellevue Ave"
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

try:
    import trimesh
    from trimesh import Trimesh
    HAS_TRIMESH = True
except ImportError:
    HAS_TRIMESH = False


@dataclass
class MeshIssue:
    address: str
    glb_path: str
    face_count: int
    vertex_count: int
    degenerate_faces: int
    duplicate_faces: int
    unreferenced_verts: int
    is_watertight: bool
    has_holes: bool
    severity_score: float
    likely_cause: str
    auto_fix_confidence: float
    suggested_fix: str
    bucket: str  # "auto_fix" or "manual_review"


def sanitize_address(address: str) -> str:
    safe = "".join(ch if (ch.isalnum() or ch == "-") else "_" for ch in address.strip())
    while "__" in safe:
        safe = safe.replace("__", "_")
    return safe.strip("_")


def diagnose_mesh(glb_path: Path) -> MeshIssue:
    """Analyze a single GLB mesh for issues."""
    address = glb_path.parent.name.replace("_", " ")

    loaded = trimesh.load(str(glb_path), process=False)

    # Combine scene to single mesh
    if isinstance(loaded, trimesh.Scene):
        meshes = [g for g in loaded.geometry.values() if isinstance(g, Trimesh)]
        if not meshes:
            return MeshIssue(
                address=address, glb_path=str(glb_path),
                face_count=0, vertex_count=0, degenerate_faces=0,
                duplicate_faces=0, unreferenced_verts=0,
                is_watertight=False, has_holes=True,
                severity_score=100.0, likely_cause="empty_scene",
                auto_fix_confidence=0.0, suggested_fix="Regenerate from params",
                bucket="manual_review",
            )
        mesh = trimesh.util.concatenate(meshes)
    else:
        mesh = loaded

    face_count = len(mesh.faces)
    vertex_count = len(mesh.vertices)

    # Count degenerate faces (area < 1e-10)
    if hasattr(mesh, "nondegenerate_faces"):
        nd_mask = mesh.nondegenerate_faces(height=1e-10)
        degenerate_faces = int((~nd_mask).sum())
    else:
        degenerate_faces = 0

    # Count duplicate faces
    if hasattr(mesh, "unique_faces"):
        uniq_mask = mesh.unique_faces()
        duplicate_faces = int((~uniq_mask).sum())
    else:
        duplicate_faces = 0

    # Unreferenced vertices
    referenced = set(mesh.faces.flatten())
    unreferenced_verts = vertex_count - len(referenced)

    is_watertight = bool(mesh.is_watertight)
    has_holes = not is_watertight

    # Severity scoring
    severity = 0.0
    if degenerate_faces > 0:
        severity += min(degenerate_faces * 5, 30)
    if duplicate_faces > 0:
        severity += min(duplicate_faces * 2, 15)
    if has_holes:
        severity += 25
    if unreferenced_verts > 50:
        severity += 10
    if face_count == 0:
        severity = 100

    # Determine cause and fix
    if face_count == 0:
        likely_cause = "empty_mesh"
        suggested_fix = "Regenerate building from params"
        confidence = 0.0
    elif degenerate_faces > 10:
        likely_cause = "sliver_faces_from_boolean_ops"
        suggested_fix = "Remove degenerates + merge by distance"
        confidence = 0.8
    elif degenerate_faces > 0:
        likely_cause = "minor_degenerate_faces"
        suggested_fix = "Remove degenerates"
        confidence = 0.95
    elif has_holes and duplicate_faces > 0:
        likely_cause = "duplicate_faces_causing_non_manifold"
        suggested_fix = "Remove duplicates + fill holes"
        confidence = 0.7
    elif has_holes:
        likely_cause = "open_edges_from_generation"
        suggested_fix = "Fill holes"
        confidence = 0.6
    else:
        likely_cause = "clean"
        suggested_fix = "None needed"
        confidence = 1.0

    bucket = "auto_fix" if confidence >= 0.7 else "manual_review"

    return MeshIssue(
        address=address, glb_path=str(glb_path),
        face_count=face_count, vertex_count=vertex_count,
        degenerate_faces=degenerate_faces, duplicate_faces=duplicate_faces,
        unreferenced_verts=unreferenced_verts,
        is_watertight=is_watertight, has_holes=has_holes,
        severity_score=round(severity, 1),
        likely_cause=likely_cause,
        auto_fix_confidence=confidence,
        suggested_fix=suggested_fix,
        bucket=bucket,
    )


def repair_mesh(glb_path: Path, fill_holes: bool = False) -> dict:
    """Apply automated repairs to a GLB mesh."""
    loaded = trimesh.load(str(glb_path), process=False)

    if isinstance(loaded, trimesh.Scene):
        meshes = [g for g in loaded.geometry.values() if isinstance(g, Trimesh)]
        if not meshes:
            return {"error": "empty_scene", "repaired": False}
        mesh = trimesh.util.concatenate(meshes)
    else:
        mesh = loaded

    faces_before = len(mesh.faces)
    verts_before = len(mesh.vertices)

    # Remove degenerate faces
    if hasattr(mesh, "nondegenerate_faces"):
        nd_mask = mesh.nondegenerate_faces(height=1e-10)
        mesh.update_faces(nd_mask)

    # Remove duplicate faces
    if hasattr(mesh, "unique_faces"):
        uniq_mask = mesh.unique_faces()
        mesh.update_faces(uniq_mask)

    # Remove unreferenced vertices
    mesh.remove_unreferenced_vertices()

    # Optional hole fill
    holes_filled = 0
    if fill_holes:
        faces_pre = len(mesh.faces)
        try:
            mesh.fill_holes()
            holes_filled = len(mesh.faces) - faces_pre
        except Exception:
            pass

    faces_after = len(mesh.faces)
    verts_after = len(mesh.vertices)

    changed = faces_after != faces_before or verts_after != verts_before or holes_filled > 0

    if changed:
        mesh.export(str(glb_path))

    return {
        "repaired": changed,
        "faces_before": faces_before,
        "faces_after": faces_after,
        "verts_before": verts_before,
        "verts_after": verts_after,
        "degenerate_removed": faces_before - faces_after + holes_filled,
        "holes_filled": holes_filled,
    }


def scan_exports(exports_dir: Path, address_filter: str | None = None) -> list[Path]:
    """Find all GLB files in exports directory."""
    glb_files = []
    for subdir in sorted(exports_dir.iterdir()):
        if not subdir.is_dir():
            continue
        if address_filter:
            addr = subdir.name.replace("_", " ")
            if address_filter.lower() not in addr.lower():
                continue
        for glb in subdir.glob("*.glb"):
            glb_files.append(glb)
    return glb_files


def main():
    parser = argparse.ArgumentParser(description="Batch mesh repair and triage")
    parser.add_argument("--exports-dir", type=Path, default=REPO_ROOT / "outputs" / "exports")
    parser.add_argument("--apply", action="store_true", help="Apply repairs")
    parser.add_argument("--fill-holes", action="store_true", help="Fill holes in meshes")
    parser.add_argument("--top", type=int, default=None, help="Show only top N by severity")
    parser.add_argument("--address", type=str, default=None, help="Filter by address")
    parser.add_argument("--report", type=Path, default=None, help="Output JSON report")
    args = parser.parse_args()

    if not HAS_TRIMESH:
        print("ERROR: trimesh is required. Install with: pip install trimesh")
        sys.exit(1)

    if not args.exports_dir.exists():
        print(f"Exports directory not found: {args.exports_dir}")
        print("No GLB meshes to repair. Run the export pipeline first:")
        print("  blender --background --python scripts/batch_export_unreal.py -- --source-dir outputs/full/")
        sys.exit(1)

    glb_files = scan_exports(args.exports_dir, args.address)
    if not glb_files:
        print(f"No GLB files found in {args.exports_dir}")
        sys.exit(1)

    print(f"Scanning {len(glb_files)} GLB meshes...")

    issues = []
    for glb in glb_files:
        try:
            issue = diagnose_mesh(glb)
            issues.append(issue)
        except Exception as e:
            print(f"  ERROR: {glb.parent.name}: {e}")

    # Sort by severity
    issues.sort(key=lambda i: i.severity_score, reverse=True)

    if args.top:
        issues = issues[:args.top]

    # Split into buckets
    auto_fix = [i for i in issues if i.bucket == "auto_fix"]
    manual_review = [i for i in issues if i.bucket == "manual_review"]
    clean = [i for i in issues if i.likely_cause == "clean"]

    print(f"\n{'='*80}")
    print(f"MESH TRIAGE REPORT")
    print(f"{'='*80}")
    print(f"Total scanned:    {len(issues)}")
    print(f"Clean:            {len(clean)}")
    print(f"Auto-fix:         {len(auto_fix)}")
    print(f"Manual review:    {len(manual_review)}")

    if auto_fix:
        print(f"\n--- AUTO-FIX CANDIDATES (confidence >= 0.7) ---")
        print(f"{'Address':<35} {'Severity':>8} {'Degen':>6} {'Holes':>6} {'Cause':<35} {'Fix'}")
        print("-" * 120)
        for i in auto_fix:
            print(f"{i.address:<35} {i.severity_score:>8.1f} {i.degenerate_faces:>6} "
                  f"{'Yes' if i.has_holes else 'No':>6} {i.likely_cause:<35} {i.suggested_fix}")

    if manual_review:
        print(f"\n--- MANUAL REVIEW (confidence < 0.7) ---")
        print(f"{'Address':<35} {'Severity':>8} {'Cause':<35} {'Fix'}")
        print("-" * 90)
        for i in manual_review:
            print(f"{i.address:<35} {i.severity_score:>8.1f} {i.likely_cause:<35} {i.suggested_fix}")

    # Apply repairs if requested
    if args.apply and auto_fix:
        print(f"\n--- APPLYING REPAIRS ---")
        repaired = 0
        for i in auto_fix:
            try:
                result = repair_mesh(Path(i.glb_path), fill_holes=args.fill_holes)
                if result["repaired"]:
                    repaired += 1
                    print(f"  REPAIRED: {i.address} "
                          f"(faces {result['faces_before']}->{result['faces_after']})")
                else:
                    print(f"  NO CHANGE: {i.address}")
            except Exception as e:
                print(f"  ERROR: {i.address}: {e}")
        print(f"\nRepaired: {repaired}/{len(auto_fix)}")

    # Save report
    if args.report:
        report = {
            "total_scanned": len(issues),
            "clean": len(clean),
            "auto_fix_count": len(auto_fix),
            "manual_review_count": len(manual_review),
            "auto_fix": [asdict(i) for i in auto_fix],
            "manual_review": [asdict(i) for i in manual_review],
            "commands": {
                "batch_repair": f"python scripts/batch_mesh_repair.py --exports-dir {args.exports_dir} --apply --fill-holes",
                "single_repair": f"python scripts/repair_export_glb_mesh.py --address \"103 Bellevue Ave\" --apply --fill-holes",
                "revalidate": f"python scripts/validate_export_pipeline.py --source-dir {args.exports_dir}",
            },
        }
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\nReport saved: {args.report}")


if __name__ == "__main__":
    main()
