#!/usr/bin/env python3
"""Heartbeat watchdog with automatic stale-task reassignment."""

from __future__ import annotations

import argparse
import time
from pathlib import Path

from agent_ops_state import (
    BACKLOG_DIR,
    LOCKS_DIR,
    OWNERSHIP_DIR,
    active_counts,
    append_reassign_log,
    load_agents,
    parse_task_card,
    read_json,
    snapshot,
    touch_heartbeat,
    utc_now_iso,
    write_json,
)


def is_manager_task(task_id: str, owner: str) -> bool:
    # Child subtasks dispatched to workers.
    if "__OLLAMA" in task_id or "__GEMINI" in task_id:
        return False
    # Manager tasks are anything not worker-owned.
    return not owner.startswith("ollama-")


def is_gemini_subtask(task_id: str) -> bool:
    return "__GEMINI" in task_id


def candidate_agents(task_id: str, current_owner: str) -> list[dict]:
    agents = load_agents()
    counts = active_counts()
    cands: list[dict] = []
    mgr = is_manager_task(task_id, current_owner)
    gemini_sub = is_gemini_subtask(task_id)
    for a in agents:
        if a.get("id") == current_owner:
            continue
        if a.get("status") != "available":
            continue
        aid = a.get("id", "")
        if gemini_sub:
            # Gemini subtasks can only be reassigned to gemini agents.
            if a.get("provider") != "gemini":
                continue
        elif mgr and (aid.startswith("ollama-") or a.get("provider") == "gemini"):
            continue
        elif not mgr and not aid.startswith("ollama-"):
            continue
        cap = int(a.get("capacity", 0))
        used = counts.get(aid, 0)
        if used >= cap:
            continue
        cands.append(
            {
                **a,
                "_used": used,
                "_cap": cap,
            }
        )
    cands.sort(key=lambda x: (x["_used"] / max(1, x["_cap"]), x["_used"], x.get("id", "")))
    return cands


def move_card(task_id: str, old_owner: str, new_owner: str) -> Path | None:
    src = Path("agent_ops") / "20_active" / old_owner / f"{task_id}.md"
    if not src.exists():
        return None
    dst_dir = Path("agent_ops") / "20_active" / new_owner
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / src.name
    dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    src.unlink()
    return dst


def update_ownership_and_locks(task_id: str, new_owner: str) -> None:
    own = OWNERSHIP_DIR / f"{task_id}.json"
    payload = read_json(own, {})
    if payload:
        payload["owner"] = new_owner
        payload["reassigned_at"] = utc_now_iso()
        write_json(own, payload)

    prefix = f"{task_id}__"
    if LOCKS_DIR.exists():
        for p in LOCKS_DIR.glob(f"{prefix}*.lock"):
            p.write_text(new_owner, encoding="utf-8")


def update_backlog_owner(task_id: str, new_owner: str) -> None:
    # Update parent backlog card if present.
    base = task_id.split("__OLLAMA")[0]
    p = BACKLOG_DIR / f"{base}.json"
    if not p.exists():
        return
    data = read_json(p, {})
    if not data:
        return
    data["owner"] = new_owner
    data["reassigned_at"] = utc_now_iso()
    write_json(p, data)


def reassign_stale(stale_minutes: int, dry_run: bool) -> int:
    state = snapshot(stale_minutes=stale_minutes)
    reassigned = 0
    for task in state["tasks"]:
        if not task.get("stale"):
            continue
        task_id = task["task_id"]
        owner = task["owner"]
        cands = candidate_agents(task_id, owner)
        if not cands:
            append_reassign_log(
                f"{utc_now_iso()} no_candidate task={task_id} owner={owner} age={task['age_seconds']}"
            )
            continue
        new_owner = cands[0]["id"]
        if dry_run:
            append_reassign_log(
                f"{utc_now_iso()} dry_run task={task_id} {owner}->{new_owner} age={task['age_seconds']}"
            )
            reassigned += 1
            continue
        moved = move_card(task_id, owner, new_owner)
        if moved is None:
            continue
        update_ownership_and_locks(task_id, new_owner)
        update_backlog_owner(task_id, new_owner)
        touch_heartbeat(task_id, new_owner, note=f"reassigned from {owner}")
        append_reassign_log(
            f"{utc_now_iso()} reassigned task={task_id} {owner}->{new_owner} age={task['age_seconds']}"
        )
        reassigned += 1
    return reassigned


def cmd_ping(args: argparse.Namespace) -> int:
    p = touch_heartbeat(args.task_id, args.agent_id, note=args.note or "")
    print(f"[OK] heartbeat updated: {p}")
    return 0


def cmd_once(args: argparse.Namespace) -> int:
    n = reassign_stale(stale_minutes=args.stale_minutes, dry_run=args.dry_run)
    print(f"[OK] stale tasks reassigned: {n}")
    return 0


def cmd_watch(args: argparse.Namespace) -> int:
    while True:
        n = reassign_stale(stale_minutes=args.stale_minutes, dry_run=args.dry_run)
        print(f"[OK] cycle complete, reassigned={n}")
        time.sleep(args.interval_sec)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Heartbeat watchdog + auto reassignment.")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_ping = sub.add_parser("ping", help="Update heartbeat for an active task.")
    p_ping.add_argument("--task-id", required=True)
    p_ping.add_argument("--agent-id", required=True)
    p_ping.add_argument("--note", default="")
    p_ping.set_defaults(func=cmd_ping)

    p_once = sub.add_parser("once", help="Run one reassignment scan.")
    p_once.add_argument("--stale-minutes", type=int, default=45)
    p_once.add_argument("--dry-run", action="store_true")
    p_once.set_defaults(func=cmd_once)

    p_watch = sub.add_parser("watch", help="Run continuous reassignment scans.")
    p_watch.add_argument("--stale-minutes", type=int, default=45)
    p_watch.add_argument("--interval-sec", type=int, default=60)
    p_watch.add_argument("--dry-run", action="store_true")
    p_watch.set_defaults(func=cmd_watch)
    return p


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
