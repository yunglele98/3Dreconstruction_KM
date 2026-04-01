from pathlib import Path

import pytest

import validate_export_pipeline as vp

pytestmark = pytest.mark.skipif(not vp.HAS_TRIMESH, reason="trimesh not installed")


def test_coerce_loaded_mesh_concatenates_scene_geometry():
    scene = vp.trimesh.Scene()
    scene.add_geometry(vp.trimesh.creation.box())
    scene.add_geometry(vp.trimesh.creation.icosphere(subdivisions=1, radius=0.5))

    coerced = vp._coerce_loaded_mesh(scene)
    assert isinstance(coerced, vp.trimesh.Trimesh)
    assert len(coerced.faces) > 0


def test_load_mesh_uses_glb_fallback_for_unsupported_fbx(tmp_path, monkeypatch):
    fbx = tmp_path / "sample.fbx"
    glb = tmp_path / "sample.glb"
    fbx.write_bytes(b"fbx")
    glb.write_bytes(b"glb")

    calls = []

    def fake_load(path, process=False):
        calls.append(Path(path).suffix.lower())
        if str(path).endswith(".fbx"):
            raise RuntimeError("file_type 'fbx' not supported")
        return {"mesh": "ok"}

    monkeypatch.setattr(vp, "HAS_TRIMESH", True)
    monkeypatch.setattr(vp.trimesh, "load", fake_load)

    mesh, msg = vp.load_mesh(fbx)
    assert mesh == {"mesh": "ok"}
    assert "Loaded GLB fallback" in msg
    assert calls == [".fbx", ".glb"]


def test_load_mesh_reports_missing_glb_fallback(tmp_path, monkeypatch):
    fbx = tmp_path / "missing_glb.fbx"
    fbx.write_bytes(b"fbx")

    def fake_load(path, process=False):
        raise RuntimeError("file_type 'fbx' not supported")

    monkeypatch.setattr(vp, "HAS_TRIMESH", True)
    monkeypatch.setattr(vp.trimesh, "load", fake_load)

    mesh, msg = vp.load_mesh(fbx)
    assert mesh is None
    assert "missing GLB fallback" in msg


def test_validate_skips_auxiliary_fbx_files(tmp_path, monkeypatch):
    base = tmp_path / "sample_building.fbx"
    lod1 = tmp_path / "sample_building_LOD1.fbx"
    coll = tmp_path / "sample_building_collision.fbx"
    base.write_bytes(b"x")
    lod1.write_bytes(b"x")
    coll.write_bytes(b"x")

    class _FakeMesh:
        is_watertight = True
        is_winding_consistent = True
        area_faces = [1.0]
        vertices = [0, 1, 2]

        class _Visual:
            uv = [0, 1, 2]

        visual = _Visual()

    monkeypatch.setattr(vp, "HAS_TRIMESH", True)
    monkeypatch.setattr(vp, "load_mesh", lambda _: (_FakeMesh(), ""))
    monkeypatch.setattr(vp, "check_watertight", lambda _: (True, "ok"))
    monkeypatch.setattr(vp, "check_normals", lambda _: (True, "ok"))
    monkeypatch.setattr(vp, "check_degenerate_faces", lambda _: (True, "ok"))
    monkeypatch.setattr(vp, "check_uv_coverage", lambda _: (True, "ok"))
    monkeypatch.setattr(vp, "check_lod_consistency", lambda _: (True, "ok"))

    results = vp.validate_building_exports(tmp_path)
    assert list(results.keys()) == ["sample building"]
