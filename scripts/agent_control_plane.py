#!/usr/bin/env python3
"""
Tiered control plane:
1) route backlog to manager agents (Claude/Codex/Gemini)
2) auto-dispatch eligible execution subtasks to local Ollama workers
3) auto-dispatch eligible validation/research subtasks to Gemini
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
OPS_ROOT = REPO_ROOT / "agent_ops"
STATE_AGENTS = OPS_ROOT / "state" / "agents.json"
STATE_CONTROL = OPS_ROOT / "state" / "control_plane.json"
BACKLOG_DIR = OPS_ROOT / "10_backlog"
ACTIVE_DIR = OPS_ROOT / "20_active"
HANDOFFS_DIR = OPS_ROOT / "30_handoffs"
OWNERSHIP_DIR = OPS_ROOT / "coordination" / "ownership"
LOCKS_DIR = OPS_ROOT / "coordination" / "locks"
ROUTER_SCRIPT = REPO_ROOT / "scripts" / "agent_delegate_router.py"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def run_router_for_managers() -> None:
    subprocess.run(
        [
            sys.executable,
            str(ROUTER_SCRIPT),
            "route",
            "--state-file",
            str(STATE_AGENTS),
            "--backlog-dir",
            str(BACKLOG_DIR),
        ],
        check=True,
        cwd=str(REPO_ROOT),
    )


def route_only_to_managers() -> None:
    agents = load_json(STATE_AGENTS)
    control = load_json(STATE_CONTROL)
    manager_set = set(control.get("manager_agents", []))
    original = agents.get("agents", [])
    adjusted = []
    for a in original:
        b = dict(a)
        if b.get("id") not in manager_set:
            b["status"] = "busy"
        adjusted.append(b)
    agents["agents"] = adjusted
    save_json(STATE_AGENTS, agents)
    try:
        run_router_for_managers()
    finally:
        agents["agents"] = original
        save_json(STATE_AGENTS, agents)


def pick_worker(control: dict, agents_payload: dict) -> dict | None:
    workers = set(control.get("worker_agents", []))
    cands = [
        a
        for a in agents_payload.get("agents", [])
        if a.get("id") in workers and a.get("status") == "available" and int(a.get("capacity", 0)) > 0
    ]
    if not cands:
        return None
    cands.sort(key=lambda a: (-int(a.get("capacity", 0)), a.get("id", "")))
    return cands[0]


def pick_gemini_agent(agents_payload: dict) -> dict | None:
    """Pick an available gemini agent with free capacity."""
    cands = [
        a
        for a in agents_payload.get("agents", [])
        if a.get("provider") == "gemini"
        and a.get("status") == "available"
        and int(a.get("capacity", 0)) > 0
    ]
    if not cands:
        return None
    cands.sort(key=lambda a: (-int(a.get("capacity", 0)), a.get("id", "")))
    return cands[0]


def _matches_keywords(task: dict, keywords: list[str]) -> bool:
    text = " ".join(
        [
            task.get("title", ""),
            task.get("description", ""),
            " ".join(task.get("skills", [])),
        ]
    ).lower()
    for kw in keywords:
        if kw.lower() in text:
            return True
    return False


def is_dispatch_candidate(task: dict, control: dict) -> bool:
    return _matches_keywords(task, control.get("dispatch_keywords", []))


def is_gemini_dispatch_candidate(task: dict, control: dict) -> bool:
    gemini_cfg = control.get("gemini_dispatch", {})
    return _matches_keywords(task, gemini_cfg.get("keywords", []))


def make_ollama_prompt(task: dict) -> str:
    scope = "\n".join(f"- {p}" for p in task.get("write_scope", []))
    return (
        f"Task {task.get('task_id')}:\n"
        f"Title: {task.get('title')}\n"
        f"Description: {task.get('description')}\n"
        f"Write scope:\n{scope}\n"
        "Deliver concise implementation/testing notes and exact command outputs."
    )


def make_gemini_prompt(task: dict) -> str:
    scope = "\n".join(f"- {p}" for p in task.get("write_scope", []))
    skills = ", ".join(task.get("skills", []))
    return (
        f"Task {task.get('task_id')}:\n"
        f"Title: {task.get('title')}\n"
        f"Description: {task.get('description')}\n"
        f"Skills: {skills}\n"
        f"Write scope:\n{scope}\n\n"
        "You are a validation and research agent for the Kensington Market 3D building project.\n"
        "Produce a structured validation report as JSON with per-field {status, expected, actual, confidence}.\n"
        "Flag uncertainty with confidence scores (0.0-1.0). Never guess.\n"
        "Report discrepancies with severity (critical/high/medium/low)."
    )


def write_worker_card(worker_id: str, parent_task: dict, model: str, subtask_id: str, prompt: str) -> Path:
    agent_dir = ACTIVE_DIR / worker_id
    agent_dir.mkdir(parents=True, exist_ok=True)
    out = agent_dir / f"{subtask_id}.md"
    out.write_text(
        "\n".join(
            [
                f"# {subtask_id}",
                "",
                f"- `owner`: {worker_id}",
                f"- `parent_task`: {parent_task['task_id']}",
                f"- `status`: active",
                f"- `dispatched_at`: {utc_now()}",
                f"- `model`: {model}",
                "",
                "## Prompt",
                "",
                prompt,
                "",
            ]
        ),
        encoding="utf-8",
    )
    return out


def write_worker_ownership(worker_id: str, parent_task: dict, subtask_id: str) -> None:
    own_path = OWNERSHIP_DIR / f"{subtask_id}.json"
    payload = {
        "task_id": subtask_id,
        "owner": worker_id,
        "parent_task": parent_task["task_id"],
        "write_scope": parent_task.get("write_scope", []),
        "assigned_at": utc_now(),
    }
    own_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    for item in parent_task.get("write_scope", []):
        safe = item.replace("\\", "__").replace("/", "__").replace(":", "_")
        lock_path = LOCKS_DIR / f"{subtask_id}__{safe}.lock"
        lock_path.write_text(worker_id, encoding="utf-8")


def list_child_cards(task_id: str, agent_set: set[str], suffix: str) -> list[Path]:
    children: list[Path] = []
    for agent in agent_set:
        wdir = ACTIVE_DIR / agent
        if not wdir.exists():
            continue
        for p in sorted(wdir.glob(f"{task_id}__{suffix}*.md")):
            children.append(p)
    return children


def next_subtask_id(task_id: str, existing_children: list[Path], suffix: str) -> str:
    if not existing_children:
        return f"{task_id}__{suffix}"
    used = {p.stem for p in existing_children}
    idx = 2
    while True:
        cand = f"{task_id}__{suffix}_{idx:02d}"
        if cand not in used:
            return cand
        idx += 1


def write_handoff(subtask_id: str, worker_id: str, model: str, result: subprocess.CompletedProcess) -> Path:
    HANDOFFS_DIR.mkdir(parents=True, exist_ok=True)
    handoff = HANDOFFS_DIR / f"{subtask_id}__{worker_id}.md"
    handoff.write_text(
        "\n".join(
            [
                f"# Handoff {subtask_id} from {worker_id}",
                "",
                f"- `model`: {model}",
                f"- `exit_code`: {result.returncode}",
                f"- `time`: {utc_now()}",
                "",
                "## stdout",
                "",
                result.stdout or "",
                "",
                "## stderr",
                "",
                result.stderr or "",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return handoff


def dispatch_to_ollama(control: dict, execute: bool) -> tuple[int, int]:
    agents = load_json(STATE_AGENTS)
    manager_set = set(control.get("manager_agents", []))
    worker_set = set(control.get("worker_agents", []))
    model = control.get("default_ollama_model", "qwen2.5-coder:14b")
    max_dispatch = int(control.get("max_subtasks_per_task", 2))
    max_children_per_task = int(control.get("max_children_per_task", 1))

    dispatched = 0
    executed = 0

    for manager in manager_set:
        manager_dir = ACTIVE_DIR / manager
        if not manager_dir.exists():
            continue
        for task_file in sorted(manager_dir.glob("TASK-*.md")):
            task_id = task_file.stem.split("__")[0]
            task_json = BACKLOG_DIR / f"{task_id}.json"
            if not task_json.exists():
                continue
            task = load_json(task_json)
            if task.get("status") != "active":
                continue
            if not is_dispatch_candidate(task, control):
                continue
            if dispatched >= max_dispatch:
                break
            existing = list_child_cards(task_id, worker_set, "OLLAMA")
            if len(existing) >= max_children_per_task:
                continue
            worker = pick_worker(control, agents)
            if worker is None:
                continue
            worker_id = worker["id"]
            subtask_id = next_subtask_id(task_id, existing, "OLLAMA")
            prompt = make_ollama_prompt(task)
            write_worker_card(worker_id, task, model, subtask_id, prompt)
            write_worker_ownership(worker_id, task, subtask_id)
            dispatched += 1

            if execute:
                result = subprocess.run(
                    ["ollama", "run", model, prompt],
                    check=False,
                    capture_output=True,
                    text=True,
                    cwd=str(REPO_ROOT),
                )
                write_handoff(subtask_id, worker_id, model, result)
                executed += 1

    return dispatched, executed


def dispatch_to_gemini(control: dict, execute: bool) -> tuple[int, int]:
    agents = load_json(STATE_AGENTS)
    manager_set = set(control.get("manager_agents", []))
    gemini_cfg = control.get("gemini_dispatch", {})
    model = gemini_cfg.get("model", "gemini-2.5-pro")
    max_dispatch = int(gemini_cfg.get("max_subtasks_per_cycle", 4))
    max_children = int(gemini_cfg.get("max_children_per_task", 2))

    # Collect all gemini agent IDs for child card lookup.
    gemini_ids = {
        a.get("id")
        for a in agents.get("agents", [])
        if a.get("provider") == "gemini"
    }

    dispatched = 0
    executed = 0

    for manager in manager_set:
        manager_dir = ACTIVE_DIR / manager
        if not manager_dir.exists():
            continue
        for task_file in sorted(manager_dir.glob("TASK-*.md")):
            task_id = task_file.stem.split("__")[0]
            task_json = BACKLOG_DIR / f"{task_id}.json"
            if not task_json.exists():
                continue
            task = load_json(task_json)
            if task.get("status") != "active":
                continue
            if not is_gemini_dispatch_candidate(task, control):
                continue
            if dispatched >= max_dispatch:
                break
            existing = list_child_cards(task_id, gemini_ids, "GEMINI")
            if len(existing) >= max_children:
                continue
            gemini_agent = pick_gemini_agent(agents)
            if gemini_agent is None:
                continue
            agent_id = gemini_agent["id"]
            subtask_id = next_subtask_id(task_id, existing, "GEMINI")
            prompt = make_gemini_prompt(task)
            write_worker_card(agent_id, task, model, subtask_id, prompt)
            write_worker_ownership(agent_id, task, subtask_id)
            dispatched += 1

            if execute:
                result = subprocess.run(
                    ["gemini", "-m", model, "-p", prompt],
                    check=False,
                    capture_output=True,
                    text=True,
                    cwd=str(REPO_ROOT),
                )
                write_handoff(subtask_id, agent_id, model, result)
                executed += 1

    return dispatched, executed


def main() -> int:
    parser = argparse.ArgumentParser(description="Tiered manager->worker control plane.")
    parser.add_argument("--execute-ollama", action="store_true", help="Run ollama CLI for dispatched subtasks.")
    parser.add_argument("--execute-gemini", action="store_true", help="Run gemini CLI for dispatched subtasks.")
    args = parser.parse_args()

    route_only_to_managers()
    control = load_json(STATE_CONTROL)

    ollama_dispatched, ollama_executed = dispatch_to_ollama(control, execute=args.execute_ollama)
    print(f"[OK] Dispatched to Ollama workers: {ollama_dispatched}")
    print(f"[OK] Executed Ollama CLI runs: {ollama_executed}")

    gemini_dispatched, gemini_executed = dispatch_to_gemini(control, execute=args.execute_gemini)
    print(f"[OK] Dispatched to Gemini: {gemini_dispatched}")
    print(f"[OK] Executed Gemini CLI runs: {gemini_executed}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
