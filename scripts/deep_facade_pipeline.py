#!/usr/bin/env python3
"""
Deep Facade Analysis Pipeline
==============================
Unified script for the full facade analysis -> merge -> promote workflow.

Usage:
    # Process a single deep analysis batch file
    python scripts/deep_facade_pipeline.py merge docs/baldwin_st_deep_batch1.json

    # Process all batch files for a street
    python scripts/deep_facade_pipeline.py merge-street baldwin

    # Promote all deep analysis to generator fields (all streets)
    python scripts/deep_facade_pipeline.py promote

    # Full pipeline: merge all batch files then promote
    python scripts/deep_facade_pipeline.py merge-street baldwin --promote

    # Report: show stats for a street
    python scripts/deep_facade_pipeline.py report baldwin

    # Audit: show which streets have deep analysis coverage
    python scripts/deep_facade_pipeline.py audit
"""

import argparse
import json
import os
import re
import sys
import tempfile
import traceback
from pathlib import Path
from datetime import datetime

_ROOT = Path(__file__).resolve().parent.parent
PARAMS_DIR = Path(os.environ.get("PARAMS_DIR", _ROOT / "params"))
DOCS_DIR = Path(os.environ.get("DOCS_DIR", _ROOT / "docs"))

VALID_ROOF_TYPES = {"flat", "gable", "cross-gable", "hip", "mansard"}
HEX_PATTERN = re.compile(r"^#[0-9A-Fa-f]{6}$")

# ── Address normalization and param file lookup ──────────────────────────

def normalize_address(addr):
    """Normalize address for param file matching."""
    if not addr:
        return ""
    addr = addr.strip()
    addr = re.sub(r'\s*\(.*?\)', '', addr)
    addr = re.sub(r'\s*-\s*[A-Z].*$', '', addr)
    if '/' in addr:
        addr = addr.split('/')[0].strip()
    if addr.startswith("~"):
        addr = addr[1:].strip()
    return addr.strip()


def _is_valid_hex(val):
    """Validate a hex colour string like #B85A3A."""
    return isinstance(val, str) and bool(HEX_PATTERN.match(val))


def _atomic_write_json(filepath, data):
    """Write JSON atomically via temp file + rename to prevent corruption."""
    filepath = Path(filepath)
    with tempfile.NamedTemporaryFile(
        mode="w", dir=filepath.parent, delete=False,
        suffix=".tmp", encoding="utf-8",
    ) as tmp:
        json.dump(data, tmp, indent=2, ensure_ascii=False)
        tmp.write("\n")
        tmp_path = Path(tmp.name)
    tmp_path.replace(filepath)


SKIP_KEYWORDS = [
    "streetscape", "alley", "lane", "rear", "parking", "payphone",
    "vacant lot", "mural", "graffiti wall", "canopy", "street sign",
    "e-scooter", "rooftop", "panoramic", "interior", "exhibit",
    "fire hydrant", "utility box", "hoarding", "construction",
]


def should_skip(addr_raw, entry):
    """Check if an entry should be skipped (non-building)."""
    if not addr_raw:
        return True
    lower = addr_raw.lower()
    for kw in SKIP_KEYWORDS:
        if kw in lower:
            return True
    if not entry.get("facade_material") and not entry.get("storeys"):
        return True
    return False


def find_param_file(address):
    """Find matching param file for an address."""
    if not address:
        return None

    fname = address.replace(" ", "_") + ".json"
    p = PARAMS_DIR / fname
    if p.exists():
        return p

    # Case-insensitive
    fname_lower = fname.lower()
    for f in PARAMS_DIR.iterdir():
        if f.name.lower() == fname_lower:
            return f

    # Prefix match (files with business names appended)
    prefix = address.replace(" ", "_")
    for f in PARAMS_DIR.iterdir():
        if f.name.startswith(prefix + "_") and f.suffix == ".json":
            return f

    # Range address: try individual numbers
    m = re.match(r"(\d+)-(\d+)\s+(.*)", address)
    if m:
        for num in [m.group(1), m.group(2)]:
            result = find_param_file(f"{num} {m.group(3)}")
            if result:
                return result

    # Address suffix A/B (e.g. "200A Baldwin St")
    m2 = re.match(r"(\d+)([A-Za-z])\s+(.*)", address)
    if m2:
        result = find_param_file(f"{m2.group(1)}{m2.group(2).lower()} {m2.group(3)}")
        if result:
            return result
        result = find_param_file(f"{m2.group(1)}{m2.group(2).upper()} {m2.group(3)}")
        if result:
            return result

    return None


# ── Deep analysis merge ──────────────────────────────────────────────────

def merge_deep_into_param(param_data, deep_entry):
    """Add deep_facade_analysis section to a param file.

    Returns (param_data, is_new) — is_new is False when an existing
    deep_facade_analysis section was overwritten.
    """
    is_new = "deep_facade_analysis" not in param_data

    brick_hex = deep_entry.get("brick_colour_hex")
    if brick_hex and not _is_valid_hex(brick_hex):
        brick_hex = None
    roof_hex = deep_entry.get("roof_colour_hex")
    if roof_hex and not _is_valid_hex(roof_hex):
        roof_hex = None

    param_data["deep_facade_analysis"] = {
        "source_photo": deep_entry.get("filename"),
        "analysis_pass": "deep_v2",
        "timestamp": datetime.now().strftime("%Y-%m-%d"),
        "storeys_observed": deep_entry.get("storeys"),
        "has_half_storey_gable": deep_entry.get("has_half_storey_gable"),
        "floor_height_ratios": deep_entry.get("floor_height_ratios"),
        "facade_material_observed": deep_entry.get("facade_material"),
        "brick_colour_hex": brick_hex,
        "brick_bond_observed": deep_entry.get("brick_bond"),
        "mortar_colour": deep_entry.get("mortar_colour"),
        "polychromatic_brick": deep_entry.get("polychromatic_brick"),
        "windows_detail": deep_entry.get("windows_detail"),
        "doors_observed": deep_entry.get("doors"),
        "roof_type_observed": deep_entry.get("roof_type"),
        "roof_pitch_deg": deep_entry.get("roof_pitch_deg"),
        "roof_material": deep_entry.get("roof_material"),
        "roof_colour_hex": roof_hex,
        "bargeboard": deep_entry.get("bargeboard"),
        "gable_window": deep_entry.get("gable_window"),
        "bay_window_observed": deep_entry.get("bay_window"),
        "chimney_observed": deep_entry.get("chimney"),
        "porch_observed": deep_entry.get("porch"),
        "storefront_observed": deep_entry.get("storefront"),
        "decorative_elements_observed": deep_entry.get("decorative_elements"),
        "party_wall_left": deep_entry.get("party_wall_left"),
        "party_wall_right": deep_entry.get("party_wall_right"),
        "colour_palette_observed": deep_entry.get("colour_palette"),
        "condition_observed": deep_entry.get("condition"),
        "condition_notes": deep_entry.get("condition_notes"),
        "depth_notes": deep_entry.get("depth_notes"),
    }

    meta = param_data.get("_meta", {})
    fusions = meta.get("fusion_applied", [])
    if "deep_facade" not in fusions:
        fusions.append("deep_facade")
    meta["fusion_applied"] = fusions
    meta["deep_facade_merge_ts"] = datetime.now().strftime("%Y-%m-%d")
    param_data["_meta"] = meta

    return param_data, is_new


# ── Generator field promotion ────────────────────────────────────────────

def _normalize_roof_type(observed):
    """Map an observed roof type string to a canonical generator value."""
    obs = (observed or "").lower().strip()
    if "cross" in obs and "gable" in obs:
        return "Cross-Gable"
    if "hip" in obs:
        return "Hip"
    if "mansard" in obs:
        return "Mansard"
    if "gable" in obs:
        return "Gable"
    if "flat" in obs:
        return "Flat"
    return None


def promote_roof(params, deep):
    changes = []
    observed_type = deep.get("roof_type_observed")
    if observed_type:
        canonical = _normalize_roof_type(observed_type)
        current = (params.get("roof_type") or "").lower()
        if canonical and canonical.lower() != current:
            params["roof_type"] = canonical
            changes.append(f"roof_type: '{current}' -> '{canonical}'")

    observed_pitch = deep.get("roof_pitch_deg")
    if observed_pitch and isinstance(observed_pitch, (int, float)) and 5 <= observed_pitch <= 75:
        current_pitch = params.get("roof_pitch_deg", 35)
        if abs(current_pitch - observed_pitch) > 5:
            params["roof_pitch_deg"] = observed_pitch
            changes.append(f"roof_pitch_deg: {current_pitch} -> {observed_pitch}")

    roof_mat = deep.get("roof_material")
    if roof_mat and not params.get("roof_material"):
        params["roof_material"] = roof_mat
        changes.append(f"roof_material: '{roof_mat}'")

    roof_hex = deep.get("roof_colour_hex")
    if roof_hex and _is_valid_hex(roof_hex) and not params.get("roof_colour"):
        params["roof_colour"] = roof_hex
        changes.append(f"roof_colour: '{roof_hex}'")

    rd = params.get("roof_detail", {})
    bargeboard = deep.get("bargeboard")
    if bargeboard and isinstance(bargeboard, dict) and bargeboard.get("present"):
        colour_hex = bargeboard.get("colour_hex")
        if colour_hex and not _is_valid_hex(colour_hex):
            colour_hex = None
        rd["bargeboard_style"] = bargeboard.get("style", "decorative")
        rd["bargeboard_colour_hex"] = colour_hex
        changes.append("roof_detail.bargeboard added")

    gw = deep.get("gable_window")
    if gw and isinstance(gw, dict) and gw.get("present"):
        rd["gable_window"] = {
            "present": True, "type": gw.get("type", "rectangular"),
            "width_m": gw.get("width_m_est", 0.6), "height_m": gw.get("height_m_est", 0.8),
        }
        if gw.get("type"):
            rd["gable_window"]["arch_type"] = gw["type"]
        changes.append("roof_detail.gable_window added")

    eave = (deep.get("depth_notes") or {}).get("eave_overhang_mm_est")
    if eave and isinstance(eave, (int, float)) and 50 <= eave <= 1200:
        rd["eave_overhang_mm"] = eave
        params["eave_overhang_mm"] = eave
        changes.append(f"eave_overhang_mm: {eave}")

    if rd:
        params["roof_detail"] = rd
    return changes


def promote_floor_heights(params, deep):
    changes = []
    ratios = deep.get("floor_height_ratios")
    observed_storeys = deep.get("storeys_observed")
    if not ratios or not observed_storeys:
        return changes
    total_h = params.get("total_height_m")
    if not total_h:
        return changes
    current_floors = params.get("floors", 2)
    obs_floors = int(observed_storeys) if isinstance(observed_storeys, (int, float)) else current_floors
    if obs_floors == current_floors and len(ratios) >= current_floors:
        ratio_sum = sum(ratios[:current_floors])
        if ratio_sum > 0:
            new_heights = [round(total_h * (r / ratio_sum), 2) for r in ratios[:current_floors]]
            old_heights = params.get("floor_heights_m", [])
            if new_heights != old_heights:
                params["floor_heights_m"] = new_heights
                changes.append(f"floor_heights_m: {old_heights} -> {new_heights}")
    if deep.get("has_half_storey_gable") and "gable" in str(params.get("roof_type", "")).lower():
        rd = params.get("roof_detail", {})
        rd["has_half_storey"] = True
        params["roof_detail"] = rd
        changes.append("half_storey_gable flagged")
    return changes


def promote_windows(params, deep):
    changes = []
    win_obs = deep.get("windows_detail")
    if not win_obs or not isinstance(win_obs, list):
        return changes
    floor_map = {"ground": "Ground floor", "first": "Ground floor", "second": "Second floor",
                 "third": "Third floor", "gable": "Gable", "attic": "Gable"}
    new_wd = []
    for w in win_obs:
        floor_key = str(w.get("floor", "")).lower()
        floor_name = floor_map.get(floor_key, w.get("floor", "Unknown"))
        entry = {"floor": floor_name}
        if w.get("note") and "storefront" in str(w.get("note", "")).lower():
            entry["windows"] = []
            entry["is_storefront"] = True
        else:
            win = {"count": w.get("count", 1), "type": w.get("type", "double-hung")}
            if w.get("frame_colour"):
                win["frame_colour"] = w["frame_colour"]
            if w.get("arch"):
                win["arch_type"] = w["arch"]
            if w.get("width_ratio") and params.get("facade_width_m"):
                win["width_m"] = round(w["width_ratio"] * params["facade_width_m"], 2)
            if w.get("height_m_est"):
                win["height_m"] = w["height_m_est"]
            entry["windows"] = [win]
        new_wd.append(entry)
    current_wd = params.get("windows_detail", [])
    if new_wd and len(new_wd) >= len(current_wd):
        params["windows_detail"] = new_wd
        changes.append(f"windows_detail: {len(current_wd)} -> {len(new_wd)} floors")
    wps = []
    for w in win_obs:
        if w.get("note") and "storefront" in str(w.get("note", "")).lower():
            wps.append(0)
        else:
            wps.append(w.get("count", 0))
    if wps:
        old_wps = params.get("windows_per_floor", [])
        if wps != old_wps:
            params["windows_per_floor"] = wps
            changes.append(f"windows_per_floor: {old_wps} -> {wps}")
    return changes


def promote_facade(params, deep):
    changes = []
    brick_hex = deep.get("brick_colour_hex")
    if brick_hex and _is_valid_hex(brick_hex):
        fd = params.get("facade_detail", {})
        old_hex = fd.get("brick_colour_hex")
        if not old_hex or old_hex in ("#B85A3A", "#D4B896"):
            fd["brick_colour_hex"] = brick_hex
            params["facade_detail"] = fd
            changes.append(f"facade_detail.brick_colour_hex: '{old_hex}' -> '{brick_hex}'")
    bond = deep.get("brick_bond_observed")
    if bond:
        fd = params.get("facade_detail", {})
        if not fd.get("bond_pattern") or fd["bond_pattern"] == "running bond":
            fd["bond_pattern"] = bond
            params["facade_detail"] = fd
            if bond != "running bond":
                changes.append(f"facade_detail.bond_pattern: '{bond}'")
    mortar = deep.get("mortar_colour")
    if mortar:
        fd = params.get("facade_detail", {})
        if not fd.get("mortar_colour"):
            fd["mortar_colour"] = mortar
            params["facade_detail"] = fd
            changes.append(f"facade_detail.mortar_colour: '{mortar}'")
    cp_obs = deep.get("colour_palette_observed")
    if cp_obs and isinstance(cp_obs, dict):
        cp = params.get("colour_palette", {})
        enriched_keys = []
        for key in ("facade", "trim", "roof", "accent"):
            val = cp_obs.get(key)
            if val and _is_valid_hex(val) and not cp.get(key):
                cp[key] = val
                enriched_keys.append(key)
        if enriched_keys:
            params["colour_palette"] = cp
            changes.append(f"colour_palette enriched ({', '.join(enriched_keys)})")
    mat_obs = deep.get("facade_material_observed")
    if mat_obs:
        current = (params.get("facade_material") or "").lower()
        obs_lower = mat_obs.lower()
        if "painted" in obs_lower and "painted" not in current:
            params["facade_colour"] = f"painted ({obs_lower})"
            changes.append("facade_colour: painted observation")
    return changes


def promote_decorative(params, deep):
    changes = []
    de_obs = deep.get("decorative_elements_observed")
    if not de_obs or not isinstance(de_obs, dict):
        return changes
    de = params.get("decorative_elements", {})
    mapping = [
        ("cornice", "cornice", lambda v: isinstance(v, dict) and v.get("present"),
         lambda: {"present": True, "height_mm": 200, "projection_mm": 150}),
        ("voussoirs", "stone_voussoirs", lambda v: isinstance(v, dict) and v.get("present"),
         lambda: {"present": True}),
        ("quoins", "quoins", lambda v: v, lambda: {"present": True}),
        ("dentil_course", "dentil_course", lambda v: v, lambda: {"present": True}),
        ("brackets", "gable_brackets", lambda v: v, lambda: {"present": True}),
        ("ornamental_shingles_in_gable", "ornamental_shingles", lambda v: v, lambda: {"present": True}),
    ]
    for obs_key, param_key, check_fn, make_fn in mapping:
        val = de_obs.get(obs_key)
        if val and check_fn(val) and param_key not in de:
            de[param_key] = make_fn()
            changes.append(f"decorative_elements.{param_key} added")
    sc = de_obs.get("string_courses")
    if sc and "string_courses" not in de:
        if isinstance(sc, list) and len(sc) > 0:
            de["string_courses"] = {"present": True, "count": len(sc)}
            changes.append(f"decorative_elements.string_courses: {len(sc)}")
        elif isinstance(sc, dict) and sc.get("present"):
            de["string_courses"] = {
                "present": True,
                "width_mm": sc.get("width_mm", 80),
                "projection_mm": sc.get("projection_mm", 30),
            }
            if sc.get("colour_hex") and _is_valid_hex(sc["colour_hex"]):
                de["string_courses"]["colour_hex"] = sc["colour_hex"]
            changes.append("decorative_elements.string_courses added")
    if de_obs.get("diamond_brick_patterns"):
        de["polychromatic_brick"] = True
        changes.append("polychromatic_brick flagged")
    if de:
        params["decorative_elements"] = de
    return changes


def promote_storefront(params, deep):
    changes = []
    sf_obs = deep.get("storefront_observed")
    if not sf_obs or not isinstance(sf_obs, dict):
        return changes
    sf = params.get("storefront", {})
    if sf_obs.get("awning") and not sf.get("awning"):
        awning = sf_obs["awning"]
        if isinstance(awning, dict) and awning.get("present"):
            sf["awning"] = {"present": True, "type": awning.get("type", "fixed"), "colour": awning.get("colour", "dark")}
            changes.append("storefront.awning added")
    if sf_obs.get("security_grille") and not sf.get("security_grille"):
        sf["security_grille"] = True
        changes.append("storefront.security_grille added")
    if sf_obs.get("signage_text") and not sf.get("signage_text"):
        sf["signage_text"] = sf_obs["signage_text"]
    if sf:
        params["storefront"] = sf
    return changes


def promote_depth(params, deep):
    changes = []
    dn = deep.get("depth_notes")
    if not dn or not isinstance(dn, dict):
        return changes
    fh = dn.get("foundation_height_m_est")
    if fh and isinstance(fh, (int, float)) and fh > 0:
        params["foundation_height_m"] = fh
        changes.append(f"foundation_height_m: {fh}")
    sc = dn.get("step_count")
    if sc and isinstance(sc, (int, float)) and sc > 0:
        doors = params.get("doors_detail", [])
        if doors and isinstance(doors, list):
            for door in doors:
                if isinstance(door, dict) and not door.get("steps"):
                    door["steps"] = int(sc)
            params["doors_detail"] = doors
            changes.append(f"doors_detail.steps: {sc}")
    return changes


def promote_doors(params, deep):
    changes = []
    doors_obs = deep.get("doors_observed")
    if not doors_obs or not isinstance(doors_obs, list):
        return changes
    if not params.get("doors_detail"):
        new_doors = []
        for i, d in enumerate(doors_obs):
            if not isinstance(d, dict):
                continue
            door = {"id": f"door_{i+1}", "type": d.get("type", "commercial"),
                    "position": d.get("position", "center"), "width_m": d.get("width_m_est", 0.9)}
            if d.get("transom"):
                door["transom"] = {"present": True, "type": "glazed"}
            if d.get("steps"):
                door["steps"] = d["steps"]
            new_doors.append(door)
        if new_doors:
            params["doors_detail"] = new_doors
            changes.append(f"doors_detail: {len(new_doors)} doors created")
    return changes


def promote_party_walls(params, deep):
    changes = []
    for side in ("party_wall_left", "party_wall_right"):
        obs = deep.get(side)
        if obs is not None and params.get(side) is None:
            params[side] = bool(obs)
            changes.append(f"{side}: {obs}")
    return changes


def promote_bay_window(params, deep):
    changes = []
    bw_obs = deep.get("bay_window_observed")
    if not bw_obs or not isinstance(bw_obs, dict):
        return changes
    bw = params.get("bay_window", {})
    if bw.get("present"):
        return changes
    if bw_obs.get("present") or bw_obs.get("type"):
        bw_type = bw_obs.get("type", "canted")
        bw["present"] = True
        bw["type"] = bw_type
        if bw_obs.get("width_m_est"):
            bw["width_m"] = bw_obs["width_m_est"]
        if bw_obs.get("projection_m_est"):
            bw["projection_m"] = bw_obs["projection_m_est"]
        if bw_obs.get("floors_spanned"):
            bw["floors_spanned"] = bw_obs["floors_spanned"]
        elif bw_obs.get("floors"):
            bw["floors"] = bw_obs["floors"]
        params["bay_window"] = bw
        changes.append(f"bay_window: type={bw_type}")
    return changes


def promote_chimney(params, deep):
    changes = []
    ch_obs = deep.get("chimney_observed")
    if not ch_obs:
        return changes
    if isinstance(ch_obs, bool) and ch_obs:
        if not params.get("chimneys"):
            params["chimneys"] = {"count": 1, "position": "side"}
            rf = params.get("roof_features", [])
            if "chimney" not in rf:
                rf.append("chimney")
                params["roof_features"] = rf
            changes.append("chimneys: 1 (observed)")
    elif isinstance(ch_obs, dict) and ch_obs.get("present"):
        if not params.get("chimneys"):
            params["chimneys"] = {
                "count": ch_obs.get("count", 1),
                "position": ch_obs.get("position", "side"),
            }
            rf = params.get("roof_features", [])
            if "chimney" not in rf:
                rf.append("chimney")
                params["roof_features"] = rf
            changes.append(f"chimneys: {ch_obs.get('count', 1)} (observed)")
    return changes


def promote_porch(params, deep):
    changes = []
    p_obs = deep.get("porch_observed")
    if not p_obs or not isinstance(p_obs, dict):
        return changes
    porch = params.get("porch", {})
    if porch.get("present"):
        return changes
    if p_obs.get("present") or p_obs.get("type"):
        porch["present"] = True
        porch["type"] = p_obs.get("type", "open")
        if p_obs.get("width_m_est"):
            porch["width_m"] = p_obs["width_m_est"]
        if p_obs.get("depth_m_est"):
            porch["depth_m"] = p_obs["depth_m_est"]
        params["porch"] = porch
        params["porch_present"] = True
        params["porch_type"] = porch["type"]
        changes.append(f"porch: type={porch['type']}")
    return changes


ALL_PROMOTERS = [promote_roof, promote_floor_heights, promote_windows,
                 promote_facade, promote_decorative, promote_storefront,
                 promote_depth, promote_doors, promote_party_walls,
                 promote_bay_window, promote_chimney, promote_porch]


# ── Pipeline commands ────────────────────────────────────────────────────

def cmd_merge(batch_files, do_promote=False, dry_run=False):
    """Merge one or more batch JSON files into param files."""
    all_entries = []
    for bf in batch_files:
        path = Path(bf)
        if not path.exists():
            path = DOCS_DIR / bf
        if not path.exists():
            print(f"[WARN] Batch file not found: {bf}")
            continue
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            all_entries.extend(data)
        elif isinstance(data, dict):
            for v in data.values():
                if isinstance(v, list):
                    all_entries.extend(v)
                    break
    print(f"Loaded {len(all_entries)} entries from {len(batch_files)} batch file(s)")
    if dry_run:
        print("[DRY RUN] No files will be modified.")

    merged = 0
    updated = 0
    promoted = 0
    skipped = 0
    errors = 0
    not_found = []
    total_changes = 0

    for entry in all_entries:
        addr_raw = entry.get("address", "")
        addr = normalize_address(addr_raw)

        if should_skip(addr_raw, entry):
            skipped += 1
            continue

        param_file = find_param_file(addr)
        if not param_file:
            not_found.append(addr)
            continue

        try:
            with open(param_file, encoding="utf-8") as f:
                param_data = json.load(f)
            if param_data.get("skipped"):
                skipped += 1
                continue

            param_data, is_new = merge_deep_into_param(param_data, entry)
            if is_new:
                merged += 1
            else:
                updated += 1

            if do_promote:
                deep = param_data["deep_facade_analysis"]
                changes = []
                for promoter in ALL_PROMOTERS:
                    changes.extend(promoter(param_data, deep))
                if changes:
                    meta = param_data.get("_meta", {})
                    meta["deep_facade_analysis_applied"] = True
                    meta["geometry_revised"] = True
                    meta["geometry_revision_ts"] = datetime.now().strftime("%Y-%m-%d")
                    meta["geometry_changes"] = changes
                    param_data["_meta"] = meta
                    promoted += 1
                    total_changes += len(changes)

            if not dry_run:
                _atomic_write_json(param_file, param_data)

            n_ch = len(param_data.get("_meta", {}).get("geometry_changes", []))
            tag = "NEW" if is_new else "UPD"
            print(f"  + [{tag}] {addr} <- {entry.get('filename', '?')} ({n_ch} changes)")

        except (json.JSONDecodeError, KeyError, TypeError) as e:
            errors += 1
            print(f"  X {addr}: {type(e).__name__}: {e}")
        except Exception as e:
            errors += 1
            print(f"  X {addr}: {e}")
            traceback.print_exc()

    print(f"\n{'='*60}")
    prefix = "[DRY RUN] " if dry_run else ""
    print(f"{prefix}MERGE {'+ PROMOTE ' if do_promote else ''}COMPLETE")
    print(f"  New merges: {merged}")
    print(f"  Updated: {updated}")
    if do_promote:
        print(f"  Promoted: {promoted}  ({total_changes} field changes)")
    print(f"  Skipped: {skipped}")
    print(f"  Errors: {errors}")
    print(f"  Not found: {len(not_found)}")
    if not_found:
        for a in sorted(set(not_found)):
            print(f"    - {a}")
    return merged + updated


def cmd_merge_street(street_key, do_promote=False, dry_run=False):
    """Find and merge all batch files for a street."""
    pattern = f"*{street_key}*deep_batch*.json"
    batch_files = sorted(DOCS_DIR.glob(pattern))
    if not batch_files:
        for alt in [f"*{street_key}*batch*.json", f"*{street_key.replace(' ', '_')}*batch*.json"]:
            batch_files = sorted(DOCS_DIR.glob(alt))
            if batch_files:
                break
    if not batch_files:
        print(f"No batch files found for '{street_key}' in {DOCS_DIR}")
        return 0
    print(f"Found {len(batch_files)} batch files for '{street_key}':")
    for bf in batch_files:
        print(f"  {bf.name}")
    return cmd_merge([str(bf) for bf in batch_files], do_promote=do_promote, dry_run=dry_run)


def cmd_promote(dry_run=False, force=False):
    """Promote all deep_facade_analysis sections to generator fields."""
    files = sorted(PARAMS_DIR.glob("*.json"))
    promoted = 0
    already = 0
    total_changes = 0
    if dry_run:
        print("[DRY RUN] No files will be modified.")
    for fpath in files:
        if fpath.name.startswith("_"):
            continue
        with open(fpath, encoding="utf-8") as f:
            params = json.load(f)
        if params.get("skipped"):
            continue
        deep = params.get("deep_facade_analysis")
        if not deep:
            continue
        if params.get("_meta", {}).get("geometry_revised") and not force:
            already += 1
            continue
        changes = []
        for promoter in ALL_PROMOTERS:
            changes.extend(promoter(params, deep))
        if changes:
            meta = params.get("_meta", {})
            meta["deep_facade_analysis_applied"] = True
            meta["geometry_revised"] = True
            meta["geometry_revision_ts"] = datetime.now().strftime("%Y-%m-%d")
            meta["geometry_changes"] = changes
            params["_meta"] = meta
            if not dry_run:
                _atomic_write_json(fpath, params)
            promoted += 1
            total_changes += len(changes)
            print(f"  + {fpath.name}: {len(changes)} changes")
    print(f"\nPromoted: {promoted} buildings, {total_changes} field changes")
    if already:
        print(f"Already promoted: {already} (use --force to re-promote)")


def cmd_audit():
    """Show deep analysis coverage by street."""
    from collections import Counter
    street_counts = Counter()
    street_deep = Counter()
    street_promoted = Counter()

    for fpath in sorted(PARAMS_DIR.glob("*.json")):
        if fpath.name.startswith("_"):
            continue
        with open(fpath, encoding="utf-8") as f:
            params = json.load(f)
        if params.get("skipped"):
            continue
        street = params.get("site", {}).get("street", "Unknown")
        street_counts[street] += 1
        if params.get("deep_facade_analysis"):
            street_deep[street] += 1
        if params.get("_meta", {}).get("geometry_revised"):
            street_promoted[street] += 1

    print(f"{'Street':<30} {'Total':>6} {'Deep':>6} {'Promoted':>9} {'Coverage':>9}")
    print("-" * 70)
    for street in sorted(street_counts.keys()):
        total = street_counts[street]
        deep = street_deep[street]
        promo = street_promoted[street]
        pct = f"{deep/total*100:.0f}%" if total > 0 else "0%"
        print(f"{street:<30} {total:>6} {deep:>6} {promo:>9} {pct:>9}")
    print("-" * 70)
    total_all = sum(street_counts.values())
    deep_all = sum(street_deep.values())
    promo_all = sum(street_promoted.values())
    print(f"{'TOTAL':<30} {total_all:>6} {deep_all:>6} {promo_all:>9} {deep_all/max(total_all,1)*100:.0f}%")


def cmd_report(street_key):
    """Show detailed stats for a street."""
    count = 0
    changes_total = 0
    buildings = []
    for fpath in sorted(PARAMS_DIR.glob("*.json")):
        if fpath.name.startswith("_"):
            continue
        if street_key.lower().replace(" ", "_") not in fpath.name.lower():
            continue
        with open(fpath, encoding="utf-8") as f:
            params = json.load(f)
        if params.get("skipped"):
            continue
        count += 1
        deep = params.get("deep_facade_analysis")
        changes = params.get("_meta", {}).get("geometry_changes", [])
        buildings.append({
            "file": fpath.name,
            "has_deep": bool(deep),
            "promoted": bool(changes),
            "changes": len(changes),
            "photo": deep.get("source_photo") if deep else None,
        })
        changes_total += len(changes)

    print(f"Street: {street_key}")
    print(f"Buildings: {count}")
    print(f"With deep analysis: {sum(1 for b in buildings if b['has_deep'])}")
    print(f"Geometry promoted: {sum(1 for b in buildings if b['promoted'])}")
    print(f"Total field changes: {changes_total}")
    print()
    for b in buildings:
        status = "OK" if b["promoted"] else ("DEEP" if b["has_deep"] else "  ")
        print(f"  [{status:>4}] {b['file']:<50} {b['changes']:>3} changes  {b['photo'] or ''}")


# ── CLI ──────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Deep Facade Analysis Pipeline")
    sub = parser.add_subparsers(dest="command")

    p_merge = sub.add_parser("merge", help="Merge batch JSON files into params")
    p_merge.add_argument("files", nargs="+", help="Batch JSON file paths")
    p_merge.add_argument("--promote", action="store_true", help="Also promote to generator fields")
    p_merge.add_argument("--dry-run", action="store_true", help="Show changes without writing")

    p_street = sub.add_parser("merge-street", help="Merge all batches for a street")
    p_street.add_argument("street", help="Street name key (e.g. 'baldwin', 'augusta')")
    p_street.add_argument("--promote", action="store_true", help="Also promote to generator fields")
    p_street.add_argument("--dry-run", action="store_true", help="Show changes without writing")

    p_promote = sub.add_parser("promote", help="Promote all deep analysis to generator fields")
    p_promote.add_argument("--dry-run", action="store_true", help="Show changes without writing")
    p_promote.add_argument("--force", action="store_true", help="Re-promote already-promoted buildings")

    p_audit = sub.add_parser("audit", help="Show coverage by street")

    p_report = sub.add_parser("report", help="Show stats for a street")
    p_report.add_argument("street", help="Street name key")

    args = parser.parse_args()

    if args.command == "merge":
        cmd_merge(args.files, do_promote=args.promote, dry_run=args.dry_run)
    elif args.command == "merge-street":
        cmd_merge_street(args.street, do_promote=args.promote, dry_run=args.dry_run)
    elif args.command == "promote":
        cmd_promote(dry_run=args.dry_run, force=args.force)
    elif args.command == "audit":
        cmd_audit()
    elif args.command == "report":
        cmd_report(args.street)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
