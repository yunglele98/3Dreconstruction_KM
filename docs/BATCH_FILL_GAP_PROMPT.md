# Fill Generation Gap — Claude Code Agent Prompt

Run this in Claude Code from the `blender_buildings` project root to clean up params and generate the ~554 missing buildings.

## Prompt

Paste this into your CLI:

```
claude 'Follow docs/BATCH_FILL_GAP_PROMPT.md to fill the generation gap.'
```

---

## Task

There are 618 building params with no .blend render in outputs/full/. Of those, ~11 are non-building photos and ~57 are duplicate photo-variants of the same address. After cleanup, ~554 legitimate buildings remain to generate. Your job is to run the cleanup, then kick off the Blender batch.

## Steps

### Step 1: Dry-run the cleanup script

```bash
python scripts/cleanup_before_batch.py --dry-run
```

Review the output. Confirm it reports:
- ~11 non-buildings to skip
- ~57 duplicates to skip
- ~25 schema fixes (missing facade_material / roof_type / building_name)
- ~554 buildings ready to generate

If the numbers look reasonable, proceed. If anything looks wrong (e.g. a real building being marked as non-building, or a canonical entry being wrong), fix the script before applying.

### Step 2: Apply the cleanup

```bash
python scripts/cleanup_before_batch.py
```

This modifies params/*.json in place:
- Adds `"skipped": true` + `"skip_reason"` to non-buildings and duplicates
- Fills `facade_material`, `roof_type`, `building_name` defaults where missing
- Records fixes in `_meta.cleanup_fixes`

### Step 3: Verify cleanup worked

```bash
python -c "
import json, glob, os
skipped = sum(1 for f in glob.glob('params/*.json') if not os.path.basename(f).startswith('_') and json.load(open(f, encoding='utf-8')).get('skipped'))
active = sum(1 for f in glob.glob('params/*.json') if not os.path.basename(f).startswith('_') and not json.load(open(f, encoding='utf-8')).get('skipped'))
rendered = len(glob.glob('outputs/full/*.blend'))
print(f'Active params: {active}')
print(f'Skipped params: {skipped}')
print(f'Already rendered: {rendered}')
print(f'Remaining to generate: {active - rendered}')
"
```

Expected: ~1,249 active, ~773 skipped, 929 rendered, ~320-554 remaining.

### Step 4: Generate missing buildings

Run Blender in batch mode with --skip-existing so it only generates the gap:

```bash
blender --background --python generate_building.py -- --params params/ --batch-individual --skip-existing --output-dir outputs/full/
```

This will:
- Scan all non-skipped params in params/
- Skip any that already have a .blend in outputs/full/
- Generate .blend + .manifest.json for each missing building
- Write a batch.manifest.json summary when done

**Estimated time:** ~15-45 minutes depending on machine (554 buildings × ~2-5s each in background mode).

**If Blender is not on PATH**, use the full path:
```bash
# Windows typical:
"C:\Program Files\Blender Foundation\Blender 4.0\blender.exe" --background --python generate_building.py -- --params params/ --batch-individual --skip-existing --output-dir outputs/full/

# Or if using Blender 3.x:
"C:\Program Files\Blender Foundation\Blender 3.6\blender.exe" --background --python generate_building.py -- --params params/ --batch-individual --skip-existing --output-dir outputs/full/
```

### Step 5: Verify completion

After the batch finishes:

```bash
python -c "
import json, glob, os
active = [f for f in glob.glob('params/*.json') if not os.path.basename(f).startswith('_') and not json.load(open(f, encoding='utf-8')).get('skipped')]
rendered = set(os.path.splitext(os.path.basename(f))[0] for f in glob.glob('outputs/full/*.blend'))
missing = [os.path.splitext(os.path.basename(f))[0] for f in active if os.path.splitext(os.path.basename(f))[0] not in rendered]
print(f'Active: {len(active)}, Rendered: {len(rendered)}, Still missing: {len(missing)}')
if missing:
    print('Missing buildings:')
    for m in sorted(missing)[:20]:
        print(f'  {m}')
    if len(missing) > 20:
        print(f'  ... and {len(missing) - 20} more')
else:
    print('ALL BUILDINGS GENERATED - 100% coverage!')
"
```

Also check the batch manifest:
```bash
cat outputs/full/batch.manifest.json | python -m json.tool | head -20
```

Look at the `counts` section — `failed` should be 0.

### Step 6: Handle any failures

If any buildings failed generation, check their param files for issues:

```bash
# Find failed buildings from manifest
python -c "
import json
m = json.load(open('outputs/full/batch.manifest.json'))
failed = [b for b in m.get('buildings', []) if b.get('status') == 'failed']
print(f'{len(failed)} failures:')
for f in failed:
    print(f'  {f[\"param_file\"]}')
"
```

Common failure causes:
- `floors: 0` or `total_height_m: 0` → set reasonable defaults (2 floors, 6.0m)
- Missing `floor_heights_m` array → will be auto-filled by generate_building.py
- Invalid `facade_material` value → normalize to one of: brick, stone, stucco, clapboard, paint, siding

Fix the param files and re-run with --skip-existing (it will only retry the ones without .blend output).

### Step 7: Commit

```bash
git add params/ scripts/cleanup_before_batch.py
git commit -m "cleanup: mark non-buildings and duplicates as skipped, fill schema gaps for batch generation"
```

After successful generation:
```bash
git add outputs/full/batch.manifest.json
git commit -m "feat(generator): batch-generate remaining 554 buildings to 100% coverage"
```

Note: don't git-add the .blend files — they're large binaries. Only commit manifests and param changes.
