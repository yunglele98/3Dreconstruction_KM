#!/usr/bin/env python3
"""
Top-level workflow runner for blender_buildings multi-agent operations.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
CHINATOWN_DIR = (
    REPO_ROOT / "PHOTOS KENSINGTON sorted" / "Chinatown Mural Lane"
)


def run(cmd: list[str], cwd: Path | None = None) -> None:
    print(">", " ".join(str(c) for c in cmd))
    subprocess.run(cmd, check=True, cwd=str(cwd or REPO_ROOT))


def cmd_route(_: argparse.Namespace) -> int:
    run([sys.executable, str(SCRIPTS_DIR / "agent_delegate_router.py"), "route"])
    return 0


def cmd_control_plane(args: argparse.Namespace) -> int:
    cmd = [sys.executable, str(SCRIPTS_DIR / "agent_control_plane.py")]
    if args.execute_ollama:
        cmd.append("--execute-ollama")
    if args.execute_gemini:
        cmd.append("--execute-gemini")
    run(cmd)
    return 0


def cmd_complete(args: argparse.Namespace) -> int:
    cmd = [
        sys.executable,
        str(SCRIPTS_DIR / "agent_delegate_router.py"),
        "complete",
        "--task-id",
        args.task_id,
    ]
    if args.agent_id:
        cmd.extend(["--agent-id", args.agent_id])
    run(cmd)
    return 0


def cmd_close(args: argparse.Namespace) -> int:
    cmd = [
        sys.executable,
        str(SCRIPTS_DIR / "agent_delegate_router.py"),
        "close",
        "--task-id",
        args.task_id,
    ]
    run(cmd)
    return 0


def cmd_watchdog(args: argparse.Namespace) -> int:
    cmd = [sys.executable, str(SCRIPTS_DIR / "agent_heartbeat_watchdog.py")]
    if args.mode == "ping":
        cmd.extend(
            [
                "ping",
                "--task-id",
                args.task_id,
                "--agent-id",
                args.agent_id,
            ]
        )
        if args.note:
            cmd.extend(["--note", args.note])
    elif args.mode == "once":
        cmd.extend(["once", "--stale-minutes", str(args.stale_minutes)])
        if args.dry_run:
            cmd.append("--dry-run")
    else:
        cmd.extend(
            [
                "watch",
                "--stale-minutes",
                str(args.stale_minutes),
                "--interval-sec",
                str(args.interval_sec),
            ]
        )
        if args.dry_run:
            cmd.append("--dry-run")
    run(cmd)
    return 0


def cmd_dashboard(args: argparse.Namespace) -> int:
    cmd = [
        sys.executable,
        str(SCRIPTS_DIR / "agent_dashboard_server.py"),
        "--host",
        args.host,
        "--port",
        str(args.port),
        "--stale-minutes",
        str(args.stale_minutes),
    ]
    if args.once_json:
        cmd.append("--once-json")
    run(cmd)
    return 0


def cmd_kensington(args: argparse.Namespace) -> int:
    runner = CHINATOWN_DIR / "run_kensington_pipeline.py"
    cmd = [
        sys.executable,
        str(runner),
        "--input-blend",
        args.input_blend,
    ]
    if args.start_at:
        cmd.extend(["--start-at", args.start_at])
    if args.end_at:
        cmd.extend(["--end-at", args.end_at])
    run(cmd, cwd=CHINATOWN_DIR)
    return 0


def cmd_gemini_runner(args: argparse.Namespace) -> int:
    cmd = [sys.executable, str(SCRIPTS_DIR / "gemini_task_runner.py")]
    if args.model:
        cmd.extend(["--model", args.model])
    if args.timeout:
        cmd.extend(["--timeout", str(args.timeout)])
    if args.loop:
        cmd.append("--loop")
        cmd.extend(["--interval", str(args.interval)])
    if args.dry_run_gemini:
        cmd.append("--dry-run")
    run(cmd)
    return 0


def cmd_ollama_runner(args: argparse.Namespace) -> int:
    cmd = [sys.executable, str(SCRIPTS_DIR / "ollama_task_runner.py")]
    if args.agent:
        for a in args.agent:
            cmd.extend(["--agent", a])
    if args.model:
        cmd.extend(["--model", args.model])
    if args.timeout:
        cmd.extend(["--timeout", str(args.timeout)])
    if args.loop:
        cmd.append("--loop")
        cmd.extend(["--interval", str(args.interval)])
    if args.auto_complete:
        cmd.append("--auto-complete")
    if args.dry_run_ollama:
        cmd.append("--dry-run")
    run(cmd)
    return 0


def cmd_gis_demo(args: argparse.Namespace) -> int:
    cmd = [
        sys.executable,
        str(SCRIPTS_DIR / "blender_gis_demo.py"),
    ]
    if args.headless:
        cmd.append("--headless")
    if args.no_massing:
        cmd.append("--no-massing")
    run(cmd)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Workflow launcher for multi-agent Blender ops")
    sub = p.add_subparsers(dest="command", required=True)

    p_route = sub.add_parser("route", help="Route backlog tasks to agents")
    p_route.set_defaults(func=cmd_route)

    p_ctrl = sub.add_parser(
        "control-plane",
        help="Route to manager agents then dispatch eligible subtasks to Ollama workers",
    )
    p_ctrl.add_argument(
        "--execute-ollama",
        action="store_true",
        help="Run ollama CLI for dispatched subtasks",
    )
    p_ctrl.add_argument(
        "--execute-gemini",
        action="store_true",
        help="Run gemini CLI for dispatched subtasks",
    )
    p_ctrl.set_defaults(func=cmd_control_plane)

    p_wd = sub.add_parser("watchdog", help="Heartbeat watchdog and stale-task reassignment")
    p_wd.add_argument("--mode", choices=["ping", "once", "watch"], default="once")
    p_wd.add_argument("--task-id")
    p_wd.add_argument("--agent-id")
    p_wd.add_argument("--note", default="")
    p_wd.add_argument("--stale-minutes", type=int, default=45)
    p_wd.add_argument("--interval-sec", type=int, default=60)
    p_wd.add_argument("--dry-run", action="store_true")
    p_wd.set_defaults(func=cmd_watchdog)

    p_dash = sub.add_parser("dashboard", help="Run local agent dashboard server")
    p_dash.add_argument("--host", default="127.0.0.1")
    p_dash.add_argument("--port", type=int, default=8765)
    p_dash.add_argument("--stale-minutes", type=int, default=45)
    p_dash.add_argument("--once-json", action="store_true")
    p_dash.set_defaults(func=cmd_dashboard)

    p_comp = sub.add_parser("complete", help="Mark a task as done and clean up locks")
    p_comp.add_argument("--task-id", required=True)
    p_comp.add_argument("--agent-id", default="")
    p_comp.set_defaults(func=cmd_complete)

    p_close = sub.add_parser("close", help="Close a task and archive it")
    p_close.add_argument("--task-id", required=True)
    p_close.set_defaults(func=cmd_close)

    p_gem = sub.add_parser("gemini-runner", help="Run Gemini task runner")
    p_gem.add_argument("--model", default=None, help="Override Gemini model")
    p_gem.add_argument("--timeout", type=int, default=None, help="Timeout per subtask (seconds)")
    p_gem.add_argument("--loop", action="store_true", help="Poll continuously")
    p_gem.add_argument("--interval", type=int, default=60, help="Poll interval in seconds")
    p_gem.add_argument("--dry-run-gemini", action="store_true", help="Preview without executing")
    p_gem.set_defaults(func=cmd_gemini_runner)

    p_ollama = sub.add_parser("ollama-runner", help="Run local Ollama task runner")
    p_ollama.add_argument("--agent", action="append", default=None, help="Ollama agent ID (can repeat)")
    p_ollama.add_argument("--model", default=None, help="Override Ollama model")
    p_ollama.add_argument("--timeout", type=int, default=None, help="Timeout per subtask (seconds)")
    p_ollama.add_argument("--loop", action="store_true", help="Poll continuously")
    p_ollama.add_argument("--interval", type=int, default=60, help="Poll interval in seconds")
    p_ollama.add_argument("--auto-complete", action="store_true", help="Auto-complete on exit 0")
    p_ollama.add_argument("--dry-run-ollama", action="store_true", help="Preview without executing")
    p_ollama.set_defaults(func=cmd_ollama_runner)

    p_kens = sub.add_parser("kensington", help="Run Kensington Chinatown lane pipeline")
    p_kens.add_argument("--input-blend", required=True)
    p_kens.add_argument("--start-at")
    p_kens.add_argument("--end-at")
    p_kens.set_defaults(func=cmd_kensington)

    p_gis = sub.add_parser("gis-demo", help="Run GIS export + Blender demo pipeline")
    p_gis.add_argument("--headless", action="store_true")
    p_gis.add_argument("--no-massing", action="store_true")
    p_gis.set_defaults(func=cmd_gis_demo)
    return p


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
