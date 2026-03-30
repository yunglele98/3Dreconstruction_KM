param(
    [Parameter(Mandatory = $true)]
    [string]$Prompt,

    [string]$Model = 'qwen2.5:0.5b',

    [int]$NumThread = 2,

    [int]$NumCtx = 1024,

    [int]$NumPredict = 220,

    [double]$Temperature = 0.2,

    [string]$KeepAlive = '0s',

    [string]$OutputDir = 'C:\Users\liam1\blender_buildings\outputs\session_runs'
)

$ErrorActionPreference = 'Stop'

# Keep Ollama background process low impact for interactive use.
Get-Process ollama -ErrorAction SilentlyContinue | ForEach-Object {
    try { $_.PriorityClass = 'BelowNormal' } catch {}
    try { $_.ProcessorAffinity = 15 } catch {}
}

if (!(Test-Path $OutputDir)) {
    New-Item -ItemType Directory -Path $OutputDir | Out-Null
}

$ts = Get-Date -Format 'yyyyMMdd_HHmmss'
$outPath = Join-Path $OutputDir "ollama_lite_response_${ts}.md"

$body = @{
    model = $Model
    prompt = $Prompt
    stream = $false
    keep_alive = $KeepAlive
    options = @{
        num_thread = $NumThread
        num_ctx = $NumCtx
        num_predict = $NumPredict
        temperature = $Temperature
        top_p = 0.9
        repeat_penalty = 1.1
    }
} | ConvertTo-Json -Depth 8

$response = Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:11434/api/generate' -ContentType 'application/json' -Body $body
$response.response | Set-Content -Encoding UTF8 $outPath

Write-Output "OUTPUT_PATH=$outPath"
Get-Content -Raw $outPath
