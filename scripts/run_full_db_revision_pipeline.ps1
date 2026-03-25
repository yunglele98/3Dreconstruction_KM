param(
  [switch]$DryRun,
  [switch]$SkipVisual,
  [int]$VisualLimit = 10,
  [string]$VisualOutputDir = "outputs/qa_visual_check"
)

$ErrorActionPreference = "Stop"

function Run-Step {
  param([string]$Cmd)
  Write-Host ""
  Write-Host ">> $Cmd" -ForegroundColor Cyan
  Invoke-Expression $Cmd
}

function Latest-Report {
  param([string]$Pattern)
  $f = Get-ChildItem -Path "outputs" -Filter $Pattern -File -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1
  if (-not $f) { throw "No report found for pattern: $Pattern" }
  return $f.FullName
}

function Step-Arg {
  if ($DryRun) { return "--dry-run" }
  return "--apply"
}

$modeArg = Step-Arg

Write-Host "=== Full DB Revision Pipeline ===" -ForegroundColor Green
Write-Host "Mode: $([string]::Join('', @($(if($DryRun){'dry-run'}else{'apply'}))))"
Write-Host "SkipVisual: $SkipVisual"

# 1) DB revision + alias enrichment pass
Run-Step "python scripts\revise_params_from_db.py $modeArg"
Run-Step "python scripts\build_address_aliases.py"
Run-Step "python scripts\revise_params_from_db.py $modeArg"

# 2) Backfill still-unmatched files with neighbor metadata/defaults
Run-Step "python scripts\backfill_unmatched_from_db_neighbors.py $modeArg"

# 3) QA gate + autofixes
Run-Step "python scripts\qa_params_gate.py"
$qa1 = Latest-Report "qa_fail_list_*.json"
Run-Step "python scripts\qa_autofix_height.py --qa-report `"$qa1`" $modeArg"

Run-Step "python scripts\qa_params_gate.py"
$qa2 = Latest-Report "qa_fail_list_*.json"
Run-Step "python scripts\qa_autofix_medium_low.py --qa-report `"$qa2`" $modeArg"

Run-Step "python scripts\qa_params_gate.py"
$qaFinal = Latest-Report "qa_fail_list_*.json"

# 4) Optional visual smoke batches
if (-not $SkipVisual) {
  $blender = "C:\Program Files\Blender Foundation\Blender 5.0\blender.exe"
  if (-not (Test-Path $blender)) {
    Write-Warning "Blender not found at $blender. Skipping visual validation."
  } else {
    foreach ($street in @("Oxford", "Bellevue", "Spadina")) {
      $cmd = "& `"$blender`" --background --python generate_building.py -- --params params/ --batch-individual --match `"$street`" --limit $VisualLimit --output-dir $VisualOutputDir"
      Run-Step $cmd
    }
  }
}

Write-Host ""
Write-Host "Pipeline complete." -ForegroundColor Green
Write-Host "Final QA report: $qaFinal"
