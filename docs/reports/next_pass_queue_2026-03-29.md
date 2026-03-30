# Next Pass Queue (Post Session 2026-03-29)

1. Start PostGIS locally and re-run `scripts/audit_storefront_conflicts.py`.
2. Generate at least 3 fresh FBX exports into `outputs/exports` and rerun `scripts/validate_export_pipeline.py` by address.
3. Apply storefront enrichment with writes: `python scripts/enrich_storefronts_advanced.py --apply`.
4. Apply porch enrichment with writes: `python scripts/enrich_porch_dimensions.py --apply`.
5. Re-run `scripts/generate_comprehensive_audit.py` and compare deltas after applied enrichments.
6. Build a focused remediation list for the 46 decorative completeness misses (bay-window heavy).
7. Add a safe guard in `scripts/normalize_params_schema.py` to force UTF-8 output or avoid filename echo on non-UTF consoles.
8. Separate backup/variant param files (`*_backup_*`, `*_custom_v*`) from active operational set to reduce noisy normalization/audits.
9. Add a non-destructive mode to `fix_structural_consistency.py` that outputs CSV of warnings only (for manual triage).
10. Triage the 112 floor-height warning cases into:
   - likely valid atypical buildings
   - clear data defects requiring correction.
