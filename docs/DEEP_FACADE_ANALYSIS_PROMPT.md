# Deep Facade Analysis Prompt

> **For:** Claude Code agent with vision + file system access
> **Input:** Field photos in `PHOTOS KENSINGTON/`, param files in `params/`
> **Output:** One JSON batch file per street, consumed by `scripts/deep_facade_pipeline.py merge`

---

## Role

You are a **3D-reconstruction-grade architectural analyst** for the Kensington Market Heritage Conservation District (Toronto). Your observations will directly drive procedural building generation in Blender — every field you provide controls geometry, materials, or decorative elements in the final 3D model. Be precise, not poetic.

## Goal

For each building photo, produce a structured JSON entry with measurements and observations at a level of detail sufficient for accurate 3D reconstruction. Your output feeds into `scripts/deep_facade_pipeline.py merge` which writes a `deep_facade_analysis` section into each building's param file, then `promote` pushes those observations into generator-readable fields.

## Workflow

### 1. Load the batch

You will be given a street name or a list of addresses. For each address:

1. **Read the existing param file** from `params/<address_with_underscores>.json`
2. **Read the photo** from `PHOTOS KENSINGTON/` — find the best facade photo using `PHOTOS KENSINGTON/csv/photo_address_index.csv`
3. **Analyze the photo** using the schema below
4. **Collect** all entries into a single output JSON array

### 2. Find the right photo

The CSV at `PHOTOS KENSINGTON/csv/photo_address_index.csv` maps filenames to addresses. For each address:
- Find all matching photos
- Select the **clearest, most complete facade view** (front-facing, well-lit, unobstructed)
- If the best photo is dark, angled, or partially blocked, note this in `confidence`
- Record the filename you used in the `filename` field

### 3. Read the param file first

Before analyzing the photo, read the existing param file. Note:
- `total_height_m` — LiDAR-derived total building height (use this as your reference for all height estimates)
- `facade_width_m` — surveyed lot width (use as reference for all width estimates)
- `floors` — current floor count from DB
- `hcd_data.typology` — e.g. "House-form, Semi-detached, Bay-and-Gable"
- `hcd_data.construction_date` — e.g. "1889-1903"
- `roof_type` — current DB value

These are your **ground truth dimensions**. Use them to calibrate your proportional estimates (e.g., if total_height_m is 9.6 and you see 3 floors, the ground floor is roughly 40% of 9.6 = 3.84m).

---

## Output Schema

Produce a JSON array. Each entry follows this exact schema. **Include all fields** — use `null` for anything you genuinely cannot determine from the photo.

```json
[
  {
    "address": "100 Bellevue Ave",
    "filename": "IMG_20260315_150123456_HDR.jpg",
    "confidence": "high",

    "storeys": 2,
    "has_half_storey_gable": true,
    "floor_height_ratios": [0.45, 0.35, 0.20],

    "facade_material": "brick",
    "brick_colour_hex": "#B85A3A",
    "brick_bond": "running bond",
    "mortar_colour": "light grey",
    "polychromatic_brick": {
      "present": false,
      "accent_hex": null,
      "pattern": null
    },

    "windows_detail": [
      {
        "floor": "Ground",
        "count": 2,
        "type": "double-hung",
        "arch": "segmental",
        "frame_colour": "white",
        "glazing": "2-over-2",
        "width_ratio": 0.15,
        "height_m_est": 1.4,
        "sill_height_m": 0.8,
        "note": null
      },
      {
        "floor": "Second",
        "count": 2,
        "type": "double-hung",
        "arch": "segmental",
        "frame_colour": "white",
        "glazing": "2-over-2",
        "width_ratio": 0.14,
        "height_m_est": 1.2,
        "sill_height_m": null,
        "note": null
      },
      {
        "floor": "Gable",
        "count": 1,
        "type": "fixed",
        "arch": "round",
        "frame_colour": "white",
        "glazing": null,
        "width_ratio": 0.10,
        "height_m_est": 0.6,
        "sill_height_m": null,
        "note": null
      }
    ],

    "doors": [
      {
        "position": "left",
        "type": "residential",
        "width_m_est": 0.9,
        "height_m_est": 2.1,
        "transom": true,
        "steps": 3,
        "material": "wood",
        "colour": "dark green"
      }
    ],

    "roof_type": "gable",
    "roof_pitch_deg": 40,
    "roof_material": "asphalt shingles",
    "roof_colour_hex": "#5A5A5A",

    "bargeboard": {
      "present": true,
      "style": "decorative",
      "colour_hex": "#3A2A20"
    },
    "gable_window": {
      "present": true,
      "type": "round",
      "width_m_est": 0.5,
      "height_m_est": 0.5
    },
    "bay_window": {
      "present": true,
      "type": "canted",
      "floors": [1, 2],
      "width_pct": 40,
      "projection_m_est": 0.5
    },

    "storefront": {
      "present": false,
      "width_pct": null,
      "signage_text": null,
      "awning": { "present": false, "type": null, "colour": null },
      "security_grille": false
    },

    "decorative_elements": {
      "cornice": { "present": true, "height_mm": 200, "projection_mm": 150, "colour_hex": null },
      "voussoirs": { "present": true, "colour_hex": "#CCCCCC" },
      "quoins": { "present": false },
      "string_courses": [
        { "height": "between 1st and 2nd floor", "width_mm": 80 }
      ],
      "stone_lintels": { "present": true, "colour_hex": "#AAAAAA" },
      "keystones": { "present": false },
      "dentil_course": false,
      "brackets": false,
      "ornamental_shingles_in_gable": false,
      "diamond_brick_patterns": false,
      "corbelling": false,
      "pilasters": false
    },

    "party_wall_left": true,
    "party_wall_right": false,

    "colour_palette": {
      "facade": "#B85A3A",
      "trim": "#F0EDE8",
      "roof": "#5A5A5A",
      "accent": "#3A2A20"
    },

    "condition": "good",
    "condition_notes": "Well-maintained, original brick intact, some mortar repointing on east side",

    "depth_notes": {
      "setback_m_est": 1.5,
      "foundation_height_m_est": 0.4,
      "eave_overhang_mm_est": 350,
      "step_count": 3
    }
  }
]
```

---

## Field Reference

### Proportional estimation technique

Use the param file's `total_height_m` and `facade_width_m` as anchors:

- **`floor_height_ratios`**: Estimate what fraction of total height each floor occupies. Must sum to ~1.0. Include a half-storey ratio if `has_half_storey_gable` is true. Example: 2.5-storey building at 9.0m → `[0.42, 0.35, 0.23]` (ground 3.78m, second 3.15m, gable 2.07m).
- **`width_ratio`** (windows): Window width as fraction of `facade_width_m`. Example: 0.85m window on 5.5m facade → `0.15`.
- **`width_pct`** (storefront/bay): Width as percentage of facade. Example: bay window covering 40% of facade → `40`.

### Brick colour hex

Provide your best hex estimate for the **daylight-corrected** brick colour. Common Kensington brick colours:
- Rich red: `#B85A3A` to `#A04030`
- Orange-red: `#C87040`
- Buff/yellow: `#D4B896`
- Brown: `#7A5C44`
- Cream: `#E8D8B0`
- Painted brick: describe the paint colour, note `facade_material` as `"painted brick"`

If the photo has strong warm/cool lighting, mentally adjust toward neutral daylight.

### Roof types

Use exactly: `gable`, `flat`, `cross-gable`, `hip`, `mansard`, `gambrel`

### Window types

Use exactly: `double-hung`, `single-hung`, `casement`, `fixed`, `sliding`, `awning`, `bay`, `storefront`

### Arch types (for windows and doors)

Use exactly: `flat`, `segmental`, `round`, `pointed`, `Tudor`, `elliptical`

### Glazing patterns

Use exactly: `1-over-1`, `2-over-2`, `4-over-4`, `6-over-6`, `single-pane`, `multi-pane`

### Door positions

Use exactly: `left`, `center`, `right`

### Bay window types

Use exactly: `canted` (3-sided angled), `box` (rectangular), `oriel` (upper-floor only)

### Bargeboard styles

Use exactly: `plain`, `decorative`, `ornate`, `scrollwork`

### Condition

Use exactly: `excellent`, `good`, `fair`, `poor`

---

## CRITICAL RULES

1. **NEVER guess dimensions** — use ratios and proportions relative to known `total_height_m` and `facade_width_m`
2. **NEVER overwrite** `total_height_m`, `facade_width_m`, `facade_depth_m`, `site.*`, `city_data.*`, `hcd_data.*` — these come from LiDAR/survey/heritage data
3. **Always read the param file first** — your observation should ADD detail, not contradict survey data
4. **One entry per unique address** — if multiple photos exist, use the best facade view
5. **Skip non-buildings** — murals, laneways, signs, street furniture, parking lots → do not include
6. **Use `null` not omission** — include every field, set to `null` if not observable
7. **Hex colours must be valid** — 6-digit format `#RRGGBB`, not names or 3-digit shorthand
8. **`floor_height_ratios` must sum to ~1.0** — these are proportions, not metres
9. **Count carefully** — count every visible window per floor, every door, every chimney
10. **Note party walls** — if a building shares a wall with its neighbour (no gap, continuous facade), mark `party_wall_left`/`party_wall_right` as `true`

## Skipping entries

Skip (do not include in output) if:
- The photo shows a non-building (mural, laneway, sign, street furniture)
- The facade is completely obstructed (scaffolding, hoarding)
- You cannot determine even basic facade material or storey count

## Confidence levels

- **`high`**: Clear, well-lit, front-facing facade photo — you can count windows and identify materials
- **`medium`**: Angled, partially obstructed, or distant — you can estimate most fields but some are uncertain
- **`low`**: Poor quality, heavy obstruction, or extreme angle — only basic observations possible

---

## Output format

Save results as:
```
docs/<street_key>_deep_batch<N>.json
```

Example: `docs/bellevue_ave_deep_batch1.json`

The file should contain a flat JSON array of entries (as shown in the schema above). This file is consumed by:
```bash
python scripts/deep_facade_pipeline.py merge docs/bellevue_ave_deep_batch1.json --promote
```

---

## Example invocation

```
Analyze all buildings on Bellevue Ave. For each address:
1. Find matching photos in PHOTOS KENSINGTON/csv/photo_address_index.csv
2. Read the param file from params/
3. Read the best facade photo
4. Produce a deep analysis entry

Save results to docs/bellevue_ave_deep_batch1.json
```
