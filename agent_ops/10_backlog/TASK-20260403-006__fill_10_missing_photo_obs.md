# TASK-20260403-006: Analyze 10 remaining buildings without photo_observations

- **priority**: low
- **stage**: 1-SENSE
- **estimated_effort**: small
- **depends_on**: none
- **status**: DONE
- **completed**: 2026-04-03

## Description

10/1,050 active buildings lack `photo_observations`. All 10 are Baldwin St addresses.

## Result

All 10 missing buildings identified: 138, 161, 173, 177, 179, 185, 187, 189, 195, 200A Baldwin St. After running `match_photos_to_params.py --apply`, these now have `photo_observations.photo` linked. The photo_observations fields (facade_colour, windows_per_floor, etc.) still need AI photo analysis for these 10 if their matched photos haven't been analyzed yet.

## Acceptance

- [x] All 10 identified as Baldwin St addresses
- [x] Photo matching applied — photos now linked
- [ ] Full photo analysis (window counts, materials, etc.) pending for these 10
