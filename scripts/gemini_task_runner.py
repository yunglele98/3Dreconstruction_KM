#!/usr/bin/env python3
"""
Local task runner for Gemini agents.

Scans agent_ops/20_active/gemini-* for pending __GEMINI subtask cards,
runs each through `gemini -m <model> -p <prompt>`, writes handoffs.

Usage:
  python scripts/gemini_task_runner.py                     # one pass
  python scripts/gemini_task_runner.py --loop --interval 60  # continuous
  python scripts/gemini_task_runner.py --dry-run             # preview
  python scripts/gemini_task_runner.py --model gemini-2.5-pro  # override model
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
OPS_ROOT = REPO_ROOT / "agent_ops"
ACTIVE_DIR = OPS_ROOT / "20_active"
HANDOFFS_DIR = OPS_ROOT / "30_handoffs"
STATE_CONTROL = OPS_ROOT / "state" / "control_plane.json"


def _find_gemini() -> str:
    import shutil
    # Check PATH first
    found = shutil.which("gemini")
    if found:
        return found
    # Common install locations
    for candidate in [
        Path.home() / "AppData" / "Roaming" / "npm" / "gemini.cmd",
        Path.home() / "AppData" / "Roaming" / "npm" / "gemini",
        Path("C:/Program Files/nodejs/gemini.cmd"),
    ]:
        if candidate.exists():
            return str(candidate)
    return "gemini"


GEMINI_BIN = _find_gemini()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_control() -> dict:
    if STATE_CONTROL.exists():
        return json.loads(STATE_CONTROL.read_text(encoding="utf-8"))
    return {}


def find_gemini_agents() -> list[str]:
    """Find all gemini agent directories under 20_active/."""
    if not ACTIVE_DIR.exists():
        return []
    return [d.name for d in sorted(ACTIVE_DIR.iterdir()) if d.is_dir() and "gemini" in d.name.lower()]


def extract_prompt_from_card(card_path: Path) -> str:
    text = card_path.read_text(encoding="utf-8")
    match = re.search(r"## Prompt\s*\n(.*)", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    lines = text.splitlines()
    content_lines = []
    past_header = False
    for line in lines:
        if past_header:
            content_lines.append(line)
        elif line.startswith("## "):
            past_header = True
            content_lines.append(line)
    return "\n".join(content_lines).strip() or text


def find_pending_cards(agents: list[str]) -> list[tuple[str, Path]]:
    pending: list[tuple[str, Path]] = []
    for agent_id in agents:
        agent_dir = ACTIVE_DIR / agent_id
        if not agent_dir.exists():
            continue
        for card in sorted(agent_dir.glob("*__GEMINI*.md")):
            subtask_id = card.stem
            handoff_md = HANDOFFS_DIR / f"{subtask_id}__{agent_id}.md"
            handoff_json = HANDOFFS_DIR / f"{subtask_id}__{agent_id}.json"
            if handoff_md.exists() or handoff_json.exists():
                continue
            pending.append((agent_id, card))
    return pending


def run_gemini(model: str, prompt: str, timeout: int) -> subprocess.CompletedProcess:
    # On Windows, .cmd files need shell=True to execute properly.
    use_shell = GEMINI_BIN.lower().endswith(".cmd")
    return subprocess.run(
        [GEMINI_BIN, "-m", model, "-p", prompt],
        capture_output=True,
        check=False,
        timeout=timeout,
        cwd=str(REPO_ROOT),
        encoding="utf-8",
        errors="replace",
        shell=use_shell,
    )


def write_handoff(subtask_id: str, agent_id: str, model: str,
                  result: subprocess.CompletedProcess) -> Path:
    HANDOFFS_DIR.mkdir(parents=True, exist_ok=True)
    handoff = HANDOFFS_DIR / f"{subtask_id}__{agent_id}.md"
    stdout = (result.stdout or "").strip()
    stderr = (result.stderr or "").strip()

    max_len = 8000
    if len(stdout) > max_len:
        stdout = stdout[:max_len] + f"\n\n... (truncated, {len(result.stdout)} chars total)"
    if len(stderr) > max_len:
        stderr = stderr[:max_len] + f"\n\n... (truncated, {len(result.stderr)} chars total)"

    handoff.write_text(
        "\n".join([
            f"# Handoff {subtask_id} from {agent_id}",
            "",
            f"- `model`: {model}",
            f"- `exit_code`: {result.returncode}",
            f"- `time`: {utc_now()}",
            f"- `result`: {'pass' if result.returncode == 0 else 'fail'}",
            "",
            "## stdout",
            "",
            stdout or "(empty)",
            "",
            "## stderr",
            "",
            stderr or "(empty)",
            "",
        ]),
        encoding="utf-8",
    )
    return handoff


def write_handoff_error(subtask_id: str, agent_id: str, model: str,
                        error: str) -> Path:
    HANDOFFS_DIR.mkdir(parents=True, exist_ok=True)
    handoff = HANDOFFS_DIR / f"{subtask_id}__{agent_id}.md"
    handoff.write_text(
        "\n".join([
            f"# Handoff {subtask_id} from {agent_id}",
            "",
            f"- `model`: {model}",
            f"- `exit_code`: -1",
            f"- `time`: {utc_now()}",
            f"- `result`: error",
            "",
            "## Error",
            "",
            error,
            "",
        ]),
        encoding="utf-8",
    )
    return handoff


def run_once(agents: list[str], model: str, timeout: int, dry_run: bool) -> int:
    pending = find_pending_cards(agents)
    if not pending:
        print("[OK] No pending Gemini subtasks.")
        return 0

    print(f"[OK] Found {len(pending)} pending Gemini subtask(s).")
    executed = 0

    for agent_id, card in pending:
        subtask_id = card.stem
        prompt = extract_prompt_from_card(card)
        prompt_preview = prompt[:120].replace("\n", " ")

        if dry_run:
            print(f"  [DRY] {subtask_id} ({agent_id}): {prompt_preview}...")
            executed += 1
            continue

        print(f"  [RUN] {subtask_id} ({agent_id}): {prompt_preview}...")

        try:
            result = run_gemini(model, prompt, timeout)
            handoff = write_handoff(subtask_id, agent_id, model, result)
            status = "pass" if result.returncode == 0 else "fail"
            print(f"    [{status.upper()}] exit={result.returncode} -> {handoff.name}")
        except subprocess.TimeoutExpired:
            err = f"Timed out after {timeout}s"
            write_handoff_error(subtask_id, agent_id, model, err)
            print(f"    [TIMEOUT] {err}")
        except FileNotFoundError:
            print("    [ERR] 'gemini' not found on PATH. Is Gemini CLI installed?")
            return executed

        executed += 1

    return executed


def main() -> int:
    control = load_control()
    gemini_cfg = control.get("gemini_dispatch", {})
    default_model = gemini_cfg.get("model", "gemini-2.5-flash")

    parser = argparse.ArgumentParser(
        description="Local task runner for Gemini agents.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--model", default=default_model, help=f"Gemini model (default: {default_model})")
    parser.add_argument("--timeout", type=int, default=300, help="Timeout per subtask in seconds (default: 300)")
    parser.add_argument("--loop", action="store_true", help="Poll continuously")
    parser.add_argument("--interval", type=int, default=60, help="Seconds between polls (default: 60)")
    parser.add_argument("--dry-run", action="store_true", help="Preview without executing")
    args = parser.parse_args()

    agents = find_gemini_agents()
    if not agents:
        print("[OK] No gemini agent directories found.")
        return 0

    print(f"[OK] Gemini task runner (model={args.model}, agents={agents})")

    if args.loop:
        while True:
            run_once(agents, args.model, args.timeout, args.dry_run)
            time.sleep(args.interval)
    else:
        run_once(agents, args.model, args.timeout, args.dry_run)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
