#!/usr/bin/env python3
"""Shared state helpers for agent ops watchdog/dashboard."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
OPS_ROOT = REPO_ROOT / "agent_ops"
STATE_AGENTS = OPS_ROOT / "state" / "agents.json"
ACTIVE_DIR = OPS_ROOT / "20_active"
OWNERSHIP_DIR = OPS_ROOT / "coordination" / "ownership"
LOCKS_DIR = OPS_ROOT / "coordination" / "locks"
SIGNALS_DIR = OPS_ROOT / "coordination" / "signals"
HEARTBEAT_DIR = SIGNALS_DIR / "heartbeats"
REASSIGN_LOG = SIGNALS_DIR / "reassignments.log"
BACKLOG_DIR = OPS_ROOT / "10_backlog"


def ensure_signal_dirs() -> None:
    HEARTBEAT_DIR.mkdir(parents=True, exist_ok=True)
    SIGNALS_DIR.mkdir(parents=True, exist_ok=True)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_now_iso() -> str:
    return utc_now().isoformat()


def parse_dt(text: str | None) -> datetime | None:
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def list_active_cards() -> list[Path]:
    if not ACTIVE_DIR.exists():
        return []
    return sorted(ACTIVE_DIR.glob("*/*.md"))


@dataclass
class TaskCard:
    task_id: str
    owner: str
    path: Path
    title: str
    is_ollama_child: bool


def parse_task_card(path: Path) -> TaskCard:
    owner = path.parent.name
    tid = path.stem
    is_child = "__OLLAMA" in tid
    title = tid
    try:
        first = path.read_text(encoding="utf-8").splitlines()[0]
        if first.startswith("# "):
            title = first[2:].strip()
    except OSError:
        pass
    return TaskCard(task_id=tid, owner=owner, path=path, title=title, is_ollama_child=is_child)


def heartbeat_path(task_id: str) -> Path:
    safe = task_id.replace("\\", "__").replace("/", "__").replace(":", "_")
    return HEARTBEAT_DIR / f"{safe}.json"


def read_heartbeat(task_id: str, fallback_mtime: datetime) -> datetime:
    hb = read_json(heartbeat_path(task_id), {})
    dt = parse_dt(hb.get("timestamp")) if isinstance(hb, dict) else None
    return dt or fallback_mtime


def touch_heartbeat(task_id: str, agent_id: str, note: str = "") -> Path:
    ensure_signal_dirs()
    p = heartbeat_path(task_id)
    payload = {
        "task_id": task_id,
        "agent_id": agent_id,
        "timestamp": utc_now_iso(),
        "note": note,
    }
    write_json(p, payload)
    return p


def load_agents() -> list[dict]:
    payload = read_json(STATE_AGENTS, {"agents": []})
    agents = payload.get("agents", [])
    return agents if isinstance(agents, list) else []


def active_counts() -> dict[str, int]:
    counts: dict[str, int] = {}
    for card in list_active_cards():
        owner = card.parent.name
        counts[owner] = counts.get(owner, 0) + 1
    return counts


def snapshot(stale_minutes: int = 45) -> dict:
    ensure_signal_dirs()
    now = utc_now()
    stale_seconds = stale_minutes * 60
    cards = [parse_task_card(p) for p in list_active_cards()]
    tasks: list[dict] = []
    for c in cards:
        fallback = datetime.fromtimestamp(c.path.stat().st_mtime, tz=timezone.utc)
        hb = read_heartbeat(c.task_id, fallback)
        age_sec = max(0, int((now - hb).total_seconds()))
        tasks.append(
            {
                "task_id": c.task_id,
                "title": c.title,
                "owner": c.owner,
                "path": str(c.path),
                "is_ollama_child": c.is_ollama_child,
                "last_heartbeat": hb.isoformat(),
                "age_seconds": age_sec,
                "stale": age_sec > stale_seconds,
            }
        )
    by_owner: dict[str, int] = {}
    for t in tasks:
        by_owner[t["owner"]] = by_owner.get(t["owner"], 0) + 1
    return {
        "generated_at": now.isoformat(),
        "stale_minutes": stale_minutes,
        "tasks": tasks,
        "active_by_owner": by_owner,
        "agents": load_agents(),
    }


def append_reassign_log(line: str) -> None:
    SIGNALS_DIR.mkdir(parents=True, exist_ok=True)
    with REASSIGN_LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


# ---------------------------------------------------------------------------
# Task lifecycle helpers
# ---------------------------------------------------------------------------

ARCHIVE_DIR = OPS_ROOT / "90_archive"


def remove_locks(task_id: str) -> int:
    """Remove all lock files for a task. Returns count of removed locks."""
    if not LOCKS_DIR.exists():
        return 0
    removed = 0
    prefix = f"{task_id}__"
    for p in LOCKS_DIR.glob(f"{prefix}*.lock"):
        p.unlink()
        removed += 1
    return removed


def remove_ownership(task_id: str) -> bool:
    """Remove ownership record for a task. Returns True if file existed."""
    own = OWNERSHIP_DIR / f"{task_id}.json"
    if own.exists():
        own.unlink()
        return True
    return False


def archive_card(task_id: str, owner: str) -> Path | None:
    """Move an active card to the archive directory. Returns archive path or None."""
    src = ACTIVE_DIR / owner / f"{task_id}.md"
    if not src.exists():
        return None
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    dst = ARCHIVE_DIR / f"{task_id}__{owner}.md"
    dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    src.unlink()
    return dst

