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

    # Promote with dry-run (show changes without writing)
    python scripts/deep_facade_pipeline.py promote --dry-run

    # Re-promote already-promoted buildings
    python scripts/deep_facade_pipeline.py promote --force

    # Full pipeline: merge all batch files then promote
    python scripts/deep_facade_pipeline.py merge-street baldwin --promote

    # Validate deep analysis data quality
    python scripts/deep_facade_pipeline.py validate

    # Report: show stats for a street
    python scripts/deep_facade_pipeline.py report baldwin

    # Audit: show which streets have deep analysis coverage
    python scripts/deep_facade_pipeline.py audit
"""

import argparse
import json
import re
import sys
from pathlib import Path
from datetime import datetime

_ROOT = Path(__file__).resolve().parent.parent
PARAMS_DIR = _ROOT / "params"
DOCS_DIR = _ROOT / "docs"

_HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


def is_valid_hex(value):
    """Return True if value is a valid 6-digit hex colour string."""
    return isinstance(value, str) and bool(_HEX_RE.match(value))


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
    """Add deep_facade_analysis section to a param file."""
    param_data["deep_facade_analysis"] = {
        "source_photo": deep_entry.get("filename"),
        "analysis_pass": "deep_v2",
        "timestamp": datetime.now().strftime("%Y-%m-%d"),
        "storeys_observed": deep_entry.get("storeys"),
        "has_half_storey_gable": deep_entry.get("has_half_storey_gable"),
        "floor_height_ratios": deep_entry.get("floor_height_ratios"),
        "facade_material_observed": deep_entry.get("facade_material"),
        "brick_colour_hex": deep_entry.get("brick_colour_hex"),
        "brick_bond_observed": deep_entry.get("brick_bond"),
        "mortar_colour": deep_entry.get("mortar_colour"),
        "polychromatic_brick": deep_entry.get("polychromatic_brick"),
        "windows_detail": deep_entry.get("windows_detail"),
        "doors_observed": deep_entry.get("doors"),
        "roof_type_observed": deep_entry.get("roof_type"),
        "roof_pitch_deg": deep_entry.get("roof_pitch_deg"),
        "roof_material": deep_entry.get("roof_material"),
        "roof_colour_hex": deep_entry.get("roof_colour_hex"),
        "bargeboard": deep_entry.get("bargeboard"),
        "gable_window": deep_entry.get("gable_window"),
        "bay_window_observed": deep_entry.get("bay_window"),
        "storefront_observed": deep_entry.get("storefront"),
        "decorative_elements_observed": deep_entry.get("decorative_elements"),
        "party_wall_left": deep_entry.get("party_wall_left"),
        "party_wall_right": deep_entry.get("party_wall_right"),
        "colour_palette_observed": deep_entry.get("colour_palette"),
        "condition_observed": deep_entry.get("condition"),
        "condition_notes": deep_entry.get("condition_notes"),
        "depth_notes": deep_entry.get("depth_notes"),
    }
    return param_data


# ── Generator field promotion ────────────────────────────────────────────

def promote_roof(params, deep):
    changes = []
    observed_type = deep.get("roof_type_observed")
    if observed_type:
        current = (params.get("roof_type") or "").lower()
        obs_lower = observed_type.lower()
        # Map observed roof types to canonical generator values
        # Longer keys first to avoid partial matches (cross-gable before gable)
        ROOF_TYPE_MAP = [
            ("cross-gable", "Cross-Gable"), ("cross_gable", "Cross-Gable"),
            ("gable", "Gable"), ("hip", "Hip"), ("mansard", "Mansard"),
            ("flat", "Flat"), ("gambrel", "Gambrel"),
        ]
        canonical = None
        for key, val in ROOF_TYPE_MAP:
            if key in obs_lower:
                canonical = val
                break
        if canonical and canonical.lower() != current:
            params["roof_type"] = canonical
            changes.append(f"roof_type: '{current}' -> '{canonical}'")

    observed_pitch = deep.get("roof_pitch_deg")
    if observed_pitch and isinstance(observed_pitch, (int, float)) and observed_pitch > 0:
        current_pitch = params.get("roof_pitch_deg", 35)
        if abs(current_pitch - observed_pitch) > 5:
            params["roof_pitch_deg"] = observed_pitch
            changes.append(f"roof_pitch_deg: {current_pitch} -> {observed_pitch}")

    # Roof material and colour (merged but previously not promoted)
    roof_mat = deep.get("roof_material")
    if roof_mat and isinstance(roof_mat, str):
        current_mat = (params.get("roof_material") or "").lower()
        obs_mat = roof_mat.lower()
        if not current_mat or current_mat in ("asphalt", "unknown"):
            params["roof_material"] = roof_mat
            changes.append(f"roof_material: '{current_mat}' -> '{roof_mat}'")
    roof_hex = deep.get("roof_colour_hex")
    if is_valid_hex(roof_hex):
        old_hex = params.get("roof_colour")
        if not old_hex or old_hex in ("#5A5A5A", "#4A5A5A"):
            params["roof_colour"] = roof_hex
            changes.append(f"roof_colour: '{old_hex}' -> '{roof_hex}'")

    rd = params.get("roof_detail", {})
    bargeboard = deep.get("bargeboard")
    if bargeboard and isinstance(bargeboard, dict) and bargeboard.get("present"):
        colour = bargeboard.get("colour_hex")
        rd["bargeboard_style"] = bargeboard.get("style", "decorative")
        if is_valid_hex(colour):
            rd["bargeboard_colour_hex"] = colour
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

    eave = deep.get("depth_notes", {}).get("eave_overhang_mm_est")
    if eave and isinstance(eave, (int, float)):
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
    floor_map = {
        "ground": "Ground floor", "ground floor": "Ground floor",
        "first": "Ground floor", "first floor": "Ground floor",
        "second": "Second floor", "second floor": "Second floor",
        "third": "Third floor", "third floor": "Third floor",
        "fourth": "Fourth floor", "fourth floor": "Fourth floor",
        "fifth": "Fifth floor", "fifth floor": "Fifth floor",
        "gable": "Gable", "attic": "Gable", "half-storey": "Gable",
    }
    new_wd = []
    for w in win_obs:
        floor_key = str(w.get("floor", "")).lower().strip()
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
            elif w.get("width_m_est"):
                win["width_m"] = w["width_m_est"]
            if w.get("height_m_est"):
                win["height_m"] = w["height_m_est"]
            if w.get("sill_height_m"):
                win["sill_height_m"] = w["sill_height_m"]
            if w.get("glazing"):
                win["glazing"] = w["glazing"]
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
    if is_valid_hex(brick_hex):
        fd = params.get("facade_detail", {})
        old_hex = fd.get("brick_colour_hex")
        # Overwrite default/skeleton values but not photo-confirmed ones
        default_hexes = {"#B85A3A", "#D4B896", "#7A5C44", "#E8D8B0", "#C87040"}
        if not old_hex or old_hex in default_hexes:
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
        for key in ("facade", "trim", "roof", "accent"):
            obs_val = cp_obs.get(key)
            if is_valid_hex(obs_val) and not cp.get(key):
                cp[key] = obs_val
        if cp:
            params["colour_palette"] = cp
            changes.append("colour_palette enriched")
    # Facade material — update when clearly different from DB
    mat_obs = deep.get("facade_material_observed")
    if mat_obs and isinstance(mat_obs, str):
        current = (params.get("facade_material") or "").lower()
        obs_lower = mat_obs.lower()
        # Check "painted" overlay first — it's an observation about finish, not a material change
        if "painted" in obs_lower and "painted" not in current:
            params["facade_colour"] = f"painted ({obs_lower})"
            changes.append("facade_colour: painted observation")
        elif not current or current in ("unknown", ""):
            # Longer keys first to avoid partial matches
            MATERIAL_MAP = [
                ("painted brick", "painted brick"), ("vinyl siding", "vinyl siding"),
                ("aluminum siding", "aluminum siding"),
                ("brick", "brick"), ("stucco", "stucco"), ("stone", "stone"),
                ("clapboard", "clapboard"), ("concrete", "concrete"), ("render", "stucco"),
            ]
            for key, val in MATERIAL_MAP:
                if key in obs_lower:
                    params["facade_material"] = val
                    changes.append(f"facade_material: '{current}' -> '{val}'")
                    break
    return changes


def promote_decorative(params, deep):
    changes = []
    de_obs = deep.get("decorative_elements_observed")
    if not de_obs or not isinstance(de_obs, dict):
        return changes
    de = params.get("decorative_elements", {})

    def _is_present(v):
        """Check if an observed value indicates presence (dict with present, or truthy)."""
        if isinstance(v, dict):
            return v.get("present", False)
        return bool(v)

    mapping = [
        ("cornice", "cornice",
         lambda v: _is_present(v),
         lambda v: {"present": True,
                     "height_mm": v.get("height_mm", 200) if isinstance(v, dict) else 200,
                     "projection_mm": v.get("projection_mm", 150) if isinstance(v, dict) else 150,
                     **({"colour_hex": v["colour_hex"]} if isinstance(v, dict) and is_valid_hex(v.get("colour_hex")) else {})}),
        ("voussoirs", "stone_voussoirs",
         lambda v: _is_present(v),
         lambda v: {"present": True,
                     **({"colour_hex": v["colour_hex"]} if isinstance(v, dict) and is_valid_hex(v.get("colour_hex")) else {})}),
        ("quoins", "quoins",
         lambda v: _is_present(v),
         lambda v: {"present": True,
                     **({"strip_width_mm": v["strip_width_mm"]} if isinstance(v, dict) and v.get("strip_width_mm") else {}),
                     **({"colour_hex": v["colour_hex"]} if isinstance(v, dict) and is_valid_hex(v.get("colour_hex")) else {})}),
        ("dentil_course", "dentil_course",
         lambda v: _is_present(v),
         lambda v: {"present": True}),
        ("brackets", "gable_brackets",
         lambda v: _is_present(v),
         lambda v: {"present": True,
                     **({"type": v["type"]} if isinstance(v, dict) and v.get("type") else {}),
                     **({"count": v["count"]} if isinstance(v, dict) and v.get("count") else {})}),
        ("ornamental_shingles_in_gable", "ornamental_shingles",
         lambda v: _is_present(v),
         lambda v: {"present": True,
                     **({"colour_hex": v["colour_hex"]} if isinstance(v, dict) and is_valid_hex(v.get("colour_hex")) else {})}),
        ("stone_lintels", "stone_lintels",
         lambda v: _is_present(v),
         lambda v: {"present": True,
                     **({"colour_hex": v["colour_hex"]} if isinstance(v, dict) and is_valid_hex(v.get("colour_hex")) else {})}),
        ("keystones", "keystones",
         lambda v: _is_present(v),
         lambda v: {"present": True}),
        ("pilasters", "pilasters",
         lambda v: _is_present(v),
         lambda v: {"present": True}),
        ("corbelling", "corbelling",
         lambda v: _is_present(v),
         lambda v: {"present": True}),
    ]
    for obs_key, param_key, check_fn, make_fn in mapping:
        val = de_obs.get(obs_key)
        if val and check_fn(val) and param_key not in de:
            de[param_key] = make_fn(val)
            changes.append(f"decorative_elements.{param_key} added")

    # String courses: handle both list and dict formats
    sc = de_obs.get("string_courses")
    if sc and "string_courses" not in de:
        if isinstance(sc, list) and len(sc) > 0:
            de["string_courses"] = {"present": True, "count": len(sc)}
            changes.append(f"decorative_elements.string_courses: {len(sc)}")
        elif isinstance(sc, dict) and sc.get("present"):
            de["string_courses"] = {"present": True, "count": sc.get("count", 1)}
            if sc.get("width_mm"):
                de["string_courses"]["width_mm"] = sc["width_mm"]
            if sc.get("projection_mm"):
                de["string_courses"]["projection_mm"] = sc["projection_mm"]
            if is_valid_hex(sc.get("colour_hex")):
                de["string_courses"]["colour_hex"] = sc["colour_hex"]
            changes.append(f"decorative_elements.string_courses added")

    # Polychromatic brick patterns
    if de_obs.get("diamond_brick_patterns") or de_obs.get("polychromatic_brick"):
        if not de.get("polychromatic_brick"):
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

    # Awning — handle both dict {"present": true, ...} and plain boolean
    if sf_obs.get("awning") and not sf.get("awning"):
        awning = sf_obs["awning"]
        if isinstance(awning, dict) and awning.get("present"):
            sf["awning"] = {"present": True, "type": awning.get("type", "fixed"), "colour": awning.get("colour", "dark")}
            changes.append("storefront.awning added")
        elif awning is True:
            sf["awning"] = {"present": True, "type": "fixed", "colour": "dark"}
            changes.append("storefront.awning added (boolean)")

    # Security grille
    if sf_obs.get("security_grille") and not sf.get("security_grille"):
        sf["security_grille"] = True
        changes.append("storefront.security_grille added")

    # Signage text
    if sf_obs.get("signage_text") and not sf.get("signage_text"):
        sf["signage_text"] = sf_obs["signage_text"]
        changes.append("storefront.signage_text added")

    # Width from percentage observation
    width_pct = sf_obs.get("width_pct")
    facade_w = params.get("facade_width_m")
    if width_pct and facade_w and not sf.get("width_m"):
        sf["width_m"] = round(facade_w * width_pct / 100, 2)
        changes.append(f"storefront.width_m: {sf['width_m']} (from {width_pct}%)")

    # Ensure has_storefront flag is set
    if sf and not params.get("has_storefront"):
        params["has_storefront"] = True
        changes.append("has_storefront: True")

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
    for side in ("left", "right"):
        key = f"party_wall_{side}"
        obs = deep.get(key)
        if obs is None:
            continue
        current = params.get(key)
        if current is None or current != obs:
            params[key] = obs
            changes.append(f"{key}: {current} -> {obs}")
    return changes


def promote_condition(params, deep):
    changes = []
    cond = deep.get("condition_observed")
    if cond and isinstance(cond, str):
        current = (params.get("condition") or "").lower()
        obs_lower = cond.lower()
        valid = {"good", "fair", "poor", "excellent"}
        if obs_lower in valid and obs_lower != current:
            params["condition"] = cond.lower()
            changes.append(f"condition: '{current}' -> '{obs_lower}'")
    notes = deep.get("condition_notes")
    if notes and isinstance(notes, str):
        assessment = params.get("assessment", {})
        if not assessment.get("condition_issues"):
            assessment["condition_issues"] = notes
            params["assessment"] = assessment
            changes.append("assessment.condition_issues added")
    return changes


ALL_PROMOTERS = [promote_roof, promote_floor_heights, promote_windows,
                 promote_facade, promote_decorative, promote_storefront,
                 promote_depth, promote_doors, promote_party_walls,
                 promote_condition]


# ── Pipeline commands ────────────────────────────────────────────────────

def cmd_merge(batch_files, do_promote=False):
    """Merge one or more batch JSON files into param files."""
    all_entries = []
    for bf in batch_files:
        path = Path(bf)
        if not path.exists():
            path = DOCS_DIR / bf
        if not path.exists():
            print(f"[WARN] Batch file not found: {bf}")
            continue
        with open(path) as f:
            data = json.load(f)
        if isinstance(data, list):
            all_entries.extend(data)
        elif isinstance(data, dict):
            for v in data.values():
                if isinstance(v, list):
                    all_entries.extend(v)
                    break
    print(f"Loaded {len(all_entries)} entries from {len(batch_files)} batch file(s)")

    merged = 0
    promoted = 0
    skipped = 0
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

            param_data = merge_deep_into_param(param_data, entry)
            merged += 1

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

            with open(param_file, "w", encoding="utf-8") as f:
                json.dump(param_data, f, indent=2, ensure_ascii=False)

            n_ch = len(param_data.get("_meta", {}).get("geometry_changes", []))
            print(f"  + {addr} <- {entry.get('filename', '?')} ({n_ch} changes)")

        except Exception as e:
            print(f"  X {addr}: {e}")

    print(f"\n{'='*60}")
    print(f"MERGE {'+ PROMOTE ' if do_promote else ''}COMPLETE")
    print(f"  Merged: {merged}")
    if do_promote:
        print(f"  Promoted: {promoted}  ({total_changes} field changes)")
    print(f"  Skipped: {skipped}")
    print(f"  Not found: {len(not_found)}")
    if not_found:
        for a in sorted(set(not_found)):
            print(f"    - {a}")
    return merged


def cmd_merge_street(street_key, do_promote=False):
    """Find and merge all batch files for a street."""
    pattern = f"*{street_key}*deep_batch*.json"
    batch_files = sorted(DOCS_DIR.glob(pattern))
    if not batch_files:
        # Try alternative patterns
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
    return cmd_merge([str(bf) for bf in batch_files], do_promote=do_promote)


def cmd_promote(dry_run=False, force=False):
    """Promote all deep_facade_analysis sections to generator fields."""
    files = sorted(PARAMS_DIR.glob("*.json"))
    promoted = 0
    skipped_already = 0
    total_changes = 0
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
            skipped_already += 1
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
                with open(fpath, "w", encoding="utf-8") as f:
                    json.dump(params, f, indent=2, ensure_ascii=False)
            promoted += 1
            total_changes += len(changes)
            prefix = "[DRY-RUN] " if dry_run else ""
            print(f"  {prefix}{fpath.name}: {len(changes)} changes")
            for c in changes:
                print(f"    - {c}")
    print(f"\n{'='*60}")
    if dry_run:
        print("DRY RUN — no files were modified")
    print(f"Promoted: {promoted} buildings, {total_changes} field changes")
    if skipped_already:
        print(f"Skipped (already promoted): {skipped_already}  (use --force to re-promote)")


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


def cmd_validate():
    """Validate deep_facade_analysis data quality across all param files."""
    files = sorted(PARAMS_DIR.glob("*.json"))
    total_with_deep = 0
    issues = []

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
        total_with_deep += 1
        name = fpath.name

        # Check hex colours are valid
        for key in ("brick_colour_hex", "roof_colour_hex"):
            val = deep.get(key)
            if val and not is_valid_hex(val):
                issues.append((name, f"{key} invalid hex: '{val}'"))

        cp = deep.get("colour_palette_observed")
        if cp and isinstance(cp, dict):
            for ck in ("facade", "trim", "roof", "accent"):
                cv = cp.get(ck)
                if cv and not is_valid_hex(cv):
                    issues.append((name, f"colour_palette_observed.{ck} invalid hex: '{cv}'"))

        # Check floor_height_ratios sum roughly to 1.0
        ratios = deep.get("floor_height_ratios")
        if ratios and isinstance(ratios, list):
            rsum = sum(r for r in ratios if isinstance(r, (int, float)))
            if rsum > 0 and abs(rsum - 1.0) > 0.15:
                issues.append((name, f"floor_height_ratios sum={rsum:.2f} (expected ~1.0)"))

        # Check storeys_observed is reasonable
        storeys = deep.get("storeys_observed")
        if storeys and isinstance(storeys, (int, float)) and (storeys < 1 or storeys > 6):
            issues.append((name, f"storeys_observed={storeys} (unusual for Kensington)"))

        # Check roof_pitch_deg is in reasonable range
        pitch = deep.get("roof_pitch_deg")
        if pitch and isinstance(pitch, (int, float)) and (pitch < 10 or pitch > 60):
            issues.append((name, f"roof_pitch_deg={pitch} (outside 10-60 range)"))

        # Check windows_detail has expected structure
        wd = deep.get("windows_detail")
        if wd and isinstance(wd, list):
            for i, w in enumerate(wd):
                if not isinstance(w, dict):
                    issues.append((name, f"windows_detail[{i}] is not a dict"))
                elif not w.get("floor"):
                    issues.append((name, f"windows_detail[{i}] missing 'floor' key"))

    print(f"Validated {total_with_deep} buildings with deep_facade_analysis")
    print(f"Found {len(issues)} issues\n")
    if issues:
        for fname, msg in issues:
            print(f"  [{fname}] {msg}")
    else:
        print("  All data valid!")
    return len(issues)


# ── CLI ──────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Deep Facade Analysis Pipeline")
    sub = parser.add_subparsers(dest="command")

    p_merge = sub.add_parser("merge", help="Merge batch JSON files into params")
    p_merge.add_argument("files", nargs="+", help="Batch JSON file paths")
    p_merge.add_argument("--promote", action="store_true", help="Also promote to generator fields")

    p_street = sub.add_parser("merge-street", help="Merge all batches for a street")
    p_street.add_argument("street", help="Street name key (e.g. 'baldwin', 'augusta')")
    p_street.add_argument("--promote", action="store_true", help="Also promote to generator fields")

    p_promote = sub.add_parser("promote", help="Promote all deep analysis to generator fields")
    p_promote.add_argument("--dry-run", action="store_true", help="Show changes without writing files")
    p_promote.add_argument("--force", action="store_true", help="Re-promote already-promoted buildings")

    p_audit = sub.add_parser("audit", help="Show coverage by street")

    p_report = sub.add_parser("report", help="Show stats for a street")
    p_report.add_argument("street", help="Street name key")

    p_validate = sub.add_parser("validate", help="Validate deep analysis data quality")

    args = parser.parse_args()

    if args.command == "merge":
        cmd_merge(args.files, do_promote=args.promote)
    elif args.command == "merge-street":
        cmd_merge_street(args.street, do_promote=args.promote)
    elif args.command == "promote":
        cmd_promote(dry_run=args.dry_run, force=args.force)
    elif args.command == "audit":
        cmd_audit()
    elif args.command == "report":
        cmd_report(args.street)
    elif args.command == "validate":
        cmd_validate()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
