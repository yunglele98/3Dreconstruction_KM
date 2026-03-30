# AI Automation Factory — Security, Workflow & Performance Audit (V4)

**Date:** 2026-03-30
**Source:** Live port scan, .env audit, workflow JSON review, Docker inspect

---

## Executive Summary

The stack has **11 security vulnerabilities**, ranging from plaintext API tokens accessible to any admin-level process, to unauthenticated services exposed on all network interfaces. Three of these are exploitable by anyone on your LAN right now. The workflow templates are scaffolds with wiring bugs. No container has resource limits.

---

## PART A: SECURITY AUDIT

### S1. CRITICAL: Qdrant Exposed on 0.0.0.0:6333 — Zero Auth

**What:** Qdrant is listening on all interfaces (`::`/`0.0.0.0`) port 6333 with no authentication. Anyone on your home/office network can:
- Read all vector embeddings
- Delete collections
- Inject poisoned vectors (RAG data poisoning)
- Use the REST API to enumerate your knowledge base

**Fix:** Bind Qdrant to Docker-internal only. Remove the `ports:` block from the qdrant service in docker-compose.yml. Other containers reach it via Docker DNS (`qdrant:6333`). If you need host access for debugging, bind to localhost only:
```yaml
ports:
  - "127.0.0.1:6333:6333"
```

### S2. CRITICAL: Ollama Exposed on 0.0.0.0:11434 — Zero Auth

**What:** Your native Ollama install listens on all interfaces. Anyone on the LAN can:
- Run inference on all 66 models (including codellama:34b, dolphin-mixtral:26GB)
- Download/delete models
- Consume your RTX 2080 Super at will
- Use uncensored models (dolphin-mistral, llama2-uncensored) for any purpose

**Fix:** Set the `OLLAMA_HOST` environment variable to `127.0.0.1:11434` (localhost only). Docker containers still reach it via `host.docker.internal:11434` because that resolves to the host's loopback.

On Windows, set it system-wide:
```powershell
[Environment]::SetEnvironmentVariable("OLLAMA_HOST", "127.0.0.1:11434", "Machine")
# Restart Ollama service after
```

### S3. CRITICAL: Dozzle Has Docker Socket + Network Exposure

**What:** Dozzle on port 8888 has `/var/run/docker.sock` mounted AND is accessible to anyone on the network. The Docker socket is root-equivalent — Dozzle can see all container logs, which include:
- Environment variables (printed on startup)
- API tokens and secrets in log output
- Database queries with credentials

**Fix:** Bind to localhost only:
```yaml
ports:
  - "127.0.0.1:8888:8080"
```

### S4. HIGH: Plaintext Secrets in .env

**What:** `C:\Windows\System32\infra\n8n\.env` contains plaintext tokens:

| Token | Type | Risk if Leaked |
|---|---|---|
| GitHub `ghp_*` | Personal access token | Full repo access |
| Slack `xoxb-*` | Bot token | Read/write all channels |
| ClickUp `pk_*` | API token | Full workspace access |
| Notion `ntn_*` | Internal integration token | Full workspace read/write |
| N8N_ENCRYPTION_KEY | Encryption key | Decrypt all n8n credentials |
| POSTGRES_PASSWORD | DB superuser | Full database access |

**Mitigating factor:** The file is in `C:\Windows\System32` which requires admin access. But any process running as admin (including Docker Desktop, Ollama, any Node.js tool) can read it.

**Fix options (pick one):**
1. **Docker secrets** — convert sensitive values to Docker secrets (compose supports `secrets:` blocks)
2. **Encrypt at rest** — use Windows DPAPI via PowerShell to encrypt the file, decrypt only when starting compose
3. **Minimum viable:** Restrict file permissions: `icacls .env /inheritance:r /grant:r liam1:(R)` — only your user account can read it

### S5. HIGH: Password Reuse Across Services

**What:** `.env` shows:
- `N8N_BASIC_AUTH_PASSWORD=gLC3YbXjJ7ZGKvsVNoyJTmkRtCQ`
- `GITEA_ADMIN_PASSWORD=gLC3YbXjJ7ZGKvsVNoyJTmkRtCQ`

Same password for n8n and Gitea admin. If either is compromised, both are.

**Fix:** Generate unique passwords for each service. Use `python -c "import secrets; print(secrets.token_urlsafe(24))"` for each.

### S6. HIGH: n8n Basic Auth Not Enforced in Compose

**What:** The .env has `N8N_BASIC_AUTH_ACTIVE=true` and `N8N_BASIC_AUTH_USER=admin`, but the docker-compose.yml doesn't pass these to the n8n container. The compose only passes `N8N_USER_MANAGEMENT_DISABLED` and `N8N_ENCRYPTION_KEY`. So n8n may be accessible without authentication at `http://<your-ip>:5678`.

**Fix:** Add to n8n environment in docker-compose.yml:
```yaml
N8N_BASIC_AUTH_ACTIVE: "true"
N8N_BASIC_AUTH_USER: ${N8N_BASIC_AUTH_USER}
N8N_BASIC_AUTH_PASSWORD: ${N8N_BASIC_AUTH_PASSWORD}
```

Or better: bind to localhost and rely on NPM for auth:
```yaml
ports:
  - "127.0.0.1:5678:5678"
```

### S7. HIGH: Unsandboxed Code Executor

**What:** The `executor` service (container name `n8n_code_executor`) runs a Flask server that accepts arbitrary Python code via POST to `/execute` and runs it with `exec()`. No authentication, no sandboxing, no input validation.

The `self-coding-workflow.json` actively routes Gitea push events to this endpoint.

Currently it's not running (not started), but if someone runs `docker compose up -d`, it will start and be exploitable.

**Fix:** Remove the entire `executor` service from docker-compose.yml. n8n has a built-in Code node that runs JavaScript/Python in a sandboxed environment — use that instead.

### S8. MEDIUM: Localtunnel Exposes Webhooks to Internet

**What:** `tunnel_url.txt` shows `https://witty-news-lose.loca.lt` — this tunnels internet traffic to n8n:5678. Anyone who discovers this URL can trigger n8n webhooks. Localtunnel provides NO authentication.

**Fix:** Route the tunnel through NPM instead of directly to n8n. NPM can require auth headers or IP whitelists. Also, consider switching from Localtunnel to Cloudflare Tunnel (free tier) which has built-in access policies.

### S9. MEDIUM: Watchtower Has Docker Socket + Auto-Update

**What:** Watchtower has `/var/run/docker.sock` (root-equivalent) and auto-updates ALL containers daily. A compromised image on Docker Hub gets auto-deployed.

**Fix (already covered in V3):** Set `WATCHTOWER_MONITOR_ONLY: "true"`.

### S10. LOW: Homepage Dashboard Exposes Service Map

**What:** The Homepage dashboard at port 8080 shows all services, their ports, and container names. This is an reconnaissance goldmine for anyone on the network.

**Fix:** Bind to localhost: `"127.0.0.1:8080:3000"`

### S11. LOW: SysMonitor No Auth

**What:** Port 5001 exposes CPU/memory stats. Low-risk data, but it confirms the machine is running an AI stack.

**Fix:** Bind to localhost: `"127.0.0.1:5001:5001"`

### Security Fix Summary — docker-compose.yml Port Changes

Replace all `0.0.0.0`-exposed ports with localhost-only bindings. Only NPM (80/443/81) should be on all interfaces:

```yaml
# KEEP on all interfaces (NPM is the entry point):
proxy:    ports: ["80:80", "443:443", "81:81"]

# BIND TO LOCALHOST ONLY:
n8n:      ports: ["127.0.0.1:5678:5678"]
gitea:    ports: ["127.0.0.1:3001:3000", "127.0.0.1:2222:22"]
qdrant:   # REMOVE ports entirely — internal only
dozzle:   ports: ["127.0.0.1:8888:8080"]
sysmon:   ports: ["127.0.0.1:5001:5001"]
dashboard: ports: ["127.0.0.1:8080:3000"]

# ALREADY INTERNAL (no change needed):
postgres: (no ports exposed) ✓
redis:    (no ports exposed) ✓
```

Access everything through NPM proxy routes. Direct ports remain for localhost debugging only.

---

## PART B: WORKFLOW AUDIT

### All 7 Workflow Templates Reviewed

| Workflow | Status | Issues |
|---|---|---|
| **Master AI Router** | Scaffold | Only checks if message contains "code" — needs real intent classification. No LLM credentials attached. |
| **Long-Term Memory (Qdrant)** | Correct architecture | Uses Ollama llama3.1:8b + nomic-embed-text + Qdrant. Will work once Qdrant `ai_memory` collection exists and knowledge base has docs. |
| **Document Scraper** | Correct architecture | Reads `knowledge_base/` → embeds to Qdrant. Will work once KB is populated. |
| **Self-Coding Pipeline** | **DANGEROUS** | Routes Gitea pushes to unsandboxed `exec()` endpoint. Must be rewritten to use n8n Code node. |
| **Sustainable AI Guard** | Bug | Reads `$json.cpu` but sysmonitor returns `$json.cpu_percent_estimate`. Will always evaluate as falsy. Fix: `$json.cpu_percent_estimate`. |
| **Forever Free Router** | Broken | Uses `duckduckgo.com/duckduckgo-inference-api` which doesn't exist. Remove DDG node, keep Ollama-only path. |
| **Starter Pack** | Minimal | GitHub webhook → Slack notify. Works if Slack credentials are configured in n8n. |

### Missing Workflows for Kensington Pipeline

The stack has zero workflows that connect to your actual Kensington pipeline. These should be built:

1. **Param Change Watcher** — Gitea push to `params/` → run `qa_params_gate.py` → run `audit_params_quality.py` → post results to Slack. (This is the n8n_gitea_qa_workflow.json from V2.)

2. **Batch Regen Trigger** — Gitea push with `params/` changes → `fingerprint_params.py` to detect changed buildings → `build_regen_batches.py` → trigger Blender regen on the Alienware via n8n Execute Command.

3. **Agent Task Router** — Schedule trigger every 5 min → check `agent_ops/10_backlog/` for new tasks → assign to available agent (Ollama for small tasks, Claude Code for complex) → move to `20_active/`.

4. **Photo Analysis Pipeline** — Manual trigger with batch ID → run `prepare_batches.py` → dispatch to Gemini/Ollama via n8n AI Agent nodes → merge results back via `translate_agent_params.py`.

5. **Health Dashboard** — Schedule every 1 min → hit sysmonitor + Qdrant + Gitea + Redis health endpoints → aggregate → store in PG for time-series → Homepage widget via API.

---

## PART C: PERFORMANCE & RESOURCE LIMITS

### Current State: Zero Resource Limits

No container (except browserless at 2GB) has memory or CPU limits. This means:
- A runaway Ollama inference can consume all 32GB RAM
- A Qdrant index rebuild can starve n8n of CPU
- A memory leak in any container can OOM the entire Docker host

### Recommended Limits

Add to each service in docker-compose.yml:

```yaml
# Critical path — give them room
n8n:
  deploy:
    resources:
      limits: { memory: 2g, cpus: "2.0" }

postgres:
  deploy:
    resources:
      limits: { memory: 1g, cpus: "1.0" }
  command: >
    postgres
    -c shared_buffers=256MB
    -c effective_cache_size=512MB
    -c work_mem=16MB
    -c maintenance_work_mem=128MB

qdrant:
  deploy:
    resources:
      limits: { memory: 1g, cpus: "1.0" }

redis:
  deploy:
    resources:
      limits: { memory: 256m, cpus: "0.5" }

# Utility — keep them light
gitea:
  deploy:
    resources:
      limits: { memory: 512m, cpus: "0.5" }

dozzle:
  deploy:
    resources:
      limits: { memory: 128m, cpus: "0.25" }

sysmonitor:
  deploy:
    resources:
      limits: { memory: 64m, cpus: "0.25" }

dashboard:
  deploy:
    resources:
      limits: { memory: 256m, cpus: "0.25" }

proxy:
  deploy:
    resources:
      limits: { memory: 256m, cpus: "0.5" }

updater:
  deploy:
    resources:
      limits: { memory: 128m, cpus: "0.25" }

browserless:
  deploy:
    resources:
      limits: { memory: 2g, cpus: "1.0" }   # already set
```

**Total reserved:** ~7.5 GB RAM, 6.5 CPU cores — leaves plenty for Ollama (native) and Blender.

### PostgreSQL Tuning

The default `postgres:16-alpine` runs with out-of-box settings (128MB shared_buffers). For your Kensington DB (1,075 buildings + 13 field survey tables + GIS data), add a custom command:

```yaml
command: >
  postgres
  -c shared_buffers=256MB
  -c effective_cache_size=512MB
  -c work_mem=16MB
  -c maintenance_work_mem=128MB
  -c random_page_cost=1.1
  -c max_connections=50
  -c log_min_duration_statement=1000
```

The last line logs any query taking >1 second — useful for catching slow PostGIS queries.

---

## PART D: CONNECTED SERVICES STATUS

### Tokens Verified Present in .env

| Service | Token Type | Can Validate? |
|---|---|---|
| **GitHub** | `ghp_` PAT | Yes — n8n can list repos. Check scope: does it have `repo` + `workflow` access? |
| **Slack** | `xoxb-` bot token | Yes — n8n can post to channels. Check: which channels is the bot invited to? |
| **ClickUp** | `pk_` API token | Yes — n8n can read/write tasks. Maps to your ClickUp workspace. |
| **Notion** | `ntn_` internal integration | Yes — n8n can read/write pages. Check: which pages has the integration been shared with? |

### What's NOT Connected (But Should Be)

Given your Kensington pipeline has `agent_ops/` task routing, these would be high-value:

1. **ClickUp → agent_ops** — Sync ClickUp tasks to `agent_ops/10_backlog/` cards. When a ClickUp task moves to "In Progress", file-create a card in `20_active/`.

2. **Slack → n8n alerts** — Post QA failures, batch completion, thermal guard triggers to a `#kensington-factory` channel.

3. **GitHub → Gitea mirror** — If you also push to GitHub, set up a Gitea mirror so both repos stay in sync.

4. **Notion → Knowledge Base** — Export Notion pages about the project (meeting notes, design decisions) into `knowledge_base/` for RAG embedding.

---

## PART E: KENSINGTON PIPELINE INTEGRATION GAPS

### What the Factory SHOULD Automate But Doesn't

| Pipeline Step | Current | Should Be |
|---|---|---|
| `export_db_params.py` | Manual CLI | n8n scheduled trigger (daily or on DB change) |
| `prepare_batches.py` | Manual CLI | n8n trigger after new params export |
| Agent photo analysis | Manual agent launch | n8n dispatches to Ollama/Claude via AI Agent nodes |
| Enrichment pipeline (6 scripts) | Manual in-order | n8n workflow chain: translate → enrich → normalize → patch → infer |
| `qa_params_gate.py` | Manual CLI | Gitea push webhook (built in V2) |
| Blender batch generation | Manual `blender --background` | n8n Execute Command triggered by param change |
| `export_deliverables.py` | Manual CLI | n8n scheduled (weekly) or on-demand |
| `writeback_to_db.py` | Manual CLI | n8n trigger after enrichment complete |

### The Missing Glue: n8n ↔ Blender

The biggest gap is Blender. n8n can't call `blender --background --python` because Blender runs on the Windows host, not inside Docker. Solutions:

1. **n8n Execute Command via host mount** — Mount a "command queue" directory into n8n. n8n writes a JSON job file. A PowerShell file watcher on the host picks it up and runs Blender.

2. **SSH to localhost** — n8n SSH node connects to the Windows host via SSH (install OpenSSH server on Windows) and runs Blender commands directly.

3. **Webhook to local script** — A lightweight Flask/FastAPI server on the host listens for n8n webhooks and spawns Blender processes. Safer than the current `exec()` approach because it only accepts structured job JSONs, not arbitrary code.

**Recommendation:** Option 3 — replace the removed Code Executor with a purpose-built Blender job runner.

---

## Claude Code CLI Prompt

```
Read docs/FACTORY_AUDIT_V4_SECURITY.md and execute the security fixes. Priority order:

PHASE 1 — LOCK DOWN PORTS (5 minutes):
Edit C:\Windows\System32\infra\n8n\docker-compose.yml
Bind all service ports to 127.0.0.1 except NPM (80/443/81).
Remove the qdrant ports: block entirely.
Remove the entire executor service block.
Run: docker compose down && docker compose up -d

PHASE 2 — LOCK DOWN OLLAMA (2 minutes):
Set OLLAMA_HOST=127.0.0.1:11434 as a system environment variable.
Restart Ollama service.

PHASE 3 — FIX PASSWORDS (5 minutes):
Generate unique passwords for n8n and Gitea admin.
Update .env with the new unique passwords.
Restrict .env file permissions to current user only.

PHASE 4 — ADD RESOURCE LIMITS (10 minutes):
Add deploy.resources.limits to every service in docker-compose.yml per the V4 audit.
Add PostgreSQL tuning parameters.
Rebuild: docker compose down && docker compose up -d

PHASE 5 — FIX WORKFLOW BUGS (10 minutes):
Fix sustainable-ai-guard.json: change $json.cpu to $json.cpu_percent_estimate
Fix forever-free-router.json: remove the DuckDuckGo node (API doesn't exist)
Fix self-coding-workflow.json: remove executor reference, use n8n Code node instead
Import all fixed workflows into n8n.

PHASE 6 — PASS N8N BASIC AUTH ENVS (2 minutes):
Add N8N_BASIC_AUTH_ACTIVE, N8N_BASIC_AUTH_USER, N8N_BASIC_AUTH_PASSWORD to the n8n environment block in docker-compose.yml.
Restart n8n.

After each phase, verify the change worked before moving on.
```
