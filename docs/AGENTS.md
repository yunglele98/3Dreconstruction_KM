# Repository Guidelines

## Project Structure & Module Organization
This repository is a script-first Blender pipeline for generating georeferenced 3D models of Kensington Market buildings (Toronto). Data flows from PostGIS through photo analysis and enrichment to Blender geometry.

404 Python scripts are in `scripts/`:
- `scripts/export_db_params.py`: exports building parameter skeletons from PostGIS (~1,062 buildings)
- `scripts/prepare_batches.py`: splits field photos into batches for AI agent analysis
- `docs/AGENT_PROMPT.md`: instructions for vision agents (Claude Code / Codex / Gemini CLI)
- `scripts/deep_facade_pipeline.py`: deep facade analysis workflow (merge, promote, audit)
- `scripts/translate_agent_params.py`: bridges agent flat output to generator structured dicts
- `scripts/enrich_skeletons.py`: fills missing params from typology/era defaults
- `scripts/enrich_facade_descriptions.py`: adds prose facade descriptions
- `scripts/normalize_params_schema.py`: converts boolean flags to structured dicts
- `scripts/patch_params_from_hcd.py`: merges HCD-derived decorative features
- `scripts/infer_missing_params.py`: fills remaining gaps (colour palette, roof material, etc.)
- `scripts/writeback_to_db.py`: pushes photo analysis results back to PostGIS
- `scripts/import_field_survey.py`: loads ArcGIS field survey GeoJSON into PostGIS
- `scripts/link_attachments.py`: links field survey photos to PostGIS features
- `scripts/export_gis_scene.py`: exports georeferenced site model for Blender
- `generate_building.py`: runs inside Blender, turns params into 3D geometry

Working data:
- `params/` — ~1,065 building parameter JSON files (~1,062 active from DB export + metadata)
- `params/_site_coordinates.json` — georeferenced placement lookup
- `batches/` — photo analysis batch files for agents (all processed)
- `PHOTOS KENSINGTON/` — 1,930 geotagged field photos + address index
- `generator_modules/` — 11 modules (7,401 lines) extracted from generator
- `tests/` — 70 pytest test files (~20,000 lines)
- `gis_scene.py` + `gis_scene.json` — Blender site model
- `outputs/` — rendered Blender output
- `scenarios/` — 5 urban planning scenario overlays + impact analysis
- `web/` — CesiumJS + Vite web planning platform
- `archive/` — retired data and scripts

## Build, Test, and Development Commands

```bash
# Step 1: Export from PostGIS
python scripts/export_db_params.py [--overwrite] [--street "Augusta Ave"]

# Step 2: Photo analysis (run agents on batches)
python scripts/prepare_batches.py
# Then: claude 'Follow docs/AGENT_PROMPT.md to process batches/batch_001.json'

# Step 3: Enrichment pipeline (run in order)
python scripts/translate_agent_params.py
python scripts/enrich_skeletons.py
python scripts/enrich_facade_descriptions.py
python scripts/normalize_params_schema.py
python scripts/patch_params_from_hcd.py
python scripts/infer_missing_params.py

# Write results back to DB
python scripts/writeback_to_db.py --migrate  # first time
python scripts/writeback_to_db.py

# Step 4: GIS site model
python scripts/export_gis_scene.py

# Step 5: Blender generation
blender --python gis_scene.py
blender --background --python generate_building.py -- --params params/22_Lippincott_St.json
blender --background --python generate_building.py -- --params params/
```

## Coding Style & Naming Conventions
Follow existing Python style: 4-space indentation, `snake_case` for functions/files, `UPPER_SNAKE_CASE` for module constants, and short docstrings on top-level helpers. Prefer `pathlib.Path` for repo-relative paths and keep JSON output stable with `indent=2`. All file I/O must use `encoding="utf-8"`. Use `(value or "").lower()` pattern instead of `.get("key", "").lower()` to handle explicit `None` values safely.

## Database
PostGIS database `kensington` on localhost:5432 (user: postgres). Contains:
- `building_assessment` — 1,075 buildings with 38 photo analysis columns
- `opendata.*` — building_footprints, massing_3d, road_centerlines, sidewalks
- `field_*` — 13 field survey tables (566 features, 512 photos)
- `census_tracts_spatial`, `ruelles_spatial`

## Testing Guidelines
Formal pytest suite in `tests/` (70 test files, ~20,000 lines). Validate by:
1. Running targeted pytest first for touched areas, then `python -m pytest tests/ -q`
2. Running scripts on a narrow sample first (e.g., `--address "22 Lippincott St"`)
3. Regenerating a known address and comparing against field photos in `PHOTOS KENSINGTON/`
4. Visual inspection of Blender output
5. Using `--dry-run` flags before large write operations

## Commit & Pull Request Guidelines
Use clear imperative commit subjects scoped to one pipeline stage. PRs should include affected addresses or JSON files, required dependencies, and screenshots for geometry/material changes.
