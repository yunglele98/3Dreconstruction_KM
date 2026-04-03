# Claude Code System Runner — Kensington Market 3D Pipeline

You are a Claude Code agent running on the **Windows production machine** (RTX 2080S, Blender 5.0, PostgreSQL 18 + PostGIS, COLMAP). Your job is to execute pipeline tasks that require local GPU, Blender, or database access — things that cannot run in CI or cloud.

## Your Environment

- **OS:** Windows 11, PowerShell
- **GPU:** NVIDIA RTX 2080S (single GPU — respect `.gpu_lock`)
- **Blender:** `"C:\Program Files\Blender Foundation\Blender 5.0\blender.exe"`
- **Python:** 3.10+ with numpy, Pillow, trimesh, psycopg2-binary, scipy, scikit-image
- **PostgreSQL 18:** localhost:5432, database `kensington`, user `postgres`, password `test123`
- **COLMAP:** `C:\Users\liam1\Apps\COLMAP\bin\colmap`
- **Repo:** `C:\Users\liam1\blender_buildings` (same as this repo)

## Key Files

- `CLAUDE.md` — full project docs and command reference
- `outputs/coverage_matrix.json` — current pipeline status
- `outputs/regen_queue.json` — buildings needing re-render
- `agent_ops/` — task kanban board

## Current Gaps (what you need to do)

Run `python scripts/generate_coverage_matrix.py` first to get current status, then execute tasks in this priority order:

### Phase 1: SENSE (GPU, ~2 hours total)
These run in sequence (single GPU):
```powershell
python scripts/sense/extract_depth.py --input "PHOTOS KENSINGTON/" --output depth_maps/ --skip-existing
python scripts/sense/segment_facades.py --input "PHOTOS KENSINGTON/" --output segmentation/ --skip-existing
python scripts/sense/extract_signage.py --input "PHOTOS KENSINGTON/" --output signage/ --skip-existing
python scripts/sense/extract_normals.py --input "PHOTOS KENSINGTON/" --output normals/ --skip-existing
python scripts/sense/extract_features.py --input "PHOTOS KENSINGTON/" --output features/ --skip-existing
```

### Phase 2: FUSE (CPU, ~5 min)
After SENSE completes, fuse results into params:
```powershell
python scripts/enrich/fuse_depth.py --apply
python scripts/enrich/fuse_segmentation.py --apply
python scripts/enrich/fuse_signage.py --apply
```

### Phase 3: GENERATE (Blender, ~4-6 hours)
Batch generate all 1,050 buildings:
```powershell
blender --background --python generate_building.py -- --params params/ --output-dir outputs/full/ --batch-individual --skip-existing
```
Then render:
```powershell
blender --background --python generate_building.py -- --params params/ --output-dir outputs/buildings_renders_v1/ --batch-individual --render --skip-existing
```

### Phase 4: EXPORT (Blender, ~3 hours)
```powershell
blender --background --python scripts/batch_export_unreal.py -- --source-dir outputs/full/
blender --background --python scripts/generate_lods.py -- --source-dir outputs/full/ --skip-existing
blender --background --python scripts/generate_collision_mesh.py -- --source-dir outputs/full/
```

### Phase 5: RECONSTRUCT (GPU + COLMAP, ~2-4 hours)
Run block-level COLMAP for streets with most photos:
```powershell
python scripts/reconstruct/run_photogrammetry_block.py --list-blocks
# Then run top-priority streets:
python scripts/reconstruct/run_photogrammetry_block.py --street "Augusta Ave" --dense
python scripts/reconstruct/run_photogrammetry_block.py --street "Kensington Ave" --dense
python scripts/reconstruct/run_photogrammetry_block.py --street "Baldwin St" --dense
```

### Phase 6: REPAIR + QA (CPU, ~15 min)
```powershell
python scripts/batch_mesh_repair.py --exports-dir outputs/exports/ --apply --fill-holes --report outputs/mesh_repair_report.json
python scripts/qa_params_gate.py --ci
python scripts/generate_coverage_matrix.py
python scripts/generate_qa_report.py
```

### Phase 7: DB + WEB (CPU, ~5 min)
```powershell
python scripts/writeback_to_db.py
python scripts/export/build_web_data.py
python scripts/export/build_web_geojson.py
python scripts/export/export_citygml.py --lod 2 --output citygml/kensington_lod2.gml
python scripts/export/export_3dtiles.py
```

### Phase 8: DELIVERABLES (CPU, ~2 min)
```powershell
python scripts/export_deliverables.py --output deliverables/
python scripts/fingerprint_params.py
```

## Rules

1. **GPU lock:** Before any GPU task, check for `.gpu_lock`. If locked, wait or skip. After GPU tasks, ensure lock is released.
2. **Skip existing:** Always use `--skip-existing` for idempotent reruns.
3. **Error handling:** If a Blender batch fails mid-run, note the last successful building and restart with `--skip-existing`.
4. **Commit after each phase:** `git add` changed outputs and commit with a message describing what completed.
5. **Coverage check:** After each phase, run `python scripts/generate_coverage_matrix.py` and report progress.
6. **Tests:** Run `python -m pytest tests/ -q` after any script changes to verify nothing broke.
7. **Never modify:** `total_height_m`, `facade_width_m`, `facade_depth_m`, `site.*`, `city_data.*`, `hcd_data.*` in params (protected fields).
8. **Sprint context:** Day 2 of 21-day sprint. Sprint start = April 2, 2026.

## Quick Status Commands

```powershell
# Pipeline status
python scripts/generate_coverage_matrix.py

# Sprint progress
python scripts/monitor/sprint_progress.py --json

# Street-level report
python scripts/street_report.py

# Per-building lookup
python scripts/deep_facade_pipeline.py report "Augusta"

# What needs re-rendering
python scripts/fingerprint_params.py
python scripts/build_regen_batches.py
```

## After Completion

Push results and report:
```powershell
git add outputs/ depth_maps/ segmentation/ signage/ normals/ features/ citygml/ tiles_3d/ web/public/data/
git commit -m "Pipeline run: SENSE + GENERATE + EXPORT phases complete"
git push -u origin main
```

Then run the final coverage check and paste the output as your completion summary.
