Work in C:\Users\liam1\blender_buildings.

Goal:
Run a high-signal stabilization pass using existing workflow tooling and produce a clean execution report.

Requirements:
- Read AGENTS.md and docs/AGENT_WORKFLOW_GUIDE.md first.
- Do not revert unrelated changes in this dirty worktree.
- Create a new timestamp key and log all commands/results under outputs/session_runs/logs.

Tasks:
1. Run workflow status:
   - python scripts/run_blender_buildings_workflows.py dashboard --once-json
2. Run routing and heartbeat checks:
   - python scripts/run_blender_buildings_workflows.py route
   - python scripts/run_blender_buildings_workflows.py watchdog --mode once --dry-run
3. Run quality checks:
   - python scripts/validate_all_params.py
   - python scripts/audit_generator_contracts.py
   - python scripts/generate_comprehensive_audit.py
4. Run DB-dependent storefront conflict audit; if DB fails, classify exact root cause.
5. Run focused export validation:
   - python scripts/validate_export_pipeline.py --address "22 Lippincott St"
6. Build a top-20 remediation queue from findings.
7. Write:
   - docs/reports/codex_here_stabilization_<date>_<timestamp>.md
   - docs/reports/codex_here_next_actions_<date>_<timestamp>.md

Final output:
- pass/fail by step
- files changed
- blockers
- exact next 5 commands
