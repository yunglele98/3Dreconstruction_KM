# TASK-20260403-001: Run match_photos_to_params for all buildings

- **priority**: high
- **stage**: 3-ENRICH
- **estimated_effort**: small
- **depends_on**: none
- **status**: DONE
- **completed**: 2026-04-03

## Description

0/1,050 buildings have `matched_photos` populated despite 1,928 field photos available and 1,040 already having `photo_observations`. Run `scripts/match_photos_to_params.py` to link photos to param files. This is required before Stage 4 generation can use the photogrammetric path.

## Result

Ran `match_photos_to_params.py --apply`. 1,035/1,050 matched (99%). 13 param files updated with newly matched photos. 15 unmatched are all Leonard Ave/Pl — zero field photos exist for these addresses (study area edge).

Match method breakdown: 1,022 previously matched + 10 number_variant + 3 fuzzy = 1,035 total.

## Acceptance

- [x] 1,035/1,050 matched (99%) via `photo_observations.photo`
- [x] No regressions in existing `photo_observations`
- [x] 15 unmatched = Leonard Ave/Pl (no photos available)
