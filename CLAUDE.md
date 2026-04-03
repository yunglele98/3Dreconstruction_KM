# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Hybrid pipeline for 3D reconstruction of ~1,050 historic Kensington Market buildings (Toronto): parametric generation (foundation) + photogrammetry (ground truth) + neural reconstruction (gap filling) + ML segmentation (automation) + urban analysis (context). Delivers to game engines, web planning platform, and heritage archives.

**Dual purpose:**
1. **Heritage reconstruction** — accurate 3D model of Kensington Market as it exists today
2. **Urban planning platform** — baseline for testing 10-year city planning scenarios (infill, adaptive reuse, streetscape changes, densification, heritage preservation)

Study area: Dundas St W (north) / Bathurst St (east) / College St (south) / Spadina Ave (west). Only the market-facing side of perimeter streets is in scope.

**Key design docs:** `docs/PIPELINE_REDESIGN_V7.md` (full architecture), `docs/SPRINT_3_WEEK_PARALLEL.md` (execution plan), `docs/FACTORY_ALWAYS_ON.md` (always-on autonomous system), `docs/PHASE_0_VISUAL_AUDIT.md` (render vs photo comparison).

**Sprint:** Day 1 = April 2, 2026 (active). 3-week sprint, 14-agent fleet (5x Claude Code + 4 Gemini/Codex + 4 Ollama), ~$7 cloud GPU total.

**Phase 0 (precedes all pipeline phases):** Visual audit comparing `outputs/buildings_renders_v1/` (parametric renders) against `PHOTOS KENSINGTON sorted/` (field photos). Produces ranked priority queue driving which buildings get photogrammetry, segmentation, or colour fixes.

## V7 Pipeline Stages

```
 0. ACQUIRE        Raw data ingestion (photos, PostGIS, iPad LiDAR, street view, open data)
 1. SENSE          Depth (Depth Anything v2), segmentation (YOLOv11+SAM2), normals, OCR, features
 2. RECONSTRUCT    COLMAP/OpenMVS photogrammetry, DUSt3R single-view, element extraction, splats
 3. ENRICH         Existing 6-script pipeline + 5 new fusion scripts (depth, seg, LiDAR, photog, signage)
 4. GENERATE       Hybrid selector: photogrammetric mesh (3+ photos) OR parametric (fallback)
 5. TEXTURE        Procedural materials + PBR extraction + AI texture projection + upscaling
 6. OPTIMIZE       LOD generation, collision mesh, mesh repair, validation
 7. ASSEMBLE       Buildings + 20 urban element categories + terrain + vegetation + roads
 8. EXPORT         UE Datasmith, Unity, CityGML LOD2+3, 3D Tiles, Potree, Gaussian splats, web platform
 9. VERIFY         pytest, param QA gate, visual regression (SSIM), mesh validation, segmentation validation
10. MONITOR        Sentry, n8n heartbeat, batch job health, agent dashboard
11. SCENARIOS      5 urban planning scenarios as JSON overlays + impact analysis (shadow, density, heritage)
```

**Generator fallback chain** (every `create_*` function): scanned element → external asset library → procedural.

## Commands

```bash
# === Phase 0: Visual Audit (render vs photo comparison) ===
python scripts/visual_audit/run_full_audit.py                    # full audit (~35 min)
python scripts/visual_audit/run_full_audit.py --limit 20         # quick test

# === Batch Render (Blender 5.1) ===
blender --background --python generate_building.py -- --params params/ --output-dir outputs/buildings_renders_v1/ --batch-individual --render
blender --background --python generate_building.py -- --params params/ --output-dir outputs/buildings_renders_v1/ --batch-individual --render --skip-existing
blender --background --python generate_building.py -- --params params/22_Lippincott_St.json --output-dir outputs/camera_test/ --batch-individual --render
blender --background --python generate_building.py -- --params params/ --batch-individual --render --cycles  # GPU Cycles (slower, higher quality)

# === Tests ===
python -m pytest tests/ -q
python -m pytest tests/test_enrich_skeletons.py -q   # single file
python -m pytest tests/test_edge_cases.py::test_name  # single test

# === Orchestration / status ===
python scripts/run_blender_buildings_workflows.py route
python scripts/run_blender_buildings_workflows.py control-plane
python scripts/run_blender_buildings_workflows.py watchdog --mode once
python scripts/run_blender_buildings_workflows.py dashboard --once-json

# === Stage 0: ACQUIRE ===
python scripts/export_db_params.py [--overwrite] [--street "Augusta Ave"]
python scripts/export_db_params.py --address "22 Lippincott St"
python scripts/acquire_ipad_scans.py --input scans/montreal/ --output data/ipad_scans/
python scripts/acquire_extract_elements.py --input data/ipad_scans/ --output assets/scanned_elements/
python scripts/acquire_streetview.py --source mapillary --bbox kensington
python scripts/acquire_open_data.py --sources overture,toronto-trees,toronto-massing

# === Stage 1: SENSE ===
python scripts/sense/extract_depth.py --model depth-anything-v2 --input "PHOTOS KENSINGTON/" --output depth_maps/
python scripts/sense/segment_facades.py --input "PHOTOS KENSINGTON/" --output segmentation/ --model yolov11+sam2
python scripts/sense/extract_normals.py --model dsine --input "PHOTOS KENSINGTON/"
python scripts/sense/extract_signage.py --model paddleocr --input "PHOTOS KENSINGTON/" --output signage/
python scripts/sense/extract_features.py --model lightglue+superpoint --input "PHOTOS KENSINGTON/" --output features/

# === Stage 2: RECONSTRUCT ===
python scripts/reconstruct/select_candidates.py --params params/ --photos "PHOTOS KENSINGTON/" --min-views 3
python scripts/reconstruct/run_photogrammetry.py --candidates reconstruction_candidates.json --output point_clouds/colmap/
python scripts/reconstruct/run_photogrammetry_block.py --block-graph outputs/spatial/adjacency_graph.json
python scripts/reconstruct/run_dust3r.py --input "PHOTOS KENSINGTON/" --params params/ --max-views 2
python scripts/reconstruct/clip_block_mesh.py --block-mesh meshes/blocks/<block>.obj --footprints postgis
python scripts/reconstruct/extract_elements.py --meshes meshes/per_building/ --segmentation segmentation/
python scripts/reconstruct/retopologize.py --input meshes/raw/ --output meshes/retopo/ --method instant-meshes
python scripts/reconstruct/calibrate_defaults.py --elements assets/elements/metadata/element_catalog.json
python scripts/reconstruct/train_splats.py --input point_clouds/colmap/ --output splats/

# === Stage 3: ENRICH (existing pipeline, run in order, each idempotent) ===
python scripts/translate_agent_params.py
python scripts/enrich_skeletons.py
python scripts/enrich_facade_descriptions.py
python scripts/normalize_params_schema.py
python scripts/patch_params_from_hcd.py
python scripts/infer_missing_params.py
# New fusion scripts:
python scripts/enrich/fuse_depth.py --depth-maps depth_maps/ --params params/
python scripts/enrich/fuse_segmentation.py --segmentation segmentation/ --params params/
python scripts/enrich/fuse_lidar.py --lidar lidar/building/ --params params/
python scripts/enrich/fuse_photogrammetry.py --meshes meshes/retopo/ --params params/
python scripts/enrich/fuse_signage.py --signage signage/ --params params/
# Post-enrichment:
python scripts/rebuild_colour_palettes.py
python scripts/diversify_colour_palettes.py
python scripts/match_photos_to_params.py
python scripts/enrich_storefronts_advanced.py
python scripts/enrich_porch_dimensions.py
python scripts/infer_setbacks.py
python scripts/consolidate_depth_notes.py
python scripts/build_adjacency_graph.py
python scripts/analyze_streetscape_rhythm.py

# === Stage 4: GENERATE (Blender) ===
blender --background --python generate_building.py -- --params params/22_Lippincott_St.json
blender --background --python generate_building.py -- --params params/ --batch-individual --dry-run
blender --background --python generate_building.py -- --params params/ --batch-individual --skip-existing
blender --background --python generate_building.py -- --params params/ --batch-individual --match "Augusta" --limit 10

# === Stage 5-6: TEXTURE + OPTIMIZE ===
python scripts/texture/extract_pbr.py --model intrinsic-anything --input "PHOTOS KENSINGTON/" --output textures/pbr/
python scripts/texture/upscale_textures.py --model realesrgan --input textures/ --scale 4
blender --background --python scripts/generate_lods.py -- --source-dir outputs/full/ --skip-existing
blender --background --python scripts/generate_collision_mesh.py -- --source-dir outputs/full/
python scripts/optimize_meshes.py --source-dir outputs/exports/
python scripts/validate_export_pipeline.py --source-dir outputs/exports/

# === Stage 7-8: ASSEMBLE + EXPORT ===
python scripts/export_gis_scene.py
blender --background --python scripts/export_building_fbx.py -- --address "22 Lippincott St"
blender --background --python scripts/batch_export_unreal.py -- --source-dir outputs/full/
python scripts/build_unreal_datasmith.py
python scripts/build_unity_prefab_manifest.py
python scripts/export/export_citygml.py --lod 3 --output citygml/kensington_lod3.gml
python scripts/export/export_3dtiles.py --input outputs/exports/ --output tiles_3d/
python scripts/export/export_potree.py --input point_clouds/ --output web/potree/
python scripts/export/build_web_data.py --params params/ --scenarios scenarios/ --output web/public/data/
python scripts/export_deliverables.py
python scripts/generate_qa_report.py

# === Stage 9: VERIFY ===
python scripts/qa_params_gate.py --ci
python scripts/audit_params_quality.py
python scripts/audit_structural_consistency.py
python scripts/audit_generator_contracts.py
python scripts/verify/visual_regression.py --renders outputs/full/ --references outputs/qa_visual_check/

# === Stage 11: SCENARIOS ===
python scripts/planning/apply_scenario.py --baseline params/ --scenario scenarios/10yr_gentle_density/
python scripts/planning/analyze_density.py --scenario scenarios/10yr_gentle_density/
python scripts/planning/shadow_impact.py --baseline params/ --scenario scenarios/10yr_gentle_density/
python scripts/planning/heritage_impact.py --scenario scenarios/10yr_gentle_density/
python scripts/planning/compare_scenarios.py --baseline outputs/full/ --scenario outputs/scenarios/gentle_density/

# === DB writeback ===
python scripts/writeback_to_db.py --migrate
python scripts/writeback_to_db.py

# === Utility ===
python scripts/fingerprint_params.py
python scripts/build_regen_batches.py
python scripts/generate_coverage_matrix.py
```

## Architecture

### Data flow (V7)

```
Raw Data Sources:
  PostGIS (building_assessment + opendata.*) ─────┐
  PHOTOS KENSINGTON/ (1,928 field photos) ────────┤
  iPad LiDAR scans (Montreal proxy) ──────────────┤
  Mapillary street view ──────────────────────────┤
  Overture Maps / Toronto Open Data ──────────────┘
                    │
  Stage 0: ACQUIRE  │  → data/, params/*.json
                    ▼
  Stage 1: SENSE    → depth_maps/, segmentation/, normals/, signage/, features/
                    ▼
  Stage 2: RECONSTRUCT → point_clouds/, meshes/, splats/, assets/elements/
                    ▼
  Stage 3: ENRICH   → params/*.json (enriched + fused)
                    ▼
  Stage 4: GENERATE → outputs/full/ (.blend + .png + .manifest.json)
                    ▼
  Stage 5-6: TEXTURE + OPTIMIZE → textures/, LODs, collision meshes
                    ▼
  Stage 7-8: ASSEMBLE + EXPORT → Datasmith, CityGML, 3D Tiles, web/
                    ▼
  Stage 9-10: VERIFY + MONITOR → QA reports, Sentry, CI
                    ▼
  Stage 11: SCENARIOS → scenarios/*/ (JSON overlays + impact analysis)
                    ▼
  Web Planning Platform (CesiumJS + Potree + splats) → Vercel
```

### Directory structure

**Existing:**
- `params/` — 1,065 JSON files (1,050 active + 3 metadata `_` prefix + 12 skipped). `_` prefix = metadata, `"skipped": true` = non-building.
- `scripts/` — 329 Python scripts. New V7 scripts go in subdirs: `scripts/sense/`, `scripts/reconstruct/`, `scripts/enrich/`, `scripts/texture/`, `scripts/analyze/`, `scripts/planning/`, `scripts/export/`, `scripts/verify/`, `scripts/monitor/`, `scripts/acquire/`, `scripts/heritage/`, `scripts/train/`, `scripts/unreal/`, `scripts/cloud/`, `scripts/game_engine/`, `scripts/qa/`, `scripts/visual_audit/`.
- `generator_modules/` — decomposed from `generate_building.py` (9,935 → 2,931 lines). 11 modules: `__init__.py`, `colours.py`, `materials.py`, `geometry.py`, `walls.py`, `windows.py`, `doors.py`, `roofs.py`, `decorative.py`, `storefront.py`, `structure.py`.
- `tests/` — 70 pytest test files.
- `outputs/` — rendered `.blend` files: `full/`, `exports/`, `demos/`, `single/`.
- `PHOTOS KENSINGTON/` — 1,928 geotagged field photos + `csv/photo_address_index.csv`.
- `agent_ops/` — kanban: `00_intake/` → `10_backlog/` → `20_active/` → `30_handoffs/` → `40_reviews/` → `60_releases/` → `90_archive/`.
- `docs/` — 37 markdown files: `PIPELINE_REDESIGN_V7.md`, `SPRINT_3_WEEK_PARALLEL.md`, `FACTORY_ALWAYS_ON.md`, `METHODOLOGY.md`, `PIPELINE_RUNBOOK.md`, `API_REFERENCE.md`, `UNREAL_IMPORT_GUIDE.md`, agent prompts, runbooks, audit reports.
- `batches/` — 8 batch dispatch files (`batch_001.json`–`batch_008.json`) for parallel Gemini/Codex agents.
- `infra/` — `n8n/` (workflow configs), `slack_commands.json`.

**New (V7):**
- `data/` — `lidar/` (raw/classified/building .laz), `street_view/`, `open_data/` (*.geojson), `terrain/` (DEM .tif), `heritage/`, `training/` (COCO annotations), `ipad_scans/`.
- `depth_maps/` — .npy + viz .png per photo (Depth Anything v2).
- `segmentation/` — masks + elements JSON per photo (YOLOv11+SAM2).
- `normals/` — .npy per photo (DSINE).
- `signage/` — OCR results per photo (PaddleOCR).
- `features/` — LightGlue+SuperPoint keypoints .h5 per photo.
- `point_clouds/` — `colmap/` (multi-view .ply), `dust3r/` (single-view .ply), `lidar/` (per-building .laz clips).
- `meshes/` — `raw/` (photogrammetric .obj), `retopo/` (quad remeshed .obj).
- `splats/` — Gaussian splat .splat files.
- `textures/` — `pbr/` (extracted), `projected/`, `upscaled/`.
- `assets/` — `elements/by_era/`, `elements/by_type/`, `elements/textures/`, `elements/metadata/`, `external/` (megascans, polyhaven, ambientcg, kenney, etc.).
- `citygml/` — LOD2 + LOD3 .gml exports.
- `tiles_3d/` — 3D Tiles for CesiumJS.
- `web/` — planning platform (CesiumJS + Potree + splats, Svelte/Vanilla TS, Vercel).
- `scenarios/` — `10yr_gentle_density/`, `10yr_green_infra/`, `10yr_heritage_first/`, `10yr_mixed_use/`, `10yr_mobility/`. Each has `interventions.json` overlay.

### Always-On Factory (n8n)

The system runs autonomously via n8n (Docker) + Cloudflare tunnel. See `docs/FACTORY_ALWAYS_ON.md`.

**15 workflows:** WF-01 Heartbeat (10min), WF-02 Overnight Pipeline (10PM), WF-03 COLMAP Block, WF-04 Photo Ingestion, WF-05 Scenario Computation, WF-06 Web Deploy, WF-07 Error Recovery, WF-08 Morning Report (7AM), WF-09 Cloud GPU Session, WF-10 Asset Library Update, WF-11 Nightly Backup, WF-12 Weekly Audit, WF-13 Design Decision Ingest, WF-14 Montreal Scan Ingest, WF-15 Sprint Progress Tracker.

**GPU lock:** Single-GPU machine (RTX 2080S). `.gpu_lock` file ensures one GPU job at a time. WF-02 and WF-03 check before starting.

**Slack command centre:** `/status`, `/queue`, `/coverage`, `/building <addr>`, `/colmap <block>`, `/scenario <name>`, `/deploy`, `/cloud <type>`, `/sprint`, `/run <script>` (whitelisted).

### Agent fleet (14 agents)

- **Tier 1 (Claude Code, Opus 4.6 1M, Max 5x):** architect, reviewer, writer-1, writer-2, ops + claude-research (Claude.ai chat for design track)
- **Tier 2 (Gemini API + Codex CLI):** gemini-batch-1/2 (Flash, n8n-automated), gemini-vision (Pro), codex-cli (manual)
- **Tier 3 (Ollama, local):** qwen2.5-coder:7b (code), qwen2.5-coder:3b (validate), llava:7b (vision), mistral:7b (summarize)

Task routing: architectural decisions → Claude; volume data processing → Gemini API; boilerplate scripts → Codex; lint/validate/format → Ollama.

### Hybrid generation (V7)

```python
def select_method(params, address):
    mesh = RETOPO_DIR / f"{sanitize(address)}.obj"
    photos = len(params.get("matched_photos", []))
    contributing = params.get("hcd_data", {}).get("contributing") == "Yes"
    if mesh.exists() and photos >= 3 and contributing:
        return "photogrammetric"    # import mesh + apply procedural materials + add parametric details
    return "parametric"             # full procedural generation
```

Photogrammetric path: import retopologized mesh → apply procedural materials → add parametric details for unseen sides (party walls, rear, foundation, gutters). Procedural path: existing `generate_building()` with 30+ `create_*` functions.

### `generate_building.py` (2,931 lines)

Runs inside Blender's Python environment (`bpy`, `bmesh`, `mathutils`). CLI args are parsed after the `--` separator.

**Entry paths:**
- Directory + `--batch-individual` → `generate_batch_individual()` — one `.blend` per building + manifest JSON
- Single file or directory → `load_and_generate()` — all buildings in one scene

**`load_and_generate()`** clears the scene, loads site coordinates from `params/_site_coordinates.json`, then for each param file resolves position (priority: site coords → legacy `geocode.json` → linear spacing fallback) and calls `generate_building()`.

**`generate_building()`** applies defaults then calls ~30 `create_*` functions in sequence:

1. `apply_hcd_guide_defaults()` — scans `hcd_data.building_features` and `statement_of_contribution` for keywords (string course, quoin, voussoir, bargeboard, bracket, shingle, cornice, bay window, storefront, dormer, chimney, turret) and injects structured `decorative_elements` dicts if not already present. Also injects `bay_window` (width computed as `facade_width_m * 0.42`, clamped 1.8-2.6m), `has_storefront`, `storefront`, and `roof_features` entries.
2. `get_era_defaults()` — brick colour, mortar, trim style, window arch type based on `hcd_data.construction_date`:
   - Pre-1889: rich red brick `(0.5, 0.15, 0.08)`, ornate trim, segmental arches
   - 1890-1913: default brick, moderate trim, mixed arches
   - 1914-1930: default brick, restrained trim, flat arches
3. `get_typology_hints()` — party walls (row → both sides, semi-detached → one side), `is_bay_and_gable`, `is_ontario_cottage` (forces 1 floor), institutional (expects 3 floors)

Then the creation sequence:

`create_walls` (hollow box, 0.3m wall thickness, material assigned by `facade_material`: brick→`create_brick_material`, paint/stucco/clapboard→`create_painted_material`) → `cut_windows` (reads `windows_detail` per-floor specs, skips ground floor if storefront, supports bay-based layouts and gable/attic windows, avoids door overlap) → `cut_doors` (`_resolve_doors` collects from 4 sources: `doors_detail`, `ground_floor_arches`, `windows_detail[].entrance`, `storefront.entrance`) → roof (`create_flat_roof` / `create_gable_roof` / `create_cross_gable_roof` / `create_hip_roof`, plus `create_gable_walls` for triangular infill) → `create_porch` → `create_bay_window` (canted 3-sided or box, supports double-height via `floors_spanned`, position: left/center/right) → `create_chimney` → `create_storefront` → `create_string_courses` → `create_quoins` → `create_tower` → `create_bargeboard` (gable roofs only) → `create_cornice_band` → `create_corbelling` → `create_window_lintels` → `create_stained_glass_transoms` → `create_brackets` → `create_ridge_finial` (gable only) → `create_voussoirs` → `create_gable_shingles` (gable only) → `create_dormer` → `create_fascia_boards` → `create_parapet_coping` → `create_hip_rooflet` → `create_gabled_parapet` → `create_turned_posts` → `create_storefront_awning` → `create_foundation` → `create_gutters` → `create_chimney_caps` → `create_porch_lattice` → `create_step_handrails`

Each `create_*` returns a list of Blender objects. After creation, objects with matching name prefixes (`frame_`, `glass_`, `lintel_`) are joined via `join_by_prefix()`, then collected into a per-building collection.

**Multi-volume buildings** (`"volumes": [...]`) take a separate path via `generate_multi_volume()`. Volumes are placed side by side (x_cursor tracks position). Each volume can have its own facade material, floors, roof type. Example: 132 Bellevue Ave fire station (main hall + tower + residential wing).

**Materials:** Procedural shader nodes (brick, wood, stone, glass, shingles, painted). Box-projection mapping via `_add_wall_coords()` uses Generated coords with X+Y as horizontal so bricks tile correctly on front AND side walls. Key material functions:
- `create_brick_material(name, brick_hex, mortar_hex, scale)` — Brick Texture node + bump mapping, mortar from `facade_detail.mortar_colour` (grey→`#8A8A8A`, light→`#C0B8A8`, default `#B0A898`)
- `create_painted_material(name, colour_hex)` — flat painted surface (stucco, clapboard)
- `create_glass_material(name)` — transparent glass for windows
- `get_or_create_material(name, colour_hex, colour_rgb, roughness)` — basic Principled BSDF
- `get_facade_hex(params)` — resolves brick colour from `facade_detail.brick_colour_hex` → `facade_colour` → material inference
- `get_trim_hex(params)` — resolves trim from `facade_detail.trim_colour_hex` → `colour_palette.trim` → era default

**Output per building:** `.blend` file + `.png` render + `.manifest.json` (records param file, collection name, HCD reference, typology, construction date). Batch mode also writes `batch.manifest.json` with counts (completed/skipped/failed).

### Enrichment pipeline detail

Each script reads `params/*.json`, modifies in place, and writes back. The `_meta` dict tracks provenance.

1. **`translate_agent_params.py`** — converts agent flat output to generator structures. Cornice strings → dicts with `height_mm`/`projection_mm`/`colour_hex` (templates: simple, decorative, bracketed, dentil). Bay window counts → structured dicts. Door strings → `doors_detail` arrays.

2. **`enrich_skeletons.py`** — fills missing params from typology and era. Key lookup tables:
   - `BRICK_COLOURS`: red→`#B85A3A`, buff→`#D4B896`, brown→`#7A5C44`, cream→`#E8D8B0`, orange→`#C87040`, grey→`#8A8A8A`
   - `TRIM_COLOURS_BY_ERA`: pre-1889→`#3A2A20` (dark brown), 1904-1913→`#2A2A2A` (near-black), 1931+→`#F0EDE8` (cream)
   - `ROOF_COLOURS`: grey→`#5A5A5A`, slate→`#4A5A5A`, brown→`#6A5040`, red→`#8A3A2A`
   - Skips files where `source != "hcd_plan_only"`.

3. **`enrich_facade_descriptions.py`** — generates prose `facade_detail.composition`, `opening_rhythm`, `heritage_expression`, `heritage_summary` from structured params.

4. **`normalize_params_schema.py`** — converts remaining boolean/string fields to structured dicts expected by the generator.

5. **`patch_params_from_hcd.py`** — merges HCD-derived decorative features (from heritage plan Vol. 2 data) into `decorative_elements`.

6. **`infer_missing_params.py`** — fills 7 final gap keys: `colour_palette`, `dormer`, `eave_overhang_mm`, `ground_floor_arches`, `roof_material`, `volumes`, `hcd_data` stub. Run LAST. Era detection: `hcd_data.construction_date` → `overall_style` keyword (victorian→1889-1903, edwardian→1904-1913, georgian→pre-1889) → `year_built_approx`, defaults to "1889-1903" (Kensington Market default).

7. **`deep_facade_pipeline.py`** — unified CLI for deep facade analysis workflow. Runs after Step 2 photo agents. Subcommands:
   - `merge <files>` — merge deep analysis JSON into param files (adds `deep_facade_analysis` section)
   - `merge-street <key> [--promote]` — find & merge all batch files for a street, optionally promote
   - `promote` — promote `deep_facade_analysis` observations into generator-readable fields (roof_pitch_deg, windows_detail, facade_detail.brick_colour_hex, decorative_elements, etc.)
   - `audit` — show deep analysis coverage by street
   - `report <street>` — per-building detail for a street

   Promotion rules: redistributes floor heights by observed ratios, updates window counts/types per floor, corrects brick colour hex for daylight, adds bargeboard/gable window/eave overhang to roof_detail, populates decorative elements (cornice, voussoirs, string courses, polychromatic brick), adds storefront awnings/grilles, sets foundation height and door step counts. Never overwrites LiDAR heights, lot dimensions, or HCD data.

### Coordinate system

SRID 2952 (NAD83 / Ontario MTM Zone 10, metres). Blender coordinates are local metres from centroid:
```
ORIGIN_X = 312672.94,  ORIGIN_Y = 4834994.86
```
`local(x, y)` in `export_gis_scene.py` subtracts origin. Building rotation computed from nearest road centerline. Legacy `geocode.json` (from `geocode_from_gis.py`) provides `blender_x`/`blender_y`/`rotation_deg` as fallback for buildings without PostGIS footprints.

### PostGIS database

`localhost:5432`, database `kensington`, user `postgres`, password `test123`.

- `building_assessment` — 1,075 buildings with `ADDRESS_FULL`, `ba_street`, `ba_street_number`, `ba_building_type`, `ba_stories`, `ba_facade_material`, LiDAR heights (`height_max_m`, `height_avg_m`), lot dims (`lot_width_ft`, `lot_depth_ft`), HCD typology (`hcd_typology`, `hcd_construction_date`, `hcd_contributing`), + 38 photo analysis columns (added by `writeback_to_db.py --migrate`: `photo_analyzed`, `photo_date`, `photo_agent`, observed colours/materials/condition)
- `opendata.*` — `building_footprints` (addresses + 2D polygons), `massing_3d` (3D polygons with `AVG_HEIGHT`), `road_centerlines`, `sidewalks`
- `field_*` — 13 field survey tables (566 features, 512 georeferenced photos from ArcGIS GeoJSON exports)
- `census_tracts_spatial`, `ruelles_spatial`

### GIS scene

`gis_scene.py` + `gis_scene.json`: 753 footprints, 464 3D massing shapes, 162 road centerlines, 41 alleys, 530 field survey features. All in local metres from centroid. Variants: `smoke_gis_scene.py` (quick validation), `strict_gis_scene.py` (strict error handling).

### Agent coordination scripts

`scripts/agent_control_plane.py`, `agent_delegate_router.py`, `agent_heartbeat_watchdog.py`, `agent_dashboard_server.py`, `agent_ops_state.py` — orchestration layer for multi-agent workflows. The router assigns tasks from `agent_ops/10_backlog/` to agents in `20_active/`, checks task dependencies, and provides lifecycle commands (`route`, `complete`, `close`). The control plane dispatches `__OLLAMA` and `__GEMINI` subtasks to workers. The watchdog monitors heartbeats and reassigns stalled tasks.

**Task runners:** `scripts/ollama_task_runner.py` and `scripts/gemini_task_runner.py` poll for pending subtask cards and execute them automatically via CLI. Gemini uses `-m gemini-2.5-flash` to bypass the local Gemma router. Ollama uses `qwen2.5-coder:7b` by default.

**Launcher prompts:** `docs/CODEX_LAUNCHER_PROMPT.md`, `docs/GEMINI_LAUNCHER_PROMPT.md`, `docs/CLAUDE_LAUNCHER_PROMPT.md`, `docs/OLLAMA_LAUNCHER_PROMPT.md` — paste into the respective CLI to start an agent on assigned tasks.

**Full stack launch:**
```powershell
.\scripts\start_agent_ops.ps1 -StartControlLoop -StartOllamaRunner -StartGeminiRunner -OllamaAutoComplete
```

### Scenario framework

Each scenario is a JSON overlay on baseline params in `scenarios/<name>/interventions.json`:
```json
{"scenario_id": "gentle_density", "interventions": [
  {"address": "22 Lippincott St", "type": "add_floor", "params_override": {"floors": 3}},
  {"address": "LANEWAY_BEHIND_22_Lippincott", "type": "new_build", "params": {...}}
]}
```
Intervention types: `add_floor`, `new_build`, `convert_ground`, `facade_renovation`, `demolish`, `green_roof`, `add_patio`, `bike_infra`, `tree_planting`, `pedestrianize`, `heritage_restore`, `signage_update`.

### Web planning platform

CesiumJS + Potree + Gaussian splats, hosted on Vercel. Features: building inspector (click → param card + photo), scenario A/B comparison (split slider), shadow analysis (time slider + season), heritage overlay (era/typology filters), timeline scrubber (1858–2036), urban metrics dashboard (density, FSI, canopy, walkability), intervention proposer, street-level view. Stack: CesiumJS, Potree, SuperSplat/gsplat.js, Svelte or Vanilla TS, D3.js, Vercel.

```bash
cd web && npm run build
# Deploy via Vercel MCP or: vercel --prod
```

## Parameter JSON Schema

Each building is a JSON file in `params/` (filename: `22_Lippincott_St.json`, spaces → `_`). Files starting with `_` are metadata, not building params. Files with `"skipped": true` are non-building photos.

**Top-level:** `building_name`, `floors`, `floor_heights_m` (array per floor), `total_height_m`, `facade_width_m`, `facade_depth_m`, `roof_type` (flat/gable/cross-gable/hip/mansard), `roof_pitch_deg`, `roof_features` (array: dormers/chimney/tower), `facade_material`, `facade_colour`, `windows_per_floor` (array per floor), `window_type`, `window_width_m`, `window_height_m`, `door_count`, `has_storefront`, `condition` (good/fair/poor), `party_wall_left`, `party_wall_right`, `roof_colour`.

**Nested sections:**
- `site` — `lon`, `lat`, `street`, `street_number`, `setback_m`, `lot_area_sqm`, `footprint_sqm`, `lot_coverage_pct`, `lots_sharing_footprint`
- `hcd_data` — `typology` (e.g., "House-form, Semi-detached, Bay-and-Gable"), `construction_date` (e.g., "1904-1913"), `architectural_style`, `construction_decade`, `sub_area`, `contributing` (Yes/No), `hcd_plan_index`, `statement_of_contribution`, `building_features` (array: decorative_brick, original_windows, etc.), `heritage_register`, `protection_level` (1-5)
- `context` — `building_type`, `general_use`, `land_use`, `commercial_use`, `business_name`, `business_category`, `zoning`, `is_vacant`, `street_character`, `morphological_zone`, `development_phase`
- `assessment` — `condition_rating` (1-5), `condition_issues`, `structural_concern`, `risk_score`, `signage`, `street_presence`
- `city_data` — `height_max_m`, `height_avg_m`, `footprint_sqm`, `gfa_sqm`, `fsi`, `lot_width_ft`, `lot_depth_ft`, `dwelling_units`, `residential_floors`, `heritage_feature_count`
- `_meta` — `address`, `source` ("postgis_export"), `translated` (bool), `translations_applied` (array), `enriched` (bool), `enrichment_source`, `gaps_filled` (bool), `inferences_applied` (array), `fusion_applied` (array: "depth", "segmentation", "signage"), `has_photogrammetric_mesh` (bool), `photogrammetric_mesh_path`, `generation_method` ("parametric"/"photogrammetric"), `element_sources` (dict: {"cornice": "scan", "windows": "library", "walls": "procedural"})
- `decorative_elements` — `decorative_brickwork` (`{present}`), `bargeboard` (`{colour_hex, style, width_mm}`), `bay_window_shape` (canted/box/oriel), `bay_window_storeys`, `string_courses` (`{present, width_mm, projection_mm, colour_hex}`), `quoins` (`{present, strip_width_mm, projection_mm, colour_hex}`), `stone_voussoirs` (`{present, colour_hex}`), `stone_lintels` (`{present, colour_hex}`), `cornice` (`{present, projection_mm, height_mm, colour_hex}`), `ornamental_shingles` (`{present, colour_hex, exposure_mm}`), `gable_brackets` (`{type, count, projection_mm, height_mm, colour_hex}`)
- `doors_detail` — array of `{id, type, position (left/center/right), width_m, height_m, transom: {present, height_m, type (glazed)}, colour, colour_hex, material, is_glass, awning}`
- `facade_detail` — `brick_colour_hex`, `bond_pattern` (running bond), `mortar_colour`, `mortar_joint_width_mm`, `trim_colour_hex`, `composition` (prose), `opening_rhythm` (prose), `heritage_expression`, `heritage_summary`
- `windows_detail` — array per floor: `{floor ("Ground floor"/"Second floor"/etc.), windows: [{count, type, width_m, height_m, sill_height_m, frame_colour, glazing (1-over-1/2-over-2/etc.)}], bay_window: {type, width_m, projection_m}, entrance: {width_m, height_m, position, type}}`
- `bay_window` — top-level: `{present, type, floors (array of floor indices), width_m, projection_m, floors_spanned}`
- `storefront` — `{type, width_m, height_m, entrance: {width_m, height_m, position, type, material}}`
- `roof_detail` — `eave_overhang_mm`, `gable_window: {present, width_m, height_m, type, arch_type}`
- `colour_palette` — `{facade, trim, roof, accent}` hex colours (inferred by `infer_missing_params.py`)
- `volumes` — array of `{id, width_m, depth_m, floor_heights_m, total_height_m, facade_colour, facade_material, roof_type}` for multi-volume buildings (triggers `generate_multi_volume()`)
- `photo_observations` — agent vision results: `facade_colour_observed`, `facade_material_observed`, `facade_condition_notes`, `condition`, `windows_per_floor`, `window_type`, `window_width_m`, `window_height_m`, `door_count`, `chimneys`, `porch_present`, `porch_type`, `photo` (filename), `photo_datetime`
- `deep_facade_analysis` — 3D-reconstruction-grade observations from AI photo analysis: `source_photo`, `storeys_observed`, `has_half_storey_gable`, `floor_height_ratios` (array), `facade_material_observed`, `brick_colour_hex` (daylight-corrected), `brick_bond_observed`, `mortar_colour`, `polychromatic_brick`, `windows_detail` (per-floor: count, type, arch, frame_colour, width_ratio), `doors_observed`, `roof_type_observed`, `roof_pitch_deg`, `bargeboard` (`{present, style, colour_hex}`), `gable_window` (`{present, type}`), `bay_window_observed`, `storefront_observed` (`{width_pct, signage_text, awning, security_grille}`), `decorative_elements_observed`, `colour_palette_observed` (`{facade, trim, roof, accent}` hex), `condition_observed`, `depth_notes` (`{setback_m_est, foundation_height_m_est, eave_overhang_mm_est, step_count}`)
- `ground_floor_arches` — `{left_arch, centre_arch, right_arch}` each with `{function (entrance/window), total_width_m, total_height_m, type (arched/segmental), door: {width_m, height_m, colour}}`

## Photo Analysis Rules (docs/AGENT_PROMPT.md)

AI agents (Claude Code / Codex / Gemini CLI) analyze March 2026 field photos and merge visual observations into params. Photo index CSV at `PHOTOS KENSINGTON/csv/photo_address_index.csv` (1,928 photos). 8 batches of 50 buildings each in `batches/batch_001.json`–`batch_008.json`, dispatched to parallel Gemini/Codex agents.

- **NEVER overwrite:** `total_height_m`, `facade_width_m`, `facade_depth_m`, `site.*`, `city_data.*`, `hcd_data.*`
- **ALWAYS update:** `facade_colour`, `windows_per_floor`, `window_type`, `window_arrangement`, `door_count`, `door_type`, `condition`, `roof_features`, `chimneys`, `porch_present`, `porch_type`, `balconies`, `balcony_type`, `cornice`, `bay_windows`, `ground_floor_arches`
- **Update only if clearly different from DB:** `facade_material`, `roof_type`, `has_storefront`, `floors`
- Results go into `photo_observations` nested dict
- Multiple photos per address: use the best facade photo, produce one update per unique address
- Non-building photos (murals, lanes, signs) → `"skipped": true` with `skip_reason`

**Field photos** (`PHOTOS KENSINGTON/`) contain 1,928 geotagged March 2026 field photos — the primary visual reference for all buildings. The HCD PDF is at `params/96c1-city-planning-kensington-market-hcd-vol-2.pdf`.

## Testing

Unit tests for enrichment pipeline scripts live in `tests/` and run with pytest:

```bash
python -m pytest tests/                          # all tests
python -m pytest tests/test_enrich_skeletons.py  # single module
```

70 test files, 1,688 tests. Covers: enrichment pipeline (enrich_skeletons, facade_descriptions, normalize_params, patch_hcd, infer_missing, translate_agent, doors_and_foundations, roof_and_heritage, window_details), colour palettes (rebuild, diversify), photo matching, storefronts, porches, setbacks, depth notes, adjacency graph, streetscape rhythm, generator contracts, generation defaults, QA report, Megascans mapping, deep facade pipeline, SSIM comparison, planning scripts, reconstruct pipeline, training pipeline, urban analysis, sprint progress, Blender asset export (FBX, LODs, collision, Datasmith, Unity), and 8+ Unreal urban-element export/import scripts. Each test creates temp param files and verifies output, idempotency, and skip-file handling.

For visual/integration validation:
1. Run scripts on a narrow sample first (`--address "22 Lippincott St"`)
2. Regenerate a known address and compare against field photos in `PHOTOS KENSINGTON/`
3. Visual inspection of rendered output (`test_render.png`)
4. `--dry-run` flag shows planned batch operations without executing

## Dependencies

- **Blender 5.1 CLI** (Blender 3.x+ APIs are the baseline for `bpy`, `bmesh`, `mathutils`)
- **Python 3.10+**, **pytest**
- **psycopg2-binary** — all PostGIS access scripts
- **PostgreSQL 18** with PostGIS
- **V7 additions:** Depth Anything v2, SAM2, YOLOv11, DSINE, PaddleOCR, LightGlue+SuperPoint (Stage 1); COLMAP, OpenMVS, DUSt3R/MASt3R, Instant Meshes, gsplat (Stage 2); RealESRGAN, Intrinsic Anything (Stage 5); py3dtiles, PotreeConverter, cjio (Stage 8); sentry-sdk (Stage 10)
- **Infrastructure:** Docker (n8n + Cloudflare tunnel), Jarvislabs CLI (`jl`) for cloud GPU ($1.49/hr A100), Vercel (free tier)

## Style

- 4-space indent, `snake_case` functions/files, `UPPER_SNAKE_CASE` constants
- `pathlib.Path` for paths, `json` with `indent=2` for output
- All file I/O: `encoding="utf-8"`
- Use `(value or "").lower()` not `.get("key", "").lower()` — handles explicit `None`
- Imperative commit messages scoped to one pipeline stage
- PRs: include affected addresses, dependencies, and screenshots for geometry/material changes
- Platform: Linux (primary dev), Windows (Blender rendering)
