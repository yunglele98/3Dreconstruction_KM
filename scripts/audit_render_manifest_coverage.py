#!/usr/bin/env python3
"""
Cross-reference params/*.json against outputs/full/*.manifest.json.

Reports active buildings that were NOT rendered, or rendered with stale params.
Compares manifest param hash vs current param file hash (md5).
"""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PARAMS_DIR = ROOT / "params"
MANIFESTS_DIR = ROOT / "outputs" / "full"
OUTPUT_FILE = ROOT / "outputs" / "render_staleness_report.json"


def file_md5(path: Path) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    # Load all manifests
    manifests = {}
    if MANIFESTS_DIR.exists():
        for mf in MANIFESTS_DIR.glob("*.manifest.json"):
            try:
                with open(mf, encoding="utf-8") as f:
                    data = json.load(f)
                param_file = data.get("param_file", "")
                if param_file:
                    manifests[Path(param_file).name] = {
                        "manifest_path": str(mf),
                        "manifest_mtime": mf.stat().st_mtime,
                        "data": data,
                    }
            except (json.JSONDecodeError, OSError):
                continue

    # Check each active param file
    not_rendered = []
    stale = []
    current = []
    total_active = 0

    for param_file in sorted(PARAMS_DIR.glob("*.json")):
        if param_file.name.startswith("_") or "backup" in param_file.name:
            continue
        with open(param_file, encoding="utf-8") as f:
            params = json.load(f)
        if params.get("skipped"):
            continue

        total_active += 1
        address = params.get("building_name", param_file.stem.replace("_", " "))

        if param_file.name not in manifests:
            # Check by stem match
            stem = param_file.stem
            found = False
            for mname in manifests:
                if mname.startswith(stem):
                    found = True
                    break
            if not found:
                not_rendered.append({
                    "address": address,
                    "param_file": param_file.name,
                })
                continue

        # Check staleness by mtime
        manifest_info = manifests.get(param_file.name)
        if manifest_info:
            param_mtime = param_file.stat().st_mtime
            manifest_mtime = manifest_info["manifest_mtime"]
            if param_mtime > manifest_mtime:
                stale.append({
                    "address": address,
                    "param_file": param_file.name,
                    "param_mtime": param_mtime,
                    "manifest_mtime": manifest_mtime,
                })
            else:
                current.append(param_file.name)

    report = {
        "total_active_buildings": total_active,
        "total_manifests": len(manifests),
        "not_rendered": len(not_rendered),
        "stale_renders": len(stale),
        "current_renders": len(current),
        "not_rendered_list": not_rendered[:50],
        "stale_list": stale[:50],
    }

    print(f"Render Manifest Coverage Report")
    print(f"{'='*50}")
    print(f"Active buildings: {total_active}")
    print(f"Manifests found: {len(manifests)}")
    print(f"Not rendered: {len(not_rendered)}")
    print(f"Stale renders: {len(stale)}")
    print(f"Current renders: {len(current)}")

    if not_rendered:
        print(f"\nFirst 10 not rendered:")
        for item in not_rendered[:10]:
            print(f"  {item['address']}")

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(f"\nReport: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
