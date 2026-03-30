# Second Agent Task — Blender Buildings Demo

You're assisting with a 3D reconstruction of Kensington Market, Toronto.

## Context
- Project: `C:\Users\liam1\blender_buildings\`
- Main script: `scripts/demo_footprint_based.py` (5,800+ lines)
- Generates 899 buildings with 140+ detail features each
- Uses PostGIS data from `outputs/gis_scene.json` and `params/*.json`
- All coordinates in SRID 2952 local metres from centroid (312672.94, 4834994.86)

## Your Tasks

1. **Review `scripts/demo_footprint_based.py` for bugs** — check for:
   - Division by zero (any `/` without guards)
   - Undefined variables (especially in the later sections)
   - Objects created without `link(obj, collection)`
   - Wrong normal directions (should use outward_normal)
   - Overlapping z-values (objects at same height clipping)

2. **Add more environment details to `main()`** section:
   - Traffic lights at major intersections (Dundas/Spadina, College/Augusta)
   - Newspaper vending machines
   - City garbage cans (large green/black)
   - Bus stop shelters
   - Community bulletin boards
   - More detailed park features (basketball court, splash pad)
   - Alley features (dumpsters, recycling, loading zones)

3. **Test the script** by running:
   ```bash
   blender --background --python scripts/demo_footprint_based.py
   ```
   Fix any errors that come up.

## Key Rules
- All GIS data from `gis_scene.json` (same coordinate source)
- Use `scene_transform(x, y)` for all raw GIS coordinates
- Use `scene_transform_angle(angle)` for all rotations
- Materials via `mat(name, hex, roughness)` — caches automatically
- Link objects via `link(obj, collection)`
- Street rotation: N-S streets use x-cutoff, E-W use y-cutoff (see ns_streets/ew_streets dicts)
- Don't refactor — only add new features or fix bugs
