# TASK-20260403-002: Fuse remaining 15 unfused buildings

- **priority**: medium
- **stage**: 3-ENRICH
- **estimated_effort**: small
- **depends_on**: none

## Description

1,035/1,050 buildings have `fusion_applied` in `_meta`. The remaining 15 need depth/segmentation fusion. Identify which buildings are missing and run the fusion scripts.

## Commands

```bash
python scripts/enrich/fuse_segmentation.py --segmentation segmentation/ --params params/
python scripts/enrich/fuse_depth.py --depth-maps depth_maps/ --params params/
```

## Acceptance

- All 1,050 active buildings have `fusion_applied` in `_meta`
