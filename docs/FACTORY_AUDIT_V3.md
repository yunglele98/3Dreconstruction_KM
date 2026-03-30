# AI Automation Factory — Deep Audit & Fixes (V3)

**Date:** 2026-03-30
**Source:** Live scan of Alienware Docker stack via Desktop Commander

---

## Executive Summary

The stack is **partially operational** — 10 of 13 defined containers are running, but several are misconfigured. The most critical issue is that n8n is silently falling back to SQLite instead of PostgreSQL, which means all workflow data lives in a single file with no backup or scaling path. Three containers defined in compose never started. 11 of 15 API key slots are empty. Redis is running but unused.

---

## 1. CRITICAL: n8n Running on SQLite, Not PostgreSQL

### The Problem

The compose file sets `DB_TYPE: postgresdb` and `DB_POSTGRESDB_DATABASE: kensington`, but n8n has a 585KB SQLite file at `/home/node/.n8n/database.sqlite`. This means n8n either failed to connect to PG on first boot (and silently fell back to SQLite), or the PG config was added after n8n first started.

Additionally, `DB_POSTGRESDB_DATABASE` is set to `kensington` — your building assessment database. n8n should NEVER share a database with application data. If n8n had connected, it would have created its tables inside your Kensington building DB.

### The Fix

1. Create a dedicated `n8n` database in PostgreSQL
2. Export all workflows and credentials from SQLite
3. Reconfigure n8n to use the new PG database
4. Restart n8n — it will auto-migrate the schema
5. Import the exported workflows and credentials

### Risk

**HIGH** — SQLite has no replication, no point-in-time recovery, and corrupts under concurrent writes. If n8n crashes mid-execution, you could lose workflow state. Fixing this is the single highest priority.

---

## 2. CRITICAL: 3 Containers Not Running

### What's Missing

| Container | Image | Purpose | Why It's Down |
|---|---|---|---|
| `n8n_ollama` | `ollama/ollama:latest` | GPU inference | Needs `nvidia` GPU driver in Docker — likely failed on startup because Docker Desktop's GPU passthrough wasn't configured |
| `n8n_code_executor` | `python:3.11-slim` | Isolated Python sandbox on :5002 | `exec()` in a Flask server — may have crashed on startup or been removed |
| `n8n_browser` | `browserless/chrome:latest` | Headless Chrome for n8n | 2GB memory limit may have OOM'd, or Docker Desktop didn't expose the socket |

### Impact

- **Ollama container**: Not needed because Ollama runs natively. But the compose still defines it, wasting a `docker compose up` attempt. Solution: either remove from compose, or mark as `profiles: [gpu]` so it only starts when explicitly requested.
- **Code Executor**: This is an unsandboxed `exec()` endpoint — a security hole. Anyone on the network can POST arbitrary Python code to port 5002. Either secure it or remove it.
- **Browserless**: Useful for n8n web scraping workflows. Should be restarted with proper memory.

---

## 3. HIGH: 11 of 15 API Keys Empty

### Current State

| Key | Status | Impact |
|---|---|---|
| `CLICKUP_API_TOKEN` | **SET** | ClickUp integration works |
| `GITHUB_TOKEN` | **SET** | GitHub integration works |
| `SLACK_TOKEN` | **SET** | Slack integration works |
| `NOTION_TOKEN` | **SET** | Notion integration works |
| `OPENROUTER_API_KEY` | EMPTY | No unified AI routing — this was supposed to be the primary inference path |
| `GROQ_API_KEY` | EMPTY | No Groq turbo inference |
| `ANTHROPIC_API_KEY` | EMPTY | Claude not available to n8n workflows |
| `OPENAI_API_KEY` | EMPTY | No GPT-5/o1 access from n8n |
| `GEMINI_API_KEY` | EMPTY | No Gemini access from n8n |
| `MISTRAL_API_KEY` | EMPTY | No Mistral access |
| `COHERE_API_KEY` | EMPTY | No Cohere RAG |
| `TOGETHER_API_KEY` | EMPTY | No Together inference |
| `AZURE_OPENAI_*` | EMPTY | No Azure GPT access |
| `GOOGLE_CLIENT_*` | EMPTY | No Google Workspace |
| `AWS_*` | EMPTY | No Bedrock access |

### Impact

The spec claims "15+ AI API keys" but only 4 productivity tool tokens are set. Zero AI inference keys are configured, which means every n8n workflow that tries to call an LLM API will fail. The local Ollama is the only working inference path.

### Fix Priority

At minimum, set `OPENROUTER_API_KEY` — it provides unified access to Claude, GPT, Gemini, Mistral, and 200+ models through one key. This single key covers 80% of the spec's "Agent Integrations" tier.

---

## 4. MEDIUM: Redis Running But Empty

### The Problem

Redis is healthy (1MB RAM used) but the keyspace is completely empty — zero keys. n8n's `N8N_REDIS_HOST=redis` is set but n8n isn't actually using Redis because:

1. n8n only uses Redis for **queue mode** (`EXECUTIONS_MODE=queue`), but the compose sets `N8N_EXECUTIONS_PROCESS=main` (single-process mode)
2. In main mode, Redis does nothing — it's just wasting RAM

### The Fix

Either:
- **Option A:** Switch to queue mode (`EXECUTIONS_MODE=queue`) to unlock parallel workflow execution. This is recommended for a multi-agent stack.
- **Option B:** Remove Redis from compose if you don't need parallel execution.

### Recommendation

Switch to queue mode. Your spec describes 5-10 parallel agents — single-process n8n can't handle that. Queue mode uses Redis as a job broker, letting n8n process multiple webhook events concurrently.

---

## 5. MEDIUM: Knowledge Base Empty

The `knowledge_base/` directory is mounted into n8n at `/home/node/knowledge_base` but is empty. This was supposed to be the RAG knowledge base for Qdrant. Without it, the `long-term-memory-workflow.json` has nothing to embed.

### Fix

Populate it with your Kensington project docs — CLAUDE.md, AGENT_PROMPT.md, the HCD PDF, and key parameter schemas. Then set up an n8n workflow that embeds these into Qdrant on file change.

---

## 6. MEDIUM: n8n Workflow JSONs Not Imported

Six workflow JSON files exist on disk but are likely not imported into n8n:

| File | Size | Purpose |
|---|---|---|
| `master-router-workflow.json` | 1.6KB | Chat trigger → if "code" → Claude, else → GPT-5 |
| `long-term-memory-workflow.json` | 1.9KB | RAG memory pipeline (needs Qdrant + knowledge base) |
| `document-scraper-workflow.json` | 2.0KB | Web scraping via Browserless |
| `self-coding-workflow.json` | 2.5KB | Agent that writes/executes code |
| `sustainable-ai-guard.json` | 2.2KB | Thermal/cost guardrails |
| `forever-free-router.json` | 1.3KB | Free-tier model routing |
| `starter-workflow-pack.json` | 0.8KB | Bundle of starter templates |

The `master-router-workflow.json` I read has a basic structure — chat trigger → if contains "code" → Claude agent, else → GPT agent. These are scaffolds, not production workflows. They need API credentials to function.

---

## 7. MEDIUM: Gitea INSTALL_LOCK Still False

Gitea's `app.ini` shows `INSTALL_LOCK = false` and `ROOT_URL` is blank. The V2 prompt addresses this, but it hasn't been run yet. Until this is fixed, Gitea shows the install wizard instead of the login page.

Additionally, the compose defines `GITEA_ADMIN_USER=agent` in .env but the V2 prompt creates user `liam`. These should be aligned.

---

## 8. LOW: SysMonitor Reads Container /proc, Not Host

The `sysmonitor.py` reads `/proc/meminfo` and `os.getloadavg()` — but it runs inside a container, so these reflect the **container's cgroup limits**, not the actual Alienware host. The RTX 2080 Super thermal data, actual host RAM, and real CPU usage are invisible.

### Fix

Mount the host's `/proc` read-only, or switch to a host-mode monitoring approach (e.g., Prometheus node_exporter as a sidecar with `--pid=host --network=host`).

---

## 9. LOW: Localtunnel URL Is Stale

`tunnel_url.txt` contains `https://witty-news-lose.loca.lt` — Localtunnel URLs are ephemeral and change on restart. There's no process keeping this tunnel alive or updating the URL. n8n webhooks that depend on this URL will break silently.

### Fix

Run Localtunnel as a persistent service that writes the current URL to a file, and have an n8n workflow that reads that file on startup to update webhook base URLs.

---

## 10. LOW: Watchtower Auto-Updating Everything

Watchtower polls daily (`WATCHTOWER_POLL_INTERVAL: 86400`) and auto-updates ALL containers. This is dangerous for a production stack — a breaking n8n update could corrupt the SQLite database or break workflow compatibility.

### Fix

Pin critical images to specific versions:
- `n8nio/n8n:1.xx.x` (not `latest`)
- `postgres:16-alpine` (already pinned, good)
- `qdrant/qdrant:v1.x.x` (not `latest`)

Or configure Watchtower to monitor-only mode with notifications instead of auto-update.

---

## Priority-Ordered Fix List

| # | Issue | Severity | Effort | Impact |
|---|---|---|---|---|
| 1 | n8n SQLite → PostgreSQL migration | CRITICAL | 30 min | Prevents data loss, enables scaling |
| 2 | Set OPENROUTER_API_KEY (at minimum) | CRITICAL | 5 min | Unlocks all AI inference in n8n |
| 3 | Fix Gitea setup (INSTALL_LOCK, ROOT_URL, admin) | HIGH | 10 min | Enables repo + webhook pipeline |
| 4 | Start Browserless container | HIGH | 5 min | Enables web scraping workflows |
| 5 | Switch n8n to queue mode (Redis) | HIGH | 15 min | Enables parallel agent execution |
| 6 | Import + configure workflow JSONs | MEDIUM | 30 min | Activates the automation workflows |
| 7 | Remove/secure Code Executor | MEDIUM | 5 min | Closes unsandboxed exec() hole |
| 8 | Populate knowledge base + embed to Qdrant | MEDIUM | 1 hour | Enables RAG memory |
| 9 | Fix Ollama in compose (profiles or remove) | LOW | 5 min | Cleans up compose, prevents startup errors |
| 10 | Pin image versions, restrict Watchtower | LOW | 10 min | Prevents surprise breaking updates |
| 11 | Fix SysMonitor to read host metrics | LOW | 20 min | Accurate thermal guard |
| 12 | Persistent Localtunnel with URL update | LOW | 30 min | Stable external webhooks |

---

## Claude Code CLI Prompt

```
You are fixing critical issues in a live AI automation Docker stack on Windows. The stack runs from C:\Windows\System32\infra\n8n\docker-compose.yml. Follow each phase exactly. Verify after each step.

### CONTEXT
- 10 containers running on n8n_default network (see docker ps)
- 3 containers from compose NOT running: n8n_ollama, n8n_code_executor, n8n_browser
- Compose file: C:\Windows\System32\infra\n8n\docker-compose.yml
- .env file: C:\Windows\System32\infra\n8n\.env
- n8n is on SQLite, not PostgreSQL (MUST FIX)
- 11 of 15 API keys in .env are empty
- Redis is running but unused (n8n in single-process mode)

### PHASE 1: MIGRATE N8N FROM SQLITE TO POSTGRESQL (CRITICAL)

This is the single most important fix. n8n is silently using SQLite despite having PG env vars.

1. Export all current workflows and credentials from n8n:
   docker exec n8n_local n8n export:workflow --all --output=/tmp/all_workflows.json
   docker exec n8n_local n8n export:credentials --all --output=/tmp/all_credentials.json
   docker cp n8n_local:/tmp/all_workflows.json C:\Windows\System32\infra\n8n\backup_workflows.json
   docker cp n8n_local:/tmp/all_credentials.json C:\Windows\System32\infra\n8n\backup_credentials.json

2. Create a dedicated n8n database (NOT kensington):
   echo CREATE DATABASE n8n_prod; | docker exec -i n8n_db psql -U postgres

3. Edit the .env file — change POSTGRES_DB line:
   Keep POSTGRES_DB=kensington (that's for the building data)
   But n8n needs a SEPARATE database. So edit docker-compose.yml:
   Change: DB_POSTGRESDB_DATABASE: ${POSTGRES_DB:-kensington}
   To:     DB_POSTGRESDB_DATABASE: n8n_prod

4. Delete the SQLite database so n8n is forced to use PG:
   docker exec n8n_local rm /home/node/.n8n/database.sqlite
   docker exec n8n_local rm -f /home/node/.n8n/database.sqlite-shm
   docker exec n8n_local rm -f /home/node/.n8n/database.sqlite-wal

5. Restart n8n:
   docker restart n8n_local

6. Wait 20 seconds for schema migration, then verify:
   echo SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'; | docker exec -i n8n_db psql -U postgres -d n8n_prod
   Expected: count > 0 (n8n creates ~30 tables)

7. Import the backed-up workflows and credentials:
   docker cp C:\Windows\System32\infra\n8n\backup_workflows.json n8n_local:/tmp/all_workflows.json
   docker cp C:\Windows\System32\infra\n8n\backup_credentials.json n8n_local:/tmp/all_credentials.json
   docker exec n8n_local n8n import:workflow --input=/tmp/all_workflows.json
   docker exec n8n_local n8n import:credentials --input=/tmp/all_credentials.json

8. Verify workflows are back:
   docker exec n8n_local n8n export:workflow --all --output=/dev/stdout 2>/dev/null | head -5

### PHASE 2: ENABLE QUEUE MODE (USE REDIS)

9. Edit docker-compose.yml — in the n8n service environment section, change:
   N8N_EXECUTIONS_PROCESS: main
   To:
   EXECUTIONS_MODE: queue

   And add:
   N8N_CONCURRENCY_PRODUCTION_LIMIT: 20

10. Restart n8n:
    docker restart n8n_local
    Wait 15 seconds.

11. Verify Redis is now being used:
    docker exec n8n_redis redis-cli INFO keyspace
    Expected: db0:keys=N (should show some keys now)

### PHASE 3: FIX MISSING CONTAINERS

12. The Ollama container in compose requires NVIDIA Docker runtime which may not be configured.
    Since Ollama runs natively on Windows, COMMENT OUT the entire ollama service block in docker-compose.yml.
    Add a comment: "# Ollama runs natively — use host.docker.internal:11434 from containers"

13. The Code Executor is an unsandboxed exec() endpoint. COMMENT IT OUT entirely.
    Add a comment: "# REMOVED: Unsandboxed exec() is a security risk. Use n8n Code node instead."

14. Start Browserless:
    docker compose -f C:\Windows\System32\infra\n8n\docker-compose.yml up -d browserless

15. Verify Browserless is running:
    docker ps --filter name=n8n_browser
    Expected: Up (healthy)

### PHASE 4: API KEYS

16. Ask the user which AI API keys they have available. At minimum they need ONE of:
    - OPENROUTER_API_KEY (recommended — unified access to all models)
    - ANTHROPIC_API_KEY
    - OPENAI_API_KEY

17. Once they provide key(s), edit C:\Windows\System32\infra\n8n\.env and fill in the values.

18. Restart n8n to pick up the new keys:
    docker restart n8n_local

### PHASE 5: IMPORT WORKFLOW TEMPLATES

19. Import all workflow JSONs into n8n:
    for %f in (C:\Windows\System32\infra\n8n\*-workflow.json C:\Windows\System32\infra\n8n\sustainable-ai-guard.json C:\Windows\System32\infra\n8n\forever-free-router.json C:\Windows\System32\infra\n8n\starter-workflow-pack.json) do (
      docker cp "%f" n8n_local:/tmp/import_wf.json
      docker exec n8n_local n8n import:workflow --input=/tmp/import_wf.json
    )

20. Also import the Kensington QA workflow if it exists:
    Find n8n_gitea_qa_workflow.json in the blender_buildings docs/infra folder.
    docker cp <path> n8n_local:/tmp/qa_wf.json
    docker exec n8n_local n8n import:workflow --input=/tmp/qa_wf.json

21. Verify all workflows imported:
    Open http://localhost:5678 and check the workflow list.

### PHASE 6: PIN IMAGES & RESTRICT WATCHTOWER

22. Edit docker-compose.yml — change these image tags:
    n8n:     n8nio/n8n:latest → pin to current version (check with: docker exec n8n_local n8n --version)
    qdrant:  qdrant/qdrant:latest → pin to current (check with: docker exec n8n_vector_db cat /qdrant/VERSION 2>/dev/null)
    gitea:   gitea/gitea:latest → pin to current (check Gitea API version response)

23. Edit the watchtower service in docker-compose.yml — add monitor-only mode:
    environment:
      WATCHTOWER_CLEANUP: "true"
      WATCHTOWER_POLL_INTERVAL: "86400"
      WATCHTOWER_MONITOR_ONLY: "true"
      WATCHTOWER_NOTIFICATIONS: "shoutrrr"
      WATCHTOWER_NOTIFICATION_URL: "generic://localhost:5678/webhook/watchtower-alerts"
    This makes Watchtower report available updates to n8n instead of auto-applying them.

### PHASE 7: COMPLETE GITEA SETUP

24. If not already done by V2 prompt:
    docker exec n8n_git sh -c "sed -i 's|^INSTALL_LOCK.*|INSTALL_LOCK = true|' /data/gitea/conf/app.ini"
    docker exec n8n_git sh -c "sed -i 's|^ROOT_URL.*|ROOT_URL = http://localhost:3001/|' /data/gitea/conf/app.ini"

25. Create admin user (use the .env credentials):
    docker exec n8n_git gitea admin user create --admin --username liam --password "CHANGE_ME_NOW" --email "liam13donaghy@gmail.com" --must-change-password=false 2>/dev/null || echo "User may already exist"

26. Restart Gitea:
    docker restart n8n_git

### PHASE 8: FIX SYSMONITOR (HOST METRICS)

27. Edit C:\Windows\System32\infra\n8n\docker-compose.yml — update the sysmonitor service:
    Add these to the sysmonitor service block:
      pid: host
      volumes:
        - ./sysmonitor.py:/app/sysmonitor.py:ro
        - /proc:/host/proc:ro

28. Edit C:\Windows\System32\infra\n8n\sysmonitor.py — change the /proc/meminfo path:
    Change: with open("/proc/meminfo", "r", encoding="utf-8") as f:
    To:     with open("/host/proc/meminfo", "r", encoding="utf-8") as f:

29. Restart sysmonitor:
    docker restart n8n_sys_monitor

### PHASE 9: POPULATE KNOWLEDGE BASE

30. Find the blender_buildings folder on the system.

31. Copy key docs into the knowledge base:
    copy <blender_buildings>\CLAUDE.md C:\Windows\System32\infra\n8n\knowledge_base\
    copy <blender_buildings>\docs\AGENT_PROMPT.md C:\Windows\System32\infra\n8n\knowledge_base\
    copy <blender_buildings>\AGENTS.md C:\Windows\System32\infra\n8n\knowledge_base\
    copy <blender_buildings>\docs\PIPELINE_RUNBOOK.md C:\Windows\System32\infra\n8n\knowledge_base\

32. These files are now available inside n8n at /home/node/knowledge_base/
    A future workflow can embed them into Qdrant for RAG.

### PHASE 10: DOCKER COMPOSE REBUILD

33. After all edits, do a full rebuild:
    cd C:\Windows\System32\infra\n8n
    docker compose down
    docker compose up -d

34. Wait 30 seconds for all services to start.

35. Full health check:
    docker ps -a (expect: all services Up except ollama and code_executor which are commented out)
    echo SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'; | docker exec -i n8n_db psql -U postgres -d n8n_prod
    docker exec n8n_redis redis-cli INFO keyspace
    curl http://localhost:5678/healthz
    curl http://localhost:3001/api/v1/version
    curl http://localhost:6333/collections
    curl http://localhost:5001/stats

36. Report final status to user with all URLs and what changed.
```

---

## Post-Fix Architecture

After running this prompt, the stack will be:

| Service | Status | DB | Notes |
|---|---|---|---|
| n8n | PostgreSQL (n8n_prod) + Redis queue | n8n_prod | Was: SQLite single-process |
| Gitea | PostgreSQL (gitea) | gitea | Was: setup incomplete |
| Qdrant | Running, timeout fixed (if V2 ran) | — | Ready for RAG embeddings |
| Redis | Active (n8n queue broker) | — | Was: running but unused |
| Browserless | Running | — | Was: not started |
| SysMonitor | Host metrics via /host/proc | — | Was: container metrics only |
| Watchtower | Monitor-only + alerts to n8n | — | Was: auto-updating everything |
| Ollama | Native (not containerized) | — | Compose entry commented out |
| Code Executor | Removed | — | Was: unsandboxed exec() hole |
| NPM | Running, needs proxy hosts (V2) | — | |

## Files Changed

| File | Change |
|---|---|
| `docker-compose.yml` | n8n DB target, queue mode, pin images, remove executor/ollama, fix sysmonitor |
| `.env` | API keys (user provides) |
| `sysmonitor.py` | /host/proc path for host metrics |
| `knowledge_base/` | Populated with Kensington project docs |
