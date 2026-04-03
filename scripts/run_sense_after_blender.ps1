# Wait for Blender to finish, then run SENSE pipeline
# Usage: powershell.exe -File scripts/run_sense_after_blender.ps1

$root = "C:\Users\liam1\blender_buildings"

Write-Host "Waiting for Blender to finish..." -ForegroundColor Yellow
while (Get-Process blender -ErrorAction SilentlyContinue) {
    Start-Sleep -Seconds 30
    Write-Host "  $(Get-Date -Format 'HH:mm:ss') Blender still running..."
}
Write-Host "$(Get-Date -Format 'HH:mm:ss') Blender finished. Starting SENSE pipeline." -ForegroundColor Green

Write-Host "`n--- Depth Extraction (~10 min) ---" -ForegroundColor Yellow
python "$root\scripts\sense\extract_depth.py" --input-dir "$root\PHOTOS KENSINGTON sorted" --output-dir "$root\depth_maps"

Write-Host "`n--- Facade Segmentation (~15 min) ---" -ForegroundColor Yellow
python "$root\scripts\sense\segment_facades.py" --input-dir "$root\PHOTOS KENSINGTON sorted" --output-dir "$root\segmentation" --annotate

Write-Host "`n--- Fusion: depth ---" -ForegroundColor Yellow
python "$root\scripts\enrich\fuse_depth.py"

Write-Host "`n--- Fusion: segmentation ---" -ForegroundColor Yellow
python "$root\scripts\enrich\fuse_segmentation.py"

Write-Host "`n=== SENSE + Fusion complete ===" -ForegroundColor Green
Write-Host "$(Get-Date -Format 'HH:mm:ss') Done."
