# Ollama Task Runner — Blender Buildings Multi-Agent

Ollama agents don't have a conversational CLI like Claude/Codex/Gemini. Instead, `scripts/ollama_task_runner.py` polls for pending `__OLLAMA` subtask cards and executes them automatically.

## Quick Start

```bash
cd G:\liam1_transfer\blender_buildings

# One-shot: run all pending subtasks
python scripts/ollama_task_runner.py

# Continuous: poll every 60s, auto-complete passing tasks
python scripts/ollama_task_runner.py --loop --interval 60 --auto-complete

# Preview what would run
python scripts/ollama_task_runner.py --dry-run

# Via workflow runner
python scripts/run_blender_buildings_workflows.py ollama-runner --loop --auto-complete
```

## PowerShell (full stack)

```powershell
# Start everything: dashboard + watchdog + control loop + ollama runner
.\scripts\start_agent_ops.ps1 -StartControlLoop -StartOllamaRunner -OllamaAutoComplete

# With Gemini dispatch too
.\scripts\start_agent_ops.ps1 -StartControlLoop -StartOllamaRunner -OllamaAutoComplete -ExecuteGemini
```

This opens separate terminals for the watchdog, dashboard, control loop (routes + dispatches), and the Ollama runner.

## How It Works

1. **Control plane dispatches subtasks** — `agent_control_plane.py` scans active manager tasks, matches keywords (test, lint, render, qa, batch, verify, artifact, etc.), and creates `__OLLAMA` subtask cards in `agent_ops/20_active/ollama-local-*/`.

2. **Runner picks them up** — `ollama_task_runner.py` scans those directories for cards that don't yet have a handoff file.

3. **Runs `ollama run <model> <prompt>`** — extracts the `## Prompt` section from the card and passes it to the Ollama CLI.

4. **Writes handoff** — saves stdout/stderr to `agent_ops/30_handoffs/<subtask_id>__<agent_id>.md` with exit code and pass/fail status.

5. **Optionally auto-completes** — with `--auto-complete`, subtasks that exit 0 are automatically marked done (locks and ownership cleaned up).

## Options

| Flag | Default | Description |
|------|---------|-------------|
| `--agent <id>` | all ollama-local-* | Process only this worker (can repeat) |
| `--model <name>` | from control_plane.json | Override Ollama model |
| `--timeout <sec>` | 300 | Kill subtask after this many seconds |
| `--loop` | off | Poll continuously instead of one-shot |
| `--interval <sec>` | 60 | Seconds between polls in loop mode |
| `--auto-complete` | off | Mark passing subtasks as done |
| `--dry-run` | off | Show what would run without executing |

## Creating Subtasks Manually

If you want to dispatch a subtask to Ollama without the control plane:

```bash
# Create a card directly
cat > agent_ops/20_active/ollama-local-1/TASK-20260327-006__OLLAMA.md << 'EOF'
# TASK-20260327-006__OLLAMA

- `owner`: ollama-local-1
- `parent_task`: TASK-20260327-006
- `status`: active
- `model`: qwen2.5-coder:14b

## Prompt

Run pytest and report results:
python -m pytest tests/ -v
Report the full output including any failures.
EOF

# Then run it
python scripts/ollama_task_runner.py --agent ollama-local-1
```

## Monitoring

```bash
# Check what's pending
python scripts/ollama_task_runner.py --dry-run

# Check handoffs written
ls agent_ops/30_handoffs/*OLLAMA*

# Dashboard shows all active tasks including Ollama subtasks
python scripts/run_blender_buildings_workflows.py dashboard --once-json
```
