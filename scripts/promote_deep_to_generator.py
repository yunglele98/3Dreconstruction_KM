"""Promote deep_facade_analysis fields into generator-readable param fields.

The generator reads: roof_type, roof_pitch_deg, windows_detail, bay_window,
colour_palette, facade_detail, decorative_elements, storefront, doors_detail,
floor_heights_m, roof_detail, facade_colour, facade_material.

Rules:
- NEVER overwrite: total_height_m, facade_width_m, facade_depth_m, site.*, city_data.*
- Promote observed data into generator fields where it improves accuracy
- Cross-reference with DB geometry data for validation
- Track all changes in _meta
"""

import json
import re
from pathlib import Path

PARAMS_DIR = Path("C:/Users/liam1/blender_buildings/params")
DOCS_DIR = Path("C:/Users/liam1/blender_buildings/docs")
DB_GEOM_PATH = DOCS_DIR / "kensington_ave_geometry_db.json"


def load_db_geometry():
    """Load DB geometry data for cross-reference."""
    if not DB_GEOM_PATH.exists():
        return {}
    with open(DB_GEOM_PATH) as f:
        data = json.load(f)
    # Build lookup by address
    lookup = {}
    ba = data.get("building_assessment_fields", [])
    if isinstance(ba, dict):
        ba = ba.get("data", [])
    for entry in ba:
        addr = (entry.get("ADDRESS_FULL") or entry.get("address_full") or "").strip()
        if addr:
            lookup[addr.upper()] = entry
    # Add massing heights
    massing = data.get("massing_3d_heights", [])
    if isinstance(massing, dict):
        massing = massing.get("data", [])
    for entry in massing:
        addr = (entry.get("ADDRESS_FULL") or entry.get("address_full") or "").strip().upper()
        if addr and addr in lookup:
            lookup[addr]["massing_height_max"] = entry.get("height_max_m") or entry.get("MAX_HEIGHT")
            lookup[addr]["massing_height_avg"] = entry.get("height_avg_m") or entry.get("AVG_HEIGHT")
    return lookup


def promote_roof(params, deep):
    """Promote roof observations into generator fields."""
    changes = []

    # Roof type - only update if deep analysis is more specific
    observed_type = deep.get("roof_type_observed")
    if observed_type:
        current = (params.get("roof_type") or "").lower()
        obs_lower = observed_type.lower()
        # Promote if current is generic or wrong
        if current in ("", "flat") and "gable" in obs_lower:
            params["roof_type"] = "Gable"
            changes.append(f"roof_type: '{current}' -> 'Gable'")
        elif current in ("", "gable") and "flat" in obs_lower:
            params["roof_type"] = "Flat"
            changes.append(f"roof_type: '{current}' -> 'Flat'")

    # Roof pitch - promote if we have a specific value and current is default
    observed_pitch = deep.get("roof_pitch_deg")
    if observed_pitch and isinstance(observed_pitch, (int, float)) and observed_pitch > 0:
        current_pitch = params.get("roof_pitch_deg", 35)
        # Only update if significantly different (>5 deg) from default
        if abs(current_pitch - observed_pitch) > 5:
            params["roof_pitch_deg"] = observed_pitch
            changes.append(f"roof_pitch_deg: {current_pitch} -> {observed_pitch}")

    # Roof detail
    rd = params.get("roof_detail", {})
    bargeboard = deep.get("bargeboard")
    if bargeboard and isinstance(bargeboard, dict) and bargeboard.get("present"):
        rd["bargeboard_style"] = bargeboard.get("style", "decorative")
        rd["bargeboard_colour_hex"] = bargeboard.get("colour_hex")
        changes.append("roof_detail.bargeboard added")

    gw = deep.get("gable_window")
    if gw and isinstance(gw, dict) and gw.get("present"):
        rd["gable_window"] = {
            "present": True,
            "type": gw.get("type", "rectangular"),
            "width_m": gw.get("width_m_est", 0.6),
            "height_m": gw.get("height_m_est", 0.8),
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
    """Promote floor height ratios into floor_heights_m."""
    changes = []
    ratios = deep.get("floor_height_ratios")
    observed_storeys = deep.get("storeys_observed")

    if not ratios or not observed_storeys:
        return changes

    total_h = params.get("total_height_m")
    if not total_h:
        return changes

    # Only promote if storey count matches or is close
    current_floors = params.get("floors", 2)
    obs_floors = int(observed_storeys) if isinstance(observed_storeys, (int, float)) else current_floors

    if obs_floors == current_floors and len(ratios) >= current_floors:
        # Distribute total height according to observed ratios
        ratio_sum = sum(ratios[:current_floors])
        if ratio_sum > 0:
            new_heights = [round(total_h * (r / ratio_sum), 2) for r in ratios[:current_floors]]
            old_heights = params.get("floor_heights_m", [])
            if new_heights != old_heights:
                params["floor_heights_m"] = new_heights
                changes.append(f"floor_heights_m: {old_heights} -> {new_heights}")

    # Half-storey gable
    if deep.get("has_half_storey_gable") and "gable" in str(params.get("roof_type", "")).lower():
        if not params.get("roof_detail", {}).get("gable_window", {}).get("present"):
            rd = params.get("roof_detail", {})
            rd["has_half_storey"] = True
            params["roof_detail"] = rd
            changes.append("half_storey_gable flagged")

    return changes


def promote_windows(params, deep):
    """Promote window observations into windows_detail."""
    changes = []
    win_obs = deep.get("windows_detail")
    if not win_obs or not isinstance(win_obs, list):
        return changes

    current_wd = params.get("windows_detail", [])

    # Build new windows_detail from deep observations
    # Map floor names to standard format
    floor_map = {
        "ground": "Ground floor",
        "first": "Ground floor",
        "second": "Second floor",
        "third": "Third floor",
        "gable": "Gable",
        "attic": "Gable",
    }

    new_wd = []
    for w in win_obs:
        floor_key = str(w.get("floor", "")).lower()
        floor_name = floor_map.get(floor_key, w.get("floor", "Unknown"))

        entry = {"floor": floor_name}

        if w.get("note") == "storefront" or "storefront" in str(w.get("note", "")).lower():
            entry["windows"] = []
            entry["is_storefront"] = True
        else:
            win = {
                "count": w.get("count", 1),
                "type": w.get("type", "double-hung"),
            }
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

    if new_wd and len(new_wd) >= len(current_wd):
        params["windows_detail"] = new_wd
        changes.append(f"windows_detail: {len(current_wd)} floors -> {len(new_wd)} floors (from deep analysis)")

    # Also update windows_per_floor from observations
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
    """Promote facade material/colour observations."""
    changes = []

    # Brick colour hex
    brick_hex = deep.get("brick_colour_hex")
    if brick_hex:
        fd = params.get("facade_detail", {})
        old_hex = fd.get("brick_colour_hex")
        if not old_hex or old_hex in ("#B85A3A", "#D4B896"):  # defaults from enrichment
            fd["brick_colour_hex"] = brick_hex
            params["facade_detail"] = fd
            changes.append(f"facade_detail.brick_colour_hex: '{old_hex}' -> '{brick_hex}'")

    # Bond pattern
    bond = deep.get("brick_bond_observed")
    if bond:
        fd = params.get("facade_detail", {})
        if not fd.get("bond_pattern") or fd["bond_pattern"] == "running bond":
            fd["bond_pattern"] = bond
            params["facade_detail"] = fd
            if bond != "running bond":
                changes.append(f"facade_detail.bond_pattern: '{bond}'")

    # Mortar colour
    mortar = deep.get("mortar_colour")
    if mortar:
        fd = params.get("facade_detail", {})
        if not fd.get("mortar_colour"):
            fd["mortar_colour"] = mortar
            params["facade_detail"] = fd
            changes.append(f"facade_detail.mortar_colour: '{mortar}'")

    # Colour palette
    cp_obs = deep.get("colour_palette_observed")
    if cp_obs and isinstance(cp_obs, dict):
        cp = params.get("colour_palette", {})
        for key in ("facade", "trim", "roof", "accent"):
            if cp_obs.get(key) and not cp.get(key):
                cp[key] = cp_obs[key]
        params["colour_palette"] = cp
        changes.append("colour_palette enriched from observations")

    # Facade material - only if observed is clearly different
    mat_obs = deep.get("facade_material_observed")
    if mat_obs:
        current = (params.get("facade_material") or "").lower()
        obs_lower = mat_obs.lower()
        if "painted" in obs_lower and "painted" not in current:
            params["facade_colour"] = f"painted ({obs_lower})"
            changes.append(f"facade_colour updated: painted observation")

    return changes


def promote_decorative(params, deep):
    """Promote decorative element observations."""
    changes = []
    de_obs = deep.get("decorative_elements_observed")
    if not de_obs or not isinstance(de_obs, dict):
        return changes

    de = params.get("decorative_elements", {})

    # Cornice
    cornice = de_obs.get("cornice")
    if isinstance(cornice, dict) and cornice.get("present"):
        if "cornice" not in de or not isinstance(de.get("cornice"), dict) or not de["cornice"].get("present"):
            de["cornice"] = {"present": True, "height_mm": 200, "projection_mm": 150}
            changes.append("decorative_elements.cornice added")

    # Voussoirs
    vous = de_obs.get("voussoirs")
    if isinstance(vous, dict) and vous.get("present"):
        if "stone_voussoirs" not in de:
            de["stone_voussoirs"] = {"present": True}
            changes.append("decorative_elements.stone_voussoirs added")

    # String courses
    sc = de_obs.get("string_courses")
    if sc and isinstance(sc, list) and len(sc) > 0:
        if "string_courses" not in de or not isinstance(de.get("string_courses"), dict):
            de["string_courses"] = {"present": True, "count": len(sc)}
            changes.append(f"decorative_elements.string_courses: {len(sc)} courses")

    # Quoins
    if de_obs.get("quoins"):
        if "quoins" not in de:
            de["quoins"] = {"present": True}
            changes.append("decorative_elements.quoins added")

    # Dentil course
    if de_obs.get("dentil_course"):
        if "dentil_course" not in de:
            de["dentil_course"] = {"present": True}
            changes.append("decorative_elements.dentil_course added")

    # Brackets
    if de_obs.get("brackets"):
        if "gable_brackets" not in de:
            de["gable_brackets"] = {"present": True}
            changes.append("decorative_elements.gable_brackets added")

    # Ornamental shingles in gable
    if de_obs.get("ornamental_shingles_in_gable"):
        if "ornamental_shingles" not in de:
            de["ornamental_shingles"] = {"present": True}
            changes.append("decorative_elements.ornamental_shingles added")

    # Diamond brick patterns
    if de_obs.get("diamond_brick_patterns"):
        de["polychromatic_brick"] = True
        de["diamond_brick_count"] = de_obs.get("diamond_count_est", 0)
        changes.append("decorative_elements.polychromatic_brick flagged")

    if de:
        params["decorative_elements"] = de

    return changes


def promote_storefront(params, deep):
    """Promote storefront observations."""
    changes = []
    sf_obs = deep.get("storefront_observed")
    if not sf_obs or not isinstance(sf_obs, dict):
        return changes

    sf = params.get("storefront", {})

    if sf_obs.get("awning") and not sf.get("awning"):
        awning = sf_obs["awning"]
        if isinstance(awning, dict) and awning.get("present"):
            sf["awning"] = {
                "present": True,
                "type": awning.get("type", "fixed"),
                "colour": awning.get("colour", "dark"),
            }
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
    """Promote depth/3D measurements."""
    changes = []
    dn = deep.get("depth_notes")
    if not dn or not isinstance(dn, dict):
        return changes

    # Foundation height
    fh = dn.get("foundation_height_m_est")
    if fh and isinstance(fh, (int, float)) and fh > 0:
        params["foundation_height_m"] = fh
        changes.append(f"foundation_height_m: {fh}")

    # Step count
    sc = dn.get("step_count")
    if sc and isinstance(sc, (int, float)) and sc > 0:
        # Add to doors_detail if exists
        doors = params.get("doors_detail", [])
        if doors and isinstance(doors, list):
            for door in doors:
                if isinstance(door, dict) and not door.get("steps"):
                    door["steps"] = int(sc)
            params["doors_detail"] = doors
            changes.append(f"doors_detail.steps: {sc}")

    # Setback
    setback = dn.get("setback_m_est")
    if setback and isinstance(setback, (int, float)) and setback > 0:
        site = params.get("site", {})
        if not site.get("setback_m") or site["setback_m"] == 0:
            site["setback_m"] = setback
            params["site"] = site
            changes.append(f"site.setback_m: {setback}")

    return changes


def promote_doors(params, deep):
    """Promote door observations."""
    changes = []
    doors_obs = deep.get("doors_observed")
    if not doors_obs or not isinstance(doors_obs, list):
        return changes

    current_doors = params.get("doors_detail", [])
    if not current_doors:
        # Create doors_detail from observations
        new_doors = []
        for i, d in enumerate(doors_obs):
            if not isinstance(d, dict):
                continue
            door = {
                "id": f"door_{i+1}",
                "type": d.get("type", "commercial"),
                "position": d.get("position", "center"),
                "width_m": d.get("width_m_est", 0.9),
            }
            if d.get("transom"):
                door["transom"] = {"present": True, "type": "glazed"}
            if d.get("steps"):
                door["steps"] = d["steps"]
            new_doors.append(door)

        if new_doors:
            params["doors_detail"] = new_doors
            changes.append(f"doors_detail: {len(new_doors)} doors created from observations")

    return changes


def main():
    db_lookup = load_db_geometry()
    print(f"Loaded DB geometry for {len(db_lookup)} buildings")

    # Find all Kensington Ave param files with deep_facade_analysis
    files = sorted(PARAMS_DIR.glob("*Kensington_Ave*.json"))
    print(f"Found {len(files)} Kensington Ave param files")

    promoted = 0
    total_changes = 0
    all_changes = {}

    for fpath in files:
        with open(fpath, encoding="utf-8") as f:
            params = json.load(f)

        if params.get("skipped"):
            continue

        deep = params.get("deep_facade_analysis")
        if not deep:
            continue

        addr = params.get("_meta", {}).get("address", fpath.stem.replace("_", " "))
        changes = []

        # Cross-reference with DB
        db_entry = db_lookup.get(addr.upper(), {})
        if db_entry:
            # Validate storey count against DB
            db_stories = db_entry.get("ba_stories") or db_entry.get("BA_STORIES")
            if db_stories and deep.get("storeys_observed"):
                obs = int(deep["storeys_observed"]) if isinstance(deep["storeys_observed"], (int, float)) else None
                if obs and obs != db_stories:
                    changes.append(f"NOTE: storey mismatch DB={db_stories} vs photo={obs}")

        # Run all promotion functions
        changes.extend(promote_roof(params, deep))
        changes.extend(promote_floor_heights(params, deep))
        changes.extend(promote_windows(params, deep))
        changes.extend(promote_facade(params, deep))
        changes.extend(promote_decorative(params, deep))
        changes.extend(promote_storefront(params, deep))
        changes.extend(promote_depth(params, deep))
        changes.extend(promote_doors(params, deep))

        if changes:
            # Update meta
            meta = params.get("_meta", {})
            meta["geometry_revised"] = True
            meta["geometry_revision_ts"] = "2026-03-26"
            meta["geometry_changes"] = changes
            params["_meta"] = meta

            with open(fpath, "w", encoding="utf-8") as f:
                json.dump(params, f, indent=2, ensure_ascii=False)

            promoted += 1
            total_changes += len(changes)
            all_changes[addr] = changes
            print(f"  + {addr}: {len(changes)} changes")

    print(f"\n{'='*60}")
    print(f"GEOMETRY REVISION COMPLETE")
    print(f"  Buildings revised: {promoted}")
    print(f"  Total changes: {total_changes}")
    print(f"  Avg changes per building: {total_changes/max(promoted,1):.1f}")

    # Save report
    report = {
        "promoted": promoted,
        "total_changes": total_changes,
        "changes_by_building": all_changes,
    }
    report_path = DOCS_DIR / "kensington_ave_geometry_revision_report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print(f"\nReport: {report_path}")


if __name__ == "__main__":
    main()
