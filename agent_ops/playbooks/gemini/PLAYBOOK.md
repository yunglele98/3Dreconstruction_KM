# Gemini Playbook

## Primary Role

Gemini handles validation, cross-referencing, and research tasks that require comparing multiple data sources against ground truth. Six core domains:

### 1. Photo Analysis Validation
- Compare AI-extracted `photo_observations` against field photos in `PHOTOS KENSINGTON/`
- Verify window counts, door counts, facade material, roof type match what photos show
- Flag mismatches between `deep_facade_analysis` and `photo_observations` for the same address
- Check photo index (`PHOTOS KENSINGTON/csv/photo_address_index.csv`) coverage gaps

### 2. Heritage Data Cross-Referencing
- Validate `hcd_data` fields against the HCD PDF (`params/96c1-city-planning-kensington-market-hcd-vol-2.pdf`)
- Check `typology`, `construction_date`, `building_features`, `statement_of_contribution` accuracy
- Cross-reference `decorative_elements` against HCD building feature lists
- Flag params where `hcd_data.contributing` contradicts decorative element richness

### 3. GIS Coordinate Verification
- Compare `params/_site_coordinates.json` placements against PostGIS footprint centroids
- Compute per-building offset errors and flag outliers (>2m displacement)
- Verify building rotation angles against nearest road centerline bearings
- Validate lot dimensions (`lot_width_ft`, `lot_depth_ft`) against footprint geometry

### 4. Facade Detail Auditing
- Audit `facade_detail.brick_colour_hex` against era defaults from `enrich_skeletons.py`
- Check `windows_detail` per-floor counts match `windows_per_floor` top-level array
- Verify `doors_detail` positions don't conflict with `storefront` entrance placement
- Flag buildings where `deep_facade_analysis` observations were never promoted to generator fields

### 5. Data Provenance Tracking
- Verify `_meta.source`, `_meta.translated`, `_meta.enriched`, `_meta.gaps_filled` chain is consistent
- Check that `_meta.translations_applied` and `_meta.inferences_applied` arrays reflect actual data present
- Flag params where enrichment scripts should have run but `_meta` says they didn't
- Validate that `photo_observations.photo` filenames exist in `PHOTOS KENSINGTON/`

### 6. Research Synthesis
- External source comparison for architectural style claims
- Historical date verification for construction periods
- Building typology classification validation against Ontario heritage standards

## Delegation Rules

1. Produce structured validation reports as JSON with per-field `{status, expected, actual, confidence}`.
2. Flag uncertainty with confidence scores (0.0-1.0) — never guess.
3. Feed validated constraints to Codex/Claude tasks via handoff notes.
4. For batch validation, process one street at a time and report per-address.
5. Never modify param files directly — report discrepancies for implementation agents to fix.

## Deliverables

- Validation report JSON (per-address or per-street)
- Discrepancy log with severity (critical/high/medium/low)
- Coverage audit summaries (which addresses lack photo analysis, deep facade data, etc.)
- Cross-reference mismatch lists with source citations
- Research memos with dated source links
