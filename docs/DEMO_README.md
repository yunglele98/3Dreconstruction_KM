# Bellevue Ave 3D Demo — Kensington Market

Procedurally generated 3D reconstruction of the Bellevue Avenue block in
Kensington Market, Toronto. 164 buildings with 90+ architectural details
per building, generated from PostGIS data + field photo analysis.

## Quick Start

```bash
# Generate the scene (~15-20 min)
blender --background --python scripts/demo_footprint_based.py

# Open in Blender
start "" outputs/demos/bellevue_footprint_demo.blend

# Render 9 views headlessly
blender --background outputs/demos/bellevue_footprint_demo.blend --python scripts/render_demo.py

# Export to web (GLTF/GLB + Three.js viewer)
blender --background outputs/demos/bellevue_footprint_demo.blend --python scripts/export_gltf.py

# Render turntable animation (120 frames)
blender --background outputs/demos/bellevue_footprint_demo.blend --python scripts/render_turntable.py
```

## Architecture

### Data Flow

```
PostGIS (building_assessment + opendata.*)
  → scripts/export_gis_scene.py → outputs/gis_scene.json + params/_site_coordinates.json
  → AI agents (Claude/Codex/Gemini) → params/*.json (1,253 building params)
  → scripts/demo_footprint_based.py → outputs/demos/bellevue_footprint_demo.blend
  → scripts/render_demo.py → outputs/demos/renders/*.png
  → scripts/export_gltf.py → outputs/demos/web/bellevue_demo.glb + viewer.html
```

### Coordinate System

- **SRID 2952** (NAD83 / Ontario MTM Zone 10, metres)
- **Origin:** (312672.94, 4834994.86) — centroid of building footprints
- **Scene rotation:** -17.5 degrees (aligns Bellevue Ave with Y axis)
- **All geometry** from `gis_scene.json` (same source = zero coordinate mismatch)

### Building Rotation

Street-name-based facing direction (100% accuracy):

| Street Type | West/South Side | East/North Side |
|-------------|-----------------|-----------------|
| N-S streets (Bellevue, Wales, Lippincott...) | 73° (ENE) | 253° (WSW) |
| E-W streets (Augusta, Nassau, Oxford...) | 343° (NNW) | 163° (SSE) |
| Denison Sq | 163° (SSE) | 343° (NNW) |
| Denison Ave | 73° (ENE) | 253° (WSW) |

Formula: `rot_deg = (360 - facing_bearing) % 360`

## Features

### Per Building (93 detail types)

**Structure:** walls (per-building colour), foundation strip, party walls, rear extensions

**Windows:** per-floor specs from params, frames, sills, lintels, reveals, muntins,
shutters, window box planters, basement windows, window AC units, oculus (round)

**Doors:** from doors_detail params, frames, transoms, thresholds, keystones, steps, handrails

**Projections:** bay windows (canted sides), balconies, porches (columns + balusters + lattice),
storefronts (awnings + signage + bulkheads + pilasters + capitals + recessed entries + patios)

**Roof:** gable/hip/flat (per-building colour), ridge cap, finial, vent, bargeboards,
dormers, gutters, eave overhangs, soffits, fascia, flashing, parapet coping, chimneys
(precise from params, with caps + flues), skylights, satellite dishes, roof vents

**Masonry detail:** string courses, cornices (with dentils + brackets), corbelling, quoins
(alternating blocks), voussoirs, stone lintels, decorative brickwork, soldier courses,
mortar lines, continuous sill bands, drip moulds, wall panels, segmental arch headers

**Material-specific:** corner boards (clapboard), stucco scoring lines, clapboard lap lines

**Utilities:** downspouts, AC units, meter boxes, fire escapes, exterior staircases,
outdoor lights, address plaques, house number plaques, overhead power lines, rain barrels

**Random elements:** murals (10%), bicycles (50% commercial), traffic cones (8%)

### Environment (69 feature types)

**Roads:** flat surfaces (7m wide), alleys (3m), sidewalks, curbs, gutters, planting strips,
lane markings (dashed yellow), parking lines, crosswalks, speed bumps, manholes,
utility covers, storm drains, puddles, road patches, curb ramps, streetcar tracks + catenary

**Trees:** 55+ bare trees with 3-5 branches (March = no leaves), tree grates,
evergreen shrubs (cone-shaped)

**Street furniture:** utility poles (cross-arms + insulators), lamp posts, power lines,
stop signs, street signs, parking meters, bollards, bike racks, fire hydrants,
mailboxes, trash/recycling bins, newspaper boxes, parked cars, litter, weeds

**Park (Bellevue Square):** polygon, fence (posts + rails), paths, benches, lamp posts,
boulders, playground structure + swing set + fence, flower beds, drinking fountain,
waste bins, dog waste station, kiosk, amphitheatre seating, raised planter

**Ground:** front walkways, brick yard walls + pillars, driveway pads, gravel patches,
retaining walls, lot boundaries, land use zones (20), ruelles (7), HCD boundary,
cycling lane

## File Structure

```
scripts/
  demo_footprint_based.py    # Main demo generator (4,660 lines)
  render_demo.py             # 9-view headless renderer
  render_turntable.py        # 360° turntable animation
  export_gltf.py             # GLTF/GLB web export + Three.js viewer
  check_positions.py         # Blender position verifier
  verify_alignment.py        # Building-road alignment checker

outputs/demos/
  bellevue_footprint_demo.blend   # Generated demo scene
  bellevue_gis_data.json          # PostGIS export for demo area
  bellevue_complete_gis.json      # Extended PostGIS export (land use, ruelles, HCD)
  bellevue_buildings_db.json      # Building assessment data
  renders/                        # Headless render output (9 PNGs)
  turntable/                      # Turntable animation frames
  web/                            # GLTF export + HTML viewer
```

## Data Sources

| Source | Features | Count |
|--------|----------|-------|
| `opendata.building_footprints` | Building outlines | 753 |
| `opendata.massing_3d` | 3D heights (LiDAR) | 464 |
| `opendata.road_centerlines` | Road geometry | 162 |
| `opendata.green_spaces` | Park polygon | 1 |
| `opendata.street_trees` | Tree locations | 55+ |
| `opendata.land_use` | Zoning polygons | 20 |
| `opendata.pedestrian_network` | Pedestrian paths | 14 |
| `public.building_assessment` | 149 columns per building | 1,075 |
| `public.field_*` | Field survey (13 tables) | 566 |
| `params/*.json` | AI photo analysis | 1,253 |
| `PHOTOS KENSINGTON/` | Field photos (March 2026) | 1,867 |

## Requirements

- Blender 5.0+ (with Python 3.x)
- PostGIS database (for regenerating gis_scene.json)
- ~2GB disk space for outputs
- ~15-20 min generation time (164 buildings)
- ffmpeg (optional, for turntable MP4)
