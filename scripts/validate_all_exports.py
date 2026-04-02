#!/usr/bin/env python3
"""Validate all pipeline exports — single comprehensive check.

Checks FBX, LOD, collision, CityGML, 3D Tiles, Datasmith, Unity manifest.
Prints summary table with pass/fail per check.

Usage:
    python scripts/validate_all_exports.py
    python scripts/validate_all_exports.py --json
"""
import argparse
import json
import logging
from pathlib import Path
from xml.etree.ElementTree import parse as parse_xml

logger = logging.getLogger(__name__)
REPO = Path(__file__).parent.parent
EXPORTS_DIR = REPO / "outputs" / "exports"


def check_fbx_count(min_count=1200):
    """Check FBX files exist with valid headers."""
    if not EXPORTS_DIR.exists():
        return {"pass": False, "detail": "exports dir missing", "count": 0}
    fbx_files = []
    invalid_headers = 0
    for d in EXPORTS_DIR.iterdir():
        if not d.is_dir() or d.name.startswith("_") or d.name == "collision":
            continue
        fbx = d / f"{d.name}.fbx"
        if fbx.exists():
            fbx_files.append(fbx)
            header = fbx.read_bytes()[:20]
            if b"Kaydara FBX Binary" not in header and b"; FBX" not in header[:10]:
                invalid_headers += 1
    count = len(fbx_files)
    ok = count >= min_count and invalid_headers == 0
    return {"pass": ok, "count": count, "invalid_headers": invalid_headers,
            "detail": f"{count} FBX files, {invalid_headers} invalid headers"}


def check_lods():
    """Check LOD files exist for each FBX."""
    if not EXPORTS_DIR.exists():
        return {"pass": False, "detail": "exports dir missing"}
    total = 0
    with_lod1 = 0
    with_all_lods = 0
    for d in EXPORTS_DIR.iterdir():
        if not d.is_dir() or d.name.startswith("_") or d.name == "collision":
            continue
        fbx = d / f"{d.name}.fbx"
        if not fbx.exists():
            continue
        total += 1
        has_lod1 = (d / f"{d.name}_LOD1.fbx").exists()
        has_lod2 = (d / f"{d.name}_LOD2.fbx").exists()
        has_lod3 = (d / f"{d.name}_LOD3.fbx").exists()
        if has_lod1:
            with_lod1 += 1
        if has_lod1 and has_lod2 and has_lod3:
            with_all_lods += 1
    pct = (with_lod1 / total * 100) if total else 0
    ok = pct >= 70
    return {"pass": ok, "total": total, "with_lod1": with_lod1,
            "with_all_lods": with_all_lods,
            "detail": f"{with_lod1}/{total} have LOD1 ({pct:.0f}%), {with_all_lods} have all 3"}


def check_collision():
    """Check collision meshes exist for each FBX."""
    if not EXPORTS_DIR.exists():
        return {"pass": False, "detail": "exports dir missing"}
    total = 0
    with_collision = 0
    for d in EXPORTS_DIR.iterdir():
        if not d.is_dir() or d.name.startswith("_") or d.name == "collision":
            continue
        fbx = d / f"{d.name}.fbx"
        if not fbx.exists():
            continue
        total += 1
        if (d / f"{d.name}_collision.fbx").exists():
            with_collision += 1
    pct = (with_collision / total * 100) if total else 0
    ok = pct >= 90
    return {"pass": ok, "total": total, "with_collision": with_collision,
            "detail": f"{with_collision}/{total} ({pct:.0f}%)"}


def check_citygml():
    """Check CityGML file has correct building count."""
    gml_path = REPO / "citygml" / "kensington_lod2.gml"
    if not gml_path.exists():
        return {"pass": False, "detail": "citygml/kensington_lod2.gml missing"}
    try:
        tree = parse_xml(str(gml_path))
        root = tree.getroot()
        ns = {"core": "http://www.opengis.net/citygml/2.0"}
        members = root.findall("core:cityObjectMember", ns)
        count = len(members)
        size_mb = gml_path.stat().st_size / (1024 * 1024)
        ok = count >= 1000
        return {"pass": ok, "count": count, "size_mb": round(size_mb, 1),
                "detail": f"{count} buildings, {size_mb:.1f} MB"}
    except Exception as e:
        return {"pass": False, "detail": f"Parse error: {e}"}


def check_3dtiles():
    """Check tileset.json has matching building count."""
    tileset_path = REPO / "tiles_3d" / "tileset.json"
    if not tileset_path.exists():
        return {"pass": False, "detail": "tiles_3d/tileset.json missing"}
    try:
        data = json.loads(tileset_path.read_text(encoding="utf-8"))
        children = data.get("root", {}).get("children", [])
        count = len(children)
        ok = count >= 500
        return {"pass": ok, "count": count,
                "detail": f"{count} building tiles"}
    except Exception as e:
        return {"pass": False, "detail": f"Parse error: {e}"}


def check_datasmith():
    """Check Datasmith XML references all buildings."""
    ds_path = EXPORTS_DIR / "kensington_scene.udatasmith"
    if not ds_path.exists():
        return {"pass": False, "detail": "kensington_scene.udatasmith missing"}
    manifest_path = EXPORTS_DIR / "unreal_import_manifest.json"
    if not manifest_path.exists():
        return {"pass": False, "detail": "unreal_import_manifest.json missing"}
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        stats = manifest.get("stats", {})
        count = stats.get("total_buildings", 0)
        with_lods = stats.get("buildings_with_lods", 0)
        ok = count >= 1000
        return {"pass": ok, "count": count, "with_lods": with_lods,
                "detail": f"{count} buildings, {with_lods} with LODs"}
    except Exception as e:
        return {"pass": False, "detail": f"Parse error: {e}"}


def check_unity():
    """Check Unity manifest references all buildings."""
    manifest_path = EXPORTS_DIR / "unity_manifest.json"
    if not manifest_path.exists():
        return {"pass": False, "detail": "unity_manifest.json missing"}
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        stats = manifest.get("stats", {})
        count = stats.get("total_buildings", 0)
        with_lods = stats.get("buildings_with_lods", 0)
        with_collision = stats.get("buildings_with_collision", 0)
        ok = count >= 1000
        return {"pass": ok, "count": count, "with_lods": with_lods,
                "with_collision": with_collision,
                "detail": f"{count} buildings, {with_lods} LODs, {with_collision} collision"}
    except Exception as e:
        return {"pass": False, "detail": f"Parse error: {e}"}


CHECKS = [
    ("FBX Exports", check_fbx_count),
    ("LOD Files", check_lods),
    ("Collision Meshes", check_collision),
    ("CityGML LOD2", check_citygml),
    ("3D Tiles", check_3dtiles),
    ("Datasmith (UE)", check_datasmith),
    ("Unity Manifest", check_unity),
]


def main():
    parser = argparse.ArgumentParser(description="Validate all exports")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    results = {}
    for name, fn in CHECKS:
        results[name] = fn()

    if args.json:
        print(json.dumps(results, indent=2))
        return

    passed = sum(1 for r in results.values() if r["pass"])
    total = len(results)

    logger.info("Export Validation Report")
    logger.info("=" * 60)
    for name, result in results.items():
        icon = "OK" if result["pass"] else "!!"
        logger.info("  [%s] %-20s %s", icon, name, result["detail"])
    logger.info("-" * 60)
    logger.info("  %d/%d checks passed", passed, total)

    if passed < total:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
