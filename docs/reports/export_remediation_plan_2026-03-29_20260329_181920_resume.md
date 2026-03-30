# Export Remediation Queue (Continuation)

Date: 2026-03-29  
Run key: 20260329_181920

## Current state
- Root validation hard fails: `1` (`103 Bellevue Ave`)
- Root warnings: `52`
- Largest remaining warning buckets:
  - `watertight` mesh warnings (53)
  - `texture_blank` variants
  - `degenerate_faces` now isolated to one address

## Priority 1 (automation-safe)
1. Maintain utility-pass completeness by running both backfill scripts after export batches:
   - `scripts/backfill_material_sidecars.py --apply`
   - `scripts/backfill_pbr_utility_maps.py --apply`
2. Preserve generated files under per-run logs with command + delta tracking.
3. Keep targeted GLB repair script for degenerate sets:
   - `scripts/repair_export_glb_mesh.py --address-csv <degenerate_csv> --apply`

## Priority 2 (geometry quality)
1. Resolve the remaining hard fail (`103 Bellevue Ave`) with manual Blender edit-mode surgery:
   - inspect zero-area/sliver faces after join/bake flow
   - dissolve/merge problematic regions and recalc normals
   - re-export + validate
2. Export address list for `watertight` warnings and process in descending complexity.
3. Re-validate touched addresses first, then root.

## Priority 3 (validator hardening)
1. Keep CLI entrypoint regression tests in CI test slice:
   - `tests/test_validate_export_pipeline_cli.py`
   - `tests/test_validate_export_pipeline_fallback.py`
2. Add one more regression test when practical:
   - `--output` path in nested non-existing directory.

## Overnight command sequence
```powershell
# from repo root
$run = '20260329_181920'
$blender = 'C:\Program Files\Blender Foundation\Blender 5.1\blender.exe'
$plan = Import-Csv "outputs/session_runs/logs/${run}_missing_glb_retry_plan.csv" | Select-Object -Skip 30

foreach ($p in $plan) {
  & $blender --background --python scripts/export_building_fbx.py -- --blend $p.blend --address $p.address --texture-size 1024 *> "outputs/session_runs/logs/${run}_overnight_$($p.safe).log"
}

python scripts/backfill_material_sidecars.py --apply
python scripts/backfill_pbr_utility_maps.py --apply
python scripts/repair_export_glb_mesh.py --address-csv "outputs/session_runs/logs/${run}_degenerate_addresses.csv" --fill-holes --apply --report "outputs/session_runs/logs/${run}_repair_glb_deg_apply.json"
python scripts/validate_export_pipeline.py --exports-dir outputs/exports --output "outputs/session_runs/logs/${run}_validation_report_root_post_overnight.json"
```

## Completion criteria for next pass
- Restore `FAIL = 0`.
- Reduce `watertight` warnings by at least 25% from current 53.
- Reduce `texture_blank` warnings by at least 20%.
