# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

## Project Overview

Script-first Blender pipeline that generates parametric 3D models of ~1,064 historic Kensington Market buildings (Toronto). Converts heritage building data (PostGIS measurements + HCD typology + AI vision photo analysis) into JSON parameter files, then generates detailed Blender geometry with procedural materials.

Study area: Dundas St W (north) / Bathurst St (east) / College St (south) / Spadina Ave (west). Only the market-facing side of perimeter streets is in scope.

## Commands

```bash
# === Current orchestration / status ===
python scripts/run_blender_buildings_workflows.py route
python scripts/run_blender_buildings_workflows.py control-plane
python scripts/run_blender_buildings_workflows.py watchdog --mode once
python scripts/run_blender_buildings_workflows.py dashboard --once-json

# === DB revision / QA pipeline ===
pwsh -File scripts/run_full_db_revision_pipeline.ps1
pwsh -File scripts/run_full_db_revision_pipeline.ps1 -DryRun -SkipVisual

# === Step 1: Export building params from PostGIS ===
python scripts/export_db_params.py [--overwrite] [--street "Augusta Ave"]
python scripts/export_db_params.py --address "22 Lippincott St"

# === Step 2: Photo analysis (AI agents analyze field photos) ===
python scripts/prepare_batches.py [--batch-size 50]
# Then run agents:  Codex 'Follow docs/AGENT_PROMPT.md to process batches/batch_001.json'

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

# === Deep facade analysis (3D-reconstruction-grade) ===
python scripts/deep_facade_pipeline.py merge-street baldwin --promote
python scripts/deep_facade_pipeline.py audit
python scripts/deep_facade_pipeline.py report baldwin

# === Utility ===
python scripts/geocode_from_gis.py            # legacy: geocode from QGIS GeoJSON exports → archive/geocode.json
python scripts/check_positions.py             # verify placement/alignment in Blender outputs
python scripts/check_materials.py             # inspect generated material assignments
python -m pytest tests/ -q
```

## Architecture

### Data flow

```
PostGIS (building_assessment + opendata.*)
  → scripts/export_db_params.py → params/*.json (skeletons with real measurements)
  → scripts/prepare_batches.py → batches/*.json (1,867 photos, 38 batches of 50)
    → AI agents (Codex/Codex/Gemini) → merge visual details into params/*.json
  → enrichment pipeline (6 scripts in order) → params/*.json (final)
  → scripts/export_gis_scene.py → gis_scene.py + gis_scene.json (site model)
  → generate_building.py (inside Blender) → .blend + .png + .manifest.json
```

### Working data directories

- `params/` — 2,048 JSON files (1,064 building params from DB export + agent-created + metadata + skipped). Files prefixed with `_` are metadata (`_site_coordinates.json`, `_analysis_summary.json`). Skipped non-building entries have `"skipped": true`.
- `batches/` — 38 batch JSONs + 38 result JSONs. All batches processed (complete).
- `scripts/` — 300+ Python scripts spanning the original param/generation pipeline plus QA, deep-facade, agent-ops, and Unreal/Unity export tooling.
- `tests/` — formal pytest suite with 62 test files covering enrichment, generator helpers, QA, export pipelines, deep facade tooling, and several pure-Python Blender-adjacent utilities.
- `generator_modules/` — shared helper modules factored out of the monolithic generator (currently includes colour utilities).
- `agent_ops/` — multi-agent backlog, active task cards, ownership locks, handoffs, and review artifacts used by the workflow runner.
- `docs/` — agent prompts, runbooks, workflow docs, and design notes (`docs/AGENT_PROMPT.md`, `docs/AGENT_WORKFLOW_GUIDE.md`, `docs/PIPELINE_RUNBOOK.md`, `AGENTS.md`, `agent_prompts_description_cleanup.md`).
- `outputs/` — rendered Blender files: `full/` (929 buildings), `batch_50/`, `batch_pilot/`, `demos/` (pilot + block scenes), `single/` (one-off renders). Also `gis_scene.json` (GIS site data).
- `PHOTOS KENSINGTON/` — 1,867 geotagged field photos (March 2026) + `csv/photo_address_index.csv` master index (columns: `filename`, `address_or_location`, `source`). Has its own `AGENTS.md` describing photo review workflows.
- `archive/` — retired data and scripts: `legacy_analysis/`, `legacy_batches/`, `reference_photos/`, `params_pilot/`, `params_demo/`, `params_block_demo/`, `params_batch_test/`, `params_batch_mixed/`, `skip_originals/`, `geocode.json`, `pilot_buildings.json`, test output runs, legacy vision scripts.

### Active operating modes

- Core historic-building pipeline: DB export → photo analysis → enrichment → GIS export → Blender generation.
- DB revision / QA pipeline: `scripts/run_full_db_revision_pipeline.ps1` orchestrates address normalization, neighbor backfill, QA reports, autofix passes, and optional visual validation. See `docs/PIPELINE_RUNBOOK.md`.
- Multi-agent operations: `scripts/run_blender_buildings_workflows.py` fronts task routing, control-plane dispatch, watchdog heartbeats, and dashboard state for `agent_ops/`. See `docs/AGENT_WORKFLOW_GUIDE.md`.
- Export / downstream packaging: the repo also contains asset-export and downstream scene-packaging pipelines for FBX, Unreal, Unity, decals, trees, and street furniture. Treat these as first-class maintained workflows, not archive material.

### `generate_building.py` (~6,200 lines)

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

`gis_scene.py` + `gis_scene.json`: 753 footprints, 464 3D massing shapes, 162 road centerlines, 41 alleys, 530 field survey features. All in local metres from centroid.

### Agent ops workflow

When working inside the shared multi-agent system:

1. Route backlog tasks with `python scripts/run_blender_buildings_workflows.py route`.
2. Use `control-plane` for manager → worker dispatch (optionally `--execute-ollama` or `--execute-gemini` where appropriate).
3. Keep heartbeats current via `watchdog --mode ping` if you are working a long-running task.
4. Review `agent_ops/coordination/ownership/` and lock files before broad edits.
5. Leave findings-first review artifacts in `agent_ops/40_reviews/` when doing review work.

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
- `ground_floor_arches` — `{left_arch, centre_arch, right_arch}` each with `{function (entrance/window), total_width_m, total_height_m, type (arched/segmental), door: {width_m, height_m, colour}}`

## Photo Analysis Rules (docs/AGENT_PROMPT.md)

AI agents (Codex / Codex / Gemini CLI) analyze March 2026 field photos and merge visual observations into params. Photo index CSV at `PHOTOS KENSINGTON/csv/photo_address_index.csv` (1,867 photos). All 38 batches have been processed (results in `batches/batch_NNN_results.json`).

- **NEVER overwrite:** `total_height_m`, `facade_width_m`, `facade_depth_m`, `site.*`, `city_data.*`, `hcd_data.*`
- **ALWAYS update:** `facade_colour`, `windows_per_floor`, `window_type`, `window_arrangement`, `door_count`, `door_type`, `condition`, `roof_features`, `chimneys`, `porch_present`, `porch_type`, `balconies`, `balcony_type`, `cornice`, `bay_windows`, `ground_floor_arches`
- **Update only if clearly different from DB:** `facade_material`, `roof_type`, `has_storefront`, `floors`
- Results go into `photo_observations` nested dict
- Multiple photos per address: use the best facade photo, produce one update per unique address
- Non-building photos (murals, lanes, signs) → `"skipped": true` with `skip_reason`

**Field photos** (`PHOTOS KENSINGTON/`) contain 1,867 geotagged March 2026 field photos — the primary visual reference for all buildings. The HCD PDF is at `params/96c1-city-planning-kensington-market-hcd-vol-2.pdf`.

## Testing

The repo now has a formal pytest suite in `tests/` in addition to Blender/manual validation.

Validate by:
1. Running targeted pytest first for touched areas, then `python -m pytest tests/ -q`
2. Running scripts on a narrow sample first (`--address "22 Lippincott St"` or a small `--limit`)
3. Regenerating a known address and comparing against field photos in `PHOTOS KENSINGTON/`
4. Using validation utilities such as `scripts/check_positions.py`, `scripts/check_materials.py`, `scripts/verify_alignment.py`, and export/QA audit scripts where relevant
5. Using `--dry-run` flags or PowerShell `-DryRun` pipeline entrypoints before large write operations

## Dependencies

- **Blender 5.0 CLI** at `C:\Program Files\Blender Foundation\Blender 5.0\blender.exe` is used by current runbooks, though Blender 3.x+ APIs are the baseline for `bpy`, `bmesh`, `mathutils`
- **Python 3.10+**
- **pytest** — formal automated test suite in `tests/`
- **psycopg2-binary** — all PostGIS access scripts
- **PostgreSQL 18** with PostGIS

## Style

- 4-space indent, `snake_case` functions/files, `UPPER_SNAKE_CASE` constants
- `pathlib.Path` for paths, `json` with `indent=2` for output
- All file I/O: `encoding="utf-8"`
- Use `(value or "").lower()` not `.get("key", "").lower()` — handles explicit `None`
- Imperative commit messages scoped to one pipeline stage
- PRs: include affected addresses, dependencies, and screenshots for geometry/material changes
