from __future__ import annotations

from pathlib import Path

from PIL import Image

from scripts.backfill_pbr_utility_maps import run_backfill


def _make_export_dir(root: Path, safe: str) -> Path:
    exp = root / safe
    tex = exp / "textures"
    tex.mkdir(parents=True, exist_ok=True)
    (exp / f"{safe}.fbx").write_text("stub", encoding="utf-8")
    # Diffuse + normal + roughness only: intentionally missing metallic/ao.
    for name in ("mat_wall_diffuse.png", "mat_wall_normal.png", "mat_wall_roughness.png"):
        Image.new("RGB", (1024, 1024), color=(128, 128, 128)).save(tex / name, format="PNG")
    return exp


def test_run_backfill_pbr_utility_maps_dry_run(tmp_path: Path):
    exports = tmp_path / "exports"
    _make_export_dir(exports, "10_Oxford_St")

    results = run_backfill(exports, apply=False)
    assert len(results) == 1
    row = results[0]
    assert row.action == "would_write"
    assert row.created_metallic is True
    assert row.created_ao is True
    assert row.size == 1024

    tex_dir = exports / "10_Oxford_St" / "textures"
    assert not (tex_dir / "backfill_metallic.png").exists()
    assert not (tex_dir / "backfill_ao.png").exists()


def test_run_backfill_pbr_utility_maps_apply(tmp_path: Path):
    exports = tmp_path / "exports"
    _make_export_dir(exports, "10_Oxford_St")

    results = run_backfill(exports, apply=True)
    assert len(results) == 1
    row = results[0]
    assert row.action == "written"
    assert row.created_metallic is True
    assert row.created_ao is True

    tex_dir = exports / "10_Oxford_St" / "textures"
    assert (tex_dir / "backfill_metallic.png").exists()
    assert (tex_dir / "backfill_ao.png").exists()
