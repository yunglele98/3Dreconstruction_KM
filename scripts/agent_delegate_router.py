#!/usr/bin/env python3
"""
Route backlog tasks to available agents by skills and capacity.
Also provides task lifecycle commands (complete, close).

Usage:
  python scripts/agent_delegate_router.py route
  python scripts/agent_delegate_router.py complete --task-id TASK-... --agent-id codex-1
  python scripts/agent_delegate_router.py close --task-id TASK-...
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from agent_ops_state import (
    archive_card,
    remove_locks,
    remove_ownership,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
OPS_ROOT = REPO_ROOT / "agent_ops"
STATE_FILE = OPS_ROOT / "state" / "agents.json"
BACKLOG_DIR = OPS_ROOT / "10_backlog"
ACTIVE_DIR = OPS_ROOT / "20_active"
OWNERSHIP_DIR = OPS_ROOT / "coordination" / "ownership"
LOCKS_DIR = OPS_ROOT / "coordination" / "locks"


DONE_STATUSES = {"done", "closed", "released"}


@dataclass
class Agent:
    id: str
    provider: str
    status: str
    capacity: int
    skills: set[str]
    assigned: int = 0

    @property
    def free(self) -> int:
        return max(0, self.capacity - self.assigned)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_agents(state_path: Path) -> list[Agent]:
    payload = json.loads(state_path.read_text(encoding="utf-8"))
    agents = []
    for a in payload.get("agents", []):
        agents.append(
            Agent(
                id=a["id"],
                provider=a.get("provider", "unknown"),
                status=a.get("status", "available"),
                capacity=int(a.get("capacity", 0)),
                skills=set(a.get("skills", [])),
            )
        )
    return agents


def load_tasks(backlog_dir: Path) -> list[dict]:
    tasks: list[dict] = []
    for path in sorted(backlog_dir.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        data["_path"] = path
        tasks.append(data)
    return tasks


def score(agent: Agent, task: dict) -> tuple[int, int, int]:
    required = set(task.get("skills", []))
    matched = len(required & agent.skills)
    missing = len(required - agent.skills)
    # Higher matched and free capacity win; missing skills penalized.
    quality = matched * 3 - missing * 2
    return (quality, matched, agent.free)


def best_agent(agents: list[Agent], task: dict) -> Agent | None:
    candidates = [a for a in agents if a.status == "available" and a.free > 0]
    if not candidates:
        return None
    ranked = sorted(candidates, key=lambda a: score(a, task), reverse=True)
    top = score(ranked[0], task)
    pool = [a for a in ranked if score(a, task) == top]
    # Balance work by selecting lowest current load ratio among equal-scored agents.
    pool.sort(key=lambda a: (a.assigned / max(a.capacity, 1), a.assigned, a.id))
    return pool[0]


def dependencies_met(task: dict, all_tasks: list[dict]) -> bool:
    """Check that every task in the dependencies list has a done/closed/released status."""
    deps = task.get("dependencies", [])
    if not deps:
        return True
    status_by_id = {t.get("task_id"): t.get("status", "") for t in all_tasks}
    for dep_id in deps:
        dep_status = status_by_id.get(dep_id)
        if dep_status not in DONE_STATUSES:
            return False
    return True


def ensure_dirs() -> None:
    for path in (ACTIVE_DIR, OWNERSHIP_DIR, LOCKS_DIR):
        path.mkdir(parents=True, exist_ok=True)


def write_active_card(agent: Agent, task: dict) -> Path:
    agent_dir = ACTIVE_DIR / agent.id
    agent_dir.mkdir(parents=True, exist_ok=True)
    out = agent_dir / f"{task['task_id']}.md"
    lines = [
        f"# {task['task_id']} - {task.get('title', '')}",
        "",
        f"- `owner`: {agent.id}",
        f"- `priority`: {task.get('priority', 'medium')}",
        f"- `estimate_points`: {task.get('estimate_points', 1)}",
        f"- `skills`: {', '.join(task.get('skills', []))}",
        f"- `status`: active",
        f"- `routed_at`: {utc_now()}",
        "",
        "## Description",
        "",
        task.get("description", ""),
        "",
        "## Write Scope",
        "",
    ]
    for p in task.get("write_scope", []):
        lines.append(f"- `{p}`")
    lines.append("")
    out.write_text("\n".join(lines), encoding="utf-8")
    return out


def write_ownership(task: dict, agent: Agent) -> None:
    out = OWNERSHIP_DIR / f"{task['task_id']}.json"
    payload = {
        "task_id": task["task_id"],
        "owner": agent.id,
        "write_scope": task.get("write_scope", []),
        "assigned_at": utc_now(),
    }
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    for item in task.get("write_scope", []):
        safe_name = item.replace("\\", "__").replace("/", "__").replace(":", "_")
        lock_path = LOCKS_DIR / f"{task['task_id']}__{safe_name}.lock"
        lock_path.write_text(agent.id, encoding="utf-8")


def update_task_file(task: dict, agent: Agent) -> None:
    task["owner"] = agent.id
    task["status"] = "active"
    task["routed_at"] = utc_now()
    path = task.pop("_path")
    path.write_text(json.dumps(task, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Subcommand: route
# ---------------------------------------------------------------------------

def cmd_route(args: argparse.Namespace) -> int:
    ensure_dirs()
    agents = load_agents(Path(args.state_file))
    tasks = load_tasks(Path(args.backlog_dir))

    routed = 0
    skipped = 0
    blocked = 0
    for task in tasks:
        if task.get("status") not in {"backlog", "queued", None}:
            continue
        if not dependencies_met(task, tasks):
            blocked += 1
            print(f"[SKIP] {task.get('task_id', '?')}: unmet dependencies {task.get('dependencies', [])}")
            continue
        agent = best_agent(agents, task)
        if agent is None:
            skipped += 1
            continue
        agent.assigned += 1
        write_active_card(agent, task)
        write_ownership(task, agent)
        update_task_file(task, agent)
        routed += 1

    print(f"[OK] Routed tasks: {routed}")
    print(f"[OK] Skipped (no capacity): {skipped}")
    print(f"[OK] Blocked (unmet deps): {blocked}")
    return 0


# ---------------------------------------------------------------------------
# Subcommand: complete
# ---------------------------------------------------------------------------

def cmd_complete(args: argparse.Namespace) -> int:
    task_path = Path(args.backlog_dir) / f"{args.task_id}.json"
    if not task_path.exists():
        print(f"[ERR] Task file not found: {task_path}")
        return 1

    task = json.loads(task_path.read_text(encoding="utf-8"))
    owner = task.get("owner", "")
    if args.agent_id and owner != args.agent_id:
        print(f"[WARN] Task owned by {owner}, not {args.agent_id} — completing anyway")

    task["status"] = "done"
    task["completed_at"] = utc_now()
    task["completed_by"] = args.agent_id or owner
    task_path.write_text(json.dumps(task, indent=2), encoding="utf-8")

    remove_locks(args.task_id)
    remove_ownership(args.task_id)
    archive_card(args.task_id, owner)

    # Report newly unblocked tasks.
    tasks = load_tasks(Path(args.backlog_dir))
    unblocked = []
    for t in tasks:
        if t.get("status") not in {"backlog", "queued", None}:
            continue
        deps = t.get("dependencies", [])
        if args.task_id in deps and dependencies_met(t, tasks):
            unblocked.append(t.get("task_id", "?"))
    if unblocked:
        print(f"[OK] Newly unblocked: {', '.join(unblocked)}")

    print(f"[OK] Completed {args.task_id}")
    return 0


# ---------------------------------------------------------------------------
# Subcommand: close
# ---------------------------------------------------------------------------

def cmd_close(args: argparse.Namespace) -> int:
    task_path = Path(args.backlog_dir) / f"{args.task_id}.json"
    if not task_path.exists():
        print(f"[ERR] Task file not found: {task_path}")
        return 1

    task = json.loads(task_path.read_text(encoding="utf-8"))
    owner = task.get("owner", "")

    task["status"] = "closed"
    task["closed_at"] = utc_now()

    remove_locks(args.task_id)
    remove_ownership(args.task_id)
    archive_card(args.task_id, owner)

    # Move task JSON to archive.
    archive_dir = OPS_ROOT / "90_archive"
    archive_dir.mkdir(parents=True, exist_ok=True)
    dest = archive_dir / task_path.name
    dest.write_text(json.dumps(task, indent=2), encoding="utf-8")
    task_path.unlink()

    print(f"[OK] Closed and archived {args.task_id}")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Route, complete, and close agent tasks.")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_route = sub.add_parser("route", help="Route backlog tasks to available agents.")
    p_route.add_argument("--state-file", default=str(STATE_FILE))
    p_route.add_argument("--backlog-dir", default=str(BACKLOG_DIR))
    p_route.set_defaults(func=cmd_route)

    p_complete = sub.add_parser("complete", help="Mark a task as done and clean up locks.")
    p_complete.add_argument("--task-id", required=True)
    p_complete.add_argument("--agent-id", default="")
    p_complete.add_argument("--backlog-dir", default=str(BACKLOG_DIR))
    p_complete.set_defaults(func=cmd_complete)

    p_close = sub.add_parser("close", help="Close a task and move it to archive.")
    p_close.add_argument("--task-id", required=True)
    p_close.add_argument("--backlog-dir", default=str(BACKLOG_DIR))
    p_close.set_defaults(func=cmd_close)

    return p


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
