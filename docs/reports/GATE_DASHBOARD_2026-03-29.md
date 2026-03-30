# QA Gate Dashboard — 2026-03-29

## Pipeline Status

| Metric | Value |
|--------|-------|
| Active buildings | 1,241 |
| Skipped entries | 813 |
| Deep facade coverage | 1,241/1,241 (100%) |
| Multi-volume buildings | 27 |
| Tests passing | 165/165 |
| QA failures | 0 critical |

## Params Quality (v8)

| Issue Type | Count |
|-----------|-------|
| storefront_inconsistency | 140 |
| suspicious_dimensions | 63 |
| unknown_facade_material | 3 |
| **Total anomalies** | **206** |
| Buildings with issues | 130/1,241 (10.5%) |

## Changes Since Last Dashboard

- Height fixes: 279 buildings already corrected (TASK-20260327-017)
- Material reconciliation: 133 buildings updated (TASK-MATERIAL-AUDIT)
- Window count fixes: 9 buildings corrected (TASK-20260327-016)
- Deep facade backfill: 1,138 buildings filled (was 103, now 1,241 — 100%)
- Multi-volume expansion: 20 buildings expanded (top candidates >10m wide)
- Generation defaults applied: 1,241 buildings (wall_thickness, mortar_hex, etc.)
- Test count: 89 → 165

## Decorative Completeness

- Buildings with HCD keywords: 440
- Complete: 394 (89.5%)
- Missing elements: 46 (mainly bay_window: 45, quoin: 1)

## Render Coverage

- Manifests found: 0 (renders on local machine, not accessible from sandbox)
- Re-render needed after today's param updates

## Remaining P0 Items (require local machine)

1. DB writeback: `python scripts/writeback_to_db.py`
2. GIS scene regen: `python scripts/export_gis_scene.py`
3. Blender batch render: `blender --background --python generate_building.py -- --params params/ --batch-individual`
4. GLOMAP reconstruction pipeline
