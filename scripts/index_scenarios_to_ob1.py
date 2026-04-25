"""Index Kensington 10yr scenarios into Open Brain (OB1).

Each scenarios/<scenario_id>/ directory becomes one OB1 thought, built from
metadata.json (description, principles, intervention counts) plus summaries
extracted from interventions.json / heritage_impact.json / density_analysis.json.

Metadata captured per thought:
    source:         3Dreconstruction_KM
    kind:           scenario
    scenario_id:    heritage_first
    scenario_name:  "Heritage First (2036)"
    intervention_count: 40
    last_indexed:   <ISO 8601>

Searchable later from anywhere with the OB1 MCP wired up:
    ob1 search "heritage preservation 2036"
    ob1 search "density gentle infill"
    ob1 search "shadow analysis mobility scenario"

Idempotent: server-side fingerprint dedup + local manifest at
.ob1-scenario-manifest.json (gitignored).

Credentials resolution: env (MCP_CONNECTION_URL, SUPABASE_ANON_KEY) ->
~/open-brain/.env.

Usage:
    python3 scripts/index_scenarios_to_ob1.py             # incremental
    python3 scripts/index_scenarios_to_ob1.py --force     # full re-index
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SCENARIOS = ROOT / "scenarios"
MANIFEST = ROOT / ".ob1-scenario-manifest.json"
MAX_CONTENT = 30_000


def _load_dotenv() -> dict[str, str]:
    p = Path.home() / "open-brain" / ".env"
    if not p.exists():
        return {}
    out: dict[str, str] = {}
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def resolve_creds() -> tuple[str, str]:
    env = _load_dotenv()
    url = os.environ.get("MCP_CONNECTION_URL") or env.get("MCP_CONNECTION_URL")
    anon = os.environ.get("SUPABASE_ANON_KEY") or env.get("SUPABASE_ANON_KEY")
    if not url or not anon:
        sys.exit("ERROR: need MCP_CONNECTION_URL and SUPABASE_ANON_KEY")
    return url, anon


def _read_json(p: Path) -> dict[str, Any]:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def render_scenario(scenario_dir: Path) -> tuple[str, dict[str, Any]] | None:
    """Build (content, metadata) for one scenario directory, or None to skip."""
    metadata = _read_json(scenario_dir / "metadata.json")
    if not metadata:
        return None
    interventions = _read_json(scenario_dir / "interventions.json")
    heritage = _read_json(scenario_dir / "heritage_impact.json")
    density = _read_json(scenario_dir / "density_analysis.json")
    shadow = _read_json(scenario_dir / "shadow_analysis.json")

    scenario_id = metadata.get("scenario_id", scenario_dir.name)
    name = metadata.get("name", scenario_id)
    description = metadata.get("description", "")
    principles = metadata.get("principles", [])
    types = metadata.get("intervention_types", {})
    total = metadata.get("total_interventions") or len(
        interventions.get("interventions", []) if isinstance(interventions, dict) else []
    )

    parts = [f"# Scenario: {name}", f"scenario_id: `{scenario_id}`", "", description]
    if principles:
        parts += ["", "## Principles"]
        parts += [f"- {p}" for p in principles]
    if types:
        parts += ["", "## Intervention types"]
        parts += [f"- {k}: {v}" for k, v in types.items()]
    if heritage:
        parts += ["", "## Heritage impact (summary)",
                  json.dumps(_compact(heritage), indent=2, default=str)]
    if density:
        parts += ["", "## Density analysis (summary)",
                  json.dumps(_compact(density), indent=2, default=str)]
    if shadow:
        parts += ["", "## Shadow analysis (summary)",
                  json.dumps(_compact(shadow), indent=2, default=str)]

    content = "\n".join(parts)
    if len(content) > MAX_CONTENT:
        content = content[: MAX_CONTENT - 100] + "\n\n[…truncated…]"

    meta = {
        "source": "3Dreconstruction_KM",
        "kind": "scenario",
        "scenario_id": scenario_id,
        "scenario_name": name,
        "intervention_count": total,
        "last_indexed": datetime.now(timezone.utc).isoformat(),
    }
    return content, meta


def _compact(obj: Any, maxlen: int = 4_000) -> Any:
    """Strip array tails and long strings so a summary fits in one thought."""
    if isinstance(obj, list):
        if len(obj) > 5:
            return obj[:5] + [f"… +{len(obj) - 5} more"]
        return [_compact(x, maxlen) for x in obj]
    if isinstance(obj, dict):
        return {k: _compact(v, maxlen) for k, v in obj.items()}
    if isinstance(obj, str) and len(obj) > maxlen:
        return obj[:maxlen] + "…"
    return obj


def _hash(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]


def _load_manifest() -> dict[str, str]:
    if not MANIFEST.exists():
        return {}
    try:
        return json.loads(MANIFEST.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_manifest(m: dict[str, str]) -> None:
    MANIFEST.write_text(json.dumps(m, indent=2, sort_keys=True), encoding="utf-8")


def post(url: str, anon: str, content: str, metadata: dict) -> tuple[bool, str]:
    payload = {
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "capture_thought",
                   "arguments": {"content": content, "metadata": metadata}},
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {anon}",
            "apikey": anon,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status == 200, r.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}: {e.reason}"
    except (urllib.error.URLError, TimeoutError) as e:
        return False, f"unreachable: {e}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    if not SCENARIOS.exists():
        sys.exit(f"ERROR: scenarios dir not found: {SCENARIOS}")

    url, anon = resolve_creds()
    manifest = {} if args.force else _load_manifest()
    indexed = unchanged = skipped = failed = 0

    for scenario_dir in sorted(p for p in SCENARIOS.iterdir() if p.is_dir()):
        rendered = render_scenario(scenario_dir)
        if rendered is None:
            skipped += 1
            continue
        content, meta = rendered
        h = _hash(content)
        key = scenario_dir.name
        if manifest.get(key) == h:
            unchanged += 1
            continue
        ok, resp = post(url, anon, content, meta)
        if ok:
            indexed += 1
            manifest[key] = h
            print(f"  ok  {key}  ({meta['intervention_count']} interventions)")
        else:
            failed += 1
            print(f"  FAIL {key}: {resp[:120]}")

    if not args.force or indexed > 0:
        _save_manifest(manifest)

    print()
    print(f"# scenarios -> OB1 -- {datetime.now(timezone.utc).isoformat()}")
    print(f"- Indexed: {indexed}   Unchanged: {unchanged}   "
          f"Skipped (no metadata.json): {skipped}   Failed: {failed}")


if __name__ == "__main__":
    main()
