#!/usr/bin/env python3
"""Autofix param drift using photo evidence as ground truth.

Promotes observed values from deep_facade_analysis and photo_observations
into generator-readable param fields where there is a clear mismatch.

Safety: NEVER overwrites total_height_m, facade_width_m, facade_depth_m,
site.*, city_data.*, hcd_data.*.
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
PARAMS_DIR = REPO_ROOT / "params"
OUT_DIR = REPO_ROOT / "outputs"

# Fields that must NEVER be overwritten
PROTECTED_TOP_LEVEL = {"total_height_m", "facade_width_m", "facade_depth_m"}
PROTECTED_SECTIONS = {"site", "city_data", "hcd_data"}

# Valid facade materials for sanity check
VALID_MATERIALS = {"brick", "stone", "stucco", "clapboard", "paint", "wood",
                   "concrete", "metal", "vinyl", "aluminum", "roughcast"}

VALID_ROOF_TYPES = {"flat", "gable", "cross-gable", "hip", "mansard",
                    "gambrel", "shed", "saltbox"}

VALID_CONDITIONS = {"good", "fair", "poor", "excellent"}

ALL_FIELDS = {"brick_colour", "windows", "material", "roof", "condition",
              "storefront", "roof_pitch", "decorative", "colour_palette"}


def _deep(params: dict) -> dict:
    """Return deep_facade_analysis or empty dict."""
    return params.get("deep_facade_analysis") or {}


def _photo_obs(params: dict) -> dict:
    """Return photo_observations or empty dict."""
    return params.get("photo_observations") or {}


def _get_nested(d: dict, *keys: str) -> Any:
    """Safe nested dict access."""
    cur = d
    for k in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(k)
    return cur


def _set_nested(d: dict, keys: list[str], value: Any) -> None:
    """Set a nested key, creating intermediate dicts as needed."""
    for k in keys[:-1]:
        if k not in d or not isinstance(d.get(k), dict):
            d[k] = {}
        d = d[k]
    d[keys[-1]] = value


def fix_brick_colour(params: dict) -> list[dict]:
    """Fix brick_colour_hex from deep_facade_analysis."""
    changes: list[dict] = []
    dfa = _deep(params)
    observed = (dfa.get("brick_colour_hex") or "").strip()
    if not observed or not observed.startswith("#"):
        return changes

    current = _get_nested(params, "facade_detail", "brick_colour_hex") or ""
    if current.lower() != observed.lower():
        old = current or "(empty)"
        _set_nested(params, ["facade_detail", "brick_colour_hex"], observed)
        changes.append({
            "field": "facade_detail.brick_colour_hex",
            "old_value": old,
            "new_value": observed,
            "source": "deep_facade_analysis.brick_colour_hex",
        })
    return changes


def fix_windows(params: dict) -> list[dict]:
    """Fix windows_per_floor from deep_facade_analysis.windows_detail."""
    changes: list[dict] = []
    dfa = _deep(params)
    wd = dfa.get("windows_detail")
    if not wd or not isinstance(wd, list):
        return changes

    # Extract per-floor window counts
    observed_counts = []
    for floor_info in wd:
        if isinstance(floor_info, dict):
            windows = floor_info.get("windows")
            if isinstance(windows, list):
                total = sum(w.get("count", 0) for w in windows if isinstance(w, dict))
                observed_counts.append(total)
            elif isinstance(floor_info.get("count"), (int, float)):
                observed_counts.append(int(floor_info["count"]))

    if not observed_counts:
        return changes

    current = params.get("windows_per_floor")
    if current != observed_counts:
        old = current if current is not None else "(empty)"
        params["windows_per_floor"] = observed_counts
        changes.append({
            "field": "windows_per_floor",
            "old_value": old,
            "new_value": observed_counts,
            "source": "deep_facade_analysis.windows_detail",
        })
    return changes


def fix_material(params: dict) -> list[dict]:
    """Fix facade_material ONLY if clearly different."""
    changes: list[dict] = []
    dfa = _deep(params)
    observed = (dfa.get("facade_material_observed") or "").strip().lower()
    if not observed or observed not in VALID_MATERIALS:
        return changes

    current = (params.get("facade_material") or "").strip().lower()
    if current != observed and current:
        # Only change if clearly different (not just a synonym)
        params["facade_material"] = observed
        changes.append({
            "field": "facade_material",
            "old_value": current,
            "new_value": observed,
            "source": "deep_facade_analysis.facade_material_observed",
        })
    elif not current:
        params["facade_material"] = observed
        changes.append({
            "field": "facade_material",
            "old_value": "(empty)",
            "new_value": observed,
            "source": "deep_facade_analysis.facade_material_observed",
        })
    return changes


def fix_roof(params: dict) -> list[dict]:
    """Fix roof_type ONLY if clearly different."""
    changes: list[dict] = []
    dfa = _deep(params)
    observed = (dfa.get("roof_type_observed") or "").strip().lower()
    if not observed or observed not in VALID_ROOF_TYPES:
        return changes

    current = (params.get("roof_type") or "").strip().lower()
    if current != observed:
        params["roof_type"] = observed
        changes.append({
            "field": "roof_type",
            "old_value": current or "(empty)",
            "new_value": observed,
            "source": "deep_facade_analysis.roof_type_observed",
        })
    return changes


def fix_condition(params: dict) -> list[dict]:
    """Fix condition from deep_facade_analysis or photo_observations."""
    changes: list[dict] = []
    dfa = _deep(params)
    po = _photo_obs(params)

    observed = (dfa.get("condition_observed") or "").strip().lower()
    if not observed:
        observed = (po.get("condition") or "").strip().lower()
    if not observed or observed not in VALID_CONDITIONS:
        return changes

    current = (params.get("condition") or "").strip().lower()
    if current != observed:
        params["condition"] = observed
        changes.append({
            "field": "condition",
            "old_value": current or "(empty)",
            "new_value": observed,
            "source": "deep_facade_analysis.condition_observed",
        })
    return changes


def fix_storefront(params: dict) -> list[dict]:
    """Fix has_storefront from deep_facade_analysis.storefront_observed."""
    changes: list[dict] = []
    dfa = _deep(params)
    sf = dfa.get("storefront_observed")
    if sf is None:
        return changes

    observed = bool(sf) if not isinstance(sf, dict) else True
    if isinstance(sf, dict):
        # If dict is empty or all None, treat as no storefront
        observed = any(v for v in sf.values())

    current = params.get("has_storefront")
    if current != observed:
        params["has_storefront"] = observed
        changes.append({
            "field": "has_storefront",
            "old_value": current if current is not None else "(empty)",
            "new_value": observed,
            "source": "deep_facade_analysis.storefront_observed",
        })
    return changes


def fix_roof_pitch(params: dict) -> list[dict]:
    """Fix roof_pitch_deg from deep_facade_analysis."""
    changes: list[dict] = []
    dfa = _deep(params)
    observed = dfa.get("roof_pitch_deg")
    if observed is None:
        return changes
    try:
        observed = float(observed)
    except (TypeError, ValueError):
        return changes
    if observed <= 0 or observed > 80:
        return changes

    current = params.get("roof_pitch_deg")
    if current != observed:
        params["roof_pitch_deg"] = observed
        changes.append({
            "field": "roof_pitch_deg",
            "old_value": current if current is not None else "(empty)",
            "new_value": observed,
            "source": "deep_facade_analysis.roof_pitch_deg",
        })
    return changes


def fix_decorative(params: dict) -> list[dict]:
    """Merge decorative_elements_observed into decorative_elements."""
    changes: list[dict] = []
    dfa = _deep(params)
    observed = dfa.get("decorative_elements_observed")
    if not observed or not isinstance(observed, dict):
        return changes

    dec = params.get("decorative_elements")
    if not isinstance(dec, dict):
        dec = {}
        params["decorative_elements"] = dec

    for key, val in observed.items():
        if key not in dec and val:
            dec[key] = val
            changes.append({
                "field": f"decorative_elements.{key}",
                "old_value": "(absent)",
                "new_value": val,
                "source": "deep_facade_analysis.decorative_elements_observed",
            })
    return changes


def fix_colour_palette(params: dict) -> list[dict]:
    """Fix colour_palette from deep_facade_analysis.colour_palette_observed."""
    changes: list[dict] = []
    dfa = _deep(params)
    observed = dfa.get("colour_palette_observed")
    if not observed or not isinstance(observed, dict):
        return changes

    palette = params.get("colour_palette")
    if not isinstance(palette, dict):
        palette = {}
        params["colour_palette"] = palette

    for key in ("facade", "trim", "roof", "accent"):
        obs_val = (observed.get(key) or "").strip()
        if obs_val and obs_val.startswith("#"):
            cur_val = palette.get(key, "")
            if (cur_val or "").lower() != obs_val.lower():
                old = cur_val or "(empty)"
                palette[key] = obs_val
                changes.append({
                    "field": f"colour_palette.{key}",
                    "old_value": old,
                    "new_value": obs_val,
                    "source": "deep_facade_analysis.colour_palette_observed",
                })
    return changes


FIELD_FIXERS = {
    "brick_colour": fix_brick_colour,
    "windows": fix_windows,
    "material": fix_material,
    "roof": fix_roof,
    "condition": fix_condition,
    "storefront": fix_storefront,
    "roof_pitch": fix_roof_pitch,
    "decorative": fix_decorative,
    "colour_palette": fix_colour_palette,
}


def atomic_write(path: Path, data: dict) -> None:
    """Write JSON atomically via temp file + os.replace."""
    content = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        os.write(fd, content.encode("utf-8"))
        os.close(fd)
        os.replace(tmp, path)
    except Exception:
        os.close(fd) if not os.get_inheritable(fd) else None
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def process_file(path: Path, fields: set[str], apply: bool) -> dict:
    """Process a single param file. Returns change record or None."""
    data = json.loads(path.read_text(encoding="utf-8"))

    if data.get("skipped"):
        return {"file": path.name, "status": "skipped", "reason": "skipped_file"}

    dfa = _deep(data)
    po = _photo_obs(data)
    if not dfa and not po:
        return {"file": path.name, "status": "skipped", "reason": "no_photo_data"}

    all_changes: list[dict] = []
    for field_name, fixer in FIELD_FIXERS.items():
        if field_name in fields:
            all_changes.extend(fixer(data))

    if not all_changes:
        return {"file": path.name, "status": "skipped", "reason": "no_drift"}

    # Record in _meta
    address = _get_nested(data, "_meta", "address") or path.stem.replace("_", " ")
    meta = data.get("_meta") if isinstance(data.get("_meta"), dict) else {}
    data["_meta"] = meta
    autofix_list = meta.get("autofix_applied", [])
    autofix_list.append({
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "script": "autofix_from_photos",
        "changes_count": len(all_changes),
        "fields_changed": list({c["field"] for c in all_changes}),
    })
    meta["autofix_applied"] = autofix_list

    if apply:
        atomic_write(path, data)

    return {
        "file": path.name,
        "address": address,
        "status": "changed",
        "changes": all_changes,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Autofix param drift using photo evidence as ground truth"
    )
    parser.add_argument("--params", default=str(PARAMS_DIR),
                        help="Path to params directory")
    parser.add_argument("--dry-run", action="store_true",
                        help="Report what would change without writing")
    parser.add_argument("--apply", action="store_true",
                        help="Actually write changes to param files")
    parser.add_argument("--fields", default="all",
                        help="Comma-separated fields to fix, or 'all'")
    parser.add_argument("--report", default=None,
                        help="Path for output report JSON")
    args = parser.parse_args()

    params_dir = Path(args.params)
    apply = args.apply and not args.dry_run

    # Resolve fields
    if args.fields == "all":
        fields = ALL_FIELDS
    else:
        fields = {f.strip() for f in args.fields.split(",")}
        invalid = fields - ALL_FIELDS
        if invalid:
            parser.error(f"Unknown fields: {invalid}. Valid: {sorted(ALL_FIELDS)}")

    param_files = sorted(
        p for p in params_dir.glob("*.json")
        if not p.name.startswith("_")
    )

    results: list[dict] = []
    for pf in param_files:
        result = process_file(pf, fields, apply)
        results.append(result)

    changed = [r for r in results if r["status"] == "changed"]
    skipped = [r for r in results if r["status"] == "skipped"]

    # Per-field stats
    field_stats: dict[str, int] = {}
    for r in changed:
        for c in r.get("changes", []):
            field_stats[c["field"]] = field_stats.get(c["field"], 0) + 1

    summary = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "mode": "apply" if apply else "dry-run",
        "params_dir": str(params_dir.resolve()),
        "fields_requested": sorted(fields),
        "total_files": len(param_files),
        "changed_count": len(changed),
        "skipped_count": len(skipped),
        "field_stats": dict(sorted(field_stats.items(), key=lambda x: -x[1])),
        "changed_files": changed,
        "skipped_files": skipped,
    }

    # Write report
    report_path = Path(args.report) if args.report else (
        OUT_DIR / f"autofix_report_{time.strftime('%Y%m%d_%H%M%S')}.json"
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    print("=== Autofix From Photos ===")
    print(f"Mode:    {summary['mode']}")
    print(f"Files:   {summary['total_files']}")
    print(f"Changed: {summary['changed_count']}")
    print(f"Skipped: {summary['skipped_count']}")
    print(f"--- Per-field changes ---")
    for field, count in sorted(field_stats.items(), key=lambda x: -x[1]):
        print(f"  {field}: {count}")
    print(f"Report:  {report_path}")


if __name__ == "__main__":
    main()
