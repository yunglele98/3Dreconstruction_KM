# Demo Refinement — Agent Prompt

Continue refining the Bellevue Ave footprint-based demo scene.

## Current State

`scripts/demo_footprint_based.py` generates buildings from GIS massing polygons with:
- Extruded walls with matched facade materials
- Windows on the 4 longest edges
- Doors from `doors_detail` params
- Storefronts from `storefront` params
- String courses, cornices, quoins from `decorative_elements`
- Flat roofs for blocks >15m, gable/hip for smaller buildings
- Roads, alleys, trees, street furniture from `gis_scene.json`

## What Needs Work

### 1. Individual Building Separation
The massing shapes from `opendata.massing_3d` are block-level (multiple rowhouses merged). Need to:
- Use `ST_Intersection(massing, footprint)` in PostGIS to clip massing by individual footprints
- Or subdivide massing blocks by building width (5.2m typical for Kensington rowhouses)
- Each individual building should get its own roof, material, windows

### 2. Bay Windows
Many Bellevue Ave buildings have bay windows (from `bay_window` in params):
- `bay_window.type`: "canted" (3-sided) or "box"
- `bay_window.width_m`, `bay_window.projection_m`
- `bay_window.floors`: which floors have the bay
- Place on the longest street-facing edge

### 3. Porches
From `porch_present` and porch params:
- Front porches with columns and railings
- Place at ground floor on the street-facing edge

### 4. Chimneys
From `roof_features` in params:
- Place on the ridge line or party wall edge
- Height: 1.0-1.5m above ridge

### 5. Better Window Detail
Use `windows_detail` array (per-floor specs) instead of evenly-spaced windows:
- Each floor has specific window count, type, width, height, sill_height
- Ground floor may have entrance instead of windows

### 6. Facade Colour
Use `facade_detail.brick_colour_hex` and `colour_palette` from params:
- Different brick colours per building (red, buff, brown, cream)
- Trim colour from `facade_detail.trim_colour_hex`

### 7. Ground Plane
Add a ground plane with grass texture between buildings and roads.

### 8. Park Details
Bellevue Square Park needs playground, benches, paths from field photos.
See `scripts/create_park.py` for the park feature creation functions.

## Key Files

| File | Purpose |
|------|---------|
| `scripts/demo_footprint_based.py` | Main demo script (edit this) |
| `outputs/gis_scene.json` | All GIS data (footprints, massing, roads, trees) |
| `params/_site_coordinates.json` | Building positions with rotation |
| `params/*.json` | Per-building params (materials, windows, decorative) |
| `generate_building.py` | Reference for parametric functions (6200 lines) |
| `scripts/create_park.py` | Park feature functions |

## How to Run

```bash
cd C:\Users\liam1\blender_buildings
blender --background --python scripts/demo_footprint_based.py
start "" outputs/demos/bellevue_footprint_demo.blend
```

## PostGIS Connection
```
host=localhost port=5432 dbname=kensington user=postgres password=test123
```
Origin: `ORIGIN_X=312672.94, ORIGIN_Y=4834994.86` (SRID 2952)

## Coordinate Rules
- ALL geometry must come from `gis_scene.json` or PostGIS with the same origin
- Never mix coordinate sources
- Building positions from `_site_coordinates.json` match `gis_scene.json` building_positions
- Test alignment with `scripts/check_positions.py`
