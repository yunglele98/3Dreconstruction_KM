"""Tests for scripts/reconstruct/ pipeline scripts."""

import csv
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts" / "reconstruct"))

from select_candidates import load_photo_index, select_candidates


# ── select_candidates ────────────────────────────────────────────────

def test_load_photo_index(tmp_path):
    idx = tmp_path / "index.csv"
    idx.write_text(
        "filename,address_or_location,source\n"
        "IMG_001.jpg,22 Lippincott St,confirmed\n"
        "IMG_002.jpg,22 Lippincott St,confirmed\n"
        "IMG_003.jpg,22 Lippincott St,confirmed\n"
        "IMG_004.jpg,100 Augusta Ave,confirmed\n",
        encoding="utf-8",
    )
    result = load_photo_index(idx)
    assert len(result["22 lippincott st"]) == 3
    assert len(result["100 augusta ave"]) == 1


def test_select_candidates_min_views(tmp_path):
    params_dir = tmp_path / "params"
    params_dir.mkdir()
    idx = tmp_path / "index.csv"

    # Building with 3 photos -> candidate
    p1 = {
        "building_name": "22 Lippincott St",
        "_meta": {"address": "22 Lippincott St"},
        "site": {"street": "Lippincott St"},
        "hcd_data": {"contributing": "Yes", "construction_date": "Pre-1889"},
    }
    (params_dir / "22_Lippincott_St.json").write_text(json.dumps(p1), encoding="utf-8")

    # Building with 1 photo -> not a candidate
    p2 = {
        "building_name": "10 Oxford St",
        "_meta": {"address": "10 Oxford St"},
        "site": {"street": "Oxford St"},
        "hcd_data": {"contributing": "No"},
    }
    (params_dir / "10_Oxford_St.json").write_text(json.dumps(p2), encoding="utf-8")

    idx.write_text(
        "filename,address_or_location,source\n"
        "IMG_001.jpg,22 Lippincott St,confirmed\n"
        "IMG_002.jpg,22 Lippincott St,confirmed\n"
        "IMG_003.jpg,22 Lippincott St,confirmed\n"
        "IMG_004.jpg,10 Oxford St,confirmed\n",
        encoding="utf-8",
    )

    candidates = select_candidates(
        params_dir, idx, tmp_path / "no_audit.json", min_views=3
    )
    assert len(candidates) == 1
    assert candidates[0]["address"] == "22 Lippincott St"
    assert candidates[0]["photo_count"] == 3
    assert candidates[0]["contributing"] is True


def test_select_candidates_street_filter(tmp_path):
    params_dir = tmp_path / "params"
    params_dir.mkdir()
    idx = tmp_path / "index.csv"

    for addr, street in [("1 A St", "A St"), ("2 B St", "B St")]:
        p = {"_meta": {"address": addr}, "site": {"street": street}}
        stem = addr.replace(" ", "_")
        (params_dir / f"{stem}.json").write_text(json.dumps(p), encoding="utf-8")

    idx.write_text(
        "filename,address_or_location,source\n"
        "IMG_1.jpg,1 A St,confirmed\n"
        "IMG_2.jpg,1 A St,confirmed\n"
        "IMG_3.jpg,1 A St,confirmed\n"
        "IMG_4.jpg,2 B St,confirmed\n"
        "IMG_5.jpg,2 B St,confirmed\n"
        "IMG_6.jpg,2 B St,confirmed\n",
        encoding="utf-8",
    )

    candidates = select_candidates(
        params_dir, idx, tmp_path / "no.json", min_views=3, street_filter="A St"
    )
    assert len(candidates) == 1
    assert candidates[0]["street"] == "A St"


def test_select_candidates_skips_skipped(tmp_path):
    params_dir = tmp_path / "params"
    params_dir.mkdir()
    idx = tmp_path / "index.csv"

    p = {"skipped": True, "_meta": {"address": "Skip"}}
    (params_dir / "Skip.json").write_text(json.dumps(p), encoding="utf-8")

    idx.write_text(
        "filename,address_or_location,source\n"
        "IMG_1.jpg,Skip,confirmed\n"
        "IMG_2.jpg,Skip,confirmed\n"
        "IMG_3.jpg,Skip,confirmed\n",
        encoding="utf-8",
    )

    candidates = select_candidates(params_dir, idx, tmp_path / "no.json", min_views=3)
    assert len(candidates) == 0


def test_select_candidates_skips_underscore_files(tmp_path):
    params_dir = tmp_path / "params"
    params_dir.mkdir()
    idx = tmp_path / "index.csv"

    p = {"_meta": {"address": "_site"}}
    (params_dir / "_site_coordinates.json").write_text(json.dumps(p), encoding="utf-8")

    idx.write_text("filename,address_or_location,source\n", encoding="utf-8")

    candidates = select_candidates(params_dir, idx, tmp_path / "no.json", min_views=1)
    assert len(candidates) == 0
