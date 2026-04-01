$projectRoot = "C:\Users\liam1\blender_buildings"
Set-Location $projectRoot

$blender = "C:\Program Files\Blender Foundation\Blender 5.1\blender.exe"
$sourceDir = "$projectRoot\outputs\full_v2"
$outputDir = "$projectRoot\outputs\fbx_export"
$logFile = "$projectRoot\fbx_batch_log.txt"
$maxJobs = 4

if (-not (Test-Path $outputDir)) { New-Item -ItemType Directory -Path $outputDir -Force }

"FBX parallel batch (v2) started at $(Get-Date)" | Out-File $logFile
$files = Get-ChildItem -Path $sourceDir -Filter "*.blend" | Sort-Object Name
$total = $files.Count
$done = 0

foreach ($blend in $files) {
    while ((Get-Job -State Running).Count -ge $maxJobs) { Start-Sleep -Seconds 1 }
    
    $addr = $blend.BaseName
    Start-Job -Name "Bake_$addr" -ScriptBlock {
        param($exe, $blendPath, $addr, $root)
        Set-Location $root
        & $exe --background $blendPath --python "$root\scripts\export_building_fbx.py" -- --address $addr --texture-size 1024 2>&1
    } -ArgumentList $blender, $blend.FullName, $addr, $projectRoot
    
    $done++
    Write-Host "[$done/$total] Queued: $addr" -ForegroundColor Cyan
    
    Get-Job -State Completed | ForEach-Object {
        $name = $_.Name.Replace("Bake_", "")
        "SUCCESS: $name" | Out-File -Append $logFile
        Remove-Job $_
    }
}

while ((Get-Job -State Running).Count -gt 0) { Start-Sleep -Seconds 5 }
"FBX batch complete at $(Get-Date)" | Out-File -Append $logFile
