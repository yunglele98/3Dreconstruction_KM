# Phase A: Complete all exports
# Run this after renders finish, or it will skip-existing

$blender = "C:\Program Files\Blender Foundation\Blender 5.1\blender.exe"
$root = "C:\Users\liam1\blender_buildings"

Write-Host "=== PHASE A: COMPLETE EXPORTS ===" -ForegroundColor Cyan
Write-Host "$(Get-Date -Format 'HH:mm:ss') Starting..."

# Step 1: FBX Export
Write-Host "`n--- Step 1: FBX Export ---" -ForegroundColor Yellow
& $blender --background --python "$root\scripts\batch_export_unreal.py" -- --source-dir "$root\outputs\full\" --skip-existing 2>&1 | Select-String -Pattern "Saved|FAIL|complete|Total"

# Step 2: LOD Generation
Write-Host "`n--- Step 2: LOD Generation ---" -ForegroundColor Yellow
& $blender --background --python "$root\scripts\generate_lods.py" -- --source-dir "$root\outputs\full\" --skip-existing 2>&1 | Select-String -Pattern "Saved|FAIL|complete|Total"

# Step 3: Collision Meshes
Write-Host "`n--- Step 3: Collision Meshes ---" -ForegroundColor Yellow
& $blender --background --python "$root\scripts\generate_collision_mesh.py" -- --source-dir "$root\outputs\full\" --skip-existing 2>&1 | Select-String -Pattern "Saved|FAIL|complete|Total"

# Step 4: Mesh Optimization (no Blender needed)
Write-Host "`n--- Step 4: Mesh Optimization ---" -ForegroundColor Yellow
python "$root\scripts\optimize_meshes.py" --source-dir "$root\outputs\exports\" --skip-existing 2>&1 | Select-String -Pattern "complete|Total|error"

# Step 5: Validate
Write-Host "`n--- Step 5: Export Validation ---" -ForegroundColor Yellow
python "$root\scripts\validate_export_pipeline.py" --source-dir "$root\outputs\exports\" 2>&1 | Select-String -Pattern "complete|pass|fail|Total"

# Step 6: Update manifests
Write-Host "`n--- Step 6: Update Manifests ---" -ForegroundColor Yellow
python "$root\scripts\build_unreal_datasmith.py" 2>&1 | Select-String -Pattern "complete|written|error"
python "$root\scripts\build_unity_prefab_manifest.py" 2>&1 | Select-String -Pattern "complete|written|error"

Write-Host "`n=== PHASE A COMPLETE ===" -ForegroundColor Green
Write-Host "$(Get-Date -Format 'HH:mm:ss') Done."
