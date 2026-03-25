# DB Param Improvements (2026-03-25)

## Scope
- Compared `params/*.json` (2,023 files) with `public.building_assessment` (1,075 rows) in PostgreSQL 18.3.
- Focus: actionable improvements for Blender generation parameters.

## Coverage Summary
- Total param files: `2,023`
- Active (not skipped): `1,317`
- Skipped: `706`
- Active address matches to DB: `1,057` (`80.3%` of active)
- Active unmatched: `260`

## High-Impact Findings

### 1) Height inflation is the main quality issue
- For matched active files, `total_height_m / BLDG_HEIGHT_AVG_M` median is `1.62`.
- Outliers: `64` files with ratio `>= 2.5`.
- Per-floor height is also high: median `5.38 m/floor` (p90 `8.44`), indicating widespread overestimation.

Priority examples:
- `309_Augusta_Ave.json` ratio `4.16` (`19.20m` vs DB `4.62m`)
- `132_Bellevue_Ave.json` ratio `4.05` (`42.88m` vs DB `10.59m`)
- `374_Spadina_Ave.json` ratio `3.84`
- `10_Glen_Baillie_Pl.json` ratio `3.43`

### 2) Address normalization can recover DB joins
- Raw unmatched active: `260`
- Recoverable with simple normalization: `49` files
  - Remove parenthetical labels (`(Urban Catwalk)`)
  - Keep first address when slash-separated (`A / B`)
  - Remove trailing descriptors (`area`, notes)

### 3) Storefront conflicts need targeted review
- `12` matched active files conflict between param `has_storefront` and DB storefront signal (`ba_storefront_status`).
- No useful photo-derived fields yet (`photo_*` is effectively empty for matched active rows).

### 4) Structural consistency checks
- `31` files: `sum(floor_heights_m)` differs from `total_height_m` by `>0.75m`
- `24` files: `len(floor_heights_m) != floors` (often due to fractional floors like `2.5`)

## Recommended Improvement Rules
1. Add normalized address join fallback before DB enrichment.
2. Recalibrate `total_height_m` using DB height anchors:
   - Flag if `total_height_m / BLDG_HEIGHT_AVG_M > 2.0` or `< 0.8`.
   - For severe outliers (`>=2.5`), auto-suggest replacement from DB height + bounded roof allowance.
3. Add storefront conflict review queue from DB `ba_storefront_status`.
4. Add param QA gate:
   - `2.4 <= total_height_m / floors <= 4.8`
   - `abs(sum(floor_heights_m) - total_height_m) <= 0.75` unless explicitly marked.
