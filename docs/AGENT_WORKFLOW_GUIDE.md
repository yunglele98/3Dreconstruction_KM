# Agent Workflow Guide (Claude + Codex + Gemini + Ollama)

## Goal

Provide a stable operating model for the 14-agent fleet (5x Claude Code + 4 Gemini/Codex + 4 Ollama + claude-research) in parallel with low conflict and predictable handoffs.

## Required Commands

1. Route backlog tasks:
`python scripts/run_blender_buildings_workflows.py route`

2. Tiered manager->worker automation:
`python scripts/run_blender_buildings_workflows.py control-plane`

3. Tiered automation + actual Ollama runs:
`python scripts/run_blender_buildings_workflows.py control-plane --execute-ollama`

4. Run Kensington lane workflow:
`python scripts/run_blender_buildings_workflows.py kensington --input-blend "<path-to-blend>"`

5. Run GIS demo workflow:
`python scripts/run_blender_buildings_workflows.py gis-demo --headless`

6. Watchdog one-shot scan:
`python scripts/run_blender_buildings_workflows.py watchdog --mode once`

7. Watchdog continuous mode:
`python scripts/run_blender_buildings_workflows.py watchdog --mode watch --stale-minutes 45 --interval-sec 60`

8. Dashboard:
`python scripts/run_blender_buildings_workflows.py dashboard`
Then open `http://127.0.0.1:8765`.

## Assignment Policy

1. Every task must be a JSON card in `agent_ops/10_backlog`.
2. Every task must define `skills`, `write_scope`, `estimate_points`.
3. Router assigns by skill match + free capacity.
4. Router creates:
- active task card under `agent_ops/20_active/<agent>/`
- ownership record under `agent_ops/coordination/ownership/`
- lock files under `agent_ops/coordination/locks/`

## Delegation Pattern

**Tier 1 (Claude Code, Opus 4.6 1M, Max 5x):** architect, reviewer, writer-1, writer-2, ops + claude-research (Claude.ai chat for design track).
**Tier 2 (Gemini API + Codex CLI):** gemini-batch-1/2 (Flash, n8n-automated), gemini-vision (Pro), codex-cli (manual).
**Tier 3 (Ollama, local):** qwen2.5-coder:7b (code), qwen2.5-coder:3b (validate), llava:7b (vision), mistral:7b (summarize).

Task routing:
1. `claude`: architectural decisions, task decomposition, risk register, documentation synthesis.
2. `codex`: implementation and integration.
3. `gemini`: volume data processing, research validation, source triangulation.
4. `ollama`: local fast loops (tests, lint, render checks, smoke QA, boilerplate).

## Automated Tiered Dispatch

1. `control-plane` temporarily limits routing to manager agents from:
- `agent_ops/state/control_plane.json` -> `manager_agents`
2. It scans active manager tasks and dispatches eligible execution subtasks to:
- `worker_agents` (Ollama local pool)
3. Keyword-based dispatch (default):
- `test`, `lint`, `render`, `qa`, `batch`, `verify`, `artifact`
4. Optional execution:
- with `--execute-ollama`, runs `ollama run <model> <prompt>` and writes handoffs in `agent_ops/30_handoffs`.

## Heartbeats, Reassignment, and Dashboard

1. Agents can ping heartbeat manually:
- `python scripts/run_blender_buildings_workflows.py watchdog --mode ping --task-id TASK-... --agent-id codex-1 --note "working"`
2. Stale tasks are detected by heartbeat age (or task card mtime fallback).
3. Reassignment updates:
- active owner card location
- ownership JSON
- lock file owner values
- backlog owner for parent task
- signal log in `agent_ops/coordination/signals/reassignments.log`
4. Dashboard API:
- `/api/state` provides JSON snapshot used by the UI.

## Handoff Requirements

1. Handoff file in `agent_ops/30_handoffs/`.
2. Include commands executed and outcomes.
3. Include unresolved risks and next owner.

## Review Gate

1. Review artifact required in `agent_ops/40_reviews/`.
2. Findings-first format with severity + file references.
3. Merge/release only after review result is `approve`.

## Full Stack Launch

### PowerShell (all components)

```powershell
.\scripts\start_agent_ops.ps1 -StartControlLoop -StartOllamaRunner -StartGeminiRunner -OllamaAutoComplete
```

This starts separate terminals for: dashboard, watchdog, control loop (routes + dispatches), Ollama runner, and Gemini runner.

### Individual components

```bash
# Dashboard web UI
python scripts/run_blender_buildings_workflows.py dashboard
# Then open http://127.0.0.1:8765

# Ollama task runner (continuous)
python scripts/ollama_task_runner.py --loop --interval 60 --auto-complete

# Gemini task runner (continuous)
python scripts/gemini_task_runner.py --loop --interval 60 --auto-complete

# Control plane with execution
python scripts/run_blender_buildings_workflows.py control-plane --execute-ollama --execute-gemini
```

## Task Lifecycle

```
10_backlog → route → 20_active/<agent>/ → agent works → 30_handoffs/ → review → 40_reviews/ → close → 90_archive/
```

## Key Configuration Files

| File | Purpose |
|------|---------|
| `agent_ops/state/control_plane.json` | Manager/worker agent IDs, dispatch keywords |
| `agent_ops/coordination/ownership/*.json` | Per-task owner records |
| `agent_ops/coordination/locks/*.json` | Write scope locks |
| `agent_ops/coordination/signals/reassignments.log` | Reassignment history |
| `agent_ops/templates/task/task_template.json` | Task card template |
| `agent_ops/templates/handoff/handoff_template.md` | Handoff template |
| `agent_ops/templates/review/review_template.md` | Review template |
