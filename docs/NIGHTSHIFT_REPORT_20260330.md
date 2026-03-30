# Nightshift Report — 2026-03-30

## Pipeline Run Summary

All scripts executed on the active project at `C:\Users\liam1\blender_buildings` (1,241 active buildings, 2,065 total param files).

### 1. QA Audit Suite

| Script | Result |
|---|---|
| `qa_params_gate.py` | 1,241 checked — **176 failures** (102 high, 74 low) |
| `audit_params_quality.py` | 1,222 buildings — **78 with issues**, 151 anomalies (140 storefront inconsistency, 8 suspicious dimensions, 3 unknown materials) |
| `audit_structural_consistency.py` | Clean — no structural inconsistencies |
| `audit_storefront_conflicts.py` | Clean — no DB/param conflicts |

### 2. Auto-Fix Scripts

| Script | Result |
|---|---|
| `fix_params_quality.py` | **916 files updated**: 745 facade colours defaulted, 165 materials normalized, 72 storefront flags fixed, 6 floor heights reinferred |
| `fix_structural_consistency.py` | 113 height warnings logged (no auto-changes — informational only) |
| `fix_height_inflation.py` | **1 severe outlier fixed** (35 Bellevue Ave: 6.4m → 3.03m). Bug fixed: added `float()` coercion for DB height values stored as strings |
| `qa_autofix_height.py` | **102 buildings corrected** using QA fail list |
| `qa_autofix_medium_low.py` | 0 changes (no medium/low severity issues remaining) |

### 3. Enrichment Pipeline

| Script | Result |
|---|---|
| `translate_agent_params.py` | 0 new translations (all already translated) |
| `enrich_skeletons.py` | 0 new enrichments (all skipped — already enriched) |
| `enrich_facade_descriptions.py` | **161 files enriched** with prose facade descriptions |
| `normalize_params_schema.py` | **2,062 files normalized** (boolean→dict cleanup) |
| `patch_params_from_hcd.py` | 0 new patches (all HCD data already merged) |
| `infer_missing_params.py` | 0 new inferences (all gaps already filled) |

### 4. Colour Palettes

| Script | Result |
|---|---|
| `rebuild_colour_palettes.py` | 0 incomplete palettes found (all 1,241 already complete) |
| `diversify_colour_palettes.py` | **25 buildings diversified**: 11 roof, 9 trim, 3 facade, 2 mortar changes |

### 5. Data Enrichment Post-Scripts

| Script | Result |
|---|---|
| `enrich_storefronts_advanced.py` | **64 storefronts enriched** (awning/signage/grille inference) |
| `enrich_porch_dimensions.py` | **1 porch enriched** (37 Nassau St) |
| `infer_setbacks.py` | **441 setbacks inferred** from street-type rules |
| `consolidate_depth_notes.py` | 0 new consolidations (all depth notes already assembled) |
| `build_adjacency_graph.py` | **1,219 adjacency records**, **287 block profiles** across 228 streets |
| `analyze_streetscape_rhythm.py` | 228 streets scored for heritage quality |

### 6. Fingerprinting and Regen Batches

| Script | Result |
|---|---|
| `fingerprint_params.py` | **1,241 new** fingerprints (all flagged for regen) |
| `build_regen_batches.py` | **25 batches** created, 1,241 buildings queued |

### 7. QA Report and Deliverables

| Output | Location |
|---|---|
| QA Report (JSON) | `outputs/qa_report.json` |
| QA Dashboard (HTML) | `outputs/qa_dashboard.html` |
| Building Summary CSV | `outputs/deliverables/building_summary.csv` |
| GeoJSON | `outputs/deliverables/kensington_buildings.geojson` |
| Street Profiles | `outputs/deliverables/street_profiles.json` (35 streets) |

QA Results: **98.4% of buildings have zero issues**, average quality score **99.9/100**. Only 20 buildings have height_mismatch warnings.

### 8. Blender Batch Generation

- **Status**: Running — full 1,241-building regeneration with `--render` flag
- **Output directory**: `outputs/full_v2/`
- **Per building**: `.blend` file + `.png` render + `.manifest.json`
- **Estimated duration**: ~1.5-2 hours (4-5 seconds per building)
- **Log**: `outputs/nightshift_regen_log.txt`

### 9. Bug Fix Applied

**`fix_height_inflation.py` type error**: The script compared `db_avg_height > 0` where `db_avg_height` was a string from PostgreSQL. Added `float()` coercion on line 98.

### 10. Critical Fix: `generate_building.py` Truncation

The main generator script (`generate_building.py`) was discovered to be **truncated at line 8,789** — missing the `generate_building()` function (341 lines) and the entire CLI entry point (633 lines). This was recovered by splicing from the D: drive backup (`D:\liam1_transfer\blender_buildings\generate_building.py`):

- `generate_building()` function: D drive lines 7063-7403 → inserted at C drive line 8792
- Entry point (`load_and_generate`, `generate_batch_individual`, `__main__`): D drive lines 7400-8032 → appended

Final file: **9,766 lines** (was 8,789 truncated, D drive reference was 8,032).

## Top Street Profiles (by building count)

| Street | Buildings | Avg Height | Material | Era |
|---|---|---|---|---|
| Augusta Ave | 157 | 7.9m | brick | Pre-1889 |
| Oxford St | 124 | 8.8m | brick | Pre-1889 |
| Spadina Ave | 109 | 8.9m | brick | 1889-1903 |
| Bellevue Ave | 108 | 7.9m | brick | Pre-1889 |
| Nassau St | 102 | 8.4m | brick | Pre-1889 |
| Kensington Ave | 99 | 8.4m | brick | Pre-1889 |
| College St | 66 | 9.8m | brick | 1889-1903 |
| Wales Ave | 62 | 8.1m | brick | Pre-1889 |
| Dundas St W | 53 | 8.5m | brick | 1889-1903 |
| Baldwin St | 51 | 7.7m | brick | Pre-1889 |
