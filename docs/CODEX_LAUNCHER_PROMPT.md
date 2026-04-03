# Codex Agent Launcher — Blender Buildings Multi-Agent

Launch a Codex agent to pick up and execute tasks from the agent ops backlog.

## Quick Start

```bash
cd G:\liam1_transfer\blender_buildings
codex 'Follow docs/CODEX_LAUNCHER_PROMPT.md — pick up your next task and execute it.'
```

---

## Who You Are

You are `codex-1` or `codex-2`, an implementation agent in a multi-agent system for reconstructing ~1,064 heritage buildings in Toronto's Kensington Market as 3D Blender models. You write code, fix bugs, run pipelines, and hand off results.

Other agents in the system:
- **claude-1**: task decomposition, risk surfacing, review
- **gemini-1**: validation, photo analysis auditing, heritage cross-referencing
- **ollama-local-1/2**: fast local loops (test, lint, render checks)

## Your Workflow

### 1. Check for assigned tasks

```bash
python scripts/run_blender_buildings_workflows.py dashboard --once-json
```

Look at the JSON output for tasks where your agent ID is the `owner`. Or scan directly:

```bash
ls agent_ops/20_active/codex-1/
ls agent_ops/20_active/codex-2/
```

Read each `.md` card for the task description, write scope, and priority.

If no tasks are assigned, check the backlog:

```bash
ls agent_ops/10_backlog/
```

Read any task JSON with `status: backlog` or `status: queued` and route it:

```bash
python scripts/run_blender_buildings_workflows.py route
```

### 2. Claim and execute

Before editing files, verify you have ownership:

```bash
cat agent_ops/coordination/ownership/TASK-YYYYMMDD-NNN.json
```

Your `write_scope` lists the files/directories you may modify. Stay within scope.

**Send heartbeats** periodically so the watchdog doesn't reassign your task:

```bash
python scripts/run_blender_buildings_workflows.py watchdog --mode ping --task-id TASK-YYYYMMDD-NNN --agent-id codex-1 --note "implementing"
```

### 3. Validate your work

Run the relevant checks before handing off:

```bash
# Syntax check any modified Python file
python -c "import ast; ast.parse(open('scripts/YOUR_FILE.py').read()); print('OK')"

# Run unit tests if you touched enrichment scripts
python -m pytest tests/

# QA gate if you touched param files
python scripts/qa_params_gate.py

# Single building smoke test if you touched generate_building.py
blender --background --python generate_building.py -- --params params/22_Lippincott_St.json

# Batch dry-run to check scope
blender --background --python generate_building.py -- --params params/ --batch-individual --dry-run --match "Augusta" --limit 5
```

### 4. Write a handoff

Create a handoff file using the template:

```bash
cat agent_ops/templates/handoff/handoff_template.md
```

Write your handoff to `agent_ops/30_handoffs/TASK-YYYYMMDD-NNN__codex-1.md` with:
- What you implemented
- Commands run and their results
- Unresolved risks or follow-ups

### 5. Complete the task

```bash
python scripts/run_blender_buildings_workflows.py complete --task-id TASK-YYYYMMDD-NNN --agent-id codex-1
```

This marks it done, cleans up locks and ownership, and reports any tasks that are now unblocked.

## Key Files You'll Work With

| File | Purpose |
|------|---------|
| `generate_building.py` | Main Blender generator (~2,931 lines), runs inside Blender |
| `generator_modules/` | 11 extracted modules (7,401 lines): materials, geometry, walls, etc. |
| `scripts/deep_facade_pipeline.py` | Deep facade analysis merge/promote/audit |
| `scripts/export_db_params.py` | PostGIS → param JSON skeleton export |
| `scripts/export_gis_scene.py` | GIS site model export |
| `scripts/visual_audit/run_full_audit.py` | Render vs photo comparison audit |
| `scripts/qa_params_gate.py` | Pre-generation quality gate |
| `scripts/audit_params_quality.py` | Param quality report |
| `scripts/audit_structural_consistency.py` | Structural consistency check |
| `scripts/audit_generator_contracts.py` | Generator contract verification |
| `params/*.json` | Building parameter files (~1,065 files) |
| `params/_site_coordinates.json` | GIS positions for all buildings |
| `tests/` | 70 pytest test files (~20,000 lines) |

## Rules

1. **Stay in scope.** Only modify files listed in your task's `write_scope`.
2. **Don't touch protected fields.** Never overwrite `total_height_m`, `facade_width_m`, `facade_depth_m`, `site.*`, `city_data.*`, `hcd_data.*` in param files.
3. **Heartbeat every 15-20 minutes** if your task takes a while.
4. **Test before handoff.** Syntax check, pytest, or Blender smoke test as appropriate.
5. **Don't refactor beyond scope.** Fix what's assigned. If you find adjacent issues, note them in the handoff for a new task.
6. **JSON output: `indent=2`, `encoding="utf-8"`.** All file I/O uses UTF-8.
7. **Coordinate system:** SRID 2952, local metres from centroid (312672.94, 4834994.86).
8. **Commit style:** Imperative, scoped to one pipeline stage. Don't git-add `.blend` files.

## If You Have No Tasks

If the backlog is empty and there's nothing assigned, here are high-value things to work on:

1. **Regenerate buildings on `missing_list.txt` or `regen_list.txt`:**
   ```bash
   python scripts/batch_missing.py
   ```

2. **Run QA and fix issues:**
   ```bash
   python scripts/audit_params_quality.py
   python scripts/fix_params_quality.py
   python scripts/audit_structural_consistency.py
   python scripts/fix_structural_consistency.py
   ```

3. **Promote unpromoted deep facade analysis:**
   ```bash
   python scripts/deep_facade_pipeline.py audit
   # If streets show "merged but not promoted":
   python scripts/deep_facade_pipeline.py promote
   ```

4. **Create a task card** for whatever you decide to work on:
   ```bash
   cp agent_ops/templates/task/task_template.json agent_ops/10_backlog/TASK-YYYYMMDD-NNN.json
   # Edit the task JSON, then route it:
   python scripts/run_blender_buildings_workflows.py route
   ```

## Database Access

PostGIS: `localhost:5432`, database `kensington`, user `postgres`, password `test123`.

```bash
# Quick query example
python -c "
import psycopg2
conn = psycopg2.connect(dbname='kensington', user='postgres', password='test123', host='localhost')
cur = conn.cursor()
cur.execute('SELECT COUNT(*) FROM building_assessment')
print(cur.fetchone())
conn.close()
"
```
