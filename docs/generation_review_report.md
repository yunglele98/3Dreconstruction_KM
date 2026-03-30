# Full Generation Review - Kensington Market (Refresh Snapshot: 2026-03-25 18:20:19 ET)

This is the **15-minute refresh** report. Output generation appears completed/stable at this snapshot (`outputs/full` last write: `2026-03-25 18:16:59 ET`).

## 1) Summary Table

| Metric | Count | Notes |
|---|---:|---|
| Total params (non-underscore files) | 2,023 | `params/*.json` excluding `_*.json` |
| Active params (not skipped) | 1,253 | `skipped != true` |
| Skipped params | 770 | |
| Rendered blends (`outputs/full`) | 1,600 | stable at snapshot |
| Rendered unique (full + batch_50 + batch_pilot + single) | 1,600 | no extra unique outside `full` |
| Missing active with no render | **1** | near-complete generation coverage |
| Duplicate address groups (active set) | 24 groups / 49 entries | address-key grouped variants |

## 2) Missing Render Breakdown

Missing list saved to: `docs/missing_renders.txt`

- Perimeter streets: **0**
- Duplicate/variant entries: **0**
- Photo-only non-building entries: **0**
- Legitimate missing building: **1**
  - `60_Leonard_Ave` (source: `None`)

### Key questions
1. Were the earlier `929` rendered buildings from `--limit`/`--match`?
   - **Inference:** no. The run continued significantly beyond that point and now reached 1,600 renders.
2. Is there a batch log/stdout capture from full generation?
   - **No** `outputs/full/batch.manifest.json` or durable full-run log was found (batch manifests exist only in `outputs/batch_50` and `outputs/batch_pilot`).
3. Any schema issues in missing params that would fail generation silently?
   - For the current missing set (1 file): **none detected** on required fields or zero-value dimension checks.

## 3) Schema Validation on Missing Params

Required fields checked:
- `building_name`, `floors`, `facade_width_m`, `total_height_m`, `facade_material`, `roof_type`

Results on current missing set (`n=1`):
- Missing required fields: **0** across all required fields
- `floors == 0`: **0**
- `facade_width_m == 0`: **0**
- `total_height_m == 0`: **0**
- Unrecognized `roof_type`: **0**
- Unrecognized `facade_material`: **0**

## 4) Duplicate Address Audit

- Duplicate groups: **24**
- Entries in duplicate groups: **49**
- Missing duplicate variants remaining: **0**
- Duplicate groups already rendered (potential waste/redundancy): **24**

Canonical rule used:
- Prefer `source == "postgis_export"`, else shortest/base address-like key.

## 5) Rendered Output Quality Check

### File-size checks (`outputs/full/*.blend`)
- Tiny `<50KB`: **0**
- Oversized `>50MB`: **0**

### Manifest checks
- `collection_name == "building_unknown"`: **21** manifests (needs metadata cleanup)

### Random sample of 20 rendered buildings
- Manifest semantic field gaps (`typology` and/or `construction_date` and/or `building_name`): **5/20**
- Param dimension invalids in sample (`floors/width/height <= 0`): **3/20**

## 6) PNG Render Gap

- PNG files in outputs: **0**
- Manifests scanned: **2,811**
- Non-null `render_path`: **0**

Conclusion:
- No evidence that `--render` was used in this generation stage.
- If PNGs are required now: `1,600 x ~30s ~= 13.3 hours` equivalent single-thread wall clock.

## 7) Photo Analysis Coverage

- `_analysis_summary.json` files in `params/`: **1**
- Params containing `photo_observations`: **590** total, **542** active
- `batches/` result JSON files: **0**

Impact:
- Most active params still rely on enrichment/defaulted observations rather than explicit persisted analysis-summary artifacts.

## 8) Site Coordinates Coverage

- Entries in `params/_site_coordinates.json`: **1,061**

Name-normalized coordinate matching:
- Active params with coordinate match: **1,051 / 1,253**
- Rendered params with coordinate match: **1,052 / 1,600**
- Rendered without coordinate match: **548**

## 9) Enrichment Pipeline Completeness (_meta flags)

On active params:
- `translated`: **1,228**
- `enriched`: **1,251**
- `gaps_filled`: **1,251**
- `no_meta`: **0**

## Recommendations (Prioritized)

1. **Close final generation gap**: run single-file generation for `60_Leonard_Ave` and verify manifest output.
2. **Add full-run manifest logging** in `outputs/full` so completion/failed/skipped stats are durable.
3. **Run metadata cleanup** for `building_unknown` manifests and missing `typology/construction_date` values.
4. **Coordinate normalization pass** for the 548 rendered files without coordinate key match.
5. **Optional final rendering stage** if PNG deliverables are required.

## Artifacts Produced

- Missing list: `docs/missing_renders.txt`
- Structured data: `docs/generation_review_data.json`
- This report: `docs/generation_review_report.md`
