# Full Generation Review — Agent Prompt

You are reviewing the Kensington Market Blender buildings pipeline to verify completeness, identify gaps, and flag quality issues. Work methodically through each section below.

## Context

This project generates parametric 3D Blender models for ~1,064 historic buildings in Toronto's Kensington Market. The pipeline: PostGIS export → photo analysis → enrichment → Blender generation. All code and data live in this repo.

**Current state (as of 2026-03-25):**
- 1,317 active (non-skipped) param files in `params/`
- 929 `.blend` files rendered in `outputs/full/`
- **618 buildings have params but NO render** — this is the primary gap
- 705 param files are correctly marked `"skipped": true` (non-building photos)
- 0 QA failures on the enrichment pipeline
- No PNG renders exist (all `render_path: null` in manifests)

---

## Review Tasks

### 1. Missing Render Analysis (618 buildings)

Generate the full list of buildings that have active params but no `.blend` in any output directory:

```bash
# Get active param names
ls params/*.json | grep -v '^params/_' > /tmp/all_params.txt
grep -rl '"skipped": true' params/*.json > /tmp/skipped.txt
comm -23 <(cat /tmp/all_params.txt | xargs -I{} basename {} .json | sort -u) \
         <(ls outputs/full/*.blend outputs/batch_50/*.blend outputs/batch_pilot/*.blend outputs/single/*.blend 2>/dev/null | xargs -I{} basename {} .blend | sort -u) \
         > /tmp/missing_renders.txt
```

For the 618 missing, categorize them:

- **Perimeter streets** (Spadina, Bathurst, College, Dundas): ~177 are on perimeter streets. Are these in scope or intentionally excluded?
- **Duplicate/variant entries**: Many addresses appear multiple times with different suffixes (e.g., `40_Nassau_St` and `40_Nassau_St_striped_awning_24h_video_sign`). Identify true duplicates vs distinct buildings.
- **Photo-only non-building entries**: ~13 appear to be alleys, murals, signs, etc. that were NOT marked as skipped. Flag these for cleanup — they should have `"skipped": true`.
- **Legitimate buildings missing renders**: The remaining ~400+ with `source: "postgis_export"` are real buildings that should have been generated. Determine why they were skipped by the batch generator.

**Key questions to answer:**
1. Were the 929 rendered buildings a `--limit` or `--match` filtered run, not a full run?
2. Is there a batch log or stdout capture from the generation run?
3. Do any of the 618 missing params have schema issues that would cause `generate_building.py` to fail silently?

### 2. Schema Validation on Missing Params

For each of the 618 missing param files, validate they have the minimum required fields for generation:

```python
REQUIRED_FIELDS = [
    'building_name', 'floors', 'facade_width_m', 'total_height_m',
    'facade_material', 'roof_type'
]
```

Report:
- Count of files missing each required field
- Count of files with `floors == 0` or `facade_width_m == 0` or `total_height_m == 0`
- Count of files with unrecognized `roof_type` values
- Count of files with unrecognized `facade_material` values

### 3. Duplicate Address Audit

Many param files appear to be duplicates of the same building (same address, different photo-derived suffixes). Run:

```bash
# Extract base addresses and find duplicates
cat /tmp/active_names.txt | sed 's/_[A-Z][a-z].*//; s/_striped.*//; s/_24h.*//; s/_fire_escape.*//' | sort | uniq -cd | sort -rn | head -30
```

For duplicates, determine:
- Which is the canonical entry (usually the one from `postgis_export` source)?
- Should the others be marked `"skipped": true`?
- Are any duplicates already rendered, causing wasted output?

### 4. Rendered Output Quality Check

For a random sample of 20 rendered buildings from `outputs/full/`:

a. Read the `.manifest.json` — verify it has valid `typology`, `construction_date`, `building_name`
b. Cross-reference the param file — verify `floors > 0`, `facade_width_m > 0`, `total_height_m > 0`
c. Check the `.blend` file size — flag any under 50KB (likely empty/failed) or over 50MB (possible issue)
d. Note any manifests where `collection_name` is `"building_unknown"` — indicates the building_name wasn't resolved

```bash
# File size distribution
ls -la outputs/full/*.blend | awk '{print $5}' | sort -n | awk 'BEGIN{print "min","p25","median","p75","max"} NR==1{min=$1} NR==int(NR*0.25){p25=$1} NR==int(NR*0.5){med=$1} NR==int(NR*0.75){p75=$1} END{print min,p25,med,p75,$1}'

# Flag tiny blends
ls -la outputs/full/*.blend | awk '$5 < 51200 {print $NF, $5, "bytes"}'

# Flag unknown buildings
grep -l '"building_unknown"' outputs/full/*.manifest.json
```

### 5. PNG Render Gap

No `.png` renders exist anywhere (`render_path: null` in all manifests). Confirm:
- Was the `--render` flag ever used in a batch run?
- Is rendering expected at this stage or deferred?
- If renders are needed, estimate time: `929 buildings × ~30s each ≈ ~8 hours`

### 6. Photo Analysis Coverage

Only 10 of 1,317 buildings have Claude Opus vision analysis (`_analysis_summary.json`). The rest use HCD typology defaults. Assess impact:

- For the 10 analyzed buildings, compare `photo_observations` fields against enrichment defaults — how different are the visual observations from the defaults?
- Are the 38 batch result files in `batches/` actually merged into params, or just sitting unprocessed?
- Check: `grep -c '"photo_observations"' params/*.json` — how many params have this section?

### 7. Site Coordinates Coverage

Buildings need coordinates for placement in the GIS scene. Check:

```bash
# How many buildings have site coordinates?
python3 -c "
import json
coords = json.load(open('params/_site_coordinates.json'))
print(f'Buildings with site coords: {len(coords)}')
"

# How many rendered buildings have coords vs using fallback?
```

### 8. Enrichment Pipeline Completeness

Verify all 6 enrichment steps ran on all active params:

```bash
# Check _meta flags
python3 -c "
import json, glob
stats = {'translated':0, 'enriched':0, 'gaps_filled':0, 'no_meta':0}
for f in glob.glob('params/*.json'):
    if '/_' in f: continue
    d = json.load(open(f))
    if d.get('skipped'): continue
    m = d.get('_meta', {})
    if not m: stats['no_meta'] += 1
    if m.get('translated'): stats['translated'] += 1
    if m.get('enriched'): stats['enriched'] += 1
    if m.get('gaps_filled'): stats['gaps_filled'] += 1
print(stats)
"
```

---

## Output Format

Produce a structured report with:

1. **Summary table**: Total params / rendered / missing / skipped / duplicates
2. **Missing render breakdown**: By category (perimeter, duplicate, non-building, legitimate gap)
3. **Schema issues**: Count and examples of params that would fail generation
4. **Quality flags**: Tiny blends, unknown buildings, missing coordinates
5. **Recommendations**: Prioritized list of next steps to reach full generation coverage

Save the report to `docs/generation_review_report.md`.
