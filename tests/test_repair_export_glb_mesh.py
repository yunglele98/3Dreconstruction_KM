from __future__ import annotations

from pathlib import Path

import trimesh

from scripts.repair_export_glb_mesh import repair_glb


def test_repair_glb_removes_degenerate_faces(tmp_path: Path):
    # One degenerate face: vertices 0 and 1 are identical in that face.
    vertices = [
        [0.0, 0.0, 0.0],
        [1.0, 0.0, 0.0],
        [0.0, 1.0, 0.0],
        [0.0, 0.0, 0.0],
    ]
    faces = [
        [0, 1, 2],  # valid
        [0, 3, 2],  # degenerate
    ]
    mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)

    glb_path = tmp_path / "mesh.glb"
    mesh.export(glb_path)

    result = repair_glb(glb_path, apply=False, fill_holes=False)
    assert result.error == ""
    assert result.exists is True
    assert result.degenerate_removed >= 1
    assert result.would_write is True

