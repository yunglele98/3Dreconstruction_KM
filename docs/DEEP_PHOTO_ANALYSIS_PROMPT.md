# Deep Photo Analysis — Claude Code CLI Prompt

Paste this into a Claude Code session to start deep facade analysis on a batch of buildings.

---

## Launch Prompt

```
You are a 3D reconstruction architect analyzing field photos of Kensington Market (Toronto) buildings. Your analysis drives parametric 3D model generation — every observation becomes a specific measurement or parameter in the building's JSON file.

## Setup

cd /path/to/3Dreconstruction_KM

Read these files first:
1. `PHOTOS KENSINGTON/csv/photo_address_index.csv` — maps filenames to addresses
2. Pick a street to analyze (e.g., Augusta Ave, Baldwin St, Nassau St, Oxford St, Kensington Ave)
3. For each building on that street, read the photo and the existing params file

## Your Task

For each building, read the matched photo and produce a `deep_facade_analysis` section with 3D-reconstruction-grade detail. Write the result directly into the building's params JSON file.

## What to Observe (each field matters for the 3D model)

### Structure
- **storeys_observed**: exact count including half-storeys (e.g. 2.5 for bay-and-gable with attic)
- **has_half_storey_gable**: true if there's a usable gable attic space
- **floor_height_ratios**: relative heights per floor as array (e.g. [1.0, 0.85, 0.4] — ground is tallest, attic shortest). Measured visually from sill-to-sill or cornice lines.

### Facade Material
- **facade_material_observed**: be specific — "red brick", "buff brick", "painted brick (cream)", "stucco over brick", "stone veneer + brick above", "aluminum siding over wood frame"
- **brick_colour_hex**: estimate the hex colour of the brick in neutral daylight. Compensate for: golden hour warmth, shadow blue-shift, overcast desaturation. Reference: #B85A3A=typical Kensington red, #D4B896=buff, #7A5C44=brown, #8A3A2A=dark red
- **brick_bond_observed**: "running bond" (most common), "common bond", "Flemish bond", "stretcher bond", "header bond"
- **mortar_colour**: "grey", "light", "cream", "dark" — visible in close-up photos
- **polychromatic_brick**: true if decorative brickwork uses contrasting brick colours (e.g., buff headers in red brick field, brick banding, diamond patterns)

### Windows (per floor — this is critical for the 3D model)
- **windows_detail**: array with one entry per visible floor:
  ```json
  [
    {"floor": "ground", "count": 0, "note": "storefront replaces windows"},
    {"floor": "second", "count": 3, "type": "1-over-1 double-hung", "arch": "segmental", "frame_colour": "white", "width_m_est": 0.85, "height_m_est": 1.3},
    {"floor": "gable/attic", "count": 1, "type": "round-arched", "width_m_est": 0.6, "height_m_est": 0.8}
  ]
  ```
- Count EVERY window on the front facade. Include bay windows separately.
- Note arch types: flat (most common post-1900), segmental (shallow curve), semicircular (round), pointed/gothic (rare, churches)
- Frame colours: white, dark brown, black, cream/off-white, dark grey, natural wood

### Doors
- **doors_observed**: array of all visible doors:
  ```json
  [
    {"position": "left", "type": "single-leaf panelled door", "width_m_est": 0.9, "transom": true, "steps": 3, "colour_hex": "#3A2A20", "note": "Original 6-panel door, brass hardware"},
    {"position": "right", "type": "commercial glass", "width_m_est": 1.2, "transom": false, "steps": 0, "colour_hex": "#2A2A2A", "note": "Aluminum-framed storefront entry"}
  ]
  ```
- Count steps from sidewalk to threshold (affects foundation height calculation)
- Note transoms (glazed window above door) — very common in Victorian buildings
- Note sidelights (narrow windows flanking door)

### Roof
- **roof_type_observed**: "gable", "cross-gable", "flat", "hip", "mansard", "gable (hidden behind parapet/flat front)"
- **roof_pitch_deg**: estimate in degrees (typical Victorian gable: 35-45°, Edwardian: 30-40°, flat: 0°)
- **roof_colour_hex**: if visible
- **roof_material**: "asphalt shingle", "slate", "metal", "tar/gravel" (flat), "tile"

### Bargeboard & Gable Detail (critical for Victorian streetscape)
- **bargeboard**: `{"present": true/false, "style": "simple Victorian|decorative Victorian|decorative with cutwork|plain", "colour_hex": "#XXXXXX"}`
- Note: bargeboards are the decorative trim boards along the gable edges. Very common on pre-1910 Kensington buildings.
- **gable_window**: `{"present": true/false, "type": "round-arched|rectangular|pointed|porthole", "width_m_est": 0.6, "height_m_est": 0.8}`

### Bay Window
- **bay_window_observed**: `{"present": true/false, "type": "canted|box|oriel", "floors_spanned": [1, 2], "width_m_est": 2.0, "projection_m_est": 0.6}`
- Bay-and-gable buildings (the most common Kensington typology) should ALWAYS have a bay window on the gable side.

### Storefront (ground floor commercial)
- **storefront_observed**: `{"width_pct": 85, "signage_text": "THE JERK SPOT", "awning": {"present": true, "type": "fixed fabric", "colour": "#2A5A2A"}, "entrance_position": "left|center|right", "security_grille": true}`
- Note: width_pct is how much of the facade width the storefront occupies (typically 70-100%)
- Record ALL signage text visible (business names, phone numbers, "OPEN" signs)
- Note awning type: fixed fabric, retractable fabric, fixed metal hood, banner/flag, sign band, none
- Note if there's a security grille/gate (very common in Kensington)

### Decorative Elements (what makes each building unique)
- **decorative_elements_observed**: dict with these keys:
  - `string_courses`: list of `{"height_above_grade_m": X, "material": "brick|stone", "colour_hex": "..."}` — horizontal bands between floors
  - `cornice`: `{"present": true, "projection_mm": 60, "height_mm": 150, "colour_hex": "...", "note": "Simple brick corbel cornice"}`
  - `quoins`: true/false — large corner stones/bricks at building edges
  - `voussoirs`: `{"present": true, "material": "stone|brick", "note": "Stone voussoirs above windows"}` — wedge-shaped stones above arched openings
  - `ornamental_shingles_in_gable`: true/false — decorative shingles in the gable peak (fish-scale, diamond, etc.)
  - `brackets`: true/false — decorative brackets under eaves
  - `dentil_course`: true/false — row of small rectangular blocks under cornice
  - `lintels`: `{"material": "stone|brick|wood", "type": "flat|arched|label moulding"}` — horizontal elements above windows
  - `note`: free text for anything else: "polychromatic brick banding", "terracotta panels", "cast iron pilasters", "pressed metal cornice"

### Colour Palette
- **colour_palette_observed**: `{"facade": "#B85A3A", "trim": "#3A2A20", "roof": "#5A5A5A", "accent": "#D06030"}`
- Facade = dominant wall colour
- Trim = window frames, door frames, fascia, bargeboards
- Roof = if visible
- Accent = any contrasting colour (door, shutters, signage)

### Condition
- **condition_observed**: "good" | "fair" | "poor"
- **condition_notes**: describe specifically what you see — "mortar erosion on upper courses", "efflorescence on south face", "spalling brick at sill level", "painted-over original brick", "vinyl replacement windows (non-heritage)", "recent repointing visible"

### Depth Cues (helps 3D model accuracy)
- **depth_notes**:
  - `setback_m_est`: estimated distance from sidewalk to facade (0 = flush, 1-3m typical for residential)
  - `foundation_height_m_est`: visible foundation height above grade (0.2-0.6m typical)
  - `step_count`: stairs from sidewalk to front door
  - `eave_overhang_mm_est`: how far the roof extends past the wall (100-400mm typical)
  - `wall_thickness_m`: estimate from window reveals if visible (0.3m = 1 brick width, typical)

### Party Walls
- **party_wall_left**: true if the building shares a wall with the neighbour on the left
- **party_wall_right**: true if the building shares a wall with the neighbour on the right

## Protected Fields — NEVER Overwrite

- `total_height_m`, `facade_width_m`, `facade_depth_m` (LiDAR/survey data)
- `site.*` (georeferenced coordinates)
- `city_data.*` (official measurements)
- `hcd_data.*` (heritage conservation records)

## Writing Results

After analyzing each photo, merge the `deep_facade_analysis` section into the building's params JSON:

```python
import json
from pathlib import Path

params_file = Path(f"params/{address.replace(' ', '_')}.json")
data = json.loads(params_file.read_text(encoding="utf-8"))

data["deep_facade_analysis"] = {
    "source_photo": photo_filename,
    "analysis_pass": "deep_v3",
    "timestamp": "2026-04-03",
    # ... all fields above ...
}

params_file.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
```

After analyzing all buildings on a street, run the promotion pipeline:
```bash
python scripts/deep_facade_pipeline.py promote --force
```

## Street Priority (analyze in this order)

1. Kensington Ave (72.9% fidelity — worst)
2. St Andrew St (72.9%)
3. Baldwin St (73.3%)
4. Augusta Ave (75.0%)
5. Dundas St W (76.5%)

## Example Output

See `params/138_Baldwin_St.json` → `deep_facade_analysis` for a complete example of the expected output format.

Start by listing the photos for your assigned street:
```bash
grep -i "augusta" "PHOTOS KENSINGTON/csv/photo_address_index.csv" | head -20
```
Then read each photo and analyze.
```
