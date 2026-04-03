# TASK-20260403-006: Analyze 10 remaining buildings without photo_observations

- **priority**: low
- **stage**: 1-SENSE
- **estimated_effort**: small
- **depends_on**: none

## Description

10/1,050 active buildings lack `photo_observations`. Identify which buildings these are, check if field photos exist for them, and run photo analysis if possible.

## Commands

```bash
python3 -c "
import json, pathlib
for f in sorted(pathlib.Path('params').glob('*.json')):
    if f.name.startswith('_'): continue
    d = json.loads(f.read_text())
    if d.get('skipped'): continue
    if not d.get('photo_observations'):
        print(f.name)
"
```

## Acceptance

- Remaining buildings identified and either analyzed or documented as having no photos available
