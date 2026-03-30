Follow a production task execution cycle in C:\Users\liam1\blender_buildings.

Read first:
- AGENTS.md
- docs/CODEX_LAUNCHER_PROMPT.md
- docs/AGENT_WORKFLOW_GUIDE.md

Execution mode:
- Pick one task from agent_ops backlog and carry it to completion.
- Keep logs in outputs/session_runs/logs with a new timestamp.
- No destructive git/database operations.

Task sequence:
1. Fetch next task:
   - python scripts/run_blender_buildings_workflows.py route
2. Send heartbeat before/after each major action:
   - python scripts/run_blender_buildings_workflows.py watchdog --mode ping --task-id <id> --agent-id codex-1 --note "<status>"
3. Execute task-specific scripts.
4. Run validation relevant to the task (params, contracts, exports, or DB checks).
5. Write handoff artifact to agent_ops/30_handoffs/.
6. Complete task:
   - python scripts/run_blender_buildings_workflows.py complete --task-id <id> --agent-id codex-1

Deliverables:
- task summary
- validation evidence
- blockers + recommended reassignment path if unresolved
