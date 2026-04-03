#!/usr/bin/env python3
"""
Compute deterministic content hashes for param files and build regen queue.

Compares hashes against existing manifests to classify buildings as
stale (param changed), new (no manifest), or fresh (hash matches).

Output: outputs/param_fingerprints.json, outputs/regen_queue.json
"""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PARAMS_DIR = ROOT / "params"
MANIFESTS_DIR = ROOT / "outputs" / "full"
OUTPUT_DIR = ROOT / "outputs"


def param_hash(params: dict) -> str:
    """Compute md5 hash of params with _meta excluded and keys sorted."""
    cleaned = {k: v for k, v in params.items() if k != "_meta"}
    content = json.dumps(cleaned, sort_keys=True, ensure_ascii=False)
    return hashlib.md5(content.encode("utf-8")).hexdigest()


def load_manifests() -> dict:
    """Load all manifests from outputs/full/. Returns {param_filename: manifest_data}."""
    manifests = {}
    if not MANIFESTS_DIR.exists():
        return manifests
    for mf in MANIFESTS_DIR.glob("*.manifest.json"):
        try:
            with open(mf, encoding="utf-8") as f:
                data = json.load(f)
            pf = data.get("param_file", "")
            if pf:
                manifests[Path(pf).name] = data
        except (json.JSONDecodeError, OSError):
            continue
    return manifests


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Fingerprint params and build regen queue")
    parser.add_argument("--params-dir", type=Path, default=PARAMS_DIR)
    parser.add_argument("--manifests-dir", type=Path, default=MANIFESTS_DIR)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--street", type=str, default=None, help="Only fingerprint this street")
    args = parser.parse_args()

    manifests = load_manifests()
    fingerprints = {}
    stale, new, fresh = [], [], []

    for param_file in sorted(PARAMS_DIR.glob("*.json")):
        if param_file.name.startswith("_") or "backup" in param_file.name:
            continue
        with open(param_file, encoding="utf-8") as f:
            params = json.load(f)
        if params.get("skipped"):
            continue

        h = param_hash(params)
        address = params.get("building_name", param_file.stem.replace("_", " "))
        mtime = param_file.stat().st_mtime

        fingerprints[address] = {
            "hash": h,
            "mtime": mtime,
            "file": param_file.name,
        }

        manifest = manifests.get(param_file.name)
        if not manifest:
            new.append({"address": address, "file": param_file.name, "hash": h})
        else:
            # Compare hash if stored, otherwise compare mtime
            manifest_hash = manifest.get("param_hash")
            if manifest_hash and manifest_hash == h:
                fresh.append({"address": address, "file": param_file.name})
            else:
                stale.append({"address": address, "file": param_file.name, "hash": h})

    # Write fingerprints
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    fp_path = OUTPUT_DIR / "param_fingerprints.json"
    with open(fp_path, "w", encoding="utf-8") as f:
        json.dump(fingerprints, f, indent=2, ensure_ascii=False)
        f.write("\n")

    # Write regen queue
    queue = {"stale": stale, "new": new, "fresh": fresh}
    queue_path = OUTPUT_DIR / "regen_queue.json"
    with open(queue_path, "w", encoding="utf-8") as f:
        json.dump(queue, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print(f"Param Fingerprinting")
    print(f"{'='*50}")
    print(f"Stale: {len(stale)}, New: {len(new)}, Fresh: {len(fresh)}")
    print(f"Fingerprints: {fp_path}")
    print(f"Regen queue: {queue_path}")


if __name__ == "__main__":
    main()
