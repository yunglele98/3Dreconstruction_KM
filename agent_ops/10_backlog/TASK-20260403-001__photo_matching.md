# TASK-20260403-001: Run match_photos_to_params for all buildings

- **priority**: high
- **stage**: 3-ENRICH
- **estimated_effort**: small
- **depends_on**: none

## Description

0/1,050 buildings have `matched_photos` populated despite 1,928 field photos available and 1,040 already having `photo_observations`. Run `scripts/match_photos_to_params.py` to link photos to param files. This is required before Stage 4 generation can use the photogrammetric path.

## Commands

```bash
python scripts/match_photos_to_params.py
```

## Acceptance

- `matched_photos` populated for 800+ buildings
- No regressions in existing `photo_observations`
