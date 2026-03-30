# AI Automation Factory — Improvements V2

**Prompt for Claude Code CLI on Alienware.**
Paste the prompt block below. It handles all fixes and improvements in order.

---

## What This Covers

1. **Gitea setup completion** — ROOT_URL fix, install lock, admin account
2. **NPM proxy host creation** — API-driven, no GUI clicking needed
3. **Qdrant timeout fix** — custom config to eliminate 408 errors
4. **Ollama Docker bridge** — wire native Ollama into the Docker network
5. **Automated backup** — scheduled PowerShell script for PG, Qdrant, Gitea, params
6. **n8n QA workflow** — import Gitea→QA pipeline workflow
7. **Kensington repo init** — git init + push to Gitea
8. **Hosts file + DNS** — local service discovery

---

## Claude Code CLI Prompt

```
You are improving an existing AI automation Docker stack on Windows. 10 containers are already running on the n8n_default network. Follow each phase in order. Skip steps that are already done. Verify after each phase.

### LIVE STATE (as of scan)
Containers running on n8n_default network:
- n8n_proxy (NPM) — ports 80/81/443 — NO proxy hosts configured, setup:false (default admin not changed)
- n8n_git (Gitea) — port 3001→3000, 222→22 — INSTALL_LOCK=false, ROOT_URL blank, DB exists
- n8n_local (n8n) — port 5678
- n8n_db (PostgreSQL 16) — databases: postgres, kensington, gitea, npm
- n8n_redis — port 6379 internal
- n8n_vector_db (Qdrant) — port 6333 — client_request_timeout=5s causing 408s
- n8n_logs (Dozzle) — port 8888→8080
- n8n_sys_monitor — port 5001
- n8n_dashboard (Homepage) — port 8080→3000
- n8n_updater (Watchtower)
Ollama: native install at C:\Users\liam1\AppData\Local\Programs\Ollama\ollama.exe, 66 models loaded
Kensington project: find blender_buildings folder (likely D: drive, search for it)

### PHASE 1: COMPLETE GITEA SETUP

Gitea is running but never completed initial setup (INSTALL_LOCK=false, ROOT_URL blank).

1. Fix Gitea's app.ini directly:
   docker exec n8n_git sh -c "sed -i 's|^ROOT_URL.*|ROOT_URL = http://localhost:3001/|' /data/gitea/conf/app.ini"
   docker exec n8n_git sh -c "sed -i 's|^INSTALL_LOCK.*|INSTALL_LOCK = true|' /data/gitea/conf/app.ini"

2. If INSTALL_LOCK was false, create the admin user via CLI:
   docker exec n8n_git gitea admin user create --admin --username liam --password "ChangeMe123!" --email "liam13donaghy@gmail.com" --must-change-password=false
   (If it errors "user already exists", that's fine — move on)

3. Restart Gitea to pick up config:
   docker restart n8n_git

4. Wait 10 seconds, then verify:
   curl -s http://localhost:3001/api/v1/version
   Expected: {"version": "1.x.x"}

5. Tell user: "Gitea is live at http://localhost:3001 — login: liam / ChangeMe123! — change your password now."

### PHASE 2: CONFIGURE NPM PROXY HOSTS VIA API

NPM is running but has no proxy hosts. First, complete initial setup, then create routes via API.

6. Get an auth token from NPM (default creds):
   Set a variable with the response:
   curl -s -X POST http://localhost:81/api/tokens -H "Content-Type: application/json" -d "{\"identity\":\"admin@example.com\",\"secret\":\"changeme\"}"

   If this returns a token, use it for all subsequent API calls as: Authorization: Bearer <token>
   If it fails (setup already completed), ask the user for their NPM admin credentials.

7. Change default admin email/password (IMPORTANT):
   curl -s -X PUT http://localhost:81/api/users/1 -H "Authorization: Bearer <token>" -H "Content-Type: application/json" -d "{\"email\":\"liam13donaghy@gmail.com\",\"nickname\":\"liam\",\"is_disabled\":false}"

8. Create proxy hosts via API. For each, POST to http://localhost:81/api/nginx/proxy-hosts with Bearer token:

   Host 1 — n8n:
   {
     "domain_names": ["n8n.localhost"],
     "forward_scheme": "http",
     "forward_host": "n8n_local",
     "forward_port": 5678,
     "allow_websocket_upgrade": true,
     "block_exploits": true,
     "access_list_id": 0,
     "certificate_id": 0,
     "meta": {"letsencrypt_agree": false, "dns_challenge": false},
     "advanced_config": "",
     "locations": [],
     "http2_support": false,
     "hsts_enabled": false,
     "hsts_subdomains": false,
     "ssl_forced": false,
     "caching_enabled": false
   }

   Host 2 — Gitea:
   Same structure, domain_names: ["git.localhost"], forward_host: "n8n_git", forward_port: 3000

   Host 3 — Dozzle:
   domain_names: ["logs.localhost"], forward_host: "n8n_logs", forward_port: 8080

   Host 4 — SysMonitor:
   domain_names: ["monitor.localhost"], forward_host: "n8n_sys_monitor", forward_port: 5001

   Host 5 — Qdrant:
   domain_names: ["qdrant.localhost"], forward_host: "n8n_vector_db", forward_port: 6333

   Host 6 — Dashboard:
   domain_names: ["dashboard.localhost"], forward_host: "n8n_dashboard", forward_port: 3000

9. Verify proxy hosts:
   curl -s http://localhost:81/api/nginx/proxy-hosts -H "Authorization: Bearer <token>" | python -m json.tool

### PHASE 3: FIX QDRANT TIMEOUTS

Qdrant's default client_request_timeout=5s is causing 408 Request Timeout errors.

10. Find the qdrant_config.yaml file in blender_buildings/docs/infra/qdrant_config.yaml

11. Copy it into the Qdrant container's config:
    docker cp <path_to>/qdrant_config.yaml n8n_vector_db:/qdrant/config/production.yaml

12. Restart Qdrant:
    docker restart n8n_vector_db

13. Wait 10 seconds, verify:
    curl -s http://localhost:6333/collections
    Expected: {"result":{"collections":[...]},"status":"ok","time":...}
    No more 408s.

### PHASE 4: WIRE NATIVE OLLAMA INTO DOCKER NETWORK

Ollama runs natively on Windows (not in Docker). Docker containers need to reach it at host.docker.internal:11434.

14. Verify Ollama is running:
    curl -s http://localhost:11434/api/tags | python -m json.tool | head -5

15. Test Docker→Ollama connectivity:
    docker exec n8n_local curl -s http://host.docker.internal:11434/api/tags | head -5

16. If that works, update n8n's environment to know about Ollama.
    Check if n8n already has OLLAMA_HOST or similar env var:
    docker exec n8n_local printenv | findstr -i ollama

    If not set, the n8n Ollama node can be configured per-workflow to use:
    Base URL: http://host.docker.internal:11434

17. Verify from n8n container:
    docker exec n8n_local curl -s -X POST http://host.docker.internal:11434/api/generate -d "{\"model\":\"gemma3:4b\",\"prompt\":\"Say hello\",\"stream\":false}" | head -c 200
    Expected: JSON response with generated text

### PHASE 5: HOSTS FILE SETUP

18. Add local DNS entries (run as Administrator):
    Add-Content C:\Windows\System32\drivers\etc\hosts "127.0.0.1 n8n.localhost git.localhost logs.localhost monitor.localhost qdrant.localhost dashboard.localhost"

19. Verify:
    curl -s http://n8n.localhost:81/       (should reach n8n via proxy)
    curl -s http://git.localhost:81/       (should reach Gitea via proxy)

### PHASE 6: AUTOMATED BACKUPS

20. Find backup_stack.ps1 in blender_buildings/docs/infra/backup_stack.ps1

21. Read the script and update the two paths at the top:
    - $backupRoot: set to a valid backup location (e.g., D:\Backups\factory or E:\Backups\factory)
    - $kensingtonSrc: set to the actual blender_buildings\params path

22. Copy backup_stack.ps1 to C:\WINDOWS\system32\infra\n8n\backup_stack.ps1

23. Test it:
    powershell -ExecutionPolicy Bypass -File "C:\WINDOWS\system32\infra\n8n\backup_stack.ps1"

24. Schedule daily at 3 AM:
    schtasks /create /tn "Factory Backup" /tr "powershell.exe -ExecutionPolicy Bypass -File C:\WINDOWS\system32\infra\n8n\backup_stack.ps1" /sc daily /st 03:00 /ru SYSTEM /f

### PHASE 7: INITIALIZE KENSINGTON REPO IN GITEA

25. Find the blender_buildings folder.

26. Copy blender_buildings/docs/infra/.gitignore-factory to blender_buildings/.gitignore
    (If .gitignore already exists, merge the two — keep existing entries, add new ones)

27. Initialize git repo if not already one:
    cd <blender_buildings_path>
    git init
    git checkout -b main

28. Stage important directories:
    git add params/ scripts/ docs/ batches/ agent_ops/ tests/ generate_building.py gis_scene.py CLAUDE.md AGENTS.md .gitignore

29. Commit:
    git commit -m "Initial import: 1,241 building params, 270 pipeline scripts, agent_ops coordination"

30. Create repo in Gitea via API:
    curl -s -X POST http://localhost:3001/api/v1/user/repos -H "Content-Type: application/json" -H "Authorization: token <GITEA_TOKEN>" -d "{\"name\":\"kensington-market\",\"description\":\"Parametric 3D models of 1,241 historic Kensington Market buildings\",\"private\":true}"

    (To get a token: curl -s -X POST http://localhost:3001/api/v1/users/liam/tokens -u "liam:ChangeMe123!" -H "Content-Type: application/json" -d "{\"name\":\"cli-token\",\"scopes\":[\"all\"]}")

31. Add remote and push:
    git remote add factory http://localhost:3001/liam/kensington-market.git
    git push -u factory main

### PHASE 8: IMPORT N8N QA WORKFLOW

32. Find n8n_gitea_qa_workflow.json in blender_buildings/docs/infra/

33. Import it into n8n. First get n8n API key:
    Open http://localhost:5678/settings/api — generate an API key if none exists.
    Or import via CLI:
    docker cp <path>/n8n_gitea_qa_workflow.json n8n_local:/tmp/qa_workflow.json
    docker exec n8n_local n8n import:workflow --input=/tmp/qa_workflow.json

34. Verify the workflow appears in n8n at http://localhost:5678

35. Configure the Gitea webhook to fire on push:
    curl -s -X POST http://localhost:3001/api/v1/repos/liam/kensington-market/hooks -H "Authorization: token <GITEA_TOKEN>" -H "Content-Type: application/json" -d "{\"type\":\"gitea\",\"config\":{\"url\":\"http://n8n_local:5678/webhook/gitea-push\",\"content_type\":\"json\"},\"events\":[\"push\",\"pull_request\"],\"active\":true}"

### PHASE 9: VERIFY EVERYTHING

36. Full health check:
    docker ps -a (all containers should be Up)
    curl -s http://localhost:81/api/               (NPM API)
    curl -s http://localhost:3001/api/v1/version    (Gitea)
    curl -s http://localhost:5678/healthz            (n8n)
    curl -s http://localhost:6333/collections        (Qdrant — no 408!)
    curl -s http://localhost:11434/api/tags          (Ollama native)

37. Report final status:
    - NPM admin: http://localhost:81
    - n8n: http://localhost:5678 or http://n8n.localhost
    - Gitea: http://localhost:3001 or http://git.localhost
    - Qdrant: http://localhost:6333 or http://qdrant.localhost
    - Logs: http://localhost:8888 or http://logs.localhost
    - Monitor: http://localhost:5001 or http://monitor.localhost
    - Dashboard: http://localhost:8080 or http://dashboard.localhost
    - Ollama: http://localhost:11434 (native), reachable from Docker as host.docker.internal:11434
    - Kensington repo: http://localhost:3001/liam/kensington-market
    - Backups: scheduled daily 3 AM to <backup_root>
    - QA workflow: auto-triggers on git push to params/
```

---

## Files Referenced

All in `blender_buildings/docs/infra/`:

| File | Purpose |
|---|---|
| `qdrant_config.yaml` | Custom Qdrant config — fixes 408 timeout, tunes storage |
| `backup_stack.ps1` | 6-stage backup: PG, Qdrant snapshots, Gitea repos, n8n workflows, params |
| `n8n_gitea_qa_workflow.json` | n8n workflow: Gitea push → QA gate → audit → report |
| `.gitignore-factory` | Git ignore for Kensington repo (skips .blend, photos, outputs) |
| `nginx-custom/server_proxy.conf` | Rate-limit zones for Qdrant, webhooks, general API |
| `nginx-custom/thermal_guard.conf` | Thermal guard Nginx integration notes |
| `thermal_guard_nginx.py` | Python sidecar: flags Nginx 503 when CPU > 70% |
| `docker-compose.proxy-git.yml` | Reference compose (NPM + Gitea already deployed) |

---

## Post-Deployment Next Steps

After running this prompt:

1. **Change passwords** — Gitea admin (ChangeMe123!), NPM admin (changeme). Do this immediately.
2. **Test the QA pipeline** — edit a param file, git push, verify n8n fires the QA workflow.
3. **Configure n8n Ollama nodes** — in any workflow using Ollama, set base URL to `http://host.docker.internal:11434`.
4. **Add more n8n workflows** — agent task routing, batch Blender regen on param change, Qdrant embedding updates.
5. **Set up Localtunnel** — point it at NPM port 80 instead of directly at n8n:5678 for better security.
