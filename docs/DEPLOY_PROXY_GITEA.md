# Deploy Nginx Proxy Manager + Gitea — Claude Code CLI Prompt

Copy the prompt below and paste it into Claude Code CLI on your Alienware.
It handles the full deployment in order: network setup, NPM, Gitea, proxy routes, repo init.

---

## Pre-requisites

- Docker Desktop running
- Your existing AI factory containers up (at minimum: `postgres`, `n8n`)
- The `blender_buildings/docs/` folder synced from Cowork (contains `docker-compose.proxy-git.yml` and `infra/`)

---

## Claude Code CLI Prompt

```
You are deploying two new services into an existing Docker-based AI automation stack on Windows. Follow these steps exactly, in order. Do NOT skip steps. Verify each step before moving to the next.

### CONTEXT
- Existing stack: n8n (5678), PostgreSQL 16 (5432), Redis (6379), Qdrant (6333), Ollama (11434), Dozzle (8888), SysMonitor (5001), Homepage (8080)
- Working directory for infra configs: C:\WINDOWS\system32\infra\n8n\
- Kensington Market project: find the blender_buildings folder (likely on D: or E: drive, search for it)
- Docker compose files may be in C:\WINDOWS\system32\infra\n8n\ or similar

### PHASE 1: NETWORK SETUP

1. Check if a shared Docker network already exists:
   docker network ls | findstr ai-factory

2. If not, create it:
   docker network create ai-factory-net

3. Connect ALL existing containers to this network (run for each):
   docker network connect ai-factory-net n8n
   docker network connect ai-factory-net postgres
   docker network connect ai-factory-net redis
   docker network connect ai-factory-net qdrant
   docker network connect ai-factory-net ollama
   docker network connect ai-factory-net dozzle
   docker network connect ai-factory-net sysmonitor
   docker network connect ai-factory-net homepage
   (Skip any that error with "already exists" — that's fine)

### PHASE 2: DEPLOY NGINX PROXY MANAGER

4. Find the docker-compose.proxy-git.yml file in the blender_buildings/docs/ folder. Copy it to the infra directory.

5. Create the nginx-custom directory for rate-limit configs:
   mkdir C:\WINDOWS\system32\infra\n8n\nginx-custom
   Copy the contents of blender_buildings/docs/infra/nginx-custom/ into it.

6. Deploy NPM only first (not Gitea yet):
   docker run -d --name nginx-proxy-manager --restart unless-stopped --network ai-factory-net -p 80:80 -p 443:443 -p 81:81 -v npm_data:/data -v npm_letsencrypt:/etc/letsencrypt -v C:\WINDOWS\system32\infra\n8n\nginx-custom:/data/nginx/custom:ro jc21/nginx-proxy-manager:latest

7. Wait 15 seconds, then verify NPM is healthy:
   docker logs nginx-proxy-manager --tail 20
   curl http://localhost:81

8. IMPORTANT: Tell the user to open http://localhost:81 in their browser and:
   - Login with admin@example.com / changeme
   - Set a new password
   - Then come back to continue

### PHASE 3: DEPLOY GITEA

9. Create the gitea database in the existing PostgreSQL:
   docker exec postgres psql -U postgres -c "CREATE DATABASE gitea;"

10. Deploy Gitea:
    docker run -d --name gitea --restart unless-stopped --network ai-factory-net -p 2222:22 -e USER_UID=1000 -e USER_GID=1000 -e GITEA__database__DB_TYPE=postgres -e GITEA__database__HOST=postgres:5432 -e GITEA__database__NAME=gitea -e GITEA__database__USER=postgres -e GITEA__database__PASSWD=test123 -e "GITEA__server__ROOT_URL=http://localhost:3000/" -e GITEA__server__SSH_DOMAIN=localhost -e GITEA__server__SSH_PORT=2222 -e GITEA__server__LFS_START_SERVER=false -e "GITEA__webhook__ALLOWED_HOST_LIST=*" -e GITEA__webhook__SKIP_TLS_VERIFY=true -v gitea_data:/data gitea/gitea:latest

11. Wait 15 seconds, verify:
    docker logs gitea --tail 20

12. Tell the user to open http://localhost:3000 (direct, before proxy is configured) and:
    - Complete initial setup (should auto-detect PostgreSQL)
    - Create admin account (username: liam, email: liam13donaghy@gmail.com)
    - Then come back to continue

### PHASE 4: CONFIGURE PROXY ROUTES IN NPM

13. Tell the user to go back to http://localhost:81 and create these Proxy Hosts:
    (NPM GUI → Proxy Hosts → Add Proxy Host)

    Host 1:
    - Domain: localhost (or factory.local if they add it to hosts file)
    - Forward Hostname: n8n
    - Forward Port: 5678
    - Enable WebSocket Support: YES

    Host 2:
    - Domain: git.localhost
    - Forward Hostname: gitea
    - Forward Port: 3000

    Host 3:
    - Domain: logs.localhost
    - Forward Hostname: dozzle
    - Forward Port: 8888
    - Add Access List (create one called "admin-only" with their credentials)

    Host 4:
    - Domain: monitor.localhost
    - Forward Hostname: sysmonitor
    - Forward Port: 5001
    - Use the same "admin-only" Access List

14. Add hosts file entry (run PowerShell as Admin):
    Add-Content C:\Windows\System32\drivers\etc\hosts "127.0.0.1 factory.local git.localhost logs.localhost monitor.localhost"

### PHASE 5: INITIALIZE KENSINGTON REPO IN GITEA

15. Find the blender_buildings folder on the system.

16. Copy the .gitignore-factory file from blender_buildings/docs/infra/ to blender_buildings/.gitignore

17. Initialize the Git repo (if not already one):
    cd <blender_buildings_path>
    git init
    git checkout -b main

18. Stage the important directories:
    git add params/ scripts/ docs/ batches/ agent_ops/ tests/ generate_building.py gis_scene.py CLAUDE.md AGENTS.md .gitignore

19. Create initial commit:
    git commit -m "Initial import: 1,241 building params, 270 pipeline scripts, agent_ops coordination"

20. Create the repo in Gitea first via API:
    curl -X POST http://localhost:3000/api/v1/user/repos -H "Content-Type: application/json" -u "liam:PASSWORD_HERE" -d "{\"name\": \"kensington-market\", \"description\": \"Parametric 3D models of 1,241 historic Kensington Market buildings\", \"private\": true}"

21. Add remote and push:
    git remote add factory http://localhost:3000/liam/kensington-market.git
    git push -u factory main

### PHASE 6: GITEA WEBHOOK → N8N

22. Tell the user to set up a webhook in Gitea:
    - Go to http://localhost:3000/liam/kensington-market/settings/hooks
    - Add Webhook → Gitea
    - Target URL: http://n8n:5678/webhook/gitea-push
    - Content Type: application/json
    - Events: Push Events, Pull Request Events
    - Active: checked

23. In n8n, create a new workflow called "Gitea Push Handler":
    - Trigger: Webhook node, path: /webhook/gitea-push, method: POST
    - Next: IF node — check if any changed file matches "params/**"
    - True branch: Execute Command node — run: python scripts/qa_params_gate.py
    - Add a second Execute Command: python scripts/audit_params_quality.py
    - End with a notification (Slack/email/whatever they have configured)

### PHASE 7: VERIFY EVERYTHING

24. Run these health checks:
    docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" | findstr /i "nginx gitea"
    curl -s http://localhost:81/api/ | head -5
    curl -s http://localhost:3000/api/v1/version
    docker network inspect ai-factory-net --format "{{range .Containers}}{{.Name}} {{end}}"

25. Report the final status to the user:
    - NPM admin: http://localhost:81
    - Gitea: http://localhost:3000 (or http://git.localhost after proxy config)
    - n8n: http://localhost:5678 (or via proxy)
    - Kensington repo: http://localhost:3000/liam/kensington-market
    - Git SSH clone: git clone ssh://git@localhost:2222/liam/kensington-market.git

### THERMAL GUARD (OPTIONAL, DO LAST)

26. Install psutil on the host: pip install psutil
27. Copy thermal_guard_nginx.py from blender_buildings/docs/infra/ to C:\WINDOWS\system32\infra\n8n\
28. Run it in background: start /B python C:\WINDOWS\system32\infra\n8n\thermal_guard_nginx.py
    Or set it up as a Windows scheduled task that runs at startup.
```

---

## Troubleshooting

**NPM can't reach containers by name:**
Containers must be on the same Docker network. Run `docker network inspect ai-factory-net` and verify all services appear.

**Gitea shows "database connection failed":**
Ensure the `gitea` database exists: `docker exec postgres psql -U postgres -c "\l"` — look for `gitea` in the list.

**Port 80 already in use:**
Windows IIS or another service may hold port 80. Check with `netstat -ano | findstr :80` and stop the conflicting service, or remap NPM to `8880:80` and `8443:443`.

**Git push fails with auth error:**
Gitea may need a personal access token instead of password auth. Create one at `http://localhost:3000/user/settings/applications` and use it as the password in `git remote set-url factory http://liam:TOKEN@localhost:3000/liam/kensington-market.git`.
