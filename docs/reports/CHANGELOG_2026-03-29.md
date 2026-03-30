# Changelog — 2026-03-29

## Handoff Fixes

- **Height corrections**: 279 buildings had total_height_m already corrected from TASK-20260327-017 (GIS massing source of truth). Script: `fix_height_from_handoff.py`
- **Material reconciliation**: 133 buildings updated facade_material from photo observations (TASK-MATERIAL-AUDIT, confidence >= 0.7). Top change: brick → mixed (110 buildings). Script: `fix_material_from_handoff.py`
- **Window count fixes**: 9 buildings corrected windows_detail counts from photo_observations (TASK-20260327-016). Script: `fix_window_totals_from_handoff.py`

## Deep Facade Backfill

- **Augusta Ave**: 152 buildings filled with synthesized deep_facade_analysis
- **Oxford St**: 126 buildings filled
- **All remaining streets**: 860 buildings filled via generic backfill script
- **Coverage**: 103/1,241 → 1,241/1,241 (100%) deep_facade_analysis coverage
- Scripts: `batch_deep_facade_augusta.py`, `batch_deep_facade_oxford.py`, `batch_deep_facade_backfill.py`

## Enrichment

- **Multi-volume expansion**: 20 buildings >10m wide converted to volumes[] arrays (top candidates by width: College St, Spadina Ave commercial rows). Script: `expand_multi_volume.py`
- **Generation defaults**: 1,241 buildings filled with missing defaults from generation_defaults.py — wall_thickness_m (1,241), mortar_colour_hex (1,241), sill_height_m (99), width_m (37), height_m (24), window_type (18), roof_pitch_deg (3). Script: `apply_generation_defaults.py`

## Validation

- **Schema validation**: 1,241 active buildings validated. 1,171 valid, 70 with issues. Auto-fixed: 53 windows_per_floor extensions, 15 floors type coercions, 1 truncation, 1 width clamp. Script: `validate_all_params.py`
- **Params quality audit v8**: 206 anomalies across 130 buildings (140 storefront_inconsistency, 63 suspicious_dimensions, 3 unknown_facade_material)
- **Decorative completeness**: 440 buildings checked against HCD keywords. 394 complete (89.5%), 46 missing elements (mainly bay_window: 45)

## Testing

- **Test count**: 89 → 165 (76 new tests)
- **New test files**:
  - `test_deep_facade_pipeline.py` — 23 tests: normalize_address, should_skip, merge, promote functions
  - `test_fix_handoff_findings.py` — 19 tests: parse_expected_features, element_is_missing, stamp_meta, fix_missing_features with temp files
  - `test_generation_defaults.py` — 17 tests: constant existence, type checks, hex validation, RGB ranges, site coordinates
  - `test_validate_string_courses.py` — 17 tests: _to_float, _course_items, _extract_height_m, _set_height, integration tests

## Exports & Deliverables

- `outputs/deliverables/building_summary.csv` — 1,241 buildings, 18 columns, sorted by street
- `outputs/deliverables/street_profiles.json` — 35 street profiles with avg height/width, dominant material/era
- `outputs/deliverables/kensington_buildings.geojson` — 1,241 features for QGIS/Mapbox/Kepler.gl
- `outputs/deliverables/qa_comparison.html` — 909 side-by-side photo/render comparison cards

## Audits

- `outputs/deep_facade_coverage_report.json` — 100% coverage across all 35 streets
- `outputs/decorative_completeness_audit.json` — 394/440 complete
- `outputs/render_staleness_report.json` — 0 manifests (renders on local machine)
- `outputs/params_quality_after_fix_v8.json` — v8 quality snapshot
- `outputs/param_validation_report.json` — full schema validation results

## Pipeline Scripts Added

- `scripts/batch_deep_facade_augusta.py`
- `scripts/batch_deep_facade_oxford.py`
- `scripts/batch_deep_facade_backfill.py`
- `scripts/expand_multi_volume.py`
- `scripts/apply_generation_defaults.py`
- `scripts/audit_deep_facade_coverage.py`
- `scripts/audit_decorative_completeness.py`
- `scripts/audit_render_manifest_coverage.py`
- `scripts/export_building_summary_csv.py`
- `scripts/export_street_profile_json.py`
- `scripts/export_geojson.py`
- `scripts/generate_qa_comparison_html.py`
- `scripts/validate_all_params.py`
- `scripts/archive_stale_outputs.py`
- `scripts/sync_working_copy.py`

## Current State

| Metric | Value |
|--------|-------|
| Active buildings | 1,241 |
| Deep facade coverage | 100% |
| Multi-volume buildings | 27 |
| Tests passing | 165/165 |
| Schema valid | 1,171/1,241 (94.4%) |
| Decorative complete | 394/440 (89.5%) |
| Export deliverables | 4 files |
