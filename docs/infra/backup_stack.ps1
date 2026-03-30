<#
.SYNOPSIS
    Automated backup for the AI Automation Factory + Kensington pipeline.
    Backs up PostgreSQL (all DBs), Qdrant snapshots, Gitea repos, n8n workflows, and params.

.USAGE
    # Manual run
    .\backup_stack.ps1

    # Schedule daily at 3 AM via Task Scheduler:
    # Action: powershell.exe
    # Arguments: -ExecutionPolicy Bypass -File "C:\WINDOWS\system32\infra\n8n\backup_stack.ps1"

.NOTES
    Retention: 7 daily backups. Oldest auto-deleted.
#>

$ErrorActionPreference = "Stop"
$timestamp = Get-Date -Format "yyyy-MM-dd_HHmmss"
$backupRoot = "D:\Backups\factory"  # Adjust to your backup drive
$retentionDays = 7

# Create backup directory
$backupDir = Join-Path $backupRoot $timestamp
New-Item -ItemType Directory -Path $backupDir -Force | Out-Null
Write-Host "=== Factory Backup: $timestamp ===" -ForegroundColor Cyan

# ── 1. PostgreSQL (all databases) ──────────────────────────────────
Write-Host "[1/6] PostgreSQL dump (all databases)..." -ForegroundColor Yellow
$pgFile = Join-Path $backupDir "postgres_all_dbs.sql.gz"
docker exec n8n_db pg_dumpall -U postgres |
    & { process { $_ } } |
    Set-Content -Path (Join-Path $backupDir "postgres_all_dbs.sql") -Encoding UTF8
# Compress
if (Get-Command Compress-Archive -ErrorAction SilentlyContinue) {
    Compress-Archive -Path (Join-Path $backupDir "postgres_all_dbs.sql") -DestinationPath "$backupDir\postgres_all_dbs.zip"
    Remove-Item (Join-Path $backupDir "postgres_all_dbs.sql") -Force
}
Write-Host "  PostgreSQL: OK" -ForegroundColor Green

# ── 2. Individual database dumps (kensington, gitea, n8n) ─────────
Write-Host "[2/6] Individual DB dumps..." -ForegroundColor Yellow
foreach ($db in @("kensington", "gitea", "npm")) {
    $dbFile = Join-Path $backupDir "${db}_dump.sql"
    docker exec n8n_db pg_dump -U postgres -d $db > $dbFile 2>$null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "  $db : OK" -ForegroundColor Green
    } else {
        Write-Host "  $db : SKIPPED (may not exist)" -ForegroundColor DarkYellow
        Remove-Item $dbFile -Force -ErrorAction SilentlyContinue
    }
}

# ── 3. Qdrant snapshot ────────────────────────────────────────────
Write-Host "[3/6] Qdrant snapshots..." -ForegroundColor Yellow
try {
    $collections = Invoke-RestMethod -Uri "http://localhost:6333/collections" -TimeoutSec 30
    foreach ($col in $collections.result.collections) {
        $colName = $col.name
        Write-Host "  Snapshotting collection: $colName"
        $snap = Invoke-RestMethod -Uri "http://localhost:6333/collections/$colName/snapshots" -Method Post -TimeoutSec 120
        $snapName = $snap.result.name
        Invoke-WebRequest -Uri "http://localhost:6333/collections/$colName/snapshots/$snapName" -OutFile "$backupDir\qdrant_${colName}_${snapName}" -TimeoutSec 120
        Write-Host "  $colName : OK" -ForegroundColor Green
    }
} catch {
    Write-Host "  Qdrant: SKIPPED (not reachable or no collections)" -ForegroundColor DarkYellow
}

# ── 4. Gitea repositories (bare clone) ────────────────────────────
Write-Host "[4/6] Gitea repo backup..." -ForegroundColor Yellow
$giteaRepoDir = Join-Path $backupDir "gitea_repos"
New-Item -ItemType Directory -Path $giteaRepoDir -Force | Out-Null
docker exec n8n_git sh -c "ls /data/git/repositories/*//*.git -d 2>/dev/null" 2>$null | ForEach-Object {
    $repoPath = $_.Trim()
    if ($repoPath) {
        $repoName = ($repoPath -split "/")[-1] -replace "\.git$", ""
        Write-Host "  Backing up repo: $repoName"
        docker exec n8n_git tar czf "/tmp/${repoName}.tar.gz" -C $repoPath . 2>$null
        docker cp "n8n_git:/tmp/${repoName}.tar.gz" "$giteaRepoDir\${repoName}.tar.gz" 2>$null
        docker exec n8n_git rm -f "/tmp/${repoName}.tar.gz" 2>$null
    }
}
# Also backup Gitea config
docker cp "n8n_git:/data/gitea/conf/app.ini" "$backupDir\gitea_app.ini" 2>$null
Write-Host "  Gitea: OK" -ForegroundColor Green

# ── 5. n8n workflows export ──────────────────────────────────────
Write-Host "[5/6] n8n workflow export..." -ForegroundColor Yellow
$n8nDir = Join-Path $backupDir "n8n_workflows"
New-Item -ItemType Directory -Path $n8nDir -Force | Out-Null
try {
    # Export via n8n CLI inside the container
    docker exec n8n_local n8n export:workflow --all --output=/tmp/workflows.json 2>$null
    docker cp "n8n_local:/tmp/workflows.json" "$n8nDir\all_workflows.json" 2>$null
    docker exec n8n_local rm -f /tmp/workflows.json 2>$null

    # Also export credentials (encrypted)
    docker exec n8n_local n8n export:credentials --all --output=/tmp/credentials.json 2>$null
    docker cp "n8n_local:/tmp/credentials.json" "$n8nDir\all_credentials_encrypted.json" 2>$null
    docker exec n8n_local rm -f /tmp/credentials.json 2>$null
    Write-Host "  n8n: OK" -ForegroundColor Green
} catch {
    Write-Host "  n8n: SKIPPED (export failed)" -ForegroundColor DarkYellow
}

# ── 6. Kensington params snapshot ─────────────────────────────────
Write-Host "[6/6] Kensington params snapshot..." -ForegroundColor Yellow
$kensingtonSrc = "D:\blender_buildings\params"  # Adjust to your actual path
if (Test-Path $kensingtonSrc) {
    Compress-Archive -Path $kensingtonSrc -DestinationPath "$backupDir\kensington_params.zip" -CompressionLevel Fastest
    Write-Host "  Params: OK ($((Get-ChildItem $kensingtonSrc -Filter '*.json').Count) files)" -ForegroundColor Green
} else {
    Write-Host "  Params: SKIPPED (path not found: $kensingtonSrc)" -ForegroundColor DarkYellow
}

# ── Retention cleanup ─────────────────────────────────────────────
Write-Host "`nCleaning backups older than $retentionDays days..." -ForegroundColor Yellow
Get-ChildItem $backupRoot -Directory |
    Where-Object { $_.CreationTime -lt (Get-Date).AddDays(-$retentionDays) } |
    ForEach-Object {
        Write-Host "  Removing old backup: $($_.Name)" -ForegroundColor DarkGray
        Remove-Item $_.FullName -Recurse -Force
    }

# ── Summary ───────────────────────────────────────────────────────
$totalSize = (Get-ChildItem $backupDir -Recurse | Measure-Object -Property Length -Sum).Sum / 1MB
Write-Host "`n=== Backup complete: $backupDir ($([math]::Round($totalSize, 1)) MB) ===" -ForegroundColor Cyan
