# Phase 0: Visual Audit

## Purpose

Compare parametric renders (`outputs/buildings_renders_v1/`) against field photos (`PHOTOS KENSINGTON/`) to identify buildings where the procedural model diverges most from reality. Produces a ranked priority queue that drives which buildings get photogrammetry, segmentation, or colour fixes.

## Workflow

1. **Render** -- Generate parametric renders for all buildings via Blender batch mode
2. **Compare** -- Compute SSIM (or MSE fallback) between render and best-match field photo
3. **Rank** -- Sort buildings by visual discrepancy score (worst first)
4. **Route** -- Feed priority queue into downstream stages:
   - Critical/High tier -> photogrammetry (Stage 2) if 3+ photos available
   - Medium tier -> segmentation fixes (Stage 1) + re-enrichment (Stage 3)
   - Low tier -> colour palette correction only (Stage 3)
   - Acceptable -> no action needed

## Outputs

- `outputs/visual_audit/priority_queue.json` -- Ranked building list with scores and detected issues
- `outputs/visual_audit/audit_summary.json` -- Aggregate statistics (totals, averages, tier distribution)
- `outputs/visual_audit/streets/` -- Per-street markdown reports

## Key Scripts

| Script | Description |
|--------|-------------|
| `scripts/visual_audit/run_full_audit.py` | Main entry point. Loads photo index, compares renders vs photos, writes priority queue and summary. |
| `scripts/visual_audit/street_summary.py` | Generates per-street summary reports from audit results. |

## Usage

```bash
python scripts/visual_audit/run_full_audit.py                    # full audit (~35 min)
python scripts/visual_audit/run_full_audit.py --limit 20         # quick test
python scripts/visual_audit/street_summary.py                    # street-level reports
```

## Tier Thresholds

| SSIM Score | Tier       | Action                        |
|------------|------------|-------------------------------|
| < 0.20     | Critical   | Photogrammetry + full re-gen  |
| 0.20-0.35  | High       | Geometry + colour fix         |
| 0.35-0.50  | Medium     | Segmentation + re-enrichment  |
| 0.50-0.65  | Low        | Colour palette correction     |
| >= 0.65    | Acceptable | No action                     |

See CLAUDE.md for full technical details.
