# Reference pattern for capturing FBX-batch lifecycle to OB1.
# Mirror this structure into run_fbx_batch.ps1 if/when you want batch-run
# observability. The vendored CLI lives at scripts\ob1 (single-file Python).
#
# Credential resolution: env vars MCP_CONNECTION_URL + SUPABASE_ANON_KEY,
# falling back to ~/open-brain/.env.

$ErrorActionPreference = "Stop"
$projectRoot = "C:\Users\liam1\blender_buildings"
$ob1 = "$PSScriptRoot\scripts\ob1"
$python = "python"

function Invoke-Ob1 {
    param([string]$Method, [string]$Content, [hashtable]$Meta)
    $args = @($ob1, $Method, $Content)
    foreach ($k in $Meta.Keys) {
        $args += "--meta"
        $args += "$k=$($Meta[$k])"
    }
    & $python @args 2>&1 | Out-Null
}

# --- Run start --------------------------------------------------------------

$batchId = (Get-Date -Format "yyyyMMddHHmmss")
$startedAt = (Get-Date).ToUniversalTime().ToString("o")
$sourceDir = "$projectRoot\outputs\full_v2"
$total = (Get-ChildItem -Path $sourceDir -Filter "*.blend").Count

Invoke-Ob1 capture "FBX batch start: $batchId ($total .blend files)" @{
    source       = "3Dreconstruction_KM"
    event        = "fbx_batch_start"
    batch_id     = $batchId
    total_files  = $total
    started_at   = $startedAt
}

# ... existing batch loop runs here, populating $done/$failed counters ...

# --- Run end (in finally / trap) --------------------------------------------

try {
    # ... existing run_fbx_batch.ps1 body ...
    $endedOk = $true
} catch {
    $endedOk = $false
    throw
} finally {
    $endedAt = (Get-Date).ToUniversalTime().ToString("o")
    Invoke-Ob1 capture "FBX batch end: $batchId status=$([string]$endedOk)" @{
        source     = "3Dreconstruction_KM"
        event      = "fbx_batch_end"
        batch_id   = $batchId
        status     = $(if ($endedOk) {"ok"} else {"failed"})
        started_at = $startedAt
        ended_at   = $endedAt
    }
}

# --- Search past batches ---------------------------------------------------
# python .\scripts\ob1 search "FBX batch" -n 10 --pretty
# python .\scripts\ob1 search "fbx_batch_end status=failed" --mode lexical
