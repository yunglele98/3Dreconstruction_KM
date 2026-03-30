# Multi-Agent Ops Structure

This folder standardizes collaboration for 5-10 parallel agents (`claude`, `codex`, `gemini`, `ollama-*`) without changing project source layout.

## Directory Map

- `00_intake/`: raw requests and new tickets.
- `10_backlog/`: normalized task cards waiting for routing.
- `20_active/<agent>/`: tasks currently assigned and in execution.
- `30_handoffs/`: completion notes transferred between agents.
- `40_reviews/`: QA and code review artifacts.
- `50_runs/`: run logs and reproducible command traces.
- `60_releases/`: promotion-ready outputs and release notes.
- `90_archive/`: closed batches and old operational state.
- `coordination/locks/`: file/path lock files for conflict avoidance.
- `coordination/ownership/`: current ownership registry.
- `coordination/signals/`: heartbeat and escalation markers.
- `state/`: active capacity/status snapshots.
- `templates/`: canonical markdown/json templates.
- `playbooks/`: per-model role guidance.

## Canonical Workflow

1. Intake: create `00_intake/<ticket>.md`.
2. Normalize: convert to `10_backlog/<task_id>.json`.
3. Route: run `python scripts/agent_delegate_router.py`.
4. Execute: agent works from `20_active/<agent>/<task_id>.md`.
5. Handoff: post result in `30_handoffs/<task_id>__<agent>.md`.
6. Review: add QA verdict in `40_reviews/<task_id>.md`.
7. Archive or release: move to `90_archive` or `60_releases`.

## Conflict Rules

1. An agent must hold a lock before editing owned files.
2. One lock file per write scope in `coordination/locks/`.
3. Cross-agent edits require handoff + review note.
4. Missing heartbeat for a task over SLA triggers reassignment.

## Recommended Team Topology (7-agent default)

1. `codex-1`: implementation owner (core code paths).
2. `codex-2`: parallel implementation owner (disjoint modules).
3. `claude-1`: requirements consolidation and risk capture.
4. `gemini-1`: research and source validation.
5. `ollama-local-1`: lint/format/test automation.
6. `ollama-local-2`: render/checkpoint runner and artifact verifier.
7. `codex-review`: code review and merge gate checks.

Adjust capacity in `state/agents.json`.
