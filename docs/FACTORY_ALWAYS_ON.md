# Factory Always-On System

## Purpose

Autonomous pipeline execution via n8n (Docker) + Cloudflare tunnel. The factory runs 15 workflows that handle overnight builds, photo ingestion, error recovery, cloud GPU sessions, and sprint progress tracking without manual intervention.

## Workflows

| ID    | Name                  | Schedule / Trigger     | Description                                    |
|-------|-----------------------|------------------------|------------------------------------------------|
| WF-01 | Heartbeat             | Every 10 min           | Health check for all pipeline components        |
| WF-02 | Overnight Pipeline    | 10 PM daily            | Full batch render + export cycle                |
| WF-03 | COLMAP Block          | On demand              | Photogrammetry reconstruction per city block    |
| WF-04 | Photo Ingestion       | On new photos          | Process and index new field photos              |
| WF-05 | Scenario Computation  | On scenario change     | Recompute scenario overlays and impact analysis |
| WF-06 | Web Deploy            | On export completion   | Deploy web platform to Vercel                   |
| WF-07 | Error Recovery        | On failure             | Retry failed jobs, reassign stalled tasks       |
| WF-08 | Morning Report        | 7 AM daily             | Summary of overnight results to Slack           |
| WF-09 | Cloud GPU Session     | On demand              | Spin up Jarvislabs A100 for heavy compute       |
| WF-10 | Asset Library Update  | Weekly                 | Sync external assets (Megascans, PolyHaven)     |
| WF-11 | Nightly Backup        | 2 AM daily             | Backup params, outputs, and database            |
| WF-12 | Weekly Audit          | Sunday                 | Full QA audit across all buildings               |
| WF-13 | Design Decision Ingest| On new decisions       | Import architectural decisions from docs         |
| WF-14 | Montreal Scan Ingest  | On new scans           | Process iPad LiDAR scans from Montreal proxy    |
| WF-15 | Sprint Progress       | Daily                  | Track sprint velocity and update dashboard       |

## GPU Lock

Single-GPU machine (RTX 2080S). A `.gpu_lock` file ensures only one GPU job runs at a time. WF-02 and WF-03 check for the lock before starting Blender or COLMAP jobs.

## Slack Command Centre

| Command                | Description                              |
|------------------------|------------------------------------------|
| `/status`              | Pipeline health overview                 |
| `/queue`               | Current job queue                        |
| `/coverage`            | Building coverage statistics             |
| `/building <addr>`     | Building detail card                     |
| `/colmap <block>`      | Trigger COLMAP for a city block          |
| `/scenario <name>`     | Run scenario computation                 |
| `/deploy`              | Deploy web platform                      |
| `/cloud <type>`        | Start cloud GPU session                  |
| `/sprint`              | Sprint progress summary                  |
| `/run <script>`        | Execute whitelisted script               |

## Infrastructure

- **n8n**: Docker container with persistent volume
- **Cloudflare tunnel**: Exposes n8n webhooks without port forwarding
- **Jarvislabs**: Cloud GPU on demand ($1.49/hr A100)
- **Vercel**: Web platform hosting (free tier)

See CLAUDE.md for full technical details.
