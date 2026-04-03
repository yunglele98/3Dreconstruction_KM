# Overnight batch: 2026-04-02
# Phase A exports + GPU sense pipeline
# Estimated runtime: 2-4 hours

$blender = "C:\Program Files\Blender Foundation\Blender 5.1\blender.exe"
$root = "C:\Users\liam1\blender_buildings"

Write-Host "=== OVERNIGHT BATCH 2026-04-02 ===" -ForegroundColor Cyan
Write-Host "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') Starting..."

# ---------------------------------------------------------------
# PHASE A: Export pipeline (Blender GPU)
# ---------------------------------------------------------------

Write-Host "`n--- Phase A Step 1: FBX Export (1,253 blends) ---" -ForegroundColor Yellow
& $blender --background --python "$root\scripts\batch_export_unreal.py" -- --source-dir "$root\outputs\full\" --skip-existing 2>&1 | Select-String -Pattern "Saved|FAIL|complete|Total|error"

Write-Host "`n--- Phase A Step 2: LOD Generation ---" -ForegroundColor Yellow
& $blender --background --python "$root\scripts\generate_lods.py" -- --source-dir "$root\outputs\full\" --skip-existing 2>&1 | Select-String -Pattern "Saved|FAIL|complete|Total|error"

Write-Host "`n--- Phase A Step 3: Collision Meshes ---" -ForegroundColor Yellow
& $blender --background --python "$root\scripts\generate_collision_mesh.py" -- --source-dir "$root\outputs\full\" --skip-existing 2>&1 | Select-String -Pattern "Saved|FAIL|complete|Total|error"

Write-Host "`n--- Phase A Step 4: Mesh Optimization (CPU) ---" -ForegroundColor Yellow
python "$root\scripts\optimize_meshes.py" --source-dir "$root\outputs\exports\" --skip-existing 2>&1 | Select-String -Pattern "complete|Total|error"

Write-Host "`n--- Phase A Step 5: Export Validation ---" -ForegroundColor Yellow
python "$root\scripts\validate_export_pipeline.py" --source-dir "$root\outputs\exports\" 2>&1 | Select-String -Pattern "complete|pass|fail|Total"

Write-Host "`n--- Phase A Step 6: Manifests ---" -ForegroundColor Yellow
python "$root\scripts\build_unreal_datasmith.py" 2>&1 | Select-String -Pattern "complete|written|error"
python "$root\scripts\build_unity_prefab_manifest.py" 2>&1 | Select-String -Pattern "complete|written|error"

# ---------------------------------------------------------------
# SENSE pipeline (GPU — runs after Phase A frees GPU)
# ---------------------------------------------------------------

Write-Host "`n--- Sense Step 1: Depth Extraction (~10 min) ---" -ForegroundColor Yellow
python "$root\scripts\sense\extract_depth.py" --input-dir "$root\PHOTOS KENSINGTON sorted" --output-dir "$root\depth_maps" 2>&1 | Select-String -Pattern "Progress|Done|Error|Processed|Skipped"

Write-Host "`n--- Sense Step 2: Facade Segmentation (~15 min) ---" -ForegroundColor Yellow
python "$root\scripts\sense\segment_facades.py" --input-dir "$root\PHOTOS KENSINGTON sorted" --output-dir "$root\segmentation" --annotate 2>&1 | Select-String -Pattern "Done|Error|Success|Skip|Total"

Write-Host "`n=== OVERNIGHT BATCH COMPLETE ===" -ForegroundColor Green
Write-Host "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') Done."
Write-Host "Next: run fusion scripts (fuse_depth, fuse_segmentation) in morning session."
