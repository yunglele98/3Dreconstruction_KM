# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Script-first Blender pipeline that generates parametric 3D models of ~1,241 historic Kensington Market buildings (Toronto). Converts heritage building data (PostGIS measurements + HCD typology + AI vision photo analysis) into JSON parameter files, then generates detailed Blender geometry with procedural materials.

Study area: Dundas St W (north) / Bathurst St (east) / College St (south) / Spadina Ave (west). Only the market-facing side of perimeter streets is in scope.

## Commands

```bash
# === Step 1: Export building params from PostGIS ===
python scripts/export_db_params.py [--overwrite] [--street "Augusta Ave"]
python scripts/export_db_params.py --address "22 Lippincott St"

# === Step 2: Photo analysis (AI agents analyze field photos) ===
python scripts/prepare_batches.py [--batch-size 50]
# Then run agents:  claude 'Follow docs/AGENT_PROMPT.md to process batches/batch_001.json'

# === Step 2b: Deep facade analysis (3D-reconstruction-grade detail) ===
# AI agents read each photo and extract per-floor windows, roof pitch, brick hex,
# decorative elements, depth measurements, etc. Output: docs/<street>_deep_batch<N>.json
# Then merge + promote into param files:
python scripts/deep_facade_pipeline.py merge-street baldwin --promote
python scripts/deep_facade_pipeline.py merge-street kensington --promote
python scripts/deep_facade_pipeline.py audit                    # coverage by street
python scripts/deep_facade_pipeline.py report baldwin           # per-building detail

# === Step 3: Enrichment pipeline (run in order, each is idempotent) ===
python scripts/translate_agent_params.py      # flat agent output → structured dicts
python scripts/enrich_skeletons.py            # typology/era-driven defaults
python scripts/enrich_facade_descriptions.py  # prose facade descriptions
python scripts/normalize_params_schema.py     # boolean→dict cleanup
python scripts/patch_params_from_hcd.py       # HCD decorative feature merge
python scripts/infer_missing_params.py        # fill remaining gaps (colour, roof, volumes)

# === Step 4: GIS site model ===
python scripts/export_gis_scene.py            # full (with 3D massing)
python scripts/export_gis_scene.py --no-massing

# === Step 5: Blender generation ===
blender --python gis_scene.py                                              # load site model
blender --background --python generate_building.py -- --params params/22_Lippincott_St.json
blender --background --python generate_building.py -- --params params/     # all buildings
blender --background --python generate_building.py -- --params params/ --batch-individual --render --output-dir outputs/
blender --background --python generate_building.py -- --params params/ --batch-individual --skip-existing
blender --background --python generate_building.py -- --params params/ --batch-individual --match "Augusta" --limit 10
blender --background --python generate_building.py -- --params params/ --batch-individual --dry-run

# === DB writeback & field survey ===
python scripts/writeback_to_db.py --migrate   # first time: adds columns
python scripts/writeback_to_db.py             # writes all analyzed params
python scripts/import_field_survey.py
python scripts/link_attachments.py

# === QA & Audit ===
python scripts/qa_params_gate.py              # pre-generation quality gate (checks required fields)
python scripts/audit_params_quality.py        # comprehensive param quality report
python scripts/audit_structural_consistency.py # check floor/height/volume consistency
python scripts/audit_storefront_conflicts.py  # detect storefront vs window conflicts
python scripts/fix_params_quality.py          # auto-fix common param issues
python scripts/fix_structural_consistency.py  # auto-fix height/floor mismatches
python scripts/fix_height_inflation.py        # correct inflated height values
python scripts/qa_autofix_height.py           # targeted height fixes
python scripts/qa_autofix_medium_low.py       # fix medium-low severity issues

# === Data Enrichment (post-agent, run in order) ===
python scripts/rebuild_colour_palettes.py     # priority-chain colour resolution (1,241 palettes)
python scripts/diversify_colour_palettes.py   # era/condition/street HSV jitter (949 unique hexes)
python scripts/match_photos_to_params.py      # 9-strategy photo matching (98.6% coverage)
python scripts/enrich_storefronts_advanced.py  # awning/signage/grille inference (537 enriched)
python scripts/enrich_porch_dimensions.py     # era-based columns/railing/steps (87 enriched)
python scripts/infer_setbacks.py              # street-type setback rules (441 inferred)
python scripts/consolidate_depth_notes.py     # 5-field depth assembly (1,241 complete)
python scripts/build_adjacency_graph.py       # neighbour detection, 287 blocks
python scripts/analyze_streetscape_rhythm.py  # heritage quality scoring per street

# === Generator Contract Audit ===
python scripts/audit_generator_contracts.py   # parse 66 create_* functions, validate params
python scripts/fix_generator_contract_gaps.py # safe defaults for missing fields

# === Asset Export Pipeline (requires Blender) ===
blender --background <blend> --python scripts/export_building_fbx.py -- --address "22 Lippincott St"
blender --background --python scripts/batch_export_unreal.py -- --source-dir outputs/full/ [--limit 10]
blender --background <blend> --python scripts/generate_lods.py -- --address "22 Lippincott St"
blender --background <blend> --python scripts/generate_collision_mesh.py -- --address "22 Lippincott St"
python scripts/optimize_meshes.py --source-dir outputs/exports/          # pymeshlab, no Blender
python scripts/build_unreal_datasmith.py                                  # Datasmith XML scene
python scripts/build_unity_prefab_manifest.py                             # Unity JSON manifest
python scripts/build_texture_atlas.py                                     # 4K atlas from param materials
python scripts/map_megascans_materials.py                                 # LAB colour → Megascans match
python scripts/validate_export_pipeline.py                                # trimesh per-asset checks

# === Deliverable Export ===
python scripts/export_building_summary_csv.py # CSV summary of all buildings
python scripts/export_geojson.py              # GeoJSON export
python scripts/export_street_profile_json.py  # street profiles JSON
python scripts/generate_qa_report.py          # HTML dashboard + JSON report

# === Utility ===
python scripts/geocode_from_gis.py            # legacy: geocode from QGIS GeoJSON exports → geocode.json
python scripts/fingerprint_params.py          # MD5 change detection for regen batches
python scripts/build_regen_batches.py         # priority-ordered batch files for Blender regen
```

## Architecture

### Data flow

```
PostGIS (building_assessment + opendata.*)
  → scripts/export_db_params.py → params/*.json (skeletons with real measurements)
  → scripts/prepare_batches.py → batches/*.json (8 batches of 50)
    → AI agents (Claude/Codex/Gemini) → merge visual details into params/*.json
  → enrichment pipeline (6 scripts in order) → params/*.json (final)
  → scripts/export_gis_scene.py → gis_scene.py + gis_scene.json (site model)
  → generate_building.py (inside Blender) → .blend + .png + .manifest.json
```

### Working data directories

- `params/` — 2,064 JSON files (~1,241 active building params + ~820 skipped + 3 metadata files prefixed with `_`: `_site_coordinates.json`, `_analysis_summary.json`, `_address_aliases.auto.json`). Skipped entries have `"skipped": true` with `skip_reason`.
- `batches/` — 8 photo analysis batch JSONs (50 buildings each) for Gemini/Codex agents.
- `scripts/` — 291 Python scripts. Some enrichment scripts define `_atomic_write_json()` (temp file + `os.replace`) to prevent corruption on concurrent writes; most write JSON directly via `json.dump()`. Major categories:
  - **Unreal urban elements** (~118 scripts): `export_unreal_*.py` (20) → extract GIS/field data per element type; `build_unreal_*.py` (28) → Unreal import bundles, material instances, decal placements; `create_*_masters_free.py` (19) → free Megascans/Quixel master meshes; `create_*_hero_variants.py` (11) → hero variant meshes; `build_*_lods_billboards.py` (11) → LOD chains + billboard impostors; `build_*_material_presets.py` (12) → material preset JSON; `refine_*_instances.py` (11) → instance placement refinement; `build_*_photo_references.py` (6) → photo reference sheets. Element types: trees, signs, poles, street furniture, alleys, alley garages, bike racks, ground, intersections, parking, fences/gates, transit stops, waste, vertical hardscape, utilities, accessibility, service backlots, park furniture, graffiti, printables, roadmarks.
  - **Enrichment** (8): `enrich_skeletons.py`, `enrich_facade_descriptions.py`, `enrich_storefronts_advanced.py`, `enrich_porch_dimensions.py`, `enrich_window_details.py`, `enrich_doors_and_foundations.py`, `enrich_roof_and_heritage.py`, `enrich_dundas_sector.py`
  - **QA/audit** (16): `audit_*.py` (10) — params quality, structural consistency, storefront conflicts, generator contracts, decorative completeness, deep facade coverage, photo analysis depth, render manifest coverage, address normalization, unmapped materials; `qa_*.py` (6) — params gate, autofix height, autofix medium-low, photo fixes/verify, fix default dims
  - **Fixes** (12): `fix_*.py` — height inflation, structural consistency, params quality, generator contract gaps, bay windows, concrete colors, window/roof placements, handoff findings, etc.
  - **Export** (9 non-Unreal): `export_db_params.py`, `export_gis_scene.py`, `export_building_fbx.py`, `export_gltf.py`, `export_building_summary_csv.py`, `export_geojson.py`, `export_street_profile_json.py`, `export_full_scene.py`, `export_tree_photo_targets.py`
  - **Agent coordination** (5 + 2 runners): `agent_control_plane.py`, `agent_delegate_router.py`, `agent_heartbeat_watchdog.py`, `agent_dashboard_server.py`, `agent_ops_state.py`, `ollama_task_runner.py`, `gemini_task_runner.py`
  - **Deep facade** (7): `deep_facade_pipeline.py` (unified CLI), `batch_deep_facade_*.py` (4: analysis, augusta, backfill, oxford), `merge_deep_facade_details.py`, `promote_deep_to_generator.py`
  - **Colour/material** (7): `rebuild_colour_palettes.py`, `diversify_colour_palettes.py`, `map_megascans_materials.py`, `build_texture_atlas.py`, `backfill_material_sidecars.py`, `backfill_pbr_utility_maps.py`, `extract_facade_textures.py`
  - **Remaining** (~30): spatial analysis (`build_adjacency_graph.py`, `analyze_streetscape_rhythm.py`, `infer_setbacks.py`), DB access (`writeback_to_db.py`, `import_field_survey.py`, `db_config.py`, `check_db_health.py`), batch generation (`build_regen_batches.py`, `fingerprint_params.py`), Blender utilities (`batch_export_unreal.py`, `generate_lods.py`, `generate_collision_mesh.py`, `optimize_meshes.py`, `render_turntable.py`), schema transforms (`translate_agent_params.py`, `normalize_params_schema.py`, `patch_params_from_hcd.py`, `infer_missing_params.py`, `consolidate_depth_notes.py`), validation (`validate_export_pipeline.py`, `validate_all_params.py`, `validate_string_courses.py`), comparison (`compare_renders.py`, `ssim_compare.py`), demos, geocoding, and one-off fixes
- `docs/` — 53 files: agent prompts (`AGENT_PROMPT.md`, launcher prompts per agent), workflow guides, batch prompts, factory audit docs, and deployment notes.
- `outputs/` — rendered Blender files and QA artifacts: `demos/` (pilot + block scenes), `gis_scene.json` (GIS site data), plus various QA autofix/revision JSON logs.
- `PHOTOS KENSINGTON/` — 1,928 geotagged field photos (March 2026) + `csv/photo_address_index.csv` master index (columns: `filename`, `address_or_location`, `source`). Has its own `CLAUDE.md` describing photo review workflows.
- `generator_modules/` — extracted modules from `generate_building.py` (see below).
- `agent_ops/` — multi-agent coordination system for 5-10 parallel agents (Claude/Codex/Gemini/Ollama). Kanban-style workflow: `00_intake/` → `10_backlog/` → `20_active/<agent>/` → `30_handoffs/` → `40_reviews/` → `60_releases/` → `90_archive/`. File-based locking in `coordination/locks/`. See `agent_ops/README.md` for full workflow.
- `tests/` — 62 test files + `conftest.py` (see Testing section).
- `AGENTS.md` — Codex-oriented variant of CLAUDE.md (stale, lower counts). Kept for Codex agent compatibility.
- `run_fbx_batch.ps1` — PowerShell batch FBX export launcher.

### `generate_building.py` (~9,800 lines)

Runs inside Blender's Python environment (`bpy`, `bmesh`, `mathutils`). CLI args are parsed after the `--` separator.

**`generator_modules/`** — beginning of a decomposition of the monolith. Currently contains `colours.py` (pure Python: `hex_to_rgb`, `COLOUR_NAME_MAP`, era defaults). Planned modules: `materials.py` (bpy-dependent), `roofs.py`, `walls.py`, `decorative.py`, `porch.py`, `storefront.py`. Import via `from generator_modules.colours import *`.

**Entry paths:**
- Directory + `--batch-individual` → `generate_batch_individual()` — one `.blend` per building + manifest JSON
- Single file or directory → `load_and_generate()` — all buildings in one scene

**`load_and_generate()`** clears the scene, loads site coordinates from `params/_site_coordinates.json`, then for each param file resolves position (priority: site coords → legacy `geocode.json` → linear spacing fallback) and calls `generate_building()`.

**`generate_building()`** applies defaults then calls 28 `create_*` functions in sequence (66 total `create_*` defs exist — 20 newer ones like `create_window_shutters`, `create_balconies`, `create_pilasters`, `create_sign_band`, `create_ground_floor_arches`, etc. are defined but not yet wired into the main call chain):

1. `apply_hcd_guide_defaults()` — scans `hcd_data.building_features` and `statement_of_contribution` for keywords (string course, quoin, voussoir, bargeboard, bracket, shingle, cornice, bay window, storefront, dormer, chimney, turret) and injects structured `decorative_elements` dicts if not already present. Also injects `bay_window` (width computed as `facade_width_m * 0.42`, clamped 1.8-2.6m), `has_storefront`, `storefront`, and `roof_features` entries.
2. `get_era_defaults()` — brick colour, mortar, trim style, window arch type based on `hcd_data.construction_date`:
   - Pre-1889: rich red brick `(0.5, 0.15, 0.08)`, ornate trim, segmental arches
   - 1890-1913: default brick, moderate trim, mixed arches
   - 1914-1930: default brick, restrained trim, flat arches
3. `get_typology_hints()` — party walls (row → both sides, semi-detached → one side), `is_bay_and_gable`, `is_ontario_cottage` (forces 1 floor), institutional (expects 3 floors)

Then the creation sequence:

`create_walls` (1, hollow box, 0.3m wall thickness) → `cut_windows` (2) → `cut_doors` (3) → roof (4: `create_flat_roof`/`create_gable_roof`/`create_cross_gable_roof`/`create_hip_roof` + `create_gable_walls`) → `create_porch` (5) → `create_bay_window` (6) → `create_chimney` (7) → `create_storefront` (8) → `create_string_courses` (9) → `create_quoins` (10) → `create_tower` (11) → `create_bargeboard` (12, gable only) → `create_cornice_band` (13) → `create_corbelling` (13b) → `create_window_lintels` (14) → `create_stained_glass_transoms` (14b) → `create_brackets` (15) → `create_ridge_finial` (16, gable only) → `create_voussoirs` (17) → `create_gable_shingles` (18, gable only) → `create_dormer` (19) → `create_fascia_boards` (20) → `create_parapet_coping` (21) → `create_hip_rooflet` (21a) → `create_gabled_parapet` (21b) → `create_turned_posts` (22) → `create_storefront_awning` (23) → `create_foundation` (24) → `create_gutters` (25) → `create_chimney_caps` (26) → `create_porch_lattice` (27) → `create_step_handrails` (28)

Each `create_*` returns a list of Blender objects. After creation, objects are joined by name prefix via `join_by_prefix()` (~37 prefixes: `frame_`, `glass_`, `muntin_`, `baluster_`, `lintel_`, `sill_`, `bracket_`, `voussoir_`, `shingle_`, `fascia_`, `soffit_`, `parapet_`, `coping_`, `gutter_`, `downspout_`, `quoin_`, `string_course_`, `cornice_`, `transom_`, etc.), then collected into a per-building collection.

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
   - Only processes files where `source` is `"hcd_plan_only"` or `"hcd_plan_skeleton"` — skips all others.

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

Configured in `scripts/db_config.py` via env vars with fallbacks: `PGHOST` (localhost), `PGPORT` (5432), `PGDATABASE` (kensington), `PGUSER` (postgres), `PGPASSWORD` (test123).

- `building_assessment` — 1,075 buildings with `ADDRESS_FULL`, `ba_street`, `ba_street_number`, `ba_building_type`, `ba_stories`, `ba_facade_material`, LiDAR heights (`height_max_m`, `height_avg_m`), lot dims (`lot_width_ft`, `lot_depth_ft`), HCD typology (`hcd_typology`, `hcd_construction_date`, `hcd_contributing`), + 38 photo analysis columns (added by `writeback_to_db.py --migrate`: `photo_analyzed`, `photo_date`, `photo_agent`, observed colours/materials/condition)
- `opendata.*` — `building_footprints` (addresses + 2D polygons), `massing_3d` (3D polygons with `AVG_HEIGHT`), `road_centerlines`, `sidewalks`
- `field_*` — 13 field survey tables (566 features, 512 georeferenced photos from ArcGIS GeoJSON exports)
- `census_tracts_spatial`, `ruelles_spatial`

### GIS scene

`gis_scene.py` + `gis_scene.json`: 753 footprints, 464 3D massing shapes, 162 road centerlines, 41 alleys, 530 field survey features. All in local metres from centroid. Variant: `smoke_gis_scene.py` (quick validation).

### Agent coordination scripts

`scripts/agent_control_plane.py`, `agent_delegate_router.py`, `agent_heartbeat_watchdog.py`, `agent_dashboard_server.py`, `agent_ops_state.py` — orchestration layer for multi-agent workflows. The router assigns tasks from `agent_ops/10_backlog/` to agents in `20_active/`, checks task dependencies, and provides lifecycle commands (`route`, `complete`, `close`). The control plane dispatches `__OLLAMA` and `__GEMINI` subtasks to workers. The watchdog monitors heartbeats and reassigns stalled tasks.

**Task runners:** `scripts/ollama_task_runner.py` and `scripts/gemini_task_runner.py` poll for pending subtask cards and execute them automatically via CLI. Gemini uses `-m gemini-2.5-flash` to bypass the local Gemma router. Ollama uses `qwen2.5-coder:7b` by default.

**Launcher prompts:** `docs/CODEX_LAUNCHER_PROMPT.md`, `docs/GEMINI_LAUNCHER_PROMPT.md`, `docs/CLAUDE_LAUNCHER_PROMPT.md`, `docs/OLLAMA_LAUNCHER_PROMPT.md` — paste into the respective CLI to start an agent on assigned tasks.

**Full stack launch:**
```powershell
.\scripts\start_agent_ops.ps1 -StartControlLoop -StartOllamaRunner -StartGeminiRunner -OllamaAutoComplete
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
- `_meta` — `address`, `source` ("postgis_export"), `translated` (bool), `translations_applied` (array), `enriched` (bool), `enrichment_source`, `gaps_filled` (bool), `inferences_applied` (array: roof_material, colour_palette, volumes, roof_detail)
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

AI agents (Claude Code / Codex / Gemini CLI) analyze March 2026 field photos and merge visual observations into params. Photo index CSV at `PHOTOS KENSINGTON/csv/photo_address_index.csv` (1,928 photos). 8 batches of 50 buildings each in `batches/batch_NNN.json`, dispatched to parallel Gemini/Codex agents.

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
python -m pytest tests/test_enrich_skeletons.py -k "test_brick_colour"  # single test
python -m pytest tests/ -x                       # stop on first failure
```

~63 test files cover: enrichment pipeline (enrich_skeletons, facade_descriptions, normalize_params, patch_hcd, infer_missing, translate_agent), colour palettes (rebuild, diversify), photo matching, storefronts, porches, setbacks, depth notes, adjacency graph, streetscape rhythm, generator contracts, QA report, Megascans mapping, Blender asset export (FBX, LODs, collision, Datasmith, Unity), and 8 Unreal urban-element export/import scripts. Each test creates temp param files and verifies output, idempotency, and skip-file handling.

**`conftest.py` workaround:** A ghost `scripts/__init__.py` (mount-sync artifact) makes Python treat `scripts/` as a package, breaking bare imports. The conftest pre-registers every `scripts/*.py` as a top-level module in `sys.modules`. Scripts that need `bpy` will fail to import and are silently skipped — their import errors surface at test time instead.

For visual/integration validation:
1. Run scripts on a narrow sample first (`--address "22 Lippincott St"`)
2. Regenerate a known address and compare against field photos in `PHOTOS KENSINGTON/`
3. Visual inspection of rendered output (`test_render.png`)
4. `--dry-run` flag shows planned batch operations without executing

## Dependencies

- **Blender 3.x+** (`bpy`, `bmesh`, `mathutils`) — generate_building.py and gis_scene.py run inside Blender
- **Python 3.10+**
- **psycopg2-binary** — all PostGIS access scripts (via `scripts/db_config.py`)
- **PostgreSQL 18** with PostGIS
- **pytest** — test runner
- **Optional:** `pymeshlab` (mesh optimization), `trimesh` (export validation), `Pillow` (texture atlas, PBR maps, decal extraction), `numpy` (facade textures, photogrammetry comparison, decals)

## Style

- 4-space indent, `snake_case` functions/files, `UPPER_SNAKE_CASE` constants
- `pathlib.Path` for paths, `json` with `indent=2` for output
- All file I/O: `encoding="utf-8"`
- Use `(value or "").lower()` not `.get("key", "").lower()` — handles explicit `None`
- Imperative commit messages scoped to one pipeline stage
- PRs: include affected addresses, dependencies, and screenshots for geometry/material changes
