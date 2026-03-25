# DB Revision Pipeline Runbook

## Purpose
Run the full param improvement pipeline end-to-end:
1. DB matching and address normalization
2. unmatched neighbor backfill metadata
3. QA gate + autofix passes
4. optional Blender visual smoke validation

## One-Command Runner

From repo root:

```powershell
pwsh -File scripts/run_full_db_revision_pipeline.ps1
```

Dry-run only (no writes):

```powershell
pwsh -File scripts/run_full_db_revision_pipeline.ps1 -DryRun -SkipVisual
```

Apply mode without visual batches:

```powershell
pwsh -File scripts/run_full_db_revision_pipeline.ps1 -SkipVisual
```

Custom visual limits/output:

```powershell
pwsh -File scripts/run_full_db_revision_pipeline.ps1 -VisualLimit 15 -VisualOutputDir outputs/qa_visual_check
```

## Prerequisites
- Python environment with `psycopg2`.
- PostgreSQL reachable through `scripts/db_config.py` env defaults.
- Blender CLI installed at:
  - `C:\Program Files\Blender Foundation\Blender 5.0\blender.exe`

## Key Artifacts
- DB revision reports: `outputs/db_param_revision_*.json`
- Alias candidate report: `outputs/address_alias_candidates.json`
- Neighbor backfill report: `outputs/db_neighbor_backfill_*.json`
- QA reports: `outputs/qa_fail_list_*.json`
- Autofix reports:
  - `outputs/qa_autofix_height_*.json`
  - `outputs/qa_autofix_medium_low_*.json`
- Visual smoke outputs (if enabled): `outputs/qa_visual_check/`

## Acceptance Check
- Final QA report should show:
  - `Failed: 0`
  - `high=0, medium=0, low=0`
