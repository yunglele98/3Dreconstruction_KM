#!/usr/bin/env python3
"""
Local task runner for Ollama agents.

Scans agent_ops/20_active/ollama-local-* for pending subtask cards,
runs each one through `ollama run`, writes handoffs, and optionally
marks tasks complete.

Usage:
  python scripts/ollama_task_runner.py                    # one pass, all pending
  python scripts/ollama_task_runner.py --loop --interval 60  # continuous polling
  python scripts/ollama_task_runner.py --agent ollama-local-1 # only one worker
  python scripts/ollama_task_runner.py --dry-run            # show what would run
  python scripts/ollama_task_runner.py --model codellama:13b # override model
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
OPS_ROOT = REPO_ROOT / "agent_ops"
ACTIVE_DIR = OPS_ROOT / "20_active"
HANDOFFS_DIR = OPS_ROOT / "30_handoffs"
STATE_CONTROL = OPS_ROOT / "state" / "control_plane.json"
ROUTER_SCRIPT = REPO_ROOT / "scripts" / "agent_delegate_router.py"

OLLAMA_AGENTS = ["ollama-local-1", "ollama-local-2"]

# Resolve ollama binary — may not be on PATH on Windows.
_OLLAMA_CANDIDATES = [
    "ollama",
    Path.home() / "AppData" / "Local" / "Programs" / "Ollama" / "ollama.exe",
    Path("C:/Program Files/Ollama/ollama.exe"),
]


def _find_ollama() -> str:
    import shutil
    for c in _OLLAMA_CANDIDATES:
        if isinstance(c, Path) and c.exists():
            return str(c)
        if isinstance(c, str) and shutil.which(c):
            return c
    return "ollama"  # fallback, let it fail with a clear error


OLLAMA_BIN = _find_ollama()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_control() -> dict:
    if STATE_CONTROL.exists():
        return json.loads(STATE_CONTROL.read_text(encoding="utf-8"))
    return {}


def extract_prompt_from_card(card_path: Path) -> str:
    """Extract the prompt section from a subtask .md card."""
    text = card_path.read_text(encoding="utf-8")
    # Look for ## Prompt section
    match = re.search(r"## Prompt\s*\n(.*)", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    # Fallback: use everything after the frontmatter
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
    """Find all __OLLAMA subtask cards that don't have a handoff yet."""
    pending: list[tuple[str, Path]] = []
    for agent_id in agents:
        agent_dir = ACTIVE_DIR / agent_id
        if not agent_dir.exists():
            continue
        for card in sorted(agent_dir.glob("*__OLLAMA*.md")):
            subtask_id = card.stem
            # Check if handoff already exists
            handoff_pattern = f"{subtask_id}__{agent_id}.md"
            if (HANDOFFS_DIR / handoff_pattern).exists():
                continue
            pending.append((agent_id, card))
    return pending


def run_ollama(model: str, prompt: str, timeout: int) -> subprocess.CompletedProcess:
    """Run ollama with the given prompt."""
    return subprocess.run(
        [OLLAMA_BIN, "run", model, prompt],
        capture_output=True,
        check=False,
        timeout=timeout,
        cwd=str(REPO_ROOT),
        encoding="utf-8",
        errors="replace",
    )


def write_handoff(subtask_id: str, agent_id: str, model: str,
                  result: subprocess.CompletedProcess) -> Path:
    HANDOFFS_DIR.mkdir(parents=True, exist_ok=True)
    handoff = HANDOFFS_DIR / f"{subtask_id}__{agent_id}.md"
    stdout = (result.stdout or "").strip()
    stderr = (result.stderr or "").strip()

    # Truncate very long output to keep handoffs readable
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


def complete_task(subtask_id: str, agent_id: str) -> None:
    """Mark a subtask as complete via the router."""
    subprocess.run(
        [
            sys.executable, str(ROUTER_SCRIPT),
            "complete",
            "--task-id", subtask_id,
            "--agent-id", agent_id,
        ],
        check=False,
        cwd=str(REPO_ROOT),
    )


def run_once(agents: list[str], model: str, timeout: int,
             dry_run: bool, auto_complete: bool) -> int:
    pending = find_pending_cards(agents)
    if not pending:
        print("[OK] No pending Ollama subtasks.")
        return 0

    print(f"[OK] Found {len(pending)} pending subtask(s).")
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
            result = run_ollama(model, prompt, timeout)
            handoff = write_handoff(subtask_id, agent_id, model, result)
            status = "pass" if result.returncode == 0 else "fail"
            print(f"    [{status.upper()}] exit={result.returncode} -> {handoff.name}")

            if auto_complete and result.returncode == 0:
                complete_task(subtask_id, agent_id)
                print(f"    [DONE] Marked {subtask_id} complete.")

        except subprocess.TimeoutExpired:
            err = f"Timed out after {timeout}s"
            write_handoff_error(subtask_id, agent_id, model, err)
            print(f"    [TIMEOUT] {err}")

        except FileNotFoundError:
            print("    [ERR] 'ollama' not found on PATH. Is Ollama installed and running?")
            return executed

        executed += 1

    return executed


def main() -> int:
    control = load_control()
    default_model = control.get("default_ollama_model", "qwen2.5-coder:14b")

    parser = argparse.ArgumentParser(
        description="Local task runner for Ollama agents.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python scripts/ollama_task_runner.py                        # run all pending once\n"
            "  python scripts/ollama_task_runner.py --loop --interval 60   # poll every 60s\n"
            "  python scripts/ollama_task_runner.py --agent ollama-local-1 # one worker only\n"
            "  python scripts/ollama_task_runner.py --dry-run              # preview\n"
        ),
    )
    parser.add_argument(
        "--agent", action="append", default=None,
        help="Ollama agent ID to process (can repeat). Default: all ollama-local-* agents.",
    )
    parser.add_argument(
        "--model", default=default_model,
        help=f"Ollama model to use (default: {default_model}).",
    )
    parser.add_argument(
        "--timeout", type=int, default=300,
        help="Timeout per subtask in seconds (default: 300).",
    )
    parser.add_argument(
        "--loop", action="store_true",
        help="Run continuously, polling for new subtasks.",
    )
    parser.add_argument(
        "--interval", type=int, default=60,
        help="Seconds between polling cycles in --loop mode (default: 60).",
    )
    parser.add_argument(
        "--auto-complete", action="store_true",
        help="Automatically mark subtasks as complete on exit_code 0.",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show what would run without executing.",
    )
    args = parser.parse_args()

    agents = args.agent or OLLAMA_AGENTS

    if args.loop:
        print(f"[OK] Ollama task runner starting (model={args.model}, poll every {args.interval}s)")
        print(f"[OK] Watching agents: {', '.join(agents)}")
        while True:
            run_once(agents, args.model, args.timeout, args.dry_run, args.auto_complete)
            time.sleep(args.interval)
    else:
        run_once(agents, args.model, args.timeout, args.dry_run, args.auto_complete)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
