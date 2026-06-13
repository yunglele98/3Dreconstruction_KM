#!/usr/bin/env python3
"""Tests for scripts/audit_render_manifest_coverage.py."""

from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import audit_render_manifest_coverage as armc


def _write_param(params_dir: Path, name: str, data: dict) -> Path:
    params_dir.mkdir(parents=True, exist_ok=True)
    p = params_dir / name
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return p


def _write_manifest(manifests_dir: Path, name: str, data: dict) -> Path:
    manifests_dir.mkdir(parents=True, exist_ok=True)
    p = manifests_dir / name
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return p


def _run(params_dir: Path, manifests_dir: Path) -> dict:
    """Patch module paths and run main(), returning the parsed JSON report."""
    orig_params = armc.PARAMS_DIR
    orig_manifests = armc.MANIFESTS_DIR
    orig_output = armc.OUTPUT_FILE
    out_file = params_dir.parent / "render_staleness_report.json"
    armc.PARAMS_DIR = params_dir
    armc.MANIFESTS_DIR = manifests_dir
    armc.OUTPUT_FILE = out_file
    try:
        armc.main()
    finally:
        armc.PARAMS_DIR = orig_params
        armc.MANIFESTS_DIR = orig_manifests
        armc.OUTPUT_FILE = orig_output
    return json.loads(out_file.read_text(encoding="utf-8"))


# ── file_md5 ──────────────────────────────────────────────────────────────────

class TestFileMd5:
    def test_returns_hex_string(self, tmp_path):
        p = tmp_path / "test.txt"
        p.write_bytes(b"hello")
        result = armc.file_md5(p)
        assert isinstance(result, str)
        assert len(result) == 32  # MD5 hex digest

    def test_empty_file(self, tmp_path):
        p = tmp_path / "empty.txt"
        p.write_bytes(b"")
        result = armc.file_md5(p)
        assert result == hashlib.md5(b"").hexdigest()

    def test_different_content_different_hash(self, tmp_path):
        p1 = tmp_path / "a.txt"
        p2 = tmp_path / "b.txt"
        p1.write_bytes(b"hello")
        p2.write_bytes(b"world")
        assert armc.file_md5(p1) != armc.file_md5(p2)

    def test_same_content_same_hash(self, tmp_path):
        p1 = tmp_path / "a.txt"
        p2 = tmp_path / "b.txt"
        p1.write_bytes(b"same content")
        p2.write_bytes(b"same content")
        assert armc.file_md5(p1) == armc.file_md5(p2)


# ── main() integration ────────────────────────────────────────────────────────

class TestMainIntegration:
    def test_empty_params_dir(self, tmp_path):
        params_dir = tmp_path / "params"
        params_dir.mkdir()
        manifests_dir = tmp_path / "manifests"
        report = _run(params_dir, manifests_dir)
        assert report["total_active_buildings"] == 0
        assert report["not_rendered"] == 0

    def test_not_rendered_building_detected(self, tmp_path):
        params_dir = tmp_path / "params"
        manifests_dir = tmp_path / "manifests"
        _write_param(params_dir, "22_Lippincott_St.json", {"building_name": "22 Lippincott St"})
        report = _run(params_dir, manifests_dir)
        assert report["total_active_buildings"] == 1
        assert report["not_rendered"] == 1
        assert any(r["param_file"] == "22_Lippincott_St.json" for r in report["not_rendered_list"])

    def test_skipped_param_not_counted(self, tmp_path):
        params_dir = tmp_path / "params"
        manifests_dir = tmp_path / "manifests"
        _write_param(params_dir, "skip.json", {"skipped": True, "building_name": "Skip"})
        report = _run(params_dir, manifests_dir)
        assert report["total_active_buildings"] == 0

    def test_metadata_param_not_counted(self, tmp_path):
        params_dir = tmp_path / "params"
        manifests_dir = tmp_path / "manifests"
        _write_param(params_dir, "_site_coordinates.json", {"building_name": "meta"})
        report = _run(params_dir, manifests_dir)
        assert report["total_active_buildings"] == 0

    def test_current_render_detected(self, tmp_path):
        params_dir = tmp_path / "params"
        manifests_dir = tmp_path / "manifests"
        # Write param first
        pf = _write_param(params_dir, "44_Augusta_Ave.json", {"building_name": "44 Augusta Ave"})
        # Write manifest AFTER param (so manifest is newer)
        time.sleep(0.01)
        _write_manifest(
            manifests_dir,
            "44_Augusta_Ave.manifest.json",
            {"param_file": "44_Augusta_Ave.json", "building_name": "44 Augusta Ave"},
        )
        report = _run(params_dir, manifests_dir)
        assert report["not_rendered"] == 0
        assert report["stale_renders"] == 0
        assert report["current_renders"] == 1

    def test_stale_render_detected(self, tmp_path):
        params_dir = tmp_path / "params"
        manifests_dir = tmp_path / "manifests"
        # Write manifest first
        _write_manifest(
            manifests_dir,
            "10_Nassau_St.manifest.json",
            {"param_file": "10_Nassau_St.json", "building_name": "10 Nassau St"},
        )
        # Write param AFTER manifest (param is newer → stale)
        time.sleep(0.01)
        _write_param(params_dir, "10_Nassau_St.json", {"building_name": "10 Nassau St"})
        report = _run(params_dir, manifests_dir)
        assert report["stale_renders"] == 1
        assert any(r["param_file"] == "10_Nassau_St.json" for r in report["stale_list"])

    def test_backup_files_skipped(self, tmp_path):
        params_dir = tmp_path / "params"
        manifests_dir = tmp_path / "manifests"
        _write_param(params_dir, "22_Lippincott_St.backup_old.json", {"building_name": "22 Lippincott St"})
        report = _run(params_dir, manifests_dir)
        assert report["total_active_buildings"] == 0

    def test_mixed_report_totals(self, tmp_path):
        params_dir = tmp_path / "params"
        manifests_dir = tmp_path / "manifests"
        # Building 1: rendered and current
        mf1 = _write_manifest(manifests_dir, "a.manifest.json", {"param_file": "a.json"})
        time.sleep(0.01)
        _write_param(params_dir, "a.json", {"building_name": "A"})
        time.sleep(0.01)
        # Make manifest newer than param for "a"
        mf1.touch()  # update mtime so it's newest
        # Building 2: not rendered
        _write_param(params_dir, "b.json", {"building_name": "B"})
        report = _run(params_dir, manifests_dir)
        assert report["total_active_buildings"] == 2
        assert report["not_rendered"] == 1

    def test_invalid_manifest_json_skipped_gracefully(self, tmp_path):
        params_dir = tmp_path / "params"
        manifests_dir = tmp_path / "manifests"
        manifests_dir.mkdir()
        (manifests_dir / "bad.manifest.json").write_text("{bad json}", encoding="utf-8")
        _write_param(params_dir, "22_Lippincott_St.json", {"building_name": "22 Lippincott St"})
        # Should not raise
        report = _run(params_dir, manifests_dir)
        assert report["total_active_buildings"] == 1
