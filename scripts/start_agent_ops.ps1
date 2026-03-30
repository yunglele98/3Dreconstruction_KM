param(
  [string]$DashboardHost = "127.0.0.1",
  [int]$StaleMinutes = 45,
  [int]$IntervalSec = 60,
  [int]$ControlLoopSec = 300,
  [int]$Port = 8765,
  [switch]$RunRoute,
  [switch]$RunControlPlane,
  [switch]$StartControlLoop,
  [switch]$HealthCheck,
  [switch]$BootstrapOnly,
  [switch]$ExecuteOllama,
  [switch]$ExecuteGemini,
  [switch]$StartGeminiRunner,
  [string]$GeminiModel,
  [int]$GeminiInterval = 60,
  [switch]$StartOllamaRunner,
  [switch]$OllamaAutoComplete,
  [string]$OllamaModel,
  [int]$OllamaTimeout = 300,
  [int]$OllamaInterval = 60,
  [switch]$NoWatchdog,
  [switch]$NoDashboard,
  [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"

function Run-Step {
  param([string]$Cmd)
  Write-Host ">> $Cmd" -ForegroundColor Cyan
  Invoke-Expression $Cmd
}

if (-not (Test-Path "scripts\run_blender_buildings_workflows.py")) {
  throw "Run this script from C:\Users\liam1\blender_buildings"
}

if ($HealthCheck) {
  Run-Step "python scripts\run_blender_buildings_workflows.py watchdog --mode once --stale-minutes $StaleMinutes"
  Run-Step "python scripts\run_blender_buildings_workflows.py dashboard --host $DashboardHost --port $Port --stale-minutes $StaleMinutes --once-json"
  Write-Host ""
  Write-Host "Health check complete." -ForegroundColor Green
  return
}

if ($BootstrapOnly -and (-not $RunRoute) -and (-not $RunControlPlane)) {
  $RunRoute = $true
  $RunControlPlane = $true
}

if ($RunRoute) {
  Run-Step "python scripts\run_blender_buildings_workflows.py route"
}

if ($RunControlPlane) {
  $cpCmd = "python scripts\run_blender_buildings_workflows.py control-plane"
  if ($ExecuteOllama) {
    $cpCmd += " --execute-ollama"
  }
  if ($ExecuteGemini) {
    $cpCmd += " --execute-gemini"
  }
  Run-Step $cpCmd
}

$watchArgs = "scripts\run_blender_buildings_workflows.py watchdog --mode watch --stale-minutes $StaleMinutes --interval-sec $IntervalSec"
$dashArgs = "scripts\run_blender_buildings_workflows.py dashboard --host $DashboardHost --port $Port --stale-minutes $StaleMinutes"
$cpFlags = ""
if ($ExecuteOllama) { $cpFlags += " --execute-ollama" }
if ($ExecuteGemini) { $cpFlags += " --execute-gemini" }
$controlLoopScript = "cd `"$PWD`"; while (`$true) { python scripts\run_blender_buildings_workflows.py route; python scripts\run_blender_buildings_workflows.py control-plane$cpFlags; Start-Sleep -Seconds $ControlLoopSec }"

$geminiRunnerArgs = "scripts\gemini_task_runner.py --loop --interval $GeminiInterval"
if ($GeminiModel) { $geminiRunnerArgs += " --model $GeminiModel" }

$ollamaRunnerArgs = "scripts\ollama_task_runner.py --loop --interval $OllamaInterval --timeout $OllamaTimeout"
if ($OllamaModel) { $ollamaRunnerArgs += " --model $OllamaModel" }
if ($OllamaAutoComplete) { $ollamaRunnerArgs += " --auto-complete" }

if ($BootstrapOnly) {
  Write-Host ""
  Write-Host "Bootstrap finished; live services not started (-BootstrapOnly)." -ForegroundColor Green
  return
}

Write-Host ""
if (-not $NoWatchdog) {
  Write-Host "Starting watchdog terminal..." -ForegroundColor Green
  Start-Process pwsh -ArgumentList @("-NoExit", "-Command", "cd `"$PWD`"; python $watchArgs")
}

if (-not $NoDashboard) {
  Write-Host "Starting dashboard terminal..." -ForegroundColor Green
  Start-Process pwsh -ArgumentList @("-NoExit", "-Command", "cd `"$PWD`"; python $dashArgs")
}

if ($StartControlLoop) {
  Write-Host "Starting route/control loop terminal..." -ForegroundColor Green
  Start-Process pwsh -ArgumentList @("-NoExit", "-Command", $controlLoopScript)
}

if ($StartGeminiRunner) {
  Write-Host "Starting Gemini task runner terminal..." -ForegroundColor Green
  Start-Process pwsh -ArgumentList @("-NoExit", "-Command", "cd `"$PWD`"; python $geminiRunnerArgs")
}

if ($StartOllamaRunner) {
  Write-Host "Starting Ollama task runner terminal..." -ForegroundColor Green
  Start-Process pwsh -ArgumentList @("-NoExit", "-Command", "cd `"$PWD`"; python $ollamaRunnerArgs")
}

if ((-not $NoBrowser) -and (-not $NoDashboard)) {
  Start-Sleep -Seconds 1
  Start-Process "http://${DashboardHost}:$Port"
}

Write-Host ""
Write-Host "Agent ops command complete." -ForegroundColor Green
if (-not $NoDashboard) {
  Write-Host "Dashboard: http://${DashboardHost}:$Port"
}
Write-Host "Useful options:"
Write-Host "  -HealthCheck"
Write-Host "  -RunRoute -RunControlPlane [-ExecuteOllama]"
Write-Host "  -BootstrapOnly"
Write-Host "  -StartControlLoop -ControlLoopSec 300"
Write-Host "  -StartGeminiRunner [-GeminiModel X] [-GeminiInterval 60]"
Write-Host "  -StartOllamaRunner [-OllamaModel X] [-OllamaAutoComplete] [-OllamaInterval 60]"
Write-Host "  -ExecuteGemini"
Write-Host "  -NoWatchdog / -NoDashboard / -NoBrowser"
