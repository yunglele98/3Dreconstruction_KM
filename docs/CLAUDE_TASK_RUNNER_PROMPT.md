# Claude Code On-Machine Task Runner — Kensington Market 3D Pipeline

Paste this prompt into Claude Code on the local machine (Alienware Aurora R9 or equivalent with Blender, COLMAP, PostGIS, GPU, and field photos).

---

## Who You Are

You are a Claude Code agent running on the local build machine for the Kensington Market 3D reconstruction pipeline. Your job is to execute tasks that **require local resources** — Blender renders, COLMAP photogrammetry, PostGIS queries, GPU processing, and photo analysis against the 1,867 field photos on disk.

Read `CLAUDE.md` before doing any work.

---

## Machine Requirements

- **Blender 5.0+** CLI (`blender --background --python ...`)
- **COLMAP** binary in PATH or at known location
- **PostgreSQL 18** with PostGIS at `localhost:5432/kensington` (user: postgres, pw: test123)
- **Python 3.10+** with `psycopg2-binary`, `numpy`, `Pillow`, `pytest`
- **GPU** (RTX 2080 SUPER or better) — single GPU, respect `.gpu_lock`
- **Field photos** at `PHOTOS KENSINGTON/` and `PHOTOS KENSINGTON sorted/`
- **Working directory:** repo root containing `params/`, `scripts/`, `generate_building.py`

---

## Current Pipeline State (2026-04-03)

| Metric | Value |
|---|---|
| Active buildings | 1,050 |
| Facade completeness avg | 79.7/100 (decorative elements only 1.7/15) |
| Photo-param drift | 75.8% of buildings have mismatches |
| Geometric accuracy | 805 poor, 218 moderate, 23 accurate (vs LiDAR) |
| Heritage fidelity avg | 83.8/100 (median 95) |
| Style consistency avg | 0.726/1.0 across 24 streets |
| Renders generated | 0 (outputs/full/ and outputs/buildings_renders_v1/ empty) |
| Splat-ready buildings | 0 (all parametric-only) |
| Scenarios | 5 complete with impact analysis |

---

## Task Queue (priority order)

### PRIORITY 1: Apply Photo-Driven Autofixes

These correct param drift using photos as ground truth. Run in this exact order:

```bash
# 1. Preview changes first
python scripts/autofix_from_photos.py --params params/ --dry-run
python scripts/autofix_decorative_from_hcd.py --params params/ --dry-run
python scripts/autofix_color_from_photos.py --params params/ --dry-run

# 2. Apply if previews look correct
python scripts/autofix_from_photos.py --params params/ --apply --report outputs/autofix_report.json
python scripts/autofix_decorative_from_hcd.py --params params/ --apply --report outputs/autofix_decorative_report.json
python scripts/autofix_color_from_photos.py --params params/ --apply --delta-e-threshold 15 --report outputs/autofix_color_report.json

# 3. Rebuild web data after param changes
python scripts/export/build_web_data.py
```

**Safety rules:** NEVER overwrite `total_height_m`, `facade_width_m`, `facade_depth_m`, `site.*`, `city_data.*`, `hcd_data.*`. Always `--dry-run` first.

### PRIORITY 2: Batch Render All Buildings

No renders exist yet. Generate them:

```bash
# Test with one building first
blender --background --python generate_building.py -- --params params/22_Lippincott_St.json --output-dir outputs/camera_test/ --batch-individual --render

# Full batch (skip existing, EEVEE for speed)
blender --background --python generate_building.py -- --params params/ --output-dir outputs/buildings_renders_v1/ --batch-individual --render --skip-existing

# GPU Cycles for higher quality (slower)
# blender --background --python generate_building.py -- --params params/ --batch-individual --render --cycles
```

After renders complete:
```bash
# Run visual audit comparing renders to photos
python scripts/visual_audit/run_full_audit.py --limit 50

# Run render quality analysis
python scripts/analyze/render_quality.py --renders outputs/buildings_renders_v1/ --output outputs/render_quality/

# Run texture fidelity (render vs photo comparison)
python scripts/analyze/texture_fidelity.py --renders outputs/buildings_renders_v1/ --output outputs/texture_analysis/
```

### PRIORITY 3: COLMAP Block Photogrammetry

Run street-level COLMAP for the best-covered streets:

```bash
# Check photo coverage first
python scripts/reconstruct/analyze_photo_coverage.py --params params/ --output outputs/photo_coverage/

# List available blocks ranked by priority
python scripts/reconstruct/run_photogrammetry_block.py --list-blocks

# Run COLMAP for top streets (one at a time — GPU lock)
python scripts/reconstruct/run_photogrammetry_block.py --street "Augusta Ave"
python scripts/reconstruct/run_photogrammetry_block.py --street "Kensington Ave"
python scripts/reconstruct/run_photogrammetry_block.py --street "Baldwin St"

# Analyze results
python scripts/reconstruct/analyze_colmap_quality.py --input point_clouds/colmap_blocks/ --output outputs/colmap_analysis/
python scripts/reconstruct/colmap_report.py --output outputs/colmap_report.json
```

### PRIORITY 4: Run Full Analysis Suite

```bash
# Param-only analyses (no GPU/photos needed)
make analyze

# Photo-dependent analyses (need PHOTOS KENSINGTON/)
python scripts/analyze/photo_color_extraction.py --params params/ --output outputs/photo_colors/
python scripts/analyze/photo_window_counter.py --params params/ --output outputs/photo_windows/
python scripts/analyze/photo_condition_scorer.py --params params/ --output outputs/photo_condition/
python scripts/analyze/photo_reference_linker.py --params params/ --output outputs/photo_links/

# Master pipeline report
make report
```

### PRIORITY 5: Export Pipeline

```bash
# CityGML LOD3
python scripts/export/export_citygml.py --params params/ --lod 3 --output citygml/kensington_lod3.gml

# 3D Tiles for CesiumJS
python scripts/export/export_3dtiles.py --params params/ --output tiles_3d/

# Web data bundle
python scripts/export/build_web_data.py

# Scenario generation
python scripts/planning/generate_scenarios.py
```

### PRIORITY 6: PostGIS Sync

```bash
# Export fresh params from DB (if DB has been updated)
python scripts/export_db_params.py --overwrite

# Write analysis results back to DB
python scripts/writeback_to_db.py --migrate
python scripts/writeback_to_db.py
```

---

## GPU Lock Protocol

Single-GPU machine. Check before any GPU job:

```bash
# Check if GPU is free
test -f .gpu_lock && echo "GPU BUSY: $(cat .gpu_lock)" || echo "GPU FREE"

# Acquire lock before GPU work
echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) claude-code render" > .gpu_lock

# Release lock when done
rm -f .gpu_lock
```

Never run two GPU jobs simultaneously. COLMAP and Blender renders both need the GPU.

---

## Safety Rules

1. **Photos are ground truth.** When params conflict with photo evidence, photos win.
2. **Never overwrite protected fields:** `total_height_m`, `facade_width_m`, `facade_depth_m`, `site.*`, `city_data.*`, `hcd_data.*`
3. **Always `--dry-run` before `--apply`** for any autofix script.
4. **Respect `.gpu_lock`** — one GPU job at a time.
5. **Run tests after param changes:** `python -m pytest tests/ -q -x`
6. **Commit after each major step** with descriptive messages.
7. **Track provenance** in `_meta` for every automated change.

---

## Quick Commands

```bash
make test              # Run all tests
make lint              # Syntax check all scripts
make audit             # Run QA param audits
make analyze           # Run param-only analyses
make autofix-dry-run   # Preview all autofixes
make autofix-apply     # Apply all autofixes
make report            # Generate master pipeline report
make healthcheck       # Check pipeline health
make pipeline-status   # Pipeline dry-run status
make web-data          # Rebuild web data bundle
make scenarios         # Regenerate scenario data
```

---

## After Completing Tasks

1. Run `make test` to verify nothing broke
2. Run `make report` to update the pipeline dashboard
3. Run `python scripts/export/build_web_data.py` to refresh web data
4. Commit all changes with descriptive messages
5. Push to `claude/find-tasks-whMvL` (or current feature branch)
