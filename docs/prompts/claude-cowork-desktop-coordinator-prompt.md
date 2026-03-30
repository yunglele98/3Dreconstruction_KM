Act as coordinator/reviewer for multi-agent execution in C:\Users\liam1\blender_buildings.

Read:
- docs/AGENT_WORKFLOW_GUIDE.md
- docs/CLAUDE_LAUNCHER_PROMPT.md
- docs/CODEX_LAUNCHER_PROMPT.md
- docs/GEMINI_LAUNCHER_PROMPT.md

Goal:
Coordinate Codex + Gemini + Claude Code runs, prevent duplicate work, and close one full cycle of backlog tasks.

Process:
1. Build current board snapshot from agent_ops folders.
2. Assign:
   - Codex: implementation task
   - Gemini: diagnostics/verification task
   - Claude Code: geometry/export QA task
3. Enforce heartbeat updates every major step.
4. Validate handoffs for completeness:
   - changed files
   - command evidence
   - validation outcomes
5. Resolve conflicts and choose winning patch set.
6. Close completed tasks and archive stale cards.
7. Produce:
   - docs/reports/claude_cowork_coordination_<date>_<timestamp>.md
   - docs/reports/claude_cowork_next_sprint_<date>_<timestamp>.md

Final output:
- board movement summary
- completed tasks
- unresolved blockers
- next sprint assignments with owners
