# AI Automation Factory — Reverse Proxy & Gitea Evaluation

**Date:** 2026-03-29
**Context:** Kensington Market 3D heritage pipeline — partially deployed Docker stack on Alienware workstation

---

## 1. Current Network Analysis

Your stack currently exposes multiple services on distinct host ports:

| Service | Port | Auth | TLS |
|---|---|---|---|
| n8n (orchestrator) | 5678 | Built-in | No |
| Qdrant (vector DB) | 6333 | None | No |
| Dozzle (logs) | 8888 | None | No |
| SysMonitor | 5001 | None | No |
| Homepage dashboard | 8080 | None | No |
| PostgreSQL | 5432 | password | No |
| Redis | 6379 | None | No |
| Localtunnel | dynamic | Webhook secret | Yes (tunnel) |

**Identified gaps:**

- No centralized TLS termination — every service is plain HTTP on localhost. The Localtunnel webhook bridge is the only encrypted path, and it bypasses all internal services.
- No unified access control — Qdrant, Dozzle, SysMonitor, and Redis are reachable by anything on the host network with zero authentication.
- Port sprawl — eight separate ports to remember. Agents configured with hardcoded `localhost:NNNN` URLs break if any port shifts.
- No service discovery — agents must know exact ports. Adding a new service means updating every workflow that references it.
- No rate limiting or request logging at the edge — if a misbehaving agent hammers Qdrant or n8n, there's no circuit breaker.

---

## 2. Verdict: Nginx Proxy Manager

**Recommendation: Yes — deploy it.**

### What it solves

Nginx Proxy Manager (NPM) sits in front of every HTTP service and provides a single entry point with a web GUI for managing proxy routes, TLS certificates, and access lists.

**Concrete benefits for your stack:**

- **Single entry point.** All services become subpaths or subdomains off one port (80/443). Agents only need to know `https://factory.local/n8n`, `https://factory.local/qdrant`, etc. If you remap a port internally, agents never notice.
- **TLS everywhere.** Self-signed or Let's Encrypt certs terminate at the proxy. Qdrant, Dozzle, SysMonitor all become HTTPS with zero changes to those containers.
- **Access lists.** NPM's built-in access lists let you password-protect Dozzle and SysMonitor without modifying their containers. You can also IP-whitelist to only allow requests from Docker's internal network.
- **Rate limiting headers.** Custom Nginx configs per proxy host let you add `limit_req_zone` to throttle runaway agents before they hit Qdrant or n8n.
- **Webhook consolidation.** Instead of Localtunnel pointing directly at n8n:5678, point it at the proxy. The proxy can then route `/webhook/*` to n8n while blocking everything else from the tunnel — reducing your attack surface.
- **Integration with SysMonitor thermal guard.** A custom Nginx location block can return 503 when a sidecar script detects CPU > 70%, implementing your thermal pause at the edge rather than relying on each agent to check.

**What it doesn't solve:** TCP-level services (PostgreSQL 5432, Redis 6379) can't be proxied by NPM. Those stay on direct ports — but they shouldn't be exposed outside the Docker network anyway.

### Trade-offs

- Adds one more container (~60 MB RAM idle).
- The NPM web GUI runs on port 81 — one more port, but it's the last one you need to remember since everything else goes through 80/443.
- Slight latency overhead (~1-2ms per request) — irrelevant for your inference workloads.

---

## 3. Verdict: Gitea (Local Git Server)

**Recommendation: Yes — deploy it, with a specific scope.**

### What it solves for the Kensington pipeline

Your `agent_ops/` system already implements file-based task coordination with locks. Gitea adds version-controlled agent autonomy on top of that:

- **Param file versioning.** Your 1,241 `params/*.json` files are the single source of truth for every building. Right now if an agent corrupts a param file, recovery means hoping you have a recent backup or manually diffing. With Gitea, every enrichment pass (`translate_agent_params.py`, `enrich_skeletons.py`, etc.) can commit its changes to a branch. Bad enrichment? `git revert` the commit.
- **Agent branch isolation.** When 5-10 parallel agents (Claude/Codex/Gemini/Ollama) run via `agent_ops/`, each agent can work on a feature branch. The control plane merges results only after the review stage (`40_reviews/`). This replaces file-based locking with Git's merge machinery, which is battle-tested for exactly this problem.
- **n8n workflow versioning.** n8n workflows are JSON. Store them in Gitea and use webhooks to auto-import on push — this gives you rollback on any workflow change.
- **Webhook-driven pipelines.** Gitea fires webhooks on push/PR events. Wire these to n8n to trigger enrichment pipelines, QA gates (`qa_params_gate.py`), or Blender batch regen automatically when param files change.
- **Knowledge base versioning.** Your `knowledge_base/` directory mounted to containers can be a Gitea repo. Agents that update the knowledge base create PRs rather than silently modifying shared state.

### What it doesn't solve

- It's not a replacement for `agent_ops/` Kanban — Gitea tracks code, not task state. Keep the file-based Kanban for task routing and use Gitea for the artifacts those tasks produce.
- Gitea won't help with binary assets (`.blend`, `.fbx` renders in `outputs/`). Those stay on disk.

### Trade-offs

- ~150 MB RAM idle, plus PostgreSQL storage (can share your existing PG 16 instance with a separate database).
- Requires agents to know basic Git operations — but your agents already use Claude Code CLI, Codex CLI, and Gemini CLI, all of which handle Git natively.
- Initial migration effort: one-time `git init` + `git add` of `params/`, `scripts/`, `docs/`, `batches/`, and `agent_ops/`.

---

## 4. Recommended Architecture

```
                          Internet
                             |
                        Localtunnel
                             |
                    ┌────────┴────────┐
                    │  Nginx Proxy    │ :80 / :443
                    │  Manager        │ GUI :81
                    └──┬──┬──┬──┬──┬─┘
                       │  │  │  │  │
         ┌─────────────┘  │  │  │  └─────────────┐
         │                │  │  │                 │
    /n8n │          /git  │  │  │ /logs      /mon │
    ┌────┴──┐    ┌───┴───┐│  │  ┌──┴───┐   ┌──┴──┐
    │ n8n   │    │ Gitea ││  │  │Dozzle│   │SysMon│
    │ :5678 │    │ :3000 ││  │  │:8888 │   │:5001 │
    └───┬───┘    └───┬───┘│  │  └──────┘   └──────┘
        │            │    │  │
        │      ┌─────┘    │  │
        │      │          │  │
    ┌───┴──────┴──────────┴──┴───┐
    │      Docker Network         │
    │   ai-factory-net (bridge)   │
    │                             │
    │  ┌────────┐  ┌───────────┐ │
    │  │ PG 16  │  │  Qdrant   │ │
    │  │ :5432  │  │  :6333    │ │
    │  └────────┘  └───────────┘ │
    │  ┌────────┐  ┌───────────┐ │
    │  │ Redis  │  │  Ollama   │ │
    │  │ :6379  │  │  :11434   │ │
    │  └────────┘  └───────────┘ │
    └─────────────────────────────┘
```

Key points: PostgreSQL, Redis, Qdrant, and Ollama are internal-only (no host port binding needed once the proxy is in place — other containers reach them by service name on the Docker network). Only the proxy exposes ports 80, 443, and 81 to the host.

---

## 5. Docker Compose — Ready to Deploy

Add these services to your existing `docker-compose.yml` (or create a new override file `docker-compose.proxy-git.yml`).

### 5a. Shared Network

If your current compose doesn't define a named network, add this at the top level:

```yaml
networks:
  ai-factory-net:
    driver: bridge
```

Then add `networks: [ai-factory-net]` to every existing service block.

### 5b. Nginx Proxy Manager

```yaml
  nginx-proxy-manager:
    image: jc21/nginx-proxy-manager:latest
    container_name: nginx-proxy-manager
    restart: unless-stopped
    ports:
      - "80:80"       # HTTP
      - "443:443"     # HTTPS
      - "81:81"       # Admin GUI
    volumes:
      - npm_data:/data
      - npm_letsencrypt:/etc/letsencrypt
      - ./nginx-custom:/data/nginx/custom   # custom rate-limit configs
    environment:
      DB_SQLITE_FILE: /data/database.sqlite
    networks:
      - ai-factory-net
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:81/api/"]
      interval: 30s
      timeout: 10s
      retries: 3

volumes:
  npm_data:
  npm_letsencrypt:
```

**First-run credentials:** `admin@example.com` / `changeme` — NPM forces a password reset on first login.

### 5c. Gitea

```yaml
  gitea:
    image: gitea/gitea:latest
    container_name: gitea
    restart: unless-stopped
    environment:
      - USER_UID=1000
      - USER_GID=1000
      # Use your existing PostgreSQL instance
      - GITEA__database__DB_TYPE=postgres
      - GITEA__database__HOST=postgres:5432
      - GITEA__database__NAME=gitea
      - GITEA__database__USER=postgres
      - GITEA__database__PASSWD=${POSTGRES_PASSWORD:-test123}
      # Server config
      - GITEA__server__ROOT_URL=https://factory.local/git/
      - GITEA__server__SSH_DOMAIN=localhost
      - GITEA__server__SSH_PORT=2222
      - GITEA__server__LFS_START_SERVER=false
      # Webhook config (allow local n8n calls)
      - GITEA__webhook__ALLOWED_HOST_LIST=*
      - GITEA__webhook__SKIP_TLS_VERIFY=true
    volumes:
      - gitea_data:/data
      - /etc/timezone:/etc/timezone:ro
      - /etc/localtime:/etc/localtime:ro
    ports:
      - "2222:22"    # Git SSH (keep this on host for CLI clones)
    networks:
      - ai-factory-net
    depends_on:
      - postgres
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:3000/api/v1/version"]
      interval: 30s
      timeout: 10s
      retries: 3

volumes:
  gitea_data:
```

**Note:** Gitea's HTTP port (3000) is intentionally NOT exposed to the host — it goes through the proxy instead.

### 5d. PostgreSQL — Create Gitea Database

Run once after Gitea is added:

```bash
docker exec -it postgres psql -U postgres -c "CREATE DATABASE gitea;"
```

---

## 6. Nginx Proxy Manager — Route Configuration

After first login at `http://localhost:81`, create these proxy hosts:

| Incoming Route | Forward Host | Forward Port | Options |
|---|---|---|---|
| `factory.local` → `/n8n/*` | `n8n` | 5678 | WebSocket support ON |
| `factory.local` → `/git/*` | `gitea` | 3000 | — |
| `factory.local` → `/qdrant/*` | `qdrant` | 6333 | Access List: admin only |
| `factory.local` → `/logs/*` | `dozzle` | 8888 | Access List: admin only |
| `factory.local` → `/monitor/*` | `sysmonitor` | 5001 | Access List: admin only |
| `factory.local` → `/dashboard/*` | `homepage` | 8080 | — |

Add `127.0.0.1 factory.local` to your Windows `hosts` file:

```powershell
Add-Content C:\Windows\System32\drivers\etc\hosts "127.0.0.1 factory.local"
```

---

## 7. Custom Rate Limiting (Thermal Guard Integration)

Create `nginx-custom/server_proxy.conf`:

```nginx
# Rate limit zone: 10 requests/sec per IP for Qdrant
limit_req_zone $binary_remote_addr zone=qdrant_limit:10m rate=10r/s;

# Rate limit zone: 20 requests/sec for n8n webhooks
limit_req_zone $binary_remote_addr zone=webhook_limit:10m rate=20r/s;
```

For the thermal guard, create a sidecar script that writes a flag file:

```python
#!/usr/bin/env python3
"""thermal_guard_nginx.py — writes 503 maintenance page when CPU > 70%"""
import psutil, time
from pathlib import Path

FLAG = Path("/data/nginx/custom/maintenance.flag")

while True:
    cpu = psutil.cpu_percent(interval=5)
    if cpu > 70:
        FLAG.touch()
    else:
        FLAG.unlink(missing_ok=True)
    time.sleep(5)
```

Then in a custom location config for heavy inference routes:

```nginx
if (-f /data/nginx/custom/maintenance.flag) {
    return 503 '{"error": "thermal_guard", "message": "CPU > 70%, inference paused"}';
}
```

---

## 8. Gitea — Initial Repository Setup

After Gitea is running and you've created an admin account, initialize the Kensington repo:

```powershell
# From your blender_buildings directory
cd C:\path\to\blender_buildings

# Initialize if not already a git repo
git init
git remote add factory http://localhost:81/git/liam/kensington-market.git

# Selective add (skip large binary outputs)
git add params/ scripts/ docs/ batches/ agent_ops/ tests/ \
        generate_building.py gis_scene.py CLAUDE.md AGENTS.md

# Create .gitignore for binaries
@"
outputs/
*.blend
*.blend1
*.fbx
*.png
PHOTOS KENSINGTON/
__pycache__/
"@ | Set-Content .gitignore

git add .gitignore
git commit -m "Initial import: params, scripts, agent_ops, docs"
git push -u factory main
```

### Webhook to n8n (auto-trigger enrichment)

In Gitea → repo Settings → Webhooks → Add:

- **URL:** `http://n8n:5678/webhook/gitea-push`
- **Events:** Push, Pull Request
- **Content type:** `application/json`

Then in n8n, create a Webhook node listening on `/webhook/gitea-push` that filters by changed paths (`params/**`) and triggers your enrichment pipeline.

---

## 9. Agent Workflow Enhancement

With both services in place, your multi-agent flow becomes:

```
Agent receives task from agent_ops/10_backlog/
  → git checkout -b agent/<agent-name>/<task-id>
  → runs analysis / enrichment scripts
  → git commit + push to Gitea
  → Gitea webhook fires → n8n receives push event
  → n8n runs qa_params_gate.py on changed files
  → QA passes → n8n auto-merges branch
  → QA fails → n8n posts failure to agent_ops/40_reviews/
  → control plane routes review to next available agent
```

This replaces the file-lock mechanism in `coordination/locks/` with Git branches — more robust, auditable, and recoverable.

---

## 10. Resource Impact Estimate

| Service | RAM (idle) | RAM (active) | CPU | Disk |
|---|---|---|---|---|
| Nginx Proxy Manager | ~60 MB | ~80 MB | Negligible | ~200 MB (certs + config) |
| Gitea | ~150 MB | ~250 MB | Light | ~500 MB + repo size |
| **Total added** | **~210 MB** | **~330 MB** | **< 2%** | **~700 MB** |

On your Alienware, this is well within thermal budget. Both services are I/O-light and won't compete with Ollama or Blender for GPU/CPU.

---

## 11. Priority Order

1. **Deploy Nginx Proxy Manager first.** It's lower-risk (purely additive, no workflow changes) and immediately improves security and discoverability. Takes ~15 minutes.
2. **Deploy Gitea second.** Requires the initial repo import and agent workflow changes. Plan ~1 hour for setup + testing the webhook pipeline.
3. **Migrate agent_ops to Git branches.** This is the highest-value change but requires updating `agent_delegate_router.py` and the launcher prompts. Plan as a separate sprint.
