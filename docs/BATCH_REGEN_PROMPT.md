# Full Regeneration — Codex Agent Prompt

Regenerate all 1,253 active buildings with corrected params (QA-fixed dimensions, materials, floor counts).

## Context

The params in `params/*.json` have been corrected through a multi-pass QA process:
- 387 facade materials normalized (Mixed masonry → brick, Vinyl siding → clapboard)
- 790 default depths fixed (32m → lot-data-derived or typology-based)
- 11 tall buildings photo-verified (floor counts, widths, heights corrected)
- 24 perimeter commercial blocks dimensionally corrected from field photos
- 141 remaining default 5x10m buildings fixed via street heuristics

The existing .blend files in `outputs/full/` were generated from pre-QA params. All 1,253 need regeneration.

## Steps

### Step 1: Verify environment

```bash
cd C:\Users\liam1\blender_buildings
blender --version
python -c "
import json
from pathlib import Path
active = sum(1 for f in Path('params').glob('*.json') if not f.name.startswith('_') and not json.load(open(f, encoding='utf-8')).get('skipped'))
rendered = len(list(Path('outputs/full').glob('*.blend')))
print(f'Active params: {active}')
print(f'Current renders: {rendered}')
"
```

Expected: ~1,253 active params, ~1,601 current renders.

### Step 2: Clear stale renders

```bash
# Move existing renders to backup (don't delete — in case of issues)
mkdir -p outputs/full_backup
mv outputs/full/*.blend outputs/full_backup/
mv outputs/full/*.manifest.json outputs/full_backup/
```

### Step 3: Regenerate all buildings

Use `scripts/batch_missing.py` which spawns one Blender process per building (avoids memory leaks in batch mode):

```bash
cd C:\Users\liam1\blender_buildings
PYTHONUNBUFFERED=1 python scripts/batch_missing.py
```

This will:
- Scan all non-skipped params (1,253 buildings)
- Check for existing .blend in `outputs/full/` (none after clearing)
- Generate each building with a fresh Blender process (120s timeout each)
- Print progress: `[N/1253] building_name OK (Xs)` or `FAILED`
- Summary at end: `Generated: N, Failed: M`

**Estimated time:** ~70 minutes (1,253 buildings × ~3.3s each)

**If a building fails:** The script reports it at the end. Common causes:
- `facade_material` not in generator's known set → normalize to brick/stone/stucco/clapboard/paint/siding
- `floors: 0` or `total_height_m: 0` → set to 2 floors, 6.0m
- Extreme dimensions (>50m wide) → may timeout at 120s, increase in script if needed

### Step 4: Generate demo block scene

After full regen, generate the Bellevue Ave 20-50 combined block scene:

```bash
# Individual builds are already done from Step 3
# Generate combined scene with GIS positioning:
blender --background --python generate_building.py -- --params params/ --match "Bellevue_Ave" --limit 30 --output-dir outputs/demos/
```

This creates a single .blend with all Bellevue Ave buildings positioned using site coordinates from `params/_site_coordinates.json`.

### Step 5: Verify completion

```bash
python -c "
import json
from pathlib import Path
active = [f for f in sorted(Path('params').glob('*.json')) if not f.name.startswith('_') and not json.load(open(f, encoding='utf-8')).get('skipped')]
rendered = set(Path(f).stem for f in Path('outputs/full').glob('*.blend'))
missing = [f.stem for f in active if f.stem not in rendered]
print(f'Active: {len(active)}, Rendered: {len(rendered)}, Missing: {len(missing)}')
if missing:
    print('Missing:')
    for m in sorted(missing)[:20]:
        print(f'  {m}')
else:
    print('ALL BUILDINGS REGENERATED')
"
```

### Step 6: Handle failures

If any buildings failed, check their params:

```bash
python -c "
import json
from pathlib import Path
KNOWN = {'brick','stone','stucco','clapboard','paint','siding','wood','concrete','metal','vinyl','glass'}
for f in sorted(Path('params').glob('*.json')):
    if f.name.startswith('_'): continue
    d = json.load(open(f, encoding='utf-8'))
    if d.get('skipped'): continue
    blend = Path('outputs/full') / f'{f.stem}.blend'
    if blend.exists(): continue
    mat = (d.get('facade_material','') or '').lower()
    fl = d.get('floors', 0) or 0
    h = d.get('total_height_m', 0) or 0
    issues = []
    if mat and mat not in KNOWN: issues.append(f'bad material: {mat}')
    if fl < 1: issues.append(f'floors={fl}')
    if h <= 0: issues.append(f'height={h}')
    print(f'{f.stem}: {issues if issues else \"unknown cause\"}')
"
```

Fix params and re-run `scripts/batch_missing.py` (it only generates missing builds).

### Step 7: Commit

```bash
git add outputs/full/batch.manifest.json
git commit -m "feat(generator): regenerate all 1253 buildings with QA-corrected params"
```

Note: don't git-add .blend files (large binaries). Only commit manifests.

### Step 8: Restore backup if needed

If something went wrong and you need the old renders back:

```bash
mv outputs/full_backup/*.blend outputs/full/
mv outputs/full_backup/*.manifest.json outputs/full/
```

Otherwise clean up:

```bash
rm -rf outputs/full_backup/
```

## Key files

| File | Purpose |
|------|---------|
| `scripts/batch_missing.py` | One-Blender-per-building batch generator |
| `scripts/qa_photo_verify.py` | QA checker (run with `--fix` to auto-fix) |
| `generate_building.py` | Main Blender generator (~6,200 lines) |
| `params/_site_coordinates.json` | GIS positions for all buildings |
| `outputs/full/` | Individual .blend files |
| `outputs/demos/` | Combined block scenes |
