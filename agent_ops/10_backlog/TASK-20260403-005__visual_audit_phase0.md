# TASK-20260403-005: Run Phase 0 visual audit

- **priority**: high
- **stage**: 0-PHASE0
- **estimated_effort**: medium (~35 min full run)
- **depends_on**: TASK-20260403-003

## Description

Phase 0 visual audit comparing parametric renders against field photos to produce a ranked priority queue. This drives which buildings get photogrammetry, segmentation, or colour fixes next.

## Commands

```bash
python scripts/visual_audit/run_full_audit.py
# Quick test first:
python scripts/visual_audit/run_full_audit.py --limit 20
```

## Acceptance

- Priority queue JSON produced ranking all rendered buildings
- SSIM scores computed for buildings with matched photos
- Report identifies top candidates for photogrammetry upgrade
