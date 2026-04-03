#!/usr/bin/env python3
"""Targeted colour correction using photo evidence.

Compares facade_detail.brick_colour_hex against
deep_facade_analysis.brick_colour_hex using approximate CIE76 delta-E
in Lab colour space. Updates colour when delta-E exceeds threshold.

Safety: only changes colour fields, never structural params.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import tempfile
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
PARAMS_DIR = REPO_ROOT / "params"
OUT_DIR = REPO_ROOT / "outputs"

DEFAULT_DELTA_E_THRESHOLD = 15.0


# ---------------------------------------------------------------------------
# Colour conversion helpers (no external deps)
# ---------------------------------------------------------------------------

def hex_to_rgb(hex_str: str) -> tuple[float, float, float] | None:
    """Convert '#RRGGBB' to (R, G, B) in [0, 255]."""
    h = hex_str.strip().lstrip("#")
    if len(h) != 6:
        return None
    try:
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        return (r, g, b)
    except ValueError:
        return None


def _srgb_linearize(c: float) -> float:
    """Linearize an sRGB channel (0-1)."""
    if c <= 0.04045:
        return c / 12.92
    return ((c + 0.055) / 1.055) ** 2.4


def rgb_to_lab(r: int, g: int, b: int) -> tuple[float, float, float]:
    """Convert sRGB (0-255) to CIE L*a*b* (D65 illuminant)."""
    # sRGB → linear
    rl = _srgb_linearize(r / 255.0)
    gl = _srgb_linearize(g / 255.0)
    bl = _srgb_linearize(b / 255.0)

    # Linear RGB → XYZ (D65)
    x = rl * 0.4124564 + gl * 0.3575761 + bl * 0.1804375
    y = rl * 0.2126729 + gl * 0.7151522 + bl * 0.0721750
    z = rl * 0.0193339 + gl * 0.1191920 + bl * 0.9503041

    # D65 reference white
    xn, yn, zn = 0.95047, 1.0, 1.08883

    def f(t: float) -> float:
        if t > 0.008856:
            return t ** (1.0 / 3.0)
        return 7.787 * t + 16.0 / 116.0

    fx, fy, fz = f(x / xn), f(y / yn), f(z / zn)

    L = 116.0 * fy - 16.0
    a = 500.0 * (fx - fy)
    b_val = 200.0 * (fy - fz)
    return (L, a, b_val)


def delta_e_cie76(hex1: str, hex2: str) -> float | None:
    """Compute CIE76 delta-E between two hex colours."""
    rgb1 = hex_to_rgb(hex1)
    rgb2 = hex_to_rgb(hex2)
    if rgb1 is None or rgb2 is None:
        return None
    lab1 = rgb_to_lab(*rgb1)
    lab2 = rgb_to_lab(*rgb2)
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(lab1, lab2)))


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


def process_file(path: Path, threshold: float, apply: bool) -> dict:
    """Process a single param file for colour correction."""
    data = json.loads(path.read_text(encoding="utf-8"))

    if data.get("skipped"):
        return {"file": path.name, "status": "skipped", "reason": "skipped_file"}

    dfa = data.get("deep_facade_analysis")
    if not isinstance(dfa, dict):
        return {"file": path.name, "status": "skipped", "reason": "no_deep_facade_analysis"}

    changes: list[dict] = []

    # --- Brick colour ---
    observed_brick = (dfa.get("brick_colour_hex") or "").strip()
    current_brick = (_get_nested(data, "facade_detail", "brick_colour_hex") or "").strip()

    if observed_brick and observed_brick.startswith("#"):
        if current_brick and current_brick.startswith("#"):
            de = delta_e_cie76(current_brick, observed_brick)
            if de is not None and de > threshold:
                _set_nested(data, ["facade_detail", "brick_colour_hex"], observed_brick)
                changes.append({
                    "field": "facade_detail.brick_colour_hex",
                    "old_value": current_brick,
                    "new_value": observed_brick,
                    "delta_e": round(de, 2),
                    "source": "deep_facade_analysis.brick_colour_hex",
                })
        elif not current_brick:
            _set_nested(data, ["facade_detail", "brick_colour_hex"], observed_brick)
            changes.append({
                "field": "facade_detail.brick_colour_hex",
                "old_value": "(empty)",
                "new_value": observed_brick,
                "delta_e": None,
                "source": "deep_facade_analysis.brick_colour_hex",
            })

    # --- Sync colour_palette.facade to match brick colour ---
    new_brick = _get_nested(data, "facade_detail", "brick_colour_hex") or ""
    if new_brick:
        palette = data.get("colour_palette")
        if not isinstance(palette, dict):
            palette = {}
            data["colour_palette"] = palette
        cur_facade = (palette.get("facade") or "").strip()
        if cur_facade.lower() != new_brick.lower():
            old_facade = cur_facade or "(empty)"
            palette["facade"] = new_brick
            # Only log if this wasn't already logged as part of brick change
            if not any(c["field"] == "colour_palette.facade" for c in changes):
                changes.append({
                    "field": "colour_palette.facade",
                    "old_value": old_facade,
                    "new_value": new_brick,
                    "delta_e": None,
                    "source": "synced from facade_detail.brick_colour_hex",
                })

    # --- Full colour_palette_observed ---
    palette_obs = dfa.get("colour_palette_observed")
    if isinstance(palette_obs, dict):
        palette = data.get("colour_palette")
        if not isinstance(palette, dict):
            palette = {}
            data["colour_palette"] = palette

        for key in ("trim", "roof", "accent"):
            obs_val = (palette_obs.get(key) or "").strip()
            if obs_val and obs_val.startswith("#"):
                cur_val = (palette.get(key) or "").strip()
                if cur_val and cur_val.startswith("#"):
                    de = delta_e_cie76(cur_val, obs_val)
                    if de is not None and de > threshold:
                        palette[key] = obs_val
                        changes.append({
                            "field": f"colour_palette.{key}",
                            "old_value": cur_val,
                            "new_value": obs_val,
                            "delta_e": round(de, 2),
                            "source": f"deep_facade_analysis.colour_palette_observed.{key}",
                        })
                elif not cur_val:
                    palette[key] = obs_val
                    changes.append({
                        "field": f"colour_palette.{key}",
                        "old_value": "(empty)",
                        "new_value": obs_val,
                        "delta_e": None,
                        "source": f"deep_facade_analysis.colour_palette_observed.{key}",
                    })

        # Also handle facade from palette_observed if not yet set by brick
        facade_obs = (palette_obs.get("facade") or "").strip()
        if facade_obs and facade_obs.startswith("#"):
            cur_facade = (palette.get("facade") or "").strip()
            if cur_facade and cur_facade.startswith("#"):
                de = delta_e_cie76(cur_facade, facade_obs)
                if de is not None and de > threshold:
                    palette["facade"] = facade_obs
                    if not any(c["field"] == "colour_palette.facade" for c in changes):
                        changes.append({
                            "field": "colour_palette.facade",
                            "old_value": cur_facade,
                            "new_value": facade_obs,
                            "delta_e": round(de, 2),
                            "source": "deep_facade_analysis.colour_palette_observed.facade",
                        })
            elif not cur_facade:
                palette["facade"] = facade_obs
                if not any(c["field"] == "colour_palette.facade" for c in changes):
                    changes.append({
                        "field": "colour_palette.facade",
                        "old_value": "(empty)",
                        "new_value": facade_obs,
                        "delta_e": None,
                        "source": "deep_facade_analysis.colour_palette_observed.facade",
                    })

    # --- Mortar colour ---
    mortar_obs = (dfa.get("mortar_colour") or "").strip()
    if mortar_obs:
        cur_mortar = _get_nested(data, "facade_detail", "mortar_colour") or ""
        if (cur_mortar or "").lower() != mortar_obs.lower():
            _set_nested(data, ["facade_detail", "mortar_colour"], mortar_obs)
            changes.append({
                "field": "facade_detail.mortar_colour",
                "old_value": cur_mortar or "(empty)",
                "new_value": mortar_obs,
                "delta_e": None,
                "source": "deep_facade_analysis.mortar_colour",
            })

    if not changes:
        return {"file": path.name, "status": "skipped", "reason": "no_colour_drift"}

    # Record in _meta
    meta = data.get("_meta") if isinstance(data.get("_meta"), dict) else {}
    data["_meta"] = meta
    color_list = meta.get("autofix_color_applied", [])
    color_list.append({
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "script": "autofix_color_from_photos",
        "delta_e_threshold": threshold,
        "changes_count": len(changes),
        "fields_changed": list({c["field"] for c in changes}),
    })
    meta["autofix_color_applied"] = color_list

    if apply:
        atomic_write(path, data)

    address = (meta.get("address") or path.stem.replace("_", " "))
    return {
        "file": path.name,
        "address": address,
        "status": "changed",
        "changes": changes,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Targeted colour correction from photo evidence"
    )
    parser.add_argument("--params", default=str(PARAMS_DIR),
                        help="Path to params directory")
    parser.add_argument("--dry-run", action="store_true",
                        help="Report what would change without writing")
    parser.add_argument("--apply", action="store_true",
                        help="Actually write changes to param files")
    parser.add_argument("--delta-e-threshold", type=float,
                        default=DEFAULT_DELTA_E_THRESHOLD,
                        help="Delta-E threshold for colour update (default 15)")
    parser.add_argument("--report", default=None,
                        help="Path for output report JSON")
    args = parser.parse_args()

    params_dir = Path(args.params)
    threshold = args.delta_e_threshold
    apply = args.apply and not args.dry_run

    param_files = sorted(
        p for p in params_dir.glob("*.json")
        if not p.name.startswith("_")
    )

    results: list[dict] = []
    for pf in param_files:
        result = process_file(pf, threshold, apply)
        results.append(result)

    changed = [r for r in results if r["status"] == "changed"]
    skipped = [r for r in results if r["status"] == "skipped"]

    # Per-field stats
    field_stats: dict[str, int] = {}
    delta_e_values: list[float] = []
    for r in changed:
        for c in r.get("changes", []):
            field_stats[c["field"]] = field_stats.get(c["field"], 0) + 1
            if c.get("delta_e") is not None:
                delta_e_values.append(c["delta_e"])

    summary = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "mode": "apply" if apply else "dry-run",
        "params_dir": str(params_dir.resolve()),
        "delta_e_threshold": threshold,
        "total_files": len(param_files),
        "changed_count": len(changed),
        "skipped_count": len(skipped),
        "delta_e_stats": {
            "count": len(delta_e_values),
            "min": round(min(delta_e_values), 2) if delta_e_values else None,
            "max": round(max(delta_e_values), 2) if delta_e_values else None,
            "mean": round(sum(delta_e_values) / len(delta_e_values), 2) if delta_e_values else None,
        },
        "field_stats": dict(sorted(field_stats.items(), key=lambda x: -x[1])),
        "changed_files": changed,
        "skipped_files": skipped,
    }

    report_path = Path(args.report) if args.report else (
        OUT_DIR / f"autofix_color_report_{time.strftime('%Y%m%d_%H%M%S')}.json"
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    print("=== Autofix Colour From Photos ===")
    print(f"Mode:      {summary['mode']}")
    print(f"Threshold: delta-E > {threshold}")
    print(f"Files:     {summary['total_files']}")
    print(f"Changed:   {summary['changed_count']}")
    print(f"Skipped:   {summary['skipped_count']}")
    if delta_e_values:
        print(f"Delta-E:   min={summary['delta_e_stats']['min']}, "
              f"max={summary['delta_e_stats']['max']}, "
              f"mean={summary['delta_e_stats']['mean']}")
    print(f"--- Per-field changes ---")
    for field, count in sorted(field_stats.items(), key=lambda x: -x[1]):
        print(f"  {field}: {count}")
    print(f"Report:    {report_path}")


if __name__ == "__main__":
    main()
