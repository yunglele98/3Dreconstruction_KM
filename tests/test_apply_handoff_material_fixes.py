#!/usr/bin/env python3
"""Tests for scripts/apply_handoff_material_fixes.py."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import apply_handoff_material_fixes as amf


def _make_param(tmp_path: Path, address: str, facade_material: str) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    stem = address.replace(" ", "_")
    p = tmp_path / f"{stem}.json"
    p.write_text(
        json.dumps(
            {
                "building_name": address,
                "facade_material": facade_material,
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


def _run_main(handoff_path: Path, params_dir: Path, apply: bool = False, min_confidence: float = 0.7) -> str:
    import argparse, io, contextlib

    args = argparse.Namespace(
        handoff=handoff_path,
        params=params_dir,
        dry_run=not apply,
        apply=apply,
        min_confidence=min_confidence,
    )
    import argparse as _ap
    orig_parse = _ap.ArgumentParser.parse_args
    _ap.ArgumentParser.parse_args = lambda self, *a, **kw: args
    try:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            amf.main()
        return buf.getvalue()
    finally:
        _ap.ArgumentParser.parse_args = orig_parse


# ── MATERIAL_PRIORITY ─────────────────────────────────────────────────────────

class TestMaterialPriority:
    def test_brick_highest_priority(self):
        assert amf.MATERIAL_PRIORITY["brick"] > amf.MATERIAL_PRIORITY["mixed"]

    def test_mixed_lower_than_specific(self):
        assert amf.MATERIAL_PRIORITY["mixed"] < amf.MATERIAL_PRIORITY["stucco"]

    def test_empty_string_lowest(self):
        assert amf.MATERIAL_PRIORITY[""] == 0


# ── find_param_file ───────────────────────────────────────────────────────────

class TestFindParamFile:
    def test_exact_match(self, tmp_path):
        _make_param(tmp_path, "22 Lippincott St", "brick")
        result = amf.find_param_file("22 Lippincott St", tmp_path)
        assert result is not None
        assert result.name == "22_Lippincott_St.json"

    def test_returns_none_when_missing(self, tmp_path):
        assert amf.find_param_file("99 Fake St", tmp_path) is None

    def test_skips_metadata_files(self, tmp_path):
        p = tmp_path / "_site_coordinates.json"
        p.write_text(json.dumps({"_meta": {"address": "22 Lippincott St"}}), encoding="utf-8")
        assert amf.find_param_file("22 Lippincott St", tmp_path) is None

    def test_fallback_to_meta_address(self, tmp_path):
        p = tmp_path / "weird_name.json"
        p.write_text(json.dumps({"building_name": "44 Augusta Ave", "_meta": {"address": "44 Augusta Ave"}}), encoding="utf-8")
        result = amf.find_param_file("44 Augusta Ave", tmp_path)
        assert result is not None


# ── main() integration ────────────────────────────────────────────────────────

class TestMainIntegration:
    def test_dry_run_does_not_modify_file(self, tmp_path):
        param_file = _make_param(tmp_path / "params", "22 Lippincott St", "mixed")
        handoff = _make_handoff(
            tmp_path,
            [
                {
                    "address": "22 Lippincott St",
                    "field": "facade_material",
                    "expected": "brick",
                    "actual": "mixed",
                    "confidence": 0.95,
                }
            ],
        )
        out = _run_main(handoff, param_file.parent, apply=False)
        assert "DRY-RUN" in out
        data = json.loads(param_file.read_text(encoding="utf-8"))
        assert data["facade_material"] == "mixed"

    def test_apply_upgrades_material(self, tmp_path):
        param_file = _make_param(tmp_path / "params", "44 Augusta Ave", "mixed")
        handoff = _make_handoff(
            tmp_path,
            [
                {
                    "address": "44 Augusta Ave",
                    "field": "facade_material",
                    "expected": "brick",
                    "actual": "mixed",
                    "confidence": 0.95,
                }
            ],
        )
        out = _run_main(handoff, param_file.parent, apply=True)
        assert "APPLIED" in out
        data = json.loads(param_file.read_text(encoding="utf-8"))
        assert data["facade_material"] == "brick"
        assert "material:mixed->brick" in data["_meta"]["handoff_fixes"]

    def test_low_confidence_skipped(self, tmp_path):
        param_file = _make_param(tmp_path / "params", "10 Nassau St", "mixed")
        handoff = _make_handoff(
            tmp_path,
            [
                {
                    "address": "10 Nassau St",
                    "field": "facade_material",
                    "expected": "brick",
                    "actual": "mixed",
                    "confidence": 0.4,  # below 0.7 threshold
                }
            ],
        )
        out = _run_main(handoff, param_file.parent, apply=True)
        assert "Applied: 0" in out

    def test_specificity_downgrade_skipped(self, tmp_path):
        # brick → mixed would be a downgrade, should be skipped
        param_file = _make_param(tmp_path / "params", "67 Baldwin St", "brick")
        handoff = _make_handoff(
            tmp_path,
            [
                {
                    "address": "67 Baldwin St",
                    "field": "facade_material",
                    "expected": "mixed",  # lower priority than brick
                    "actual": "brick",
                    "confidence": 0.95,
                }
            ],
        )
        out = _run_main(handoff, param_file.parent, apply=True)
        assert "Applied: 0" in out

    def test_same_material_skipped(self, tmp_path):
        param_file = _make_param(tmp_path / "params", "1 Kensington Ave", "brick")
        handoff = _make_handoff(
            tmp_path,
            [
                {
                    "address": "1 Kensington Ave",
                    "field": "facade_material",
                    "expected": "brick",
                    "actual": "brick",
                    "confidence": 0.99,
                }
            ],
        )
        out = _run_main(handoff, param_file.parent, apply=True)
        assert "Applied: 0" in out

    def test_non_material_field_ignored(self, tmp_path):
        param_file = _make_param(tmp_path / "params", "5 Oxford St", "stucco")
        handoff = _make_handoff(
            tmp_path,
            [
                {
                    "address": "5 Oxford St",
                    "field": "total_height_m",  # wrong field
                    "expected": "brick",
                    "actual": "stucco",
                    "confidence": 0.99,
                }
            ],
        )
        out = _run_main(handoff, param_file.parent, apply=True)
        assert "Applied: 0" in out

    def test_current_doesnt_match_actual_skipped(self, tmp_path):
        # Param has been updated already (stucco), but finding says actual=mixed
        param_file = _make_param(tmp_path / "params", "20 Baldwin St", "stucco")
        handoff = _make_handoff(
            tmp_path,
            [
                {
                    "address": "20 Baldwin St",
                    "field": "facade_material",
                    "expected": "brick",
                    "actual": "mixed",  # doesn't match current "stucco"
                    "confidence": 0.95,
                }
            ],
        )
        out = _run_main(handoff, param_file.parent, apply=True)
        assert "Applied: 0" in out

    def test_address_not_found_counted(self, tmp_path):
        (tmp_path / "params").mkdir()
        handoff = _make_handoff(
            tmp_path,
            [
                {
                    "address": "999 Ghost St",
                    "field": "facade_material",
                    "expected": "brick",
                    "actual": "mixed",
                    "confidence": 0.95,
                }
            ],
        )
        out = _run_main(handoff, tmp_path / "params", apply=True)
        assert "Not found: 1" in out

    def test_multiple_findings_applied_independently(self, tmp_path):
        params_dir = tmp_path / "params"
        _make_param(params_dir, "A St", "mixed")
        _make_param(params_dir, "B St", "mixed")
        handoff = _make_handoff(
            tmp_path,
            [
                {"address": "A St", "field": "facade_material", "expected": "brick", "actual": "mixed", "confidence": 0.95},
                {"address": "B St", "field": "facade_material", "expected": "stucco", "actual": "mixed", "confidence": 0.95},
            ],
        )
        out = _run_main(handoff, params_dir, apply=True)
        assert "Applied: 2" in out
        assert json.loads((params_dir / "A_St.json").read_text())["facade_material"] == "brick"
        assert json.loads((params_dir / "B_St.json").read_text())["facade_material"] == "stucco"
