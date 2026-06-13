#!/usr/bin/env python3
"""Tests for scripts/apply_handoff_height_fixes.py."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import apply_handoff_height_fixes as ahf


def _make_param(tmp_path: Path, address: str, total_height_m: float, floors: int = 2) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    stem = address.replace(" ", "_")
    p = tmp_path / f"{stem}.json"
    p.write_text(
        json.dumps(
            {
                "building_name": address,
                "total_height_m": total_height_m,
                "floors": floors,
                "floor_heights_m": [total_height_m / floors] * floors,
                "_meta": {"address": address},
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return p


def _make_handoff(tmp_path: Path, findings: list) -> Path:
    p = tmp_path / "handoff.json"
    p.write_text(json.dumps({"findings": findings}, indent=2), encoding="utf-8")
    return p


# ── find_param_file ───────────────────────────────────────────────────────────

class TestFindParamFile:
    def test_exact_stem_match(self, tmp_path):
        _make_param(tmp_path, "22 Lippincott St", 7.0)
        result = ahf.find_param_file("22 Lippincott St", tmp_path)
        assert result is not None
        assert result.name == "22_Lippincott_St.json"

    def test_returns_none_when_not_found(self, tmp_path):
        result = ahf.find_param_file("99 Nonexistent St", tmp_path)
        assert result is None

    def test_fallback_to_meta_address(self, tmp_path):
        p = tmp_path / "some_other_name.json"
        p.write_text(
            json.dumps({"building_name": "44 Augusta Ave", "_meta": {"address": "44 Augusta Ave"}}),
            encoding="utf-8",
        )
        result = ahf.find_param_file("44 Augusta Ave", tmp_path)
        assert result is not None
        assert result.name == "some_other_name.json"

    def test_skips_metadata_files(self, tmp_path):
        p = tmp_path / "_site_coordinates.json"
        p.write_text(json.dumps({"_meta": {"address": "22 Lippincott St"}}), encoding="utf-8")
        result = ahf.find_param_file("22 Lippincott St", tmp_path)
        assert result is None


# ── main() integration ────────────────────────────────────────────────────────

class TestMainIntegration:
    def _run_main(self, handoff_path: Path, params_dir: Path, apply: bool = False) -> str:
        import argparse, io, contextlib

        args = argparse.Namespace(
            handoff=handoff_path,
            params=params_dir,
            dry_run=not apply,
            apply=apply,
            min_confidence=0.9,
            max_delta_pct=50,
        )
        original = ahf.parse_args if hasattr(ahf, "parse_args") else None
        # Patch argparse.ArgumentParser.parse_args globally for the call
        import argparse as _ap
        orig_parse = _ap.ArgumentParser.parse_args
        _ap.ArgumentParser.parse_args = lambda self, *a, **kw: args
        try:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                ahf.main()
            return buf.getvalue()
        finally:
            _ap.ArgumentParser.parse_args = orig_parse

    def test_dry_run_reports_would_apply(self, tmp_path):
        param_file = _make_param(tmp_path / "params", "22 Lippincott St", 7.0)
        handoff = _make_handoff(
            tmp_path,
            [
                {
                    "address": "22 Lippincott St",
                    "field": "total_height_m",
                    "expected": 9.0,
                    "actual": 7.0,
                    "confidence": 0.95,
                }
            ],
        )
        out = self._run_main(handoff, param_file.parent, apply=False)
        assert "DRY-RUN" in out
        assert "Applied: 1" in out
        # File should NOT be modified
        data = json.loads(param_file.read_text(encoding="utf-8"))
        assert data["total_height_m"] == pytest.approx(7.0)

    def test_apply_updates_param_file(self, tmp_path):
        param_file = _make_param(tmp_path / "params", "44 Augusta Ave", 6.0, floors=2)
        handoff = _make_handoff(
            tmp_path,
            [
                {
                    "address": "44 Augusta Ave",
                    "field": "total_height_m",
                    "expected": 8.0,
                    "actual": 6.0,
                    "confidence": 0.95,
                }
            ],
        )
        out = self._run_main(handoff, param_file.parent, apply=True)
        assert "APPLIED" in out
        data = json.loads(param_file.read_text(encoding="utf-8"))
        assert data["total_height_m"] == pytest.approx(8.0)
        assert len(data["floor_heights_m"]) == 2
        assert sum(data["floor_heights_m"]) == pytest.approx(8.0)
        assert "height_from_gis:8.0" in data["_meta"]["handoff_fixes"]

    def test_low_confidence_finding_skipped(self, tmp_path):
        param_file = _make_param(tmp_path / "params", "10 Nassau St", 7.0)
        handoff = _make_handoff(
            tmp_path,
            [
                {
                    "address": "10 Nassau St",
                    "field": "total_height_m",
                    "expected": 9.0,
                    "actual": 7.0,
                    "confidence": 0.5,  # below threshold
                }
            ],
        )
        out = self._run_main(handoff, param_file.parent, apply=True)
        assert "Applied: 0" in out

    def test_non_height_finding_ignored(self, tmp_path):
        param_file = _make_param(tmp_path / "params", "67 Baldwin St", 7.0)
        handoff = _make_handoff(
            tmp_path,
            [
                {
                    "address": "67 Baldwin St",
                    "field": "facade_material",  # wrong field
                    "expected": "brick",
                    "actual": "stucco",
                    "confidence": 0.99,
                }
            ],
        )
        out = self._run_main(handoff, param_file.parent, apply=True)
        assert "Applied: 0" in out

    def test_extreme_delta_skipped(self, tmp_path):
        # 7.0 → 50.0 is > 50% change limit
        param_file = _make_param(tmp_path / "params", "1 Augusta Ave", 7.0)
        handoff = _make_handoff(
            tmp_path,
            [
                {
                    "address": "1 Augusta Ave",
                    "field": "total_height_m",
                    "expected": 50.0,
                    "actual": 7.0,
                    "confidence": 0.99,
                }
            ],
        )
        out = self._run_main(handoff, param_file.parent, apply=True)
        assert "Applied: 0" in out

    def test_already_corrected_param_skipped(self, tmp_path):
        # If the file's current height no longer matches the finding's "actual", skip
        param_file = _make_param(tmp_path / "params", "5 Oxford St", 9.0)  # already at 9.0
        handoff = _make_handoff(
            tmp_path,
            [
                {
                    "address": "5 Oxford St",
                    "field": "total_height_m",
                    "expected": 9.0,
                    "actual": 7.0,  # the old/wrong value
                    "confidence": 0.99,
                }
            ],
        )
        out = self._run_main(handoff, param_file.parent, apply=True)
        # current height (9.0) doesn't match actual (7.0), so skip
        assert "Applied: 0" in out

    def test_address_not_found_counted(self, tmp_path):
        (tmp_path / "params").mkdir()
        handoff = _make_handoff(
            tmp_path,
            [
                {
                    "address": "999 Fake St",
                    "field": "total_height_m",
                    "expected": 9.0,
                    "actual": 7.0,
                    "confidence": 0.99,
                }
            ],
        )
        out = self._run_main(handoff, tmp_path / "params", apply=True)
        assert "Not found: 1" in out
