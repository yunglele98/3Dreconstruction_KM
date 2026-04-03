# Claude Code On-Machine — Pipeline Execution Prompt

Paste into Claude Code on the Alienware Aurora R9 (or any machine with Blender + COLMAP + PostGIS + GPU).

Working directory: `C:\Users\liam1\blender_buildings`

Read `CLAUDE.md` thoroughly before starting. Run `python -m pytest tests/ -q` to verify baseline.

---

## Machine Requirements

| Component | Path / Config |
|-----------|--------------|
| **Blender** | `C:\Program Files\Blender Foundation\Blender 5.1\blender.exe` |
| **COLMAP** | `C:\Tools\COLMAP\COLMAP.bat` |
| **OpenMVS** | `C:\Tools\OpenMVS\` |
| **PostgreSQL 18** | localhost:5432, db=kensington, user=postgres, pw=test123 |
| **Python** | 3.12+ with numpy, Pillow, psycopg2-binary, trimesh |
| **GPU** | RTX 2080 SUPER 8GB (single GPU — respect .gpu_lock) |

---

## Your Mission

Execute the V7 pipeline stages that require local hardware: GPU renders, COLMAP reconstruction, PostGIS queries, and ML model inference. Follow the task list below **in order**. Skip any task marked DONE. After each major task, run `python scripts/generate_coverage_matrix.py` to track progress.

---

## TASK 1 — Batch Render All 1,050 Buildings (~4-6 hours)

Coverage target: `rendered` from 0% → 100%.

```powershell
# Render all buildings (skip any already rendered)
blender --background --python generate_building.py -- --params params/ --output-dir outputs/full/ --batch-individual --render --skip-existing

# If memory issues, do 50 at a time:
blender --background --python generate_building.py -- --params params/ --output-dir outputs/full/ --batch-individual --render --skip-existing --limit 50
```

**Verify:**
```bash
python scripts/generate_coverage_matrix.py
# rendered should be ~1050
ls outputs/full/*.blend | wc -l
```

**Smoke check 5 samples:**
```powershell
$samples = @("22_Lippincott_St", "81_Bellevue_Ave", "200_Augusta_Ave", "132_Bellevue_Ave", "100_Bellevue_Ave")
foreach ($s in $samples) {
    blender --background --python generate_building.py -- --params "params/$s.json" --output-dir outputs/smoke_test/ --render
}
```

Compare renders against field photos in `PHOTOS KENSINGTON sorted/` for the same addresses. Flag any major discrepancies.

---

## TASK 2 — FBX/GLB Export (~2 hours)

Coverage target: `exported` from 0% → 100%.

```powershell
# Export all buildings to FBX
blender --background --python scripts/export_building_fbx.py -- --source-dir outputs/full/ --output-dir outputs/exports/

# Generate LODs
blender --background --python scripts/generate_lods.py -- --source-dir outputs/full/ --skip-existing

# Generate collision meshes
blender --background --python scripts/generate_collision_mesh.py -- --source-dir outputs/full/

# Validate exports
python scripts/validate_export_pipeline.py --source-dir outputs/exports/
```

---

## TASK 3 — COLMAP Block Photogrammetry (~3-6 hours per block)

Coverage target: at least 5 street blocks reconstructed.

**Check .gpu_lock before starting — only one GPU job at a time.**

```bash
# List priority blocks
python scripts/reconstruct/run_photogrammetry_block.py --list-blocks

# Run top-priority block (usually Augusta Ave)
python scripts/reconstruct/run_photogrammetry_block.py --street "Augusta Ave" --dense

# After sparse completes, clip to per-building
python scripts/reconstruct/clip_block_mesh.py --block-mesh point_clouds/colmap_blocks/Augusta_Ave/fused.ply --footprints gis_scene --street "Augusta Ave"
```

**Priority blocks (in order):**
1. Augusta Ave (154 buildings, most photos)
2. Kensington Ave (78 buildings)
3. Baldwin St (49 buildings)
4. Nassau St (42 buildings)
5. College St (49 buildings, arterial)

After each block, run per-building COLMAP for buildings with 3+ individual photos:
```bash
python scripts/reconstruct/select_candidates.py --params params/ --photos "PHOTOS KENSINGTON/" --min-views 3
python scripts/reconstruct/run_photogrammetry.py --candidates reconstruction_candidates.json --limit 20
```

---

## TASK 4 — Depth Map Extraction (~30 min with GPU)

Coverage target: `depth_map` from 0% → 100%.

```bash
# GPU mode (Depth Anything v2, ~0.5 sec/image)
python scripts/sense/extract_depth.py --input "PHOTOS KENSINGTON/" --output depth_maps/ --method gpu --skip-existing

# If GPU OOM, use edge fallback:
python scripts/sense/extract_depth.py --input "PHOTOS KENSINGTON/" --output depth_maps/ --method edge --skip-existing

# Fuse into params
python scripts/enrich/fuse_depth.py --depth-maps depth_maps/ --params params/
```

---

## TASK 5 — Facade Segmentation (~45 min with GPU)

Coverage target: `seg_map` from 0% → 100%.

```bash
# GPU mode (YOLOv11)
python scripts/sense/segment_facades.py --input "PHOTOS KENSINGTON/" --output segmentation/ --method gpu --skip-existing

# Fuse into params
python scripts/enrich/fuse_segmentation.py --segmentation segmentation/ --params params/
```

---

## TASK 6 — Signage OCR + Feature Extraction

```bash
# OCR (PaddleOCR or tesseract)
python scripts/sense/extract_signage.py --input "PHOTOS KENSINGTON/" --output signage/ --skip-existing

# Fuse signage into params
python scripts/enrich/fuse_signage.py --signage signage/ --params params/

# Feature extraction (for COLMAP matching)
python scripts/sense/extract_features.py --input "PHOTOS KENSINGTON/" --output features/ --skip-existing

# Surface normals
python scripts/sense/extract_normals.py --input "PHOTOS KENSINGTON/" --output normals/ --skip-existing
```

---

## TASK 7 — Weathering + Displacement Textures (~20 min)

```bash
# Generate per-building weathering overlays
python scripts/texture/generate_weathering.py --params params/ --output textures/weathering/

# Generate displacement maps for all materials
python scripts/texture/generate_displacement.py --batch --output textures/displacement/

# Extract PBR maps from field photos
python scripts/texture/extract_pbr.py --input "PHOTOS KENSINGTON sorted/" --output textures/pbr/ --method edge --limit 200

# Upscale textures
python scripts/texture/upscale_textures.py --input textures/baked/ --output textures/upscaled/
```

---

## TASK 8 — PostGIS Writeback + QA

```bash
# Write photo analysis back to DB
python scripts/writeback_to_db.py --migrate   # first time only
python scripts/writeback_to_db.py

# Run QA gate
python scripts/qa_params_gate.py --ci
python scripts/audit_params_quality.py
python scripts/audit_structural_consistency.py
python scripts/audit_generator_contracts.py

# Fix any anomalies found
python scripts/fix_param_anomalies.py --dry-run
python scripts/fix_param_anomalies.py
```

---

## TASK 9 — Export Pipeline

```bash
# CityGML LOD3
python scripts/export/export_citygml.py --lod 3 --output citygml/kensington_lod3.gml

# 3D Tiles for CesiumJS
python scripts/export/export_3dtiles.py --input outputs/exports/ --output tiles_3d/

# Web platform data bundle
python scripts/export/build_web_data.py --params params/ --scenarios scenarios/ --output web/public/data/

# Unreal Datasmith
blender --background --python scripts/batch_export_unreal.py -- --source-dir outputs/full/
python scripts/build_unreal_datasmith.py

# GeoJSON + deliverables
python scripts/export_gis_scene.py
python scripts/export_deliverables.py
python scripts/generate_qa_report.py
```

---

## TASK 10 — Gaussian Splat Training (cloud GPU recommended)

```bash
# Prepare cloud session (packages COLMAP outputs for A100)
python scripts/reconstruct/train_splats.py --prepare-cloud --output splats/

# OR run locally if GPU has enough VRAM:
python scripts/reconstruct/train_splats.py --input point_clouds/colmap/ --batch --limit 10
```

---

## TASK 11 — Scenario Generation + Analysis

```bash
# Apply all 5 scenarios
for scenario in scenarios/*/; do
    name=$(basename "$scenario")
    python scripts/planning/apply_scenario.py --baseline params/ --scenario "$scenario" --output "outputs/scenarios/$name/"
done

# Analyze each
for scenario in scenarios/*/; do
    name=$(basename "$scenario")
    python scripts/planning/shadow_impact.py --baseline params/ --scenario "outputs/scenarios/$name/" --season winter --output "outputs/scenarios/$name/shadow.json"
    python scripts/planning/heritage_impact.py --baseline params/ --scenario "$scenario" --output "outputs/scenarios/$name/heritage.json"
done
```

---

## Progress Tracking

After each task, update the coverage matrix and sprint tracker:

```bash
python scripts/generate_coverage_matrix.py
python scripts/monitor/sprint_progress.py --json
```

Target coverage by end of session:

| Metric | Before | Target |
|--------|--------|--------|
| rendered | 0% | 100% |
| exported | 0% | 100% |
| depth_map | 0% | 100% |
| seg_map | 0% | 100% |
| COLMAP blocks | 0 | 5+ |

---

## Rules

1. **GPU lock:** Check `.gpu_lock` before starting GPU tasks. Only one GPU job at a time.
2. **Never overwrite:** `total_height_m`, `facade_width_m`, `facade_depth_m`, `site.*`, `city_data.*`, `hcd_data.*`
3. **Stamp provenance:** All param changes go through `_meta` tracking.
4. **Test before commit:** `python -m pytest tests/ -q` must pass before any git commit.
5. **Skip existing:** Always use `--skip-existing` flags for incremental work.
6. **Errors:** If a task fails, log the error, skip it, and continue to the next task. Fix failures in a second pass.

---

## When Done

```bash
python scripts/generate_coverage_matrix.py
python scripts/monitor/sprint_progress.py
python scripts/audit_generator_contracts.py
python -m pytest tests/ -q
git add -A && git commit -m "pipeline: batch render + COLMAP + SENSE + exports"
git push
```
